#!/usr/bin/env python3
"""
NBA Data Pipeline — game by game, leak-free
Walks every NBA game since 2012-13 in date order, recording each team's state BEFORE the
game, and outputs:
  data/nba/nba_team_state.csv             — live team table: model state + display stats
  data/nba/nba_game_features_current.csv  — per-game feature rows for every current-season
                                            game (played → pre-game values, upcoming → latest)
  data/nba/nba_roster_history.csv         — daily roster ratings of the current season
  data/processed/nba_training_data.csv    — labelled rows for model training

Source: ESPN's public scoreboard (stats.nba.com blocks cloud hosts such as GitHub Actions
and Render) — scores and shooting totals for every game — plus ESPN season team stats
(turnovers, offensive rebounds) for the display table. Months are cached under
data/nba/raw/; only months of the current season are re-downloaded.

Features (one row per team per game, mirrored for the opponent):
  - Elo rating (538-style: margin-of-victory multiplier, 1/4 regression between seasons),
    run continuously since 2012-13 so there's no opening-night cold start
  - Recency-weighted point margin per game, carried across seasons and shrunk toward 0
  - Rest days (capped) and second night of a back-to-back
  - Roster rating: last season's per-minute Game Score of the players on the roster, weighted
    by expected minutes (this season: today's rosters, one snapshot a day; past seasons: the
    players each team finished with) — so summer moves count from opening night
  - Home court (neutral sites — 2020 bubble, international games — count as away for both)

Run:
    python nba/pipeline.py

Estimated runtime: ~3 min on first run (≈170 monthly scoreboards), <30 s after.
"""

import datetime
import json
import time
import urllib.request
import zoneinfo
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

ROOT      = Path(__file__).parent.parent
NBA_DIR   = ROOT / "data" / "nba"
RAW_DIR   = NBA_DIR / "raw"
PROCESSED = ROOT / "data" / "processed"
for _d in (NBA_DIR, RAW_DIR, PROCESSED):
    _d.mkdir(parents=True, exist_ok=True)

ET = zoneinfo.ZoneInfo("America/New_York")


def season_year(day: datetime.date) -> int:
    """ESPN's season year = the year the season ends (2026-27 → 2027); a new one from August."""
    return day.year + 1 if day.month >= 8 else day.year


TODAY          = datetime.datetime.now(ET).date()
CURRENT_SEASON = season_year(TODAY)
FIRST_SEASON   = 2013                                    # 2012-13: Elo / margin burn-in
TRAIN_SEASONS  = list(range(2016, CURRENT_SEASON))       # 2015-16 … last season

SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
TEAMS_URL  = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams"
TEAM_STATS = ("https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/seasons/{season}"
              "/types/2/teams/{team_id}/statistics")
ROSTER_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/roster"
PLAYERS_URL = ("https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/statistics/byathlete"
               "?isqualified=false&limit=1000&season={season}&seasontype=2&sort=general.avgMinutes:desc")
ROSTER_HISTORY = NBA_DIR / "nba_roster_history.csv"
UA = {"User-Agent": "Mozilla/5.0"}

# Season types kept: 2 regular season, 3 playoffs, 5 play-in
GAME_TYPES = {2, 3, 5}
BUBBLE_START = "2020-07-01"

# ── Model constants ─────────────────────────────────────────────────────────────
ELO_MEAN   = 1505.0
ELO_K      = 20.0
ELO_HFA    = 100.0    # home-court bonus used only inside the Elo update
ELO_REVERT = 1 / 4    # fraction regressed to the mean between seasons

FORM_DECAY   = 0.93   # per-game weight decay (~10-game half-life)
SEASON_DECAY = 0.50   # extra decay at a season boundary
PRIOR_GAMES  = 4.0    # pseudo-games of a 0 margin → shrinks early-season noise

MAX_REST = 4          # rest days are capped: opening night / long breaks count as fully rested
# Possessions ≈ FGA + 0.44·FTA − OREB + TOV; the scoreboard has no OREB / TOV, whose gap is
# about this many per game in recent seasons
TOV_MINUS_OREB = 3.5

