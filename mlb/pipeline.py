#!/usr/bin/env python3
"""
MLB Data Pipeline — v3 (game-by-game, leak-free)
Walks every regular-season game since 2019 in date order, recording each team's
state BEFORE the game, and outputs:
  data/mlb/mlb_stats_current.csv       — live team table (season stats + model state)
  data/mlb/mlb_pitcher_ratings.csv     — current FIP rating for every starter (API lookups)
  data/processed/mlb_training_data.csv — labelled rows for model training

Features (one row per team per game, mirrored for the opponent):
  - Elo rating (K=4, 1/3 regression between seasons)
  - Starting pitcher FIP to date: decayed across his previous starts, shrunk toward
    league average for pitchers with little history. (v2 used the pitcher's
    full-season ERA, which leaked the results of future games into training.)
  - Bullpen quality (decayed bullpen ERA) and fatigue (bullpen innings in the
    3 days before the game)
  - Recent offense (decayed OPS) and recent run differential
  - Home field

Sources: MLB Stats API — schedules, team game logs (hitting + pitching) and
starting-pitcher game logs. Past seasons are cached under data/mlb/raw/.

Run:
    python mlb/pipeline.py

Estimated runtime: ~10 min on first run, ~2-3 min afterwards (only the current
season is re-downloaded).
"""

import json
import time
import urllib.request
import zoneinfo
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import statsapi

ROOT       = Path(__file__).parent.parent
MLB_DIR    = ROOT / "data" / "mlb"
RAW_DIR    = MLB_DIR / "raw"
PROCESSED  = ROOT / "data" / "processed"
for _d in (MLB_DIR, RAW_DIR, PROCESSED):
    _d.mkdir(parents=True, exist_ok=True)

CURRENT_SEASON = 2026
DATA_SEASONS   = list(range(2019, CURRENT_SEASON + 1))  # 2019-2020 = burn-in for ratings
TRAIN_SEASONS  = list(range(2021, CURRENT_SEASON))

API = "https://statsapi.mlb.com/api/v1"
UA  = {"User-Agent": "CourtEdge/1.0"}

# ── Model constants ─────────────────────────────────────────────────────────────
ELO_MEAN, ELO_K, ELO_HFA, ELO_REVERT = 1500.0, 4.0, 24.0, 1 / 3

GAME_DECAY   = 0.97   # per-game decay for team offense / run diff (~23-game half-life)
SEASON_DECAY = 0.50   # extra decay at a season boundary
PRIOR_GAMES  = 10.0   # pseudo-games of league-average play

LG_OBP, LG_SLG = 0.315, 0.405
PRIOR_PA, PRIOR_AB = 380.0, 340.0

SP_DECAY      = 0.95  # per-start decay (~13-start half-life)
SP_PRIOR_IP   = 25.0
LG_FIP        = 4.20
SP_UNKNOWN    = 4.40  # rating for a starter with no history (debuts skew below average)
FIP_CONST     = 3.10

BP_DECAY      = 0.98  # per-game decay for bullpen ERA
BP_PRIOR_IP   = 60.0
LG_BP_ERA     = 4.10
FATIGUE_DAYS  = 3

