#!/usr/bin/env python3
"""
NHL Data Pipeline — game by game, leak-free
Walks every NHL game since 2012-13 in date order, recording each team's state BEFORE the
game, and outputs:
  data/nhl/nhl_team_state.csv             — live team table: model state + display stats
  data/nhl/nhl_game_features_current.csv  — per-game feature rows for every current-season
                                            game (played → pre-game values, upcoming → latest)
  data/processed/nhl_training_data.csv    — labelled rows for model training

Source: ESPN's public scoreboard — goals by period, overtime / shootout, and each side's
goalie saves (so shots on goal) for every game. Months are cached under data/nhl/raw/; only
months of the current season are re-downloaded.

Features (one row per team per game, mirrored for the opponent):
  - Elo rating (margin-of-victory multiplier, 1/3 regression between seasons), run
    continuously since 2012-13 so there's no opening-night cold start
  - Recency-weighted goal differential per game (a shootout counts as a tie), carried across
    seasons and shrunk toward 0
  - Recency-weighted shot share (shots for / all shots): who controls play, less noisy than goals
  - Recency-weighted save percentage of the team's goalies
  - Rest days (capped) and second night of a back-to-back
  - Home ice (neutral sites — 2020 bubble, international games — count as away for both)

Run:
    python nhl/pipeline.py

Estimated runtime: ~3 min on first run (≈130 monthly scoreboards), <30 s after.
"""

import datetime
import json
import math
import time
import urllib.request
import zoneinfo
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

ROOT      = Path(__file__).parent.parent
NHL_DIR   = ROOT / "data" / "nhl"
RAW_DIR   = NHL_DIR / "raw"
PROCESSED = ROOT / "data" / "processed"
for _d in (NHL_DIR, RAW_DIR, PROCESSED):
    _d.mkdir(parents=True, exist_ok=True)

ET = zoneinfo.ZoneInfo("America/New_York")


def season_year(day: datetime.date) -> int:
    """ESPN's season year = the year the season ends (2026-27 → 2027); a new one from August."""
    return day.year + 1 if day.month >= 8 else day.year


TODAY          = datetime.datetime.now(ET).date()
CURRENT_SEASON = season_year(TODAY)
FIRST_SEASON   = 2013                                    # 2012-13: Elo / form burn-in
TRAIN_SEASONS  = list(range(2015, CURRENT_SEASON))       # 2014-15 … last season

SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard"
TEAMS_URL  = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/teams"
UA = {"User-Agent": "Mozilla/5.0"}

# Season types kept: 2 regular season, 3 playoffs
GAME_TYPES = {2, 3}
# Relocated franchises: ESPN id of the old team → id of the current one
FRANCHISE_IDS = {"24": "129764"}     # Arizona (Phoenix) Coyotes → Utah

# ── Model constants ─────────────────────────────────────────────────────────────
ELO_MEAN   = 1505.0
ELO_K      = 6.0
ELO_HFA    = 35.0     # home-ice bonus used only inside the Elo update
ELO_REVERT = 1 / 3    # fraction regressed to the mean between seasons

FORM_DECAY   = 0.95   # per-game weight decay (~14-game half-life): hockey results are noisy
SEASON_DECAY = 0.50   # extra decay at a season boundary
PRIOR_GAMES  = 8.0    # pseudo-games of an average team → shrinks early-season noise
LEAGUE_SV    = 0.905  # prior save percentage

MAX_REST = 4          # rest days are capped: opening night / long breaks count as fully rested

DIVISIONS = {
    "Atlantic":     {"BOS", "BUF", "DET", "FLA", "MTL", "OTT", "TB", "TOR"},
    "Metropolitan": {"CAR", "CBJ", "NJ", "NYI", "NYR", "PHI", "PIT", "WSH"},
    "Central":      {"CHI", "COL", "DAL", "MIN", "NSH", "STL", "UTAH", "WPG"},
    "Pacific":      {"ANA", "CGY", "EDM", "LA", "SJ", "SEA", "VAN", "VGK"},
}
EAST_DIVISIONS = {"Atlantic", "Metropolitan"}


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
    """{ESPN team id: {name, abbr, conference, division}} for the 32 franchises (current names)."""
    data = _get_json(TEAMS_URL)
    out = {}
    for t in data["sports"][0]["leagues"][0]["teams"]:
        t = t["team"]
        div = next((d for d, abbrs in DIVISIONS.items() if t["abbreviation"] in abbrs), "")
        out[str(t["id"])] = {"name": t["displayName"], "abbr": t["abbreviation"], "division": div,
                             "conference": "East" if div in EAST_DIVISIONS else "West"}
    return out