# Roster rating: last season's per-minute Game Score of the players on the roster, weighted by
# their expected minutes. Players with few minutes are pulled toward replacement level.
PLAYER_PRIOR_MIN = 600.0   # minutes of replacement-level play mixed into every player's rate
REPLACEMENT_PCTL = 0.20    # replacement level = this percentile among players with 500+ minutes
ROOKIE_MPG       = 10.0    # expected minutes per game for a player with no NBA minutes last season
MAX_MPG          = 36.0
TEAM_MINUTES     = 240.0   # 5 players × 48 minutes

EAST = {"ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DET", "IND", "MIA", "MIL", "NY", "ORL", "PHI", "TOR", "WSH"}
_PLAYER_KEYS = {"gamesPlayed", "minutes", "points", "fieldGoalsMade", "fieldGoalsAttempted", "freeThrowsMade",
                "freeThrowsAttempted", "rebounds", "assists", "steals", "blocks", "fouls", "turnovers"}

_STAT_KEYS = {"fieldGoalsAttempted": "fga", "fieldGoalsMade": "fgm", "freeThrowsAttempted": "fta",
              "freeThrowsMade": "ftm", "threePointFieldGoalsAttempted": "fg3a",
              "threePointFieldGoalsMade": "fg3m"}


def _progress(msg: str) -> None:
    print(msg, flush=True)


def _get_json(url: str, retries: int = 3) -> dict:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(1.5 * (attempt + 1))
    return {}


# ── Data loading ────────────────────────────────────────────────────────────────

def load_teams() -> dict[str, dict]:
    """{ESPN team id: {name, abbr, conference}} for the 30 franchises (current names)."""
    data = _get_json(TEAMS_URL)
    out = {}
    for t in data["sports"][0]["leagues"][0]["teams"]:
        t = t["team"]
        out[str(t["id"])] = {"name": t["displayName"], "abbr": t["abbreviation"],
                             "conference": "East" if t["abbreviation"] in EAST else "West"}
    return out


def _parse_event(ev: dict) -> dict | None:
    comp = (ev.get("competitions") or [{}])[0]
    sides = {c.get("homeAway"): c for c in comp.get("competitors", [])}
    if "home" not in sides or "away" not in sides:
        return None
    st = comp.get("status", {}).get("type", {})
    season = ev.get("season") or {}

    def side(c: dict) -> dict:
        stats = {_STAT_KEYS[s["name"]]: float(s.get("displayValue") or 0)
                 for s in c.get("statistics", []) if s.get("name") in _STAT_KEYS}
        try:
            score = int(c["score"]) if c.get("score") not in (None, "") else None
        except (TypeError, ValueError):
            score = None
        return {"id": str(c.get("team", {}).get("id")), "score": score, **stats}

    return {
        "game_id":     str(ev.get("id")),
        "start_utc":   ev.get("date", ""),
        "season":      int(season.get("year") or 0),
        "season_type": int(season.get("type") or 0),
        "neutral":     bool(comp.get("neutralSite")),
        "completed":   bool(st.get("completed")),
        "status":      st.get("name", ""),
        "home":        side(sides["home"]),
        "away":        side(sides["away"]),
    }


def _fetch_month(ym: tuple[int, int]) -> list[dict]:
    """Every game ESPN lists in a month; past seasons are cached for good."""
    y, m = ym
    path = RAW_DIR / f"scoreboard_{y}{m:02d}.json"
    month_season = season_year(datetime.date(y, m, 1))
    if path.exists() and month_season < CURRENT_SEASON:
        return json.loads(path.read_text(encoding="utf-8"))
    data = _get_json(f"{SCOREBOARD}?dates={y}{m:02d}&limit=1000")
    games = [g for g in (_parse_event(e) for e in data.get("events", [])) if g]
    path.write_text(json.dumps(games), encoding="utf-8")
    return games