# ── Park factors (2023-2025 multi-year average, neutral = 1.0) ─────────────────
PARK_FACTORS: dict[str, float] = {
    "Colorado Rockies":       1.15,
    "Cincinnati Reds":        1.08,
    "Texas Rangers":          1.07,
    "Boston Red Sox":         1.05,
    "Chicago Cubs":           1.04,
    "Houston Astros":         1.02,
    "Philadelphia Phillies":  1.02,
    "Atlanta Braves":         1.02,
    "Milwaukee Brewers":      1.01,
    "New York Yankees":       1.01,
    "Pittsburgh Pirates":     1.00,
    "Minnesota Twins":        1.00,
    "Detroit Tigers":         1.00,
    "Toronto Blue Jays":      0.99,
    "New York Mets":          0.99,
    "Kansas City Royals":     0.99,
    "Los Angeles Angels":     0.99,
    "St. Louis Cardinals":    0.98,
    "Chicago White Sox":      0.98,
    "Cleveland Guardians":    0.98,
    "Baltimore Orioles":      0.97,
    "Seattle Mariners":       0.97,
    "Oakland Athletics":      0.97,
    "Athletics":              0.97,
    "Tampa Bay Rays":         0.97,
    "Miami Marlins":          0.96,
    "Washington Nationals":   0.96,
    "Arizona Diamondbacks":   0.96,
    "Los Angeles Dodgers":    0.95,
    "San Francisco Giants":   0.94,
    "San Diego Padres":       0.93,
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _safe_float(val: object, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _progress(msg: str) -> None:
    print(msg, flush=True)


def _ip(val: object) -> float:
    """MLB innings notation ("5.2" = 5⅔) → float innings."""
    s = str(val or "0")
    whole, _, frac = s.partition(".")
    try:
        return float(whole) + (float(frac) / 3 if frac else 0.0)
    except ValueError:
        return 0.0


def _get(url: str, retries: int = 3, timeout: int = 30) -> dict:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(1.5 * (attempt + 1))
    return {}


def _cached(name: str, season: int, fetch):
    """Past seasons are immutable → cache on disk; the current season is always refetched."""
    path = RAW_DIR / f"{name}_{season}.json"
    if season < CURRENT_SEASON and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    data = fetch()
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


# ── Team catalogue ─────────────────────────────────────────────────────────────

def get_all_teams() -> dict[int, str]:
    raw = statsapi.get("teams", {"sportId": 1, "activeStatus": "Y"})
    return {t["id"]: t["name"] for t in raw.get("teams", [])}


# ── Raw data fetchers ──────────────────────────────────────────────────────────

def fetch_schedule(season: int) -> list[dict]:
    """All regular-season games (any status) with probable/actual starters."""
    def _fetch():
        games: dict[int, dict] = {}
        for start, end in ((f"{season}-03-01", f"{season}-05-31"),
                           (f"{season}-06-01", f"{season}-08-15"),
                           (f"{season}-08-16", f"{season}-11-30")):
            data = _get(f"{API}/schedule?sportId=1&gameType=R&startDate={start}&endDate={end}"
                        f"&hydrate=probablePitcher&limit=2000")
            for d in data.get("dates", []):
                for g in d.get("games", []):
                    t = g.get("teams", {})
                    home, away = t.get("home", {}), t.get("away", {})
                    games[g["gamePk"]] = {   # later entries (resumed games) overwrite earlier ones
                        "game_pk":     g["gamePk"],
                        "date":        d.get("date"),
                        "game_number": g.get("gameNumber", 1),
                        "state":       g.get("status", {}).get("codedGameState", ""),
                        "home_id":     home.get("team", {}).get("id"),
                        "away_id":     away.get("team", {}).get("id"),
                        "home_score":  home.get("score"),
                        "away_score":  away.get("score"),
                        "home_sp":     home.get("probablePitcher", {}).get("id"),
                        "away_sp":     away.get("probablePitcher", {}).get("id"),
                        "home_sp_name": home.get("probablePitcher", {}).get("fullName"),
                        "away_sp_name": away.get("probablePitcher", {}).get("fullName"),
                    }
            time.sleep(0.3)
        return sorted(games.values(), key=lambda g: (g["date"], g["game_number"], g["game_pk"]))
    return _cached("schedule", season, _fetch)


def fetch_team_logs(season: int, team_ids: list[int]) -> dict[str, dict]:
    """{"team_id:gamePk": {"pit": stat, "hit": stat}} from team game logs."""
    def _one(args):
        tid, group = args
        try:
            data = _get(f"{API}/teams/{tid}/stats?stats=gameLog&group={group}&season={season}&gameType=R")
        except Exception as e:
            _progress(f"    WARNING: {group} log failed team={tid} season={season}: {e}")
            return tid, group, []
        splits = data.get("stats", [{}])[0].get("splits", []) if data.get("stats") else []
        return tid, group, [(s.get("game", {}).get("gamePk"), s.get("stat", {})) for s in splits]

    def _fetch():
        out: dict[str, dict] = {}
        jobs = [(tid, grp) for tid in team_ids for grp in ("pitching", "hitting")]
        with ThreadPoolExecutor(max_workers=6) as ex:
            for tid, group, rows in ex.map(_one, jobs):
                for pk, stat in rows:
                    out.setdefault(f"{tid}:{pk}", {})["pit" if group == "pitching" else "hit"] = stat
        return out
    return _cached("team_logs", season, _fetch)


def fetch_pitcher_logs(season: int, pitcher_ids: list[int]) -> dict[str, list]:
    """{pitcher_id: [{pk, team_id, date, gs, ip, er, hr, bb, hbp, k, name}, ...]}"""
    def _one(pid):
        try:
            data = _get(f"{API}/people/{pid}/stats?stats=gameLog&group=pitching&season={season}&gameType=R")
        except Exception:
            return pid, []
        rows = []
        for s in (data.get("stats", [{}])[0].get("splits", []) if data.get("stats") else []):
            st = s.get("stat", {})
            rows.append({
                "pk": s.get("game", {}).get("gamePk"), "team_id": s.get("team", {}).get("id"),
                "gs": int(st.get("gamesStarted", 0) or 0), "ip": _ip(st.get("inningsPitched")),
                "er": int(st.get("earnedRuns", 0) or 0), "hr": int(st.get("homeRuns", 0) or 0),
                "bb": int(st.get("baseOnBalls", 0) or 0), "hbp": int(st.get("hitByPitch", 0) or 0),
                "k": int(st.get("strikeOuts", 0) or 0), "name": s.get("player", {}).get("fullName", ""),
            })
        return pid, rows

    def _fetch():
        with ThreadPoolExecutor(max_workers=6) as ex:
            return {str(pid): rows for pid, rows in ex.map(_one, pitcher_ids)}
    return _cached("pitcher_logs", season, _fetch)


# ── Rolling state ──────────────────────────────────────────────────────────────

class TeamState:
    def __init__(self):
        self.elo = ELO_MEAN
        self.season: int | None = None
        # offense: decayed on-base numerator/denominator, total bases, at-bats
        self.ob = self.pa = self.tb = self.ab = 0.0
        self.rd = self.rd_w = 0.0              # run differential sum / weight
        self.bp_er = self.bp_ip = 0.0          # bullpen earned runs / innings (decayed)
        self.bp_usage: list[tuple[str, float]] = []  # (date, bullpen IP)
        self.results: list[tuple[bool, int]] = []    # current-season (won, run diff)

    def new_season(self, season: int) -> None:
        if self.season is not None and self.season != season:
            self.elo = self.elo * (1 - ELO_REVERT) + ELO_MEAN * ELO_REVERT
            for k in ("ob", "pa", "tb", "ab", "rd", "rd_w"):
                setattr(self, k, getattr(self, k) * SEASON_DECAY)
            self.results = []
        self.season = season

    def ops(self) -> float:
        obp = (self.ob + LG_OBP * PRIOR_PA) / (self.pa + PRIOR_PA)
        slg = (self.tb + LG_SLG * PRIOR_AB) / (self.ab + PRIOR_AB)
        return obp + slg

    def run_diff(self) -> float:
        return self.rd / (self.rd_w + PRIOR_GAMES)

    def bullpen_era(self) -> float:
        return 9 * (self.bp_er + LG_BP_ERA / 9 * BP_PRIOR_IP) / (self.bp_ip + BP_PRIOR_IP)

    def bullpen_ip_before(self, game_date: str) -> float:
        d = date.fromisoformat(game_date)
        lo = (d - timedelta(days=FATIGUE_DAYS)).isoformat()
        return sum(ip for dt, ip in self.bp_usage[-12:] if lo <= dt < game_date)

    def form(self) -> tuple[float, float]:
        r20, r15 = self.results[-20:], self.results[-15:]
        if not r20:
            return 0.5, 0.0
        w = [0.88 ** i for i in range(len(r20) - 1, -1, -1)]
        return (round(sum(wi * won for wi, (won, _) in zip(w, r20)) / sum(w), 3),
                round(sum(rd for _, rd in r15) / len(r15), 2))


class PitcherRatings:
    def __init__(self):
        self.num: dict[int, float] = defaultdict(float)   # decayed 13HR + 3(BB+HBP) − 2K
        self.ip: dict[int, float] = defaultdict(float)
        self.starts: dict[int, int] = defaultdict(int)
        self.name: dict[int, str] = {}

    def fip(self, pid: int | None) -> float:
        if not pid or pid not in self.ip:
            return SP_UNKNOWN
        return (self.num[pid] + SP_PRIOR_IP * (LG_FIP - FIP_CONST)) / (self.ip[pid] + SP_PRIOR_IP) + FIP_CONST

    def update(self, pid: int, line: dict) -> None:
        self.num[pid] = self.num[pid] * SP_DECAY + 13 * line["hr"] + 3 * (line["bb"] + line["hbp"]) - 2 * line["k"]
        self.ip[pid]  = self.ip[pid] * SP_DECAY + line["ip"]
        self.starts[pid] += 1
        if line.get("name"):
            self.name[pid] = line["name"]


# ── Feature builder ────────────────────────────────────────────────────────────

def build_features(all_teams: dict[int, str]) -> tuple[pd.DataFrame, dict[int, TeamState], PitcherRatings]:
    teams: dict[int, TeamState] = defaultdict(TeamState)
    sps = PitcherRatings()
    rows: list[dict] = []
    team_ids = list(all_teams)

    for season in DATA_SEASONS:
        _progress(f"\n[{season}] schedule...")
        sched = fetch_schedule(season)
        final = [g for g in sched if g["state"] in ("F", "O") and g["home_id"] and g["away_id"]
                 and g["home_score"] is not None and g["away_score"] is not None]
        _progress(f"  {len(final)} final games — team logs...")
        tlogs = fetch_team_logs(season, team_ids)
        sp_ids = sorted({pid for g in sched for pid in (g["home_sp"], g["away_sp"]) if pid})
        _progress(f"  pitcher logs for {len(sp_ids)} starters...")
        plogs = fetch_pitcher_logs(season, sp_ids)

        # actual starter line per (gamePk, team)
        starter_line: dict[tuple[int, int], tuple[int, dict]] = {}
        for pid, games in plogs.items():
            for ln in games:
                if ln["gs"] == 1 and ln["pk"]:
                    starter_line[(ln["pk"], ln["team_id"])] = (int(pid), ln)

        n_rows = 0
        for g in final:
            hid, aid, pk = g["home_id"], g["away_id"], g["game_pk"]
            h, a = teams[hid], teams[aid]
            h.new_season(season)
            a.new_season(season)

            side = {}
            for tid, st, sp_key in ((hid, h, "home_sp"), (aid, a, "away_sp")):
                pid, line = starter_line.get((pk, tid), (g[sp_key], None))
                side[tid] = {"sp": pid, "line": line, "sp_fip": sps.fip(pid),
                             "elo": st.elo, "ops": st.ops(), "rd": st.run_diff(),
                             "bp_era": st.bullpen_era(), "bp_ip3": st.bullpen_ip_before(g["date"])}

            home_won = g["home_score"] > g["away_score"]
            if season in TRAIN_SEASONS and g["home_score"] != g["away_score"]:
                for tid, oid, is_home in ((hid, aid, 1), (aid, hid, 0)):
                    t, o = side[tid], side[oid]
                    rows.append({
                        "season": season, "game_date": g["date"], "game_pk": pk,
                        "team_name": all_teams.get(tid, str(tid)), "opp_name": all_teams.get(oid, str(oid)),
                        "home": is_home,
                        "elo_diff":           round(t["elo"] - o["elo"], 1),
                        "sp_fip":             round(t["sp_fip"], 3),
                        "opp_sp_fip":         round(o["sp_fip"], 3),
                        "sp_fip_diff":        round(t["sp_fip"] - o["sp_fip"], 3),
                        "ops_diff":           round(t["ops"] - o["ops"], 4),
                        "run_diff_ewm_diff":  round(t["rd"] - o["rd"], 3),
                        "bullpen_era_diff":   round(t["bp_era"] - o["bp_era"], 3),
                        "bullpen_ip3":        round(t["bp_ip3"], 2),
                        "opp_bullpen_ip3":    round(o["bp_ip3"], 2),
                        "bullpen_ip3_diff":   round(t["bp_ip3"] - o["bp_ip3"], 2),
                        "win": int(home_won == bool(is_home)),
                    })
                    n_rows += 1

            # ── post-game updates ──────────────────────────────────────────────
            margin = g["home_score"] - g["away_score"]
            dr = h.elo + ELO_HFA - a.elo
            shift = ELO_K * ((1.0 if home_won else 0.0) - 1 / (1 + 10 ** (-dr / 400)))
            h.elo += shift
            a.elo -= shift

            for tid, st, m in ((hid, h, margin), (aid, a, -margin)):
                st.rd = st.rd * GAME_DECAY + m
                st.rd_w = st.rd_w * GAME_DECAY + 1
                st.results.append((m > 0, m))
                log = tlogs.get(f"{tid}:{pk}", {})
                hit, pit = log.get("hit"), log.get("pit")
                if hit:
                    for k in ("ob", "pa", "tb", "ab"):
                        setattr(st, k, getattr(st, k) * GAME_DECAY)
                    st.ob += sum(int(hit.get(k, 0) or 0) for k in ("hits", "baseOnBalls", "hitByPitch"))
                    st.pa += sum(int(hit.get(k, 0) or 0) for k in ("atBats", "baseOnBalls", "hitByPitch", "sacFlies"))
                    st.tb += int(hit.get("totalBases", 0) or 0)
                    st.ab += int(hit.get("atBats", 0) or 0)
                sp_line = side[tid]["line"]
                if pit and sp_line:
                    bp_ip = max(0.0, _ip(pit.get("inningsPitched")) - sp_line["ip"])
                    bp_er = max(0, int(pit.get("earnedRuns", 0) or 0) - sp_line["er"])
                    st.bp_er = st.bp_er * BP_DECAY + bp_er
                    st.bp_ip = st.bp_ip * BP_DECAY + bp_ip
                    st.bp_usage.append((g["date"], bp_ip))
                if sp_line:
                    sps.update(side[tid]["sp"], sp_line)

        # names for probable starters without a line yet (debuts)
        for g in sched:
            for k in ("home", "away"):
                if g[f"{k}_sp"] and g[f"{k}_sp_name"]:
                    sps.name.setdefault(g[f"{k}_sp"], g[f"{k}_sp_name"])
        _progress(f"  {n_rows} training rows")

    for st in teams.values():
        st.new_season(CURRENT_SEASON)
    return pd.DataFrame(rows), teams, sps


# ── Season team stats (display + standings) ────────────────────────────────────

def get_pitcher_splits(team_id: int, season: int) -> tuple[float, float, float]:
    """Return (sp_era, bullpen_era, fip) for a team/season."""
    url = (
        f"https://statsapi.mlb.com/api/v1/stats"
        f"?stats=season&group=pitching&season={season}"
        f"&sportId=1&teamId={team_id}&gameType=R&limit=60"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CourtEdge/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception:
        return 4.50, 4.00, 4.20

    sp_er = sp_ip = 0.0
    bp_er = bp_ip = 0.0
    fip_hr = fip_bb = fip_hbp = fip_k = 0
    fip_ip = 0.0

    for group in data.get("stats", []):
        for split in group.get("splits", []):
            s      = split.get("stat", {})
            gs     = int(s.get("gamesStarted", 0) or 0)
            er     = int(s.get("earnedRuns",   0) or 0)
            hr     = int(s.get("homeRuns",     0) or 0)
            bb     = int(s.get("baseOnBalls",  0) or 0)
            hbp    = int(s.get("hitBatsmen",   0) or 0)
            k      = int(s.get("strikeOuts",   0) or 0)
            ip = _ip(s.get("inningsPitched"))
            if ip < 1.0:
                continue
            if gs >= 3:
                sp_er += er;  sp_ip += ip
            else:
                bp_er += er;  bp_ip += ip
            fip_hr  += hr
            fip_bb  += bb
            fip_hbp += hbp
            fip_k   += k
            fip_ip  += ip

    sp_era      = round(sp_er / sp_ip * 9, 2) if sp_ip > 0 else 4.50
    bullpen_era = round(bp_er / bp_ip * 9, 2) if bp_ip > 0 else 4.00
    if fip_ip > 0:
        raw_fip = (13 * fip_hr + 3 * (fip_bb + fip_hbp) - 2 * fip_k) / fip_ip + 3.10
        fip = round(max(1.0, min(raw_fip, 9.0)), 2)
    else:
        fip = 4.20
    return sp_era, bullpen_era, fip


def get_team_stats(team_id: int, season: int) -> dict:
    time.sleep(0.25)
    try:
        hit_raw = statsapi.get("team_stats", {
            "teamId": team_id, "stats": "season", "group": "hitting",
            "season": season, "sportIds": 1,
        })
        pit_raw = statsapi.get("team_stats", {
            "teamId": team_id, "stats": "season", "group": "pitching",
            "season": season, "sportIds": 1,
        })
        h = hit_raw["stats"][0]["splits"][0]["stat"] if hit_raw.get("stats") else {}
        p = pit_raw["stats"][0]["splits"][0]["stat"] if pit_raw.get("stats") else {}

        rs = _safe_float(h.get("runs"), 700.0)
        ra = _safe_float(p.get("runs"), 700.0)

        sp_era, bullpen_era, fip = get_pitcher_splits(team_id, season)

        return {
            "batting_avg":  _safe_float(h.get("avg"),                0.250),
            "ops":          _safe_float(h.get("ops"),                0.700),
            "obp":          _safe_float(h.get("obp"),                0.320),
            "slg":          _safe_float(h.get("slg"),                0.420),
            "runs_scored":  rs,
            "era":          _safe_float(p.get("era"),                4.50),
            "whip":         _safe_float(p.get("whip"),               1.30),
            "k_per9":       _safe_float(p.get("strikeoutsPer9Inn"),  8.0),
            "bb_per9":      _safe_float(p.get("walksPer9Inn"),       3.2),
            "sp_era":       sp_era,
            "bullpen_era":  bullpen_era,
            "fip":          fip,
            "runs_allowed": ra,
            "run_diff":     rs - ra,
        }
    except Exception as exc:
        _progress(f"    WARNING: stats fetch failed team_id={team_id} season={season}: {exc}")
        return {}


def build_current_stats(all_teams: dict[int, str], state: dict[int, TeamState],
                        season: int = CURRENT_SEASON) -> pd.DataFrame:
    """Season stats + W-L (display) merged with the model's current team state."""
    _progress(f"\nBuilding current-season team table ({season})...")

    wl_map: dict[int, tuple[int, int]] = {}
    try:
        standings = statsapi.standings_data(
            leagueId="103,104", season=season, standingsTypes="regularSeason"
        )
        for div in standings.values():
            for t in div["teams"]:
                wl_map[t["team_id"]] = (int(t.get("w", 0)), int(t.get("l", 0)))
    except Exception as exc:
        _progress(f"  WARNING: standings fetch failed: {exc}")

    # Bullpen fatigue is measured relative to today's games (US Eastern date)
    today = datetime.now(zoneinfo.ZoneInfo("America/New_York")).date().isoformat()

    rows: list[dict] = []
    for tid, tname in all_teams.items():
        s = get_team_stats(tid, season)
        if not s:
            continue
        w, l = wl_map.get(tid, (0, 0))
        gp = w + l
        st = state.get(tid, TeamState())
        l10, rd15 = st.form()
        s.update({
            "team_id":     tid,
            "team_name":   tname,
            "wins":        w,
            "losses":      l,
            "win_pct":     round(w / gp, 3) if gp else 0.500,
            "park_factor": PARK_FACTORS.get(tname, 1.0),
            "win_pct_last10":  l10,
            "run_diff_last15": rd15,
            # model state
            "elo":             round(st.elo, 1),
            "ops_ewm":         round(st.ops(), 4),
            "run_diff_ewm":    round(st.run_diff(), 3),
            "bullpen_era_ewm": round(st.bullpen_era(), 3),
            "bullpen_ip3":     round(st.bullpen_ip_before(today), 2),
            "state_date":      today,
        })
        rows.append(s)

    df = pd.DataFrame(rows)
    out = MLB_DIR / "mlb_stats_current.csv"
    df.to_csv(out, index=False)
    _progress(f"  Saved: {out}  ({len(df)} teams)")

    _progress("  Top-5 by Elo:")
    for _, r in df.sort_values("elo", ascending=False).head(5).iterrows():
        _progress(f"    {r['team_name']:24s} W={int(r['wins']):3d} L={int(r['losses']):3d}  Elo={r['elo']:.0f}  "
                  f"OPS~{r['ops_ewm']:.3f}  BP ERA~{r['bullpen_era_ewm']:.2f}  BP IP(3d)={r['bullpen_ip3']:.1f}")
    return df


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _progress("=" * 60)
    _progress("  MLB Data Pipeline  (v3 — game-by-game, leak-free)")
    _progress(f"  Data seasons     : {DATA_SEASONS[0]}-{DATA_SEASONS[-1]}")
    _progress(f"  Training seasons : {TRAIN_SEASONS[0]}-{TRAIN_SEASONS[-1]}")
    _progress("=" * 60)
    t0 = time.time()

    all_teams = get_all_teams()
    _progress(f"\nActive MLB teams : {len(all_teams)}")

    train_df, state, sps = build_features(all_teams)
    out = PROCESSED / "mlb_training_data.csv"
    train_df.to_csv(out, index=False)

    pr = pd.DataFrame([
        {"pitcher_id": pid, "name": sps.name.get(pid, ""), "sp_fip": round(sps.fip(pid), 3),
         "ip_weighted": round(sps.ip[pid], 1), "starts": sps.starts[pid]}
        for pid in sps.ip
    ]).sort_values("sp_fip")
    pr.to_csv(MLB_DIR / "mlb_pitcher_ratings.csv", index=False)
    _progress(f"\n  Saved: {MLB_DIR / 'mlb_pitcher_ratings.csv'}  ({len(pr)} starters)")

    build_current_stats(all_teams, state)

    elapsed = round(time.time() - t0)
    _progress(f"\n{'=' * 60}")
    _progress(f"  Done in {elapsed // 60}m {elapsed % 60}s")
    _progress(f"  Training rows  : {len(train_df):,}")
    _progress(f"  Win rate       : {train_df['win'].mean():.3f}  (should be ~0.500)")
    _progress(f"  Saved          : {out}")
    _progress(f"{'=' * 60}")