def _parse_event(ev: dict) -> dict | None:
    comp = (ev.get("competitions") or [{}])[0]
    sides = {c.get("homeAway"): c for c in comp.get("competitors", [])}
    if "home" not in sides or "away" not in sides:
        return None
    status = comp.get("status", {})
    st = status.get("type", {})
    season = ev.get("season") or {}

    def side(c: dict) -> dict:
        stats = {s["name"]: s.get("displayValue") for s in c.get("statistics", [])}
        try:
            score = int(c["score"]) if c.get("score") not in (None, "") else None
        except (TypeError, ValueError):
            score = None
        try:
            saves = int(stats["saves"]) if stats.get("saves") not in (None, "") else None
        except (TypeError, ValueError):
            saves = None
        tid = str(c.get("team", {}).get("id"))
        return {"id": FRANCHISE_IDS.get(tid, tid), "score": score, "saves": saves}

    return {
        "game_id":     str(ev.get("id")),
        "start_utc":   ev.get("date", ""),
        "season":      int(season.get("year") or 0),
        "season_type": int(season.get("type") or 0),
        "neutral":     bool(comp.get("neutralSite")),
        "completed":   bool(st.get("completed")),
        "status":      st.get("name", ""),
        "period":      int(status.get("period") or 0),
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
    """All NHL games (regular season, playoffs) since FIRST_SEASON, oldest first."""
    months, d = [], datetime.date(FIRST_SEASON - 1, 10, 1)
    last = datetime.date(CURRENT_SEASON, 6, 1)
    while d <= last:
        months.append((d.year, d.month))
        d = datetime.date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    # The 2020 playoffs ran in the Edmonton / Toronto bubbles through September
    months += [(2020, 7), (2020, 8), (2020, 9)]
    with ThreadPoolExecutor(max_workers=6) as ex:
        chunks = list(ex.map(_fetch_month, sorted(set(months))))
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
    return games


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
        """margin: home goals minus away goals (a shootout or overtime win is ±1)."""
        dr = self.rating[home] + (0.0 if neutral else ELO_HFA) - self.rating[away]
        exp_home = 1 / (1 + 10 ** (-dr / 400))
        winner_dr = dr if margin > 0 else -dr
        # Hockey margin multiplier (538's NHL Elo): grows slowly with the goal margin
        mult = (0.6686 * math.log(abs(margin)) + 0.8048) * 2.05 / (winner_dr * 0.001 + 2.05)
        shift = ELO_K * mult * ((1.0 if margin > 0 else 0.0) - exp_home)
        self.rating[home] += shift
        self.rating[away] -= shift


class Form:
    """Exponentially-weighted per-game values carried across seasons, each shrunk toward a
    league-average prior with PRIOR_GAMES pseudo-games."""
    PRIORS = {"margin": 0.0, "shot_share": 0.5, "sv_pct": LEAGUE_SV, "gf": 3.0, "ga": 3.0,
              "sf": 30.0, "sa": 30.0, "sos": 0.0}

    def __init__(self):
        self.sums: dict[str, dict[str, list[float]]] = {}
        self.season: dict[str, int] = {}

    def _team(self, team: str) -> dict[str, list[float]]:
        return self.sums.setdefault(team, {k: [0.0, 0.0] for k in self.PRIORS})

    def value(self, team: str, season: int) -> dict[str, float]:
        s = self._team(team)
        if team in self.season and self.season[team] != season:
            for v in s.values():
                v[0] *= SEASON_DECAY
                v[1] *= SEASON_DECAY
        self.season[team] = season
        return {k: (sx + PRIOR_GAMES * self.PRIORS[k]) / (sw + PRIOR_GAMES) for k, (sx, sw) in s.items()}

    def update(self, team: str, vals: dict[str, float | None]) -> None:
        for k, v in self._team(team).items():
            v[0] *= FORM_DECAY
            v[1] *= FORM_DECAY
            if vals.get(k) is not None:
                v[0] += vals[k]
                v[1] += 1.0


def _box(me: dict, opp: dict, shootout: bool, i_won: bool) -> dict[str, float | None]:
    """Per-game values from the scoreboard. Shots on goal = the other goalie's saves + goals
    (the shootout winner's extra goal isn't a real one)."""
    gf, ga = me["score"], opp["score"]
    if shootout:
        gf, ga = (gf - 1, ga) if i_won else (gf, ga - 1)
    out: dict[str, float | None] = {"margin": gf - ga, "gf": gf, "ga": ga}
    if me.get("saves") is not None and opp.get("saves") is not None:
        sf, sa = opp["saves"] + gf, me["saves"] + ga
        if sf + sa > 20:
            out.update(sf=sf, sa=sa, shot_share=sf / (sf + sa), sv_pct=me["saves"] / sa if sa else None)
    return out


# ── Feature builder ─────────────────────────────────────────────────────────────

def _rest(prev_date: str | None, date: str) -> int:
    if not prev_date:
        return MAX_REST
    days = (datetime.date.fromisoformat(date) - datetime.date.fromisoformat(prev_date)).days
    return max(1, min(days, MAX_REST))


def build_features(games: list[dict], teams: dict[str, dict]):
    """Walk every game chronologically, emitting pre-game feature rows (two per game), then
    updating all rolling state with the result.

    Returns (rows DataFrame, Elo, Form, current-season records, last game dates)."""
    elo, form = Elo(), Form()
    last_played: dict[str, str] = {}    # team → date of its last completed game
    last_listed: dict[str, str] = {}    # team → date of its previous game on the schedule
    record: dict[str, dict] = {}        # current regular season: W, L, OTL, streak, GF, GA
    rows: list[dict] = []

    for g in games:
        season, h_id, a_id = g["season"], g["home"]["id"], g["away"]["id"]
        home, away = teams[h_id]["name"], teams[a_id]["name"]
        date = g["date"]
        completed = (g["completed"] and g["home"]["score"] is not None and g["away"]["score"] is not None
                     and g["home"]["score"] != g["away"]["score"])

        elo_h, elo_a = elo.start_game(home, season), elo.start_game(away, season)
        f_h, f_a = form.value(home, season), form.value(away, season)
        prev = last_played if completed else last_listed
        rest_h, rest_a = _rest(prev.get(home), date), _rest(prev.get(away), date)

        margin_home = g["home"]["score"] - g["away"]["score"] if completed else None
        for team, opp, is_home, e_t, e_o, f_t, f_o, r_t, r_o in (
                (home, away, 1, elo_h, elo_a, f_h, f_a, rest_h, rest_a),
                (away, home, 0, elo_a, elo_h, f_a, f_h, rest_a, rest_h)):
            rows.append({
                "season": season, "season_type": g["season_type"], "game_date": date,
                "start_utc": g["start_utc"], "game_id": g["game_id"],
                "team": team, "opp": opp,
                "home": int(is_home and not g["neutral"]), "neutral": int(g["neutral"]),
                "elo": round(e_t, 1), "opp_elo": round(e_o, 1), "elo_diff": round(e_t - e_o, 1),
                "margin_ewm": round(f_t["margin"], 4), "opp_margin_ewm": round(f_o["margin"], 4),
                "margin_ewm_diff": round(f_t["margin"] - f_o["margin"], 4),
                "shot_share": round(f_t["shot_share"], 4), "opp_shot_share": round(f_o["shot_share"], 4),
                "shot_share_diff": round(f_t["shot_share"] - f_o["shot_share"], 4),
                "sv_pct": round(f_t["sv_pct"], 4), "opp_sv_pct": round(f_o["sv_pct"], 4),
                "sv_pct_diff": round(f_t["sv_pct"] - f_o["sv_pct"], 4),
                "rest_days": r_t, "opp_rest_days": r_o, "rest_diff": r_t - r_o,
                "b2b": int(r_t == 1), "opp_b2b": int(r_o == 1),
                "completed": int(completed),
                "overtime": int(completed and g["period"] > 3),
                "team_score": (g["home"]["score"] if is_home else g["away"]["score"]) if completed else None,
                "opp_score": (g["away"]["score"] if is_home else g["home"]["score"]) if completed else None,
                "win": (int((margin_home > 0) == bool(is_home)) if completed else None),
            })
        last_listed[home] = last_listed[away] = date

        if not completed:
            continue

        # ── Post-game state updates ────────────────────────────────────────────
        shootout = g["period"] >= 5 and g["season_type"] == 2
        elo.update(home, away, margin_home, g["neutral"])
        form.update(home, {**_box(g["home"], g["away"], shootout, margin_home > 0), "sos": f_a["margin"]})
        form.update(away, {**_box(g["away"], g["home"], shootout, margin_home < 0), "sos": f_h["margin"]})
        last_played[home] = last_played[away] = date
        if season == CURRENT_SEASON and g["season_type"] == 2:
            for team, m in ((home, margin_home), (away, -margin_home)):
                r = record.setdefault(team, {"wins": 0, "losses": 0, "otl": 0, "streak": 0, "gf": 0, "ga": 0})
                won = m > 0
                if won:
                    r["wins"] += 1
                elif g["period"] > 3:
                    r["otl"] += 1          # overtime / shootout loss: still a standings point
                else:
                    r["losses"] += 1
                r["streak"] = (max(r["streak"], 0) + 1) if won else (min(r["streak"], 0) - 1)
                goals = g["home"]["score"] if team == home else g["away"]["score"]
                r["gf"] += goals
                r["ga"] += goals - m
    return pd.DataFrame(rows), elo, form, record, last_played


def team_table(teams: dict[str, dict], elo: Elo, form: Form, record: dict, last_played: dict) -> pd.DataFrame:
    """Live team table for the API: model state plus display stats."""
    rows = []
    for tid, t in teams.items():
        name = t["name"]
        f = form.value(name, CURRENT_SEASON)
        r = record.get(name, {"wins": 0, "losses": 0, "otl": 0, "streak": 0, "gf": 0, "ga": 0})
        gp = r["wins"] + r["losses"] + r["otl"]
        rows.append({
            "team_name": name, "team_id": tid, "abbr": t["abbr"],
            "conference": t["conference"], "division": t["division"],
            "games_played": gp, "wins": r["wins"], "losses": r["losses"], "otl": r["otl"],
            "points": 2 * r["wins"] + r["otl"],
            "elo": round(elo.start_game(name, CURRENT_SEASON), 1),
            "margin_ewm": round(f["margin"], 4),
            "shot_share": round(f["shot_share"], 4), "sv_pct": round(f["sv_pct"], 4),
            # Recency-weighted per-game values, carried from last season
            "gf_ewm": round(f["gf"], 2), "ga_ewm": round(f["ga"], 2),
            "sf_ewm": round(f["sf"], 1), "sa_ewm": round(f["sa"], 1),
            "goal_diff": r["gf"] - r["ga"],
            "win_streak": r["streak"],
            "last_game_date": last_played.get(name, ""),
            "state_date": TODAY.isoformat(),
        })
    return pd.DataFrame(rows).sort_values("team_name")


if __name__ == "__main__":
    t0 = time.time()
    _progress("=" * 55)
    _progress(f"  NHL Data Pipeline - current season {CURRENT_SEASON - 1}-{str(CURRENT_SEASON)[-2:]}")
    _progress("=" * 55)

    teams = load_teams()
    _progress(f"\n{len(teams)} teams. Scoreboards {FIRST_SEASON - 1}-10 -> {CURRENT_SEASON}-06...")
    games = load_games(teams)
    done = sum(g["completed"] for g in games)
    _progress(f"  {len(games):,} games ({done:,} played)")

    _progress("\nBuilding features game by game...")
    rows, elo, form, record, last_played = build_features(games, teams)

    train = rows[rows["season"].isin(TRAIN_SEASONS) & (rows["completed"] == 1)].drop(columns=["completed"])
    train_path = PROCESSED / "nhl_training_data.csv"
    train.to_csv(train_path, index=False)
    _progress(f"  Training rows: {len(train):,} ({len(train) // 2:,} games, seasons "
              f"{TRAIN_SEASONS[0]}-{TRAIN_SEASONS[-1]}) -> {train_path.name}")

    cur = rows[rows["season"] == CURRENT_SEASON]
    cur_path = NHL_DIR / "nhl_game_features_current.csv"
    cur.to_csv(cur_path, index=False)
    _progress(f"  Current-season rows: {len(cur):,} ({int(cur['completed'].sum()) // 2} played) -> {cur_path.name}")

    table = team_table(teams, elo, form, record, last_played)
    state_path = NHL_DIR / "nhl_team_state.csv"
    table.to_csv(state_path, index=False)
    _progress(f"  -> {state_path.name}")
    for _, r in table.sort_values("elo", ascending=False).head(5).iterrows():
        _progress(f"    {r['team_name']:26s} Elo={r['elo']:.0f}  goals~{r['margin_ewm']:+.2f}  "
                  f"shots~{r['shot_share']:.3f}  sv~{r['sv_pct']:.3f}  {r['wins']}-{r['losses']}-{r['otl']}")
    _progress(f"\nDone in {time.time() - t0:.0f}s")