def load_games(teams: dict[str, dict]) -> list[dict]:
    """All NBA games (regular season, play-in, playoffs) since FIRST_SEASON, oldest first."""
    months, d = [], datetime.date(FIRST_SEASON - 1, 10, 1)
    last = datetime.date(CURRENT_SEASON, 6, 1)
    while d <= last:
        months.append((d.year, d.month))
        d = datetime.date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    with ThreadPoolExecutor(max_workers=6) as ex:
        chunks = list(ex.map(_fetch_month, months))
    by_id: dict[str, dict] = {}
    for chunk in chunks:
        for g in chunk:
            if (g["season"] >= FIRST_SEASON and g["season_type"] in GAME_TYPES
                    and g["home"]["id"] in teams and g["away"]["id"] in teams
                    and g["status"] not in ("STATUS_POSTPONED", "STATUS_CANCELED")):
                by_id[g["game_id"]] = g
    games = sorted(by_id.values(), key=lambda g: (g["start_utc"], g["game_id"]))
    for g in games:
        start = datetime.datetime.fromisoformat(g["start_utc"].replace("Z", "+00:00"))
        g["date"] = start.astimezone(ET).date().isoformat()
        # ESPN doesn't flag the 2020 Orlando bubble (restart from July 30) as neutral
        if g["season"] == 2020 and g["date"] >= BUBBLE_START:
            g["neutral"] = True
    return games


def load_season_team_stats(teams: dict[str, dict]) -> dict[str, dict]:
    """{team id: turnover / offensive-rebound rates}, this season blended with last season by
    games played (10 games of last season as a prior) — for the display table only."""
    def one(args: tuple[str, int]) -> tuple[str, int, dict]:
        tid, season = args
        try:
            data = _get_json(TEAM_STATS.format(season=season, team_id=tid), retries=2)
        except Exception:
            return tid, season, {}
        vals = {s["name"]: float(s.get("value") or 0)
                for c in data.get("splits", {}).get("categories", []) for s in c.get("stats", [])}
        return tid, season, vals

    jobs = [(tid, s) for tid in teams for s in (CURRENT_SEASON, CURRENT_SEASON - 1)]
    with ThreadPoolExecutor(max_workers=8) as ex:
        res = {(tid, s): v for tid, s, v in ex.map(one, jobs)}
    out = {}
    for tid in teams:
        cur, prev = res.get((tid, CURRENT_SEASON), {}), res.get((tid, CURRENT_SEASON - 1), {})
        n_cur, n_prev = cur.get("gamesPlayed", 0.0), min(prev.get("gamesPlayed", 0.0), 10.0)

        def blend(key: str) -> float | None:
            parts = [(v[key], w) for v, w in ((cur, n_cur), (prev, n_prev)) if w and key in v]
            return sum(x * w for x, w in parts) / sum(w for _, w in parts) if parts else None

        tov_ratio, oreb_pct = blend("turnoverRatio"), blend("offensiveReboundPct")
        out[tid] = {"tov_pct": None if tov_ratio is None else tov_ratio / 100, "oreb_pct": oreb_pct}
    return out


# ── Roster ratings ──────────────────────────────────────────────────────────────

def load_player_season(season: int) -> pd.DataFrame:
    """Every player's regular-season totals and team (his team at the end of that season)."""
    path = RAW_DIR / f"players_{season}.json"
    if path.exists() and season < CURRENT_SEASON:
        rows = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = _get_json(PLAYERS_URL.format(season=season))
        names = {c["name"]: c.get("names", []) for c in data.get("categories", [])}
        rows = []
        for a in data.get("athletes", []):
            ath = a.get("athlete", {})
            row = {"id": str(ath.get("id")), "name": ath.get("displayName"), "team": ath.get("teamShortName", "")}
            for c in a.get("categories", []):
                for n, v in zip(names.get(c["name"], []), c.get("totals", [])):
                    if n in _PLAYER_KEYS:
                        try:
                            row[n] = float(str(v).replace(",", ""))
                        except ValueError:
                            row[n] = 0.0
            rows.append(row)
        path.write_text(json.dumps(rows), encoding="utf-8")
    df = pd.DataFrame(rows)
    for k in _PLAYER_KEYS:
        df[k] = df[k].fillna(0.0) if k in df else 0.0
    return df


def player_ratings(prev: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    """(per-player rate + expected minutes for next season, replacement rate) from one season.
    Rate = Hollinger Game Score per minute, shrunk toward replacement level."""
    gs = (prev.points + 0.4 * prev.fieldGoalsMade - 0.7 * prev.fieldGoalsAttempted
          - 0.4 * (prev.freeThrowsAttempted - prev.freeThrowsMade) + 0.4 * prev.rebounds + prev.steals
          + 0.7 * prev.assists + 0.7 * prev.blocks - 0.4 * prev.fouls - prev.turnovers)
    raw = gs / prev.minutes.clip(lower=1)
    repl = float(raw[prev.minutes >= 500].quantile(REPLACEMENT_PCTL))
    out = pd.DataFrame({
        "id":      prev["id"],
        "rate":    (gs + PLAYER_PRIOR_MIN * repl) / (prev.minutes + PLAYER_PRIOR_MIN),
        # Minutes per game played: a player who missed games through injury keeps his role
        "exp_min": (prev.minutes / prev.gamesPlayed.clip(lower=1)).clip(upper=MAX_MPG),
    })
    return out, repl


def roster_ratings(roster: pd.DataFrame, ratings: pd.DataFrame, repl: float,
                   teams: dict[str, dict]) -> dict[str, float]:
    """{team name: roster rating} for a roster (id, team abbr), centered on the league average.
    The 240 minutes of a game go down the rotation (most expected minutes first); minutes the
    roster can't fill are played at replacement level."""
    m = roster.merge(ratings, on="id", how="left")
    m["rate"] = m["rate"].fillna(repl)
    m["exp_min"] = m["exp_min"].fillna(ROOKIE_MPG)
    abbr_to_name = {t["abbr"]: t["name"] for t in teams.values()}
    out = {}
    for abbr, g in m.groupby("team"):
        if abbr not in abbr_to_name:
            continue
        g = g.sort_values(["exp_min", "rate"], ascending=False)
        before = g.exp_min.cumsum() - g.exp_min                 # minutes already handed out
        mins = (TEAM_MINUTES - before).clip(lower=0).clip(upper=g.exp_min)
        out[abbr_to_name[abbr]] = (float((mins * g.rate).sum()) + (TEAM_MINUTES - mins.sum()) * repl) / TEAM_MINUTES
    mean = sum(out.values()) / len(out)
    return {t: round(v - mean, 4) for t, v in out.items()}


def load_current_rosters(teams: dict[str, dict]) -> pd.DataFrame:
    """Today's rosters (player id, team abbr) from ESPN."""
    def one(tid: str) -> list[dict]:
        data = _get_json(ROSTER_URL.format(team_id=tid))
        return [{"id": str(p["id"]), "team": teams[tid]["abbr"]} for p in data.get("athletes", [])]
    with ThreadPoolExecutor(max_workers=8) as ex:
        return pd.DataFrame([r for rows in ex.map(one, teams) for r in rows])


def season_roster_ratings(teams: dict[str, dict]) -> dict[int, dict[str, float]]:
    """{season: {team: roster rating}} for past seasons: the season's players (by the team they
    finished it with) rated on the season before."""
    out, prev = {}, load_player_season(FIRST_SEASON - 1)
    for season in range(FIRST_SEASON, CURRENT_SEASON):
        cur = load_player_season(season)
        ratings, repl = player_ratings(prev)
        out[season] = roster_ratings(cur[["id", "team"]], ratings, repl, teams)
        prev = cur
    return out


def current_roster_history(teams: dict[str, dict]) -> pd.DataFrame:
    """Daily roster ratings of the current season (date, team, roster), today's added: a played
    game is rated with the roster of its own day, never a later one."""
    ratings, repl = player_ratings(load_player_season(CURRENT_SEASON - 1))
    today = roster_ratings(load_current_rosters(teams), ratings, repl, teams)
    hist = pd.read_csv(ROSTER_HISTORY) if ROSTER_HISTORY.exists() else pd.DataFrame(columns=["date", "team", "roster"])
    hist = hist[(hist["date"] != TODAY.isoformat()) & (hist["date"] >= f"{CURRENT_SEASON - 1}-08-01")]
    new = pd.DataFrame({"date": TODAY.isoformat(), "team": list(today), "roster": list(today.values())})
    return pd.concat([hist, new], ignore_index=True).sort_values(["date", "team"])


def roster_lookup(by_season: dict[int, dict[str, float]], history: pd.DataFrame):
    """roster(season, team, date) → rating: by season in the past, by day this season (the
    latest snapshot on or before the date; the first one for games before it existed)."""
    snaps = {d: dict(zip(g["team"], g["roster"])) for d, g in history.groupby("date")}
    days = sorted(snaps)

    def get(season: int, team: str, date: str) -> float:
        if season < CURRENT_SEASON:
            return by_season.get(season, {}).get(team, 0.0)
        earlier = [d for d in days if d <= date]
        return snaps[earlier[-1] if earlier else days[0]].get(team, 0.0)
    return get


# ── Rolling state trackers ──────────────────────────────────────────────────────

class Elo:
    def __init__(self):
        self.rating: dict[str, float] = {}
        self.season: dict[str, int] = {}

    def start_game(self, team: str, season: int) -> float:
        r = self.rating.get(team, ELO_MEAN)
        if team in self.season and self.season[team] != season:
            r = r * (1 - ELO_REVERT) + ELO_MEAN * ELO_REVERT
        self.rating[team], self.season[team] = r, season
        return r

    def update(self, home: str, away: str, margin: int, neutral: bool) -> None:
        dr = self.rating[home] + (0.0 if neutral else ELO_HFA) - self.rating[away]
        exp_home = 1 / (1 + 10 ** (-dr / 400))
        winner_dr = dr if margin > 0 else -dr
        mult = (abs(margin) + 3) ** 0.8 / (7.5 + 0.006 * winner_dr)
        shift = ELO_K * mult * ((1.0 if margin > 0 else 0.0) - exp_home)
        self.rating[home] += shift
        self.rating[away] -= shift


class Form:
    """Exponentially-weighted per-game averages carried across seasons.
    `margin` is shrunk toward 0 with PRIOR_GAMES pseudo-games; the rest are plain averages."""
    KEYS = ("margin", "ortg", "drtg", "pace", "ts", "fg3_rate", "ftr", "sos")

    def __init__(self):
        self.sums: dict[str, dict[str, list[float]]] = {}
        self.season: dict[str, int] = {}

    def _team(self, team: str) -> dict[str, list[float]]:
        return self.sums.setdefault(team, {k: [0.0, 0.0] for k in self.KEYS})

    def value(self, team: str, season: int) -> dict[str, float | None]:
        s = self._team(team)
        if team in self.season and self.season[team] != season:
            for v in s.values():
                v[0] *= SEASON_DECAY
                v[1] *= SEASON_DECAY
        self.season[team] = season
        out = {k: (sx / sw if sw else None) for k, (sx, sw) in s.items()}
        out["margin"] = s["margin"][0] / (s["margin"][1] + PRIOR_GAMES)
        return out

    def update(self, team: str, vals: dict[str, float]) -> None:
        for k, v in self._team(team).items():
            v[0] *= FORM_DECAY
            v[1] *= FORM_DECAY
            if vals.get(k) is not None:
                v[0] += vals[k]
                v[1] += 1.0


def _box(me: dict, opp: dict) -> dict[str, float | None]:
    """Per-game efficiency from the scoreboard totals."""
    if not me.get("fga") or not opp.get("fga"):
        return {"margin": me["score"] - opp["score"]}
    poss = ((me["fga"] + 0.44 * me["fta"] + TOV_MINUS_OREB) + (opp["fga"] + 0.44 * opp["fta"] + TOV_MINUS_OREB)) / 2
    return {
        "margin":   me["score"] - opp["score"],
        "ortg":     100 * me["score"] / poss,
        "drtg":     100 * opp["score"] / poss,
        "pace":     poss,
        "ts":       me["score"] / (2 * (me["fga"] + 0.44 * me["fta"])),
        "fg3_rate": me["fg3a"] / me["fga"],
        "ftr":      me["fta"] / me["fga"],
    }


# ── Feature builder ─────────────────────────────────────────────────────────────

def _rest(prev_date: str | None, date: str) -> int:
    if not prev_date:
        return MAX_REST
    days = (datetime.date.fromisoformat(date) - datetime.date.fromisoformat(prev_date)).days
    return max(1, min(days, MAX_REST))


def build_features(games: list[dict], teams: dict[str, dict], roster):
    """Walk every game chronologically, emitting pre-game feature rows (two per game), then
    updating all rolling state with the result. `roster(season, team, date)` gives the roster
    rating (see roster_lookup).

    Returns (rows DataFrame, Elo, Form, current-season records)."""
    elo, form = Elo(), Form()
    last_played: dict[str, str] = {}    # team → date of its last completed game
    last_listed: dict[str, str] = {}    # team → date of its previous game on the schedule
    record: dict[str, dict] = {}        # current regular season: wins, losses, streak, pf, pa
    rows: list[dict] = []

    for g in games:
        season, h_id, a_id = g["season"], g["home"]["id"], g["away"]["id"]
        home, away = teams[h_id]["name"], teams[a_id]["name"]
        date = g["date"]
        completed = g["completed"] and g["home"]["score"] is not None and g["away"]["score"] is not None

        elo_h, elo_a = elo.start_game(home, season), elo.start_game(away, season)
        f_h, f_a = form.value(home, season), form.value(away, season)
        # Played games: rest since the last game; upcoming ones: since the previous scheduled game
        prev = last_played if completed else last_listed
        rest_h, rest_a = _rest(prev.get(home), date), _rest(prev.get(away), date)

        margin_home = g["home"]["score"] - g["away"]["score"] if completed else None
        ros_h, ros_a = roster(season, home, date), roster(season, away, date)
        for team, opp, is_home, e_t, e_o, f_t, f_o, r_t, r_o, ro_t, ro_o in (
                (home, away, 1, elo_h, elo_a, f_h, f_a, rest_h, rest_a, ros_h, ros_a),
                (away, home, 0, elo_a, elo_h, f_a, f_h, rest_a, rest_h, ros_a, ros_h)):
            rows.append({
                "season": season, "season_type": g["season_type"], "game_date": date,
                "start_utc": g["start_utc"], "game_id": g["game_id"],
                "team": team, "opp": opp,
                "home": int(is_home and not g["neutral"]), "neutral": int(g["neutral"]),
                "elo": round(e_t, 1), "opp_elo": round(e_o, 1), "elo_diff": round(e_t - e_o, 1),
                "margin_ewm": round(f_t["margin"], 3), "opp_margin_ewm": round(f_o["margin"], 3),
                "margin_ewm_diff": round(f_t["margin"] - f_o["margin"], 3),
                "rest_days": r_t, "opp_rest_days": r_o, "rest_diff": r_t - r_o,
                "b2b": int(r_t == 1), "opp_b2b": int(r_o == 1),
                "roster": ro_t, "opp_roster": ro_o, "roster_diff": round(ro_t - ro_o, 4),
                "completed": int(completed),
                "team_score": (g["home"]["score"] if is_home else g["away"]["score"]) if completed else None,
                "opp_score": (g["away"]["score"] if is_home else g["home"]["score"]) if completed else None,
                "win": (int((margin_home > 0) == bool(is_home)) if completed else None),
            })
        last_listed[home] = last_listed[away] = date

        if not completed:
            continue

        # ── Post-game state updates ────────────────────────────────────────────
        elo.update(home, away, margin_home, g["neutral"])
        box_h, box_a = _box(g["home"], g["away"]), _box(g["away"], g["home"])
        form.update(home, {**box_h, "sos": f_a["margin"]})
        form.update(away, {**box_a, "sos": f_h["margin"]})
        last_played[home] = last_played[away] = date
        if season == CURRENT_SEASON and g["season_type"] == 2:
            for team, m in ((home, margin_home), (away, -margin_home)):
                r = record.setdefault(team, {"wins": 0, "losses": 0, "streak": 0, "pf": 0, "pa": 0})
                won = m > 0
                r["wins" if won else "losses"] += 1
                r["streak"] = (max(r["streak"], 0) + 1) if won else (min(r["streak"], 0) - 1)
                pts = g["home"]["score"] if team == home else g["away"]["score"]
                r["pf"] += pts
                r["pa"] += pts - m
    return pd.DataFrame(rows), elo, form, record, last_played


def team_table(teams: dict[str, dict], elo: Elo, form: Form, record: dict, last_played: dict,
               season_stats: dict[str, dict], roster_today: dict[str, float]) -> pd.DataFrame:
    """Live team table for the API: model state plus the display stats of the game page."""
    rows = []
    for tid, t in teams.items():
        name = t["name"]
        f = form.value(name, CURRENT_SEASON)
        r = record.get(name, {"wins": 0, "losses": 0, "streak": 0, "pf": 0, "pa": 0})
        gp = r["wins"] + r["losses"]
        ss = season_stats.get(tid, {})
        rows.append({
            "team_name": name, "team_id": tid, "abbr": t["abbr"], "conference": t["conference"],
            "games_played": gp, "wins": r["wins"], "losses": r["losses"],
            "win_pct": round(r["wins"] / gp, 3) if gp else 0.0,
            "elo": round(elo.start_game(name, CURRENT_SEASON), 1),
            "margin_ewm": round(f["margin"], 3),
            "roster": roster_today.get(name, 0.0),
            # Recency-weighted ratings (per 100 estimated possessions), carried from last season
            "off_rtg": round(f["ortg"], 1), "def_rtg": round(f["drtg"], 1),
            "net_rtg": round(f["ortg"] - f["drtg"], 1), "pace": round(f["pace"], 1),
            "ts_pct": round(f["ts"], 4), "fg3_rate": round(f["fg3_rate"], 4), "ftr": round(f["ftr"], 4),
            "srs": round(f["margin"] + (f["sos"] or 0.0), 2),
            "tov_pct": None if ss.get("tov_pct") is None else round(ss["tov_pct"], 4),
            "oreb_pct": None if ss.get("oreb_pct") is None else round(ss["oreb_pct"], 4),
            "point_diff": round((r["pf"] - r["pa"]) / gp, 1) if gp else 0.0,
            "win_streak": r["streak"],
            "last_game_date": last_played.get(name, ""),
            "state_date": TODAY.isoformat(),
        })
    return pd.DataFrame(rows).sort_values("team_name")


if __name__ == "__main__":
    t0 = time.time()
    _progress("=" * 55)
    _progress(f"  NBA Data Pipeline - current season {CURRENT_SEASON - 1}-{str(CURRENT_SEASON)[-2:]}")
    _progress("=" * 55)

    teams = load_teams()
    _progress(f"\n{len(teams)} teams. Scoreboards {FIRST_SEASON - 1}-10 -> {CURRENT_SEASON}-06...")
    games = load_games(teams)
    done = sum(g["completed"] for g in games)
    _progress(f"  {len(games):,} games ({done:,} played)")

    _progress("\nRoster ratings (player stats by season, today's rosters)...")
    by_season = season_roster_ratings(teams)
    history = current_roster_history(teams)
    history.to_csv(ROSTER_HISTORY, index=False)
    roster = roster_lookup(by_season, history)
    roster_today = {t["name"]: roster(CURRENT_SEASON, t["name"], TODAY.isoformat()) for t in teams.values()}
    best = sorted(roster_today.items(), key=lambda x: -x[1])[:3]
    _progress("  Best rosters today: " + ", ".join(f"{t} {v:+.3f}" for t, v in best))

    _progress("\nBuilding features game by game...")
    rows, elo, form, record, last_played = build_features(games, teams, roster)

    train = rows[rows["season"].isin(TRAIN_SEASONS) & (rows["completed"] == 1)].drop(columns=["completed"])
    train_path = PROCESSED / "nba_training_data.csv"
    train.to_csv(train_path, index=False)
    _progress(f"  Training rows: {len(train):,} ({len(train) // 2:,} games, seasons "
              f"{TRAIN_SEASONS[0]}-{TRAIN_SEASONS[-1]}) -> {train_path.name}")

    cur = rows[rows["season"] == CURRENT_SEASON]
    cur_path = NBA_DIR / "nba_game_features_current.csv"
    cur.to_csv(cur_path, index=False)
    _progress(f"  Current-season rows: {len(cur):,} ({int(cur['completed'].sum()) // 2} played) -> {cur_path.name}")

    _progress("\nSeason team stats (turnovers, offensive rebounds)...")
    table = team_table(teams, elo, form, record, last_played, load_season_team_stats(teams), roster_today)
    state_path = NBA_DIR / "nba_team_state.csv"
    table.to_csv(state_path, index=False)
    _progress(f"  -> {state_path.name}")
    for _, r in table.sort_values("elo", ascending=False).head(5).iterrows():
        _progress(f"    {r['team_name']:26s} Elo={r['elo']:.0f}  margin~{r['margin_ewm']:+.1f}  "
                  f"net~{r['net_rtg']:+.1f}  {r['wins']}-{r['losses']}")
    _progress(f"\nDone in {time.time() - t0:.0f}s")
