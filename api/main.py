"""
NBA Playoff Predictor API

Endpoints:
  GET  /api/teams          — list of 30 teams
  GET  /api/today          — today's games with auto-predictions
  POST /api/predict        — series + game-by-game prediction for any matchup

Usage:
    uvicorn api.main:app --reload --reload-dir api
"""

import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

ROOT                = Path(__file__).parent.parent
MODEL_PATH          = ROOT / "models" / "logistic_regression.pkl"
STATS_PATH          = ROOT / "data" / "raw" / "reg_season_2025_26.csv"
PLAYOFF_STATS_PATH  = ROOT / "data" / "raw" / "playoff_stats_2024_25.csv"
# Order must match train.py FEATURES exactly
FEATURES = [
    "off_rtg", "def_rtg", "net_rtg", "pace", "rest_days",
    "ts_pct", "tov_pct", "oreb_pct", "home",
    "win_streak", "srs", "point_diff", "fg3_rate", "ftr",
    "back_to_back", "travel_km", "prev_margin",
    "playoff_net_rtg",
    "win_pct_last10", "net_rtg_last15", "opp_3pt_pct_allowed", "bench_net_rtg",
    "net_rtg_diff", "off_vs_def_diff", "pace_diff", "srs_diff",
    "series_wins", "elimination_game",
]
_CONTEXT_FEATURES = {
    "home", "back_to_back", "travel_km", "prev_margin", "series_wins", "elimination_game",
    "net_rtg_diff", "off_vs_def_diff", "pace_diff", "srs_diff",
}
# Features read directly from the stats CSV (context + differentials injected separately)
STAT_FEATURES = [f for f in FEATURES if f not in _CONTEXT_FEATURES]
# 2-2-1-1-1 format: True = team_a (higher seed) is home
HOME_SCHEDULE = [True, True, False, False, True, False, True]

# Arena coordinates (lat, lon) for travel distance calculation
ARENA_COORDS = {
    "ATL": (33.757, -84.396), "BOS": (42.366, -71.062), "BKN": (40.683, -73.975),
    "CHA": (35.225, -80.839), "CHI": (41.881, -87.674), "CLE": (41.497, -81.688),
    "DAL": (32.790, -96.810), "DEN": (39.749, -105.008), "DET": (42.341, -83.055),
    "GSW": (37.768, -122.387), "HOU": (29.751, -95.362), "IND": (39.764, -86.156),
    "LAC": (33.942, -118.339), "LAL": (34.043, -118.267), "MEM": (35.138, -90.051),
    "MIA": (25.781, -80.187), "MIL": (43.045, -87.917), "MIN": (44.979, -93.276),
    "NOP": (29.949, -90.082), "NYK": (40.751, -73.993), "OKC": (35.463, -97.515),
    "ORL": (28.539, -81.384), "PHI": (39.901, -75.172), "PHX": (33.446, -112.071),
    "POR": (45.532, -122.667), "SAC": (38.580, -121.500), "SAS": (29.427, -98.437),
    "TOR": (43.643, -79.379), "UTA": (40.768, -111.901), "WAS": (38.898, -77.021),
}

# ESPN team IDs — used to fetch live injury reports
ESPN_TEAM_IDS: dict[str, int] = {
    "Atlanta Hawks": 1,         "Boston Celtics": 2,          "New Orleans Pelicans": 3,
    "Chicago Bulls": 4,         "Cleveland Cavaliers": 5,     "Dallas Mavericks": 6,
    "Denver Nuggets": 7,        "Detroit Pistons": 8,         "Golden State Warriors": 9,
    "Houston Rockets": 10,      "Indiana Pacers": 11,         "LA Clippers": 12,
    "Los Angeles Clippers": 12, "Los Angeles Lakers": 13,     "LA Lakers": 13,
    "Miami Heat": 14,           "Milwaukee Bucks": 15,        "Minnesota Timberwolves": 16,
    "Brooklyn Nets": 17,        "New York Knicks": 18,        "Orlando Magic": 19,
    "Philadelphia 76ers": 20,   "Phoenix Suns": 21,           "Portland Trail Blazers": 22,
    "Sacramento Kings": 23,     "San Antonio Spurs": 24,      "Oklahoma City Thunder": 25,
    "Utah Jazz": 26,            "Washington Wizards": 27,     "Toronto Raptors": 28,
    "Memphis Grizzlies": 29,    "Charlotte Hornets": 30,
}
# Fraction of a player's minutes lost per status level
STATUS_WEIGHTS: dict[str, float] = {
    "Out": 1.0, "Doubtful": 0.75, "Questionable": 0.5, "Day-To-Day": 0.25,
}

ROUND_NAMES = {1: "First Round", 2: "Conference Semifinals", 3: "Conference Finals", 4: "NBA Finals"}

TEAM_TO_ABBR = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN",
    "Charlotte Hornets": "CHA", "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN", "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW", "Houston Rockets": "HOU", "Indiana Pacers": "IND",
    "LA Clippers": "LAC", "Los Angeles Clippers": "LAC", "LA Lakers": "LAL",
    "Los Angeles Lakers": "LAL", "Memphis Grizzlies": "MEM", "Miami Heat": "MIA",
    "Milwaukee Bucks": "MIL", "Minnesota Timberwolves": "MIN", "New Orleans Pelicans": "NOP",
    "New York Knicks": "NYK", "Oklahoma City Thunder": "OKC", "Orlando Magic": "ORL",
    "Philadelphia 76ers": "PHI", "Phoenix Suns": "PHX", "Portland Trail Blazers": "POR",
    "Sacramento Kings": "SAC", "San Antonio Spurs": "SAS", "Toronto Raptors": "TOR",
    "Utah Jazz": "UTA", "Washington Wizards": "WAS",
}

app = FastAPI(title="NBA Playoff Predictor")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _load_model():
    with open(MODEL_PATH, "rb") as f:
        return pickle.load(f)


def _add_context_defaults(df: pd.DataFrame) -> pd.DataFrame:
    df["rest_days"]        = 5
    df["back_to_back"]     = 0
    df["travel_km"]        = 0.0
    df["prev_margin"]      = 0.0
    df["series_wins"]      = 0
    df["elimination_game"] = 0
    return df


def _merge_playoff_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Join previous season's playoff net rating onto the stats DataFrame."""
    if PLAYOFF_STATS_PATH.exists():
        playoff = pd.read_csv(PLAYOFF_STATS_PATH)[["team_id", "playoff_net_rtg"]]
        df = df.merge(playoff, on="team_id", how="left")
        df["playoff_net_rtg"] = df["playoff_net_rtg"].fillna(0.0)
    else:
        df["playoff_net_rtg"] = 0.0
    return df


def _fill_optional_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Fill optional stat columns that may be absent from older CSVs."""
    defaults = {
        "win_pct_last10": 0.5, "net_rtg_last15": 0.0,
        "opp_3pt_pct_allowed": 0.35, "bench_net_rtg": 0.0,
    }
    for col, val in defaults.items():
        if col not in df.columns:
            df[col] = val
        else:
            df[col] = df[col].fillna(val)
    return df


def _load_stats_by_name() -> pd.DataFrame:
    df = pd.read_csv(STATS_PATH)
    df = _merge_playoff_stats(df)
    df = _fill_optional_stats(df)
    return _add_context_defaults(df).set_index("team_name")


def _load_stats_by_id() -> pd.DataFrame:
    df = pd.read_csv(STATS_PATH)
    df = _merge_playoff_stats(df)
    df = _fill_optional_stats(df)
    return _add_context_defaults(df).set_index("team_id")


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


def _game_prob(
    model, stats: pd.DataFrame,
    team_a: str, team_b: str,
    team_a_is_home: bool,
    wins_a: int = 0, wins_b: int = 0,
    ctx_a: dict | None = None,
    ctx_b: dict | None = None,
) -> float:
    """Return P(team_a wins a single game) via normalized logistic scores.

    wins_a / wins_b are the current series wins before this game.
    ctx_a / ctx_b override any contextual features.
    """
    def _build(team, opp, is_home, series_wins, opp_wins):
        row = stats.loc[team, STAT_FEATURES].to_dict()
        opp_row = stats.loc[opp].to_dict() if opp in stats.index else {}
        row["home"]             = 1 if is_home else 0
        row["back_to_back"]     = 0
        row["travel_km"]        = 0.0
        row["prev_margin"]      = 0.0
        row["series_wins"]      = series_wins
        row["elimination_game"] = 1 if opp_wins == 3 else 0
        row["net_rtg_diff"]     = float(row.get("net_rtg", 0)) - float(opp_row.get("net_rtg", 0))
        row["off_vs_def_diff"]  = float(row.get("off_rtg", 0)) - float(opp_row.get("def_rtg", 0))
        row["pace_diff"]        = float(row.get("pace", 0))    - float(opp_row.get("pace", 0))
        row["srs_diff"]         = float(row.get("srs", 0))     - float(opp_row.get("srs", 0))
        return row

    a = _build(team_a, team_b, team_a_is_home, wins_a, wins_b)
    if ctx_a:
        a.update(ctx_a)

    b = _build(team_b, team_a, not team_a_is_home, wins_b, wins_a)
    if ctx_b:
        b.update(ctx_b)

    p_a = float(model.predict_proba(pd.DataFrame([a])[FEATURES])[0][1])
    p_b = float(model.predict_proba(pd.DataFrame([b])[FEATURES])[0][1])
    return p_a / (p_a + p_b)


def _adjust_for_injuries(p: float, injury_a: float, injury_b: float) -> float:
    """Rescale win probability based on relative health factors (1.0 = full health)."""
    if injury_a == injury_b == 1.0:
        return p
    p_adj = (p * injury_a) / (p * injury_a + (1 - p) * injury_b)
    return max(0.01, min(0.99, p_adj))


def _simulate_series(
    model, stats, team_a: str, team_b: str,
    injury_a: float = 1.0, injury_b: float = 1.0,
    n: int = 10_000, seed: int = 42,
) -> list:
    """Monte Carlo simulation — probabilities computed dynamically with series context."""
    rng = np.random.default_rng(seed)
    buckets = {"4-0": [0, 0], "4-1": [0, 0], "4-2": [0, 0], "4-3": [0, 0]}
    for _ in range(n):
        wa = wb = game_idx = 0
        while wa < 4 and wb < 4:
            h = HOME_SCHEDULE[game_idx]
            p = _adjust_for_injuries(
                _game_prob(model, stats, team_a, team_b, h, wins_a=wa, wins_b=wb),
                injury_a, injury_b,
            )
            if rng.random() < p:
                wa += 1
            else:
                wb += 1
            game_idx += 1
        key = f"4-{wb}" if wa == 4 else f"4-{wa}"
        buckets[key][0 if wa == 4 else 1] += 1
    return [
        {"result": k, "team_a_pct": round(v[0] / n * 100, 1), "team_b_pct": round(v[1] / n * 100, 1)}
        for k, v in buckets.items()
    ]


def _sample_series(model, stats, team_a: str, team_b: str, seed: int = 7) -> list:
    """Draw one representative series with dynamic per-game probabilities."""
    rng = np.random.default_rng(seed)
    games, wa, wb, game_idx = [], 0, 0, 0
    while wa < 4 and wb < 4:
        h = HOME_SCHEDULE[game_idx]
        p = _game_prob(model, stats, team_a, team_b, h, wins_a=wa, wins_b=wb)
        a_wins = rng.random() < p
        if a_wins:
            wa += 1
        else:
            wb += 1
        game_idx += 1
        games.append({
            "game": game_idx,
            "winner": team_a if a_wins else team_b,
            "team_a_prob": round(p * 100, 1),
            "team_b_prob": round((1 - p) * 100, 1),
            "series_score": f"{wa}–{wb}",
            "clinching": wa == 4 or wb == 4,
        })
    return games


def _build_prediction(
    model, stats_by_name, team_a: str, team_b: str,
    injury_a: float = 1.0, injury_b: float = 1.0,
) -> dict:
    outcomes = _simulate_series(model, stats_by_name, team_a, team_b, injury_a, injury_b)
    series_a = sum(o["team_a_pct"] for o in outcomes)
    series_b = sum(o["team_b_pct"] for o in outcomes)
    # avg game prob at series start (0–0) for display
    avg_p = sum(
        _game_prob(model, stats_by_name, team_a, team_b, h, wins_a=0, wins_b=0)
        for h in HOME_SCHEDULE
    ) / len(HOME_SCHEDULE)
    return {
        "team_a": team_a,
        "team_b": team_b,
        "team_a_series_prob": round(series_a, 1),
        "team_b_series_prob": round(series_b, 1),
        "team_a_game_prob": round(avg_p * 100, 1),
        "team_b_game_prob": round((1 - avg_p) * 100, 1),
        "predicted_winner": team_a if series_a >= series_b else team_b,
        "games": _sample_series(model, stats_by_name, team_a, team_b),
        "outcomes": outcomes,
    }


# ── Injury helpers ────────────────────────────────────────────────────────────

_player_minutes_cache: pd.DataFrame | None = None
_injuries_cache: dict[str, list[dict]] | None = None
_injuries_cache_time: float = 0.0
_INJURIES_TTL = 3600.0  # re-fetch after 1 hour


def _get_player_minutes() -> pd.DataFrame:
    from nba_api.stats.endpoints import leaguedashplayerstats
    import time as _time
    _time.sleep(0.6)
    df = leaguedashplayerstats.LeagueDashPlayerStats(
        season="2025-26",
        season_type_all_star="Regular Season",
        per_mode_detailed="PerGame",
    ).get_data_frames()[0]
    cols = ["PLAYER_NAME", "TEAM_ABBREVIATION", "MIN", "PTS", "AST", "REB", "STL", "BLK"]
    df = df[[c for c in cols if c in df.columns]].copy()
    df["IMPACT"] = (
        df.get("PTS", 0) * 1.0
        + df.get("AST", 0) * 1.5
        + df.get("REB", 0) * 1.2
        + df.get("STL", 0) * 2.0
        + df.get("BLK", 0) * 2.0
    )
    return df


def _get_player_minutes_cached() -> pd.DataFrame:
    global _player_minutes_cache
    if _player_minutes_cache is None:
        try:
            _player_minutes_cache = _get_player_minutes()
        except Exception:
            _player_minutes_cache = pd.DataFrame(
                columns=["PLAYER_NAME", "TEAM_ABBREVIATION", "MIN", "PTS"]
            )
    return _player_minutes_cache


def _fetch_all_espn_injuries() -> dict[str, list[dict]]:
    """Fetch all 30 teams' injuries in one ESPN request. Returns {team_display_name: [injuries]}.
    Result is cached for _INJURIES_TTL seconds."""
    import json, urllib.request, time as _time
    global _injuries_cache, _injuries_cache_time

    now = _time.time()
    if _injuries_cache is not None and (now - _injuries_cache_time) < _INJURIES_TTL:
        return _injuries_cache

    url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        result: dict[str, list[dict]] = {
            entry.get("displayName", ""): entry.get("injuries", [])
            for entry in data.get("injuries", [])
        }
        _injuries_cache = result
        _injuries_cache_time = now
        return result
    except Exception:
        return _injuries_cache if _injuries_cache is not None else {}


def _compute_injury_factor(
    injuries: list[dict], team_name: str, player_minutes: pd.DataFrame
) -> tuple[float, list[dict]]:
    abbr = TEAM_TO_ABBR.get(team_name, "")
    team_df    = player_minutes[player_minutes["TEAM_ABBREVIATION"] == abbr].copy()
    top8       = team_df.nlargest(8, "MIN")
    top8_names = set(top8["PLAYER_NAME"].str.lower())
    # Use composite IMPACT score; fall back to MIN if column missing
    impact_col   = "IMPACT" if "IMPACT" in top8.columns else "MIN"
    total_impact = float(top8[impact_col].sum())
    name_to_impact = {r["PLAYER_NAME"].lower(): float(r[impact_col]) for _, r in team_df.iterrows()}
    name_to_pts    = {r["PLAYER_NAME"].lower(): float(r["PTS"]) for _, r in team_df.iterrows() if "PTS" in r.index}

    missing_impact = 0.0
    affected: list[dict] = []

    for inj in injuries:
        name   = inj.get("athlete", {}).get("displayName", "")
        status = inj.get("status", "")
        weight = STATUS_WEIGHTS.get(status, 0.0)
        if not name or weight == 0.0:
            continue

        impact = name_to_impact.get(name.lower())
        ppg    = name_to_pts.get(name.lower())

        if impact is not None and name.lower() in top8_names and total_impact > 0:
            missing_impact += impact * weight

        affected.append({
            "name":         name,
            "status":       status,
            "pts_per_game": round(ppg, 1) if ppg is not None else None,
        })

    factor = max(0.40, round(1.0 - missing_impact / total_impact, 3)) if total_impact > 0 else 1.0
    return factor, affected


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/api/teams")
def get_teams() -> list[str]:
    return sorted(_load_stats_by_name().index.tolist())


@app.get("/api/debug/injuries")
def debug_injuries(team: str):
    """Try multiple ESPN/NBA endpoints and return raw responses — for debugging only."""
    import json, urllib.request
    espn_id = ESPN_TEAM_IDS.get(team)
    urls = [
        f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{espn_id}/injuries",
        f"https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/teams/{espn_id}/injuries?limit=25",
        "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries",
    ]
    results = {}
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read())
            results[url] = {"keys": list(data.keys()) if isinstance(data, dict) else type(data).__name__, "data": data}
        except Exception as e:
            results[url] = {"error": str(e)}
    return results


@app.get("/api/injuries")
def get_injuries(team_a: str, team_b: str):
    """Return live ESPN injury status + computed health factor (0–1) for two teams."""
    all_injuries   = _fetch_all_espn_injuries()
    player_minutes = _get_player_minutes_cached()
    results: dict  = {}
    for team in (team_a, team_b):
        inj = all_injuries.get(team, [])
        factor, players = _compute_injury_factor(inj, team, player_minutes)
        results[team] = {"factor": factor, "players": players}
    return results


_series_cache: dict[str, dict] = {}
_series_cache_time: dict[str, float] = {}
_SERIES_CACHE_TTL = 1800.0


@app.get("/api/series_history")
def get_series_history(team_a: str, team_b: str):
    """Return series win probability after each game played so far."""
    import time as _time

    cache_key = f"{team_a}|{team_b}"
    now = _time.time()
    if cache_key in _series_cache and (now - _series_cache_time.get(cache_key, 0.0)) < _SERIES_CACHE_TTL:
        return _series_cache[cache_key]

    # Per-game win probability from model
    try:
        _model = _load_model()
        stats  = _load_stats_by_name()
        pred   = _build_prediction(_model, stats, team_a, team_b)
        p_game = pred["games"][0]["team_a_prob"] / 100.0
    except Exception:
        p_game = 0.5

    def series_prob(wa: int, wb: int, p: float, target: int = 4) -> float:
        memo: dict = {}
        def dp(i: int, j: int) -> float:
            if i == target: return 1.0
            if j == target: return 0.0
            if (i, j) in memo: return memo[(i, j)]
            v = p * dp(i + 1, j) + (1 - p) * dp(i, j + 1)
            memo[(i, j)] = v
            return v
        return round(dp(wa, wb) * 100, 1)

    pre_prob = series_prob(0, 0, p_game)
    history: list[dict] = [
        {"game": "Pre", "team_a_prob": pre_prob, "team_b_prob": round(100 - pre_prob, 1), "series": "0-0"}
    ]

    try:
        from nba_api.stats.endpoints import leaguegamelog
        _time.sleep(0.6)
        df     = leaguegamelog.LeagueGameLog(season="2025-26", season_type_all_star="Playoffs").get_data_frames()[0]
        abbr_a = TEAM_TO_ABBR.get(team_a, "")
        abbr_b = TEAM_TO_ABBR.get(team_b, "")

        if abbr_a and abbr_b:
            games = df[df["TEAM_ABBREVIATION"] == abbr_a]
            games = games[games["MATCHUP"].str.contains(abbr_b, na=False)]
            games = games.sort_values("GAME_DATE")

            wa, wb = 0, 0
            for _, row in games.iterrows():
                if row["WL"] == "W":
                    wa += 1
                else:
                    wb += 1
                prob = series_prob(wa, wb, p_game)
                history.append({
                    "game":        f"G{wa + wb}",
                    "team_a_prob": prob,
                    "team_b_prob": round(100 - prob, 1),
                    "series":      f"{wa}-{wb}",
                })
    except Exception:
        pass

    result = {"team_a": team_a, "team_b": team_b, "history": history}
    _series_cache[cache_key] = result
    _series_cache_time[cache_key] = now
    return result


def _series_win_prob(wa: int, wb: int, p_game: float, target: int = 4) -> float:
    """DP probability that team_a wins the series from state (wa wins, wb wins)."""
    memo: dict = {}
    def dp(i: int, j: int) -> float:
        if i == target: return 1.0
        if j == target: return 0.0
        if (i, j) in memo: return memo[(i, j)]
        v = p_game * dp(i + 1, j) + (1 - p_game) * dp(i, j + 1)
        memo[(i, j)] = v
        return v
    return round(dp(wa, wb) * 100, 1)


def _playoff_round(game_id: str) -> int:
    """Parse round number from NBA playoff game_id.
    CSV format  (8 chars):  42500RSG  → round at char 5
    nba_api format (10 chars): 004250RSG → round at char 7
    """
    try:
        s = str(int(game_id))  # strip leading zeros
        if len(s) == 8:   # CSV: 42500RSG
            return int(s[5])
        if len(s) == 10:  # nba_api: 0042500RSG
            return int(s[7])
        return 0
    except Exception:
        return 0


_bracket_cache: dict | None = None
_bracket_cache_time: float = 0.0
_BRACKET_CACHE_TTL = 600.0

_completed_series_cache: set | None = None
_completed_series_cache_time: float = 0.0
_COMPLETED_SERIES_TTL = 900.0


def _get_completed_series() -> set:
    """Return set of frozenset(abbr_a, abbr_b) for playoff series where one team has 4 wins."""
    import time as _time
    global _completed_series_cache, _completed_series_cache_time

    now = _time.time()
    if _completed_series_cache is not None and (now - _completed_series_cache_time) < _COMPLETED_SERIES_TTL:
        return _completed_series_cache

    try:
        from nba_api.stats.endpoints import leaguegamelog
        _time.sleep(0.6)
        df = leaguegamelog.LeagueGameLog(
            season="2025-26", season_type_all_star="Playoffs"
        ).get_data_frames()[0]

        home_rows = df[df["MATCHUP"].str.contains(" vs. ", na=False)]
        series_wins: dict = {}
        for _, row in home_rows.iterrows():
            parts = row["MATCHUP"].split(" vs. ")
            if len(parts) != 2:
                continue
            home_abbr = parts[0].strip()
            away_abbr = parts[1].strip()
            key = frozenset([home_abbr, away_abbr])
            if key not in series_wins:
                series_wins[key] = {}
            winner = home_abbr if row["WL"] == "W" else away_abbr
            series_wins[key][winner] = series_wins[key].get(winner, 0) + 1

        completed = {k for k, wins in series_wins.items() if any(w >= 4 for w in wins.values())}
        _completed_series_cache = completed
        _completed_series_cache_time = now
        return completed
    except Exception:
        return _completed_series_cache if _completed_series_cache is not None else set()


@app.get("/api/bracket")
def get_bracket():
    """Return all playoff series grouped by round with current score and win probability."""
    import time as _time
    global _bracket_cache, _bracket_cache_time

    now = _time.time()
    if _bracket_cache is not None and (now - _bracket_cache_time) < _BRACKET_CACHE_TTL:
        return _bracket_cache

    try:
        from nba_api.stats.endpoints import leaguegamelog
        import time as _t
        _t.sleep(0.6)
        df = leaguegamelog.LeagueGameLog(
            season="2025-26", season_type_all_star="Playoffs"
        ).get_data_frames()[0]

        model = _load_model()
        stats = _load_stats_by_name()

        home_rows = df[df["MATCHUP"].str.contains(" vs. ", na=False)].copy()
        away_index = df[df["MATCHUP"].str.contains(" @ ", na=False)].set_index("GAME_ID")

        # Build series dict keyed by (round, sorted team pair)
        series_map: dict[tuple, dict] = {}
        for _, row in home_rows.iterrows():
            game_id   = str(row["GAME_ID"])
            round_num = _playoff_round(game_id)
            if round_num == 0:
                continue
            home_team = str(row["TEAM_NAME"])
            if game_id not in away_index.index:
                continue
            away_team = str(away_index.loc[game_id, "TEAM_NAME"])
            if home_team not in stats.index or away_team not in stats.index:
                continue

            pair = tuple(sorted([home_team, away_team]))
            key  = (round_num, pair)
            if key not in series_map:
                series_map[key] = {"round": round_num, "team_a": pair[0], "team_b": pair[1],
                                    "team_a_wins": 0, "team_b_wins": 0}
            winner = home_team if row["WL"] == "W" else away_team
            if winner == pair[0]:
                series_map[key]["team_a_wins"] += 1
            else:
                series_map[key]["team_b_wins"] += 1

        # Build result rounds
        rounds_data: dict[int, list] = {}
        for (round_num, pair), s in series_map.items():
            wa, wb = s["team_a_wins"], s["team_b_wins"]
            status = "complete" if wa == 4 or wb == 4 else "active"
            winner = s["team_a"] if wa == 4 else (s["team_b"] if wb == 4 else None)
            try:
                p_game = _game_prob(model, stats, s["team_a"], s["team_b"],
                                    team_a_is_home=True, wins_a=wa, wins_b=wb)
                ta_prob = _series_win_prob(wa, wb, p_game)
            except Exception:
                ta_prob = 50.0
            rounds_data.setdefault(round_num, []).append({
                "team_a":             s["team_a"],
                "team_b":             s["team_b"],
                "team_a_wins":        wa,
                "team_b_wins":        wb,
                "team_a_series_prob": ta_prob,
                "team_b_series_prob": round(100 - ta_prob, 1),
                "status":             status,
                "winner":             winner,
            })

        rounds = [
            {"round": r, "name": ROUND_NAMES.get(r, f"Round {r}"), "series": rounds_data[r]}
            for r in sorted(rounds_data)
        ]
        result = {"rounds": rounds}
        _bracket_cache = result
        _bracket_cache_time = now
        return result
    except Exception:
        return {"rounds": []}


@app.get("/api/team")
def get_team(name: str):
    """Return stats and recent predictions for a specific team."""
    import time as _time
    stats = _load_stats_by_name()
    if name not in stats.index:
        raise HTTPException(status_code=404, detail=f"Team not found: {name}")

    display = ["off_rtg", "def_rtg", "net_rtg", "pace", "ts_pct",
               "tov_pct", "oreb_pct", "srs", "point_diff", "fg3_rate", "win_streak"]
    row = stats.loc[name]
    team_stats = {col: round(float(row[col]), 2) for col in display if col in stats.columns}

    # Recent games from predictions log
    recent: list[dict] = []
    try:
        from nba_api.stats.endpoints import leaguegamelog
        _time.sleep(0.6)
        df = leaguegamelog.LeagueGameLog(
            season="2025-26", season_type_all_star="Playoffs"
        ).get_data_frames()[0]

        abbr = TEAM_TO_ABBR.get(name, "")
        abbr_to_team = {v: k for k, v in TEAM_TO_ABBR.items() if " " in k}
        model = _load_model()

        team_games = df[df["TEAM_ABBREVIATION"] == abbr].sort_values("GAME_DATE", ascending=False)
        away_rows  = df[df["MATCHUP"].str.contains(" @ ", na=False)].set_index("GAME_ID")

        for _, row in team_games.head(15).iterrows():
            matchup = str(row["MATCHUP"])
            if " vs. " in matchup:
                home_abbr = matchup.split(" vs. ")[0].strip()
                away_abbr = matchup.split(" vs. ")[1].strip()
                home_team = abbr_to_team.get(home_abbr)
                away_team = abbr_to_team.get(away_abbr)
            elif " @ " in matchup:
                away_abbr = matchup.split(" @ ")[0].strip()
                home_abbr = matchup.split(" @ ")[1].strip()
                home_team = abbr_to_team.get(home_abbr)
                away_team = abbr_to_team.get(away_abbr)
            else:
                continue
            if not home_team or not away_team:
                continue
            if home_team not in stats.index or away_team not in stats.index:
                continue
            try:
                p_away = _game_prob(model, stats, away_team, home_team, team_a_is_home=False)
            except Exception:
                continue
            pred_winner = away_team if p_away >= 0.5 else home_team
            actual_winner = home_team if row["WL"] == "W" else away_team
            game_id = str(row["GAME_ID"])
            home_score = int(row["PTS"]) if pd.notna(row["PTS"]) else None
            away_score = None
            if game_id in away_rows.index:
                ar = away_rows.loc[game_id]
                away_score = int(ar["PTS"]) if pd.notna(ar["PTS"]) else None
            recent.append({
                "game_id":        game_id,
                "date":           row["GAME_DATE"],
                "away_team":      away_team,
                "home_team":      home_team,
                "predicted_winner": pred_winner,
                "actual_winner":  actual_winner,
                "correct":        pred_winner == actual_winner,
                "away_score":     away_score,
                "home_score":     home_score,
                "round":          ROUND_NAMES.get(_playoff_round(game_id), "Playoffs"),
            })
    except Exception:
        pass

    return {"name": name, "stats": team_stats, "recent_games": recent}


def _team_travel_km(away_name: str, home_name: str) -> float:
    """Distance from away team's home arena to the game arena (home team's city)."""
    a = TEAM_TO_ABBR.get(away_name, "")
    h = TEAM_TO_ABBR.get(home_name, "")
    if a in ARENA_COORDS and h in ARENA_COORDS and a != h:
        return round(_haversine_km(*ARENA_COORDS[a], *ARENA_COORDS[h]), 1)
    return 0.0


def _fetch_day(
    date_str: str, model, stats_by_id, stats_by_name,
    played_yesterday: set | None = None,
    fetch_injuries: bool = False,
) -> dict:
    """Fetch one day's games and attach predictions."""
    import time
    from nba_api.stats.endpoints import scoreboardv3

    time.sleep(0.6)
    board = scoreboardv3.ScoreboardV3(game_date=date_str)
    data  = board.get_dict()
    games = data["scoreboard"]["games"]
    date  = data["scoreboard"]["gameDate"]

    STATUS = {1: "Scheduled", 2: "Live", 3: "Final"}

    # Fetch all injuries in one ESPN request, then look up each playing team
    injury_factors: dict[str, float] = {}
    injury_players: dict[str, list] = {}
    if fetch_injuries:
        all_injuries   = _fetch_all_espn_injuries()
        player_minutes = _get_player_minutes_cached()
        for g in games:
            for side in (g["homeTeam"], g["awayTeam"]):
                tid = side["teamId"]
                if tid not in stats_by_id.index:
                    continue
                name = str(stats_by_id.loc[tid, "team_name"])
                if name not in injury_factors:
                    inj = all_injuries.get(name, [])
                    factor, players = _compute_injury_factor(inj, name, player_minutes)
                    injury_factors[name] = factor
                    injury_players[name] = players

    results = []
    for g in games:
        home    = g["homeTeam"]
        away    = g["awayTeam"]
        home_id = home["teamId"]
        away_id = away["teamId"]

        if home_id not in stats_by_id.index or away_id not in stats_by_id.index:
            continue

        home_name = str(stats_by_id.loc[home_id, "team_name"])
        away_name = str(stats_by_id.loc[away_id, "team_name"])

        prev = played_yesterday or set()
        ctx_away = {
            "back_to_back": 1 if away_name in prev else 0,
            "travel_km":    _team_travel_km(away_name, home_name),
        }
        ctx_home = {
            "back_to_back": 1 if home_name in prev else 0,
            "travel_km":    0.0,
        }

        inj_away = injury_factors.get(away_name, 1.0)
        inj_home = injury_factors.get(home_name, 1.0)

        try:
            p_raw = _game_prob(
                model, stats_by_name, away_name, home_name,
                team_a_is_home=False, ctx_a=ctx_away, ctx_b=ctx_home,
            )
            p_away = _adjust_for_injuries(p_raw, inj_away, inj_home)
        except Exception:
            continue

        away_impact = round((_adjust_for_injuries(p_raw, inj_away, 1.0) - p_raw) * 100, 1) if inj_away != 1.0 else 0.0
        home_impact = round((p_raw - _adjust_for_injuries(p_raw, 1.0, inj_home)) * 100, 1) if inj_home != 1.0 else 0.0

        results.append({
            "game_id":             g["gameId"],
            "status":              STATUS.get(g["gameStatus"], "Scheduled"),
            "status_text":         g.get("gameStatusText", "TBD"),
            "away_team":           away_name,
            "home_team":           home_name,
            "away_score":          away.get("score"),
            "home_score":          home.get("score"),
            "away_win_prob":       round(p_away * 100, 1),
            "home_win_prob":       round((1 - p_away) * 100, 1),
            "predicted_winner":    away_name if p_away >= 0.5 else home_name,
            "away_injury_impact":  away_impact,
            "home_injury_impact":  home_impact,
            "away_injury_players": [{"name": p["name"], "status": p["status"]} for p in injury_players.get(away_name, [])],
            "home_injury_players": [{"name": p["name"], "status": p["status"]} for p in injury_players.get(home_name, [])],
        })

    # Remove scheduled playoff games that belong to an already-completed series
    if results:
        is_playoff = any(str(g["gameId"]).lstrip("0").startswith("4") for g in games)
        if is_playoff:
            completed = _get_completed_series()
            if completed:
                results = [
                    r for r in results
                    if frozenset([
                        TEAM_TO_ABBR.get(r["away_team"], ""),
                        TEAM_TO_ABBR.get(r["home_team"], ""),
                    ]) not in completed
                ]

    return {"date": date, "games": results}


@app.get("/api/today")
def get_today_games():
    import datetime
    model         = _load_model()
    stats_by_id   = _load_stats_by_id()
    stats_by_name = _load_stats_by_name()
    today = datetime.date.today().strftime("%m/%d/%Y")
    try:
        return _fetch_day(today, model, stats_by_id, stats_by_name)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/schedule")
def get_schedule(days: int = 7):
    """Return the next `days` days of games with predictions (max 14)."""
    import datetime
    days = min(days, 14)
    model         = _load_model()
    stats_by_id   = _load_stats_by_id()
    stats_by_name = _load_stats_by_name()

    # Fetch yesterday's teams so day-1 back-to-backs are detected correctly
    played_yesterday: set = set()
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%m/%d/%Y")
    try:
        yest = _fetch_day(yesterday, model, stats_by_id, stats_by_name, set())
        played_yesterday = {g["away_team"] for g in yest["games"]} | {g["home_team"] for g in yest["games"]}
    except Exception:
        pass

    schedule = []
    for i in range(days):
        d = (datetime.date.today() + datetime.timedelta(days=i)).strftime("%m/%d/%Y")
        try:
            day = _fetch_day(
                d, model, stats_by_id, stats_by_name, played_yesterday,
                fetch_injuries=(i == 0),  # only fetch injuries for today
            )
            if day["games"]:
                schedule.append(day)
            played_yesterday = {g["away_team"] for g in day["games"]} | {g["home_team"] for g in day["games"]}
        except Exception:
            played_yesterday = set()
            continue

    return {"schedule": schedule}




class MatchupRequest(BaseModel):
    team_a: str
    team_b: str


@app.post("/api/predict")
def predict(body: MatchupRequest):
    model = _load_model()
    stats = _load_stats_by_name()
    for t in (body.team_a, body.team_b):
        if t not in stats.index:
            raise HTTPException(status_code=404, detail=f"Team not found: {t}")
    return _build_prediction(model, stats, body.team_a, body.team_b)


@app.get("/api/compare")
def compare_teams(
    team_a: str, team_b: str,
    injury_a: float = 1.0, injury_b: float = 1.0,
):
    """Return side-by-side stats + series prediction for two teams.

    injury_a / injury_b: health factor 0.5–1.0 (1.0 = full health, 0.7 = key starter out).
    """
    stats = _load_stats_by_name()
    for t in (team_a, team_b):
        if t not in stats.index:
            raise HTTPException(status_code=404, detail=f"Team not found: {t}")

    injury_a = max(0.1, min(1.0, injury_a))
    injury_b = max(0.1, min(1.0, injury_b))

    display = [
        "off_rtg", "def_rtg", "net_rtg", "pace", "ts_pct",
        "tov_pct", "oreb_pct", "srs", "point_diff", "fg3_rate", "ftr", "win_streak",
    ]

    def team_stats(name: str) -> dict:
        row = stats.loc[name]
        return {col: round(float(row[col]), 3) for col in display if col in stats.columns}

    model = _load_model()
    return {
        "team_a":       team_a,
        "team_b":       team_b,
        "team_a_stats": team_stats(team_a),
        "team_b_stats": team_stats(team_b),
        "prediction":   _build_prediction(model, stats, team_a, team_b, injury_a, injury_b),
    }


_predictions_log_cache: dict | None = None
_predictions_log_cache_time: float = 0.0
_PREDICTIONS_LOG_TTL = 300.0


@app.get("/api/predictions_log")
def get_predictions_log(n: int = 5):
    """Return the last n completed playoff games with model prediction vs actual result."""
    import time as _time
    global _predictions_log_cache, _predictions_log_cache_time

    now = _time.time()
    if _predictions_log_cache is not None and (now - _predictions_log_cache_time) < _PREDICTIONS_LOG_TTL:
        return _predictions_log_cache

    try:
        from nba_api.stats.endpoints import leaguegamelog
        _time.sleep(0.6)
        df = leaguegamelog.LeagueGameLog(
            season="2025-26", season_type_all_star="Playoffs"
        ).get_data_frames()[0]

        abbr_to_team = {v: k for k, v in TEAM_TO_ABBR.items()}
        home_rows = df[df["MATCHUP"].str.contains(" vs. ", na=False)].copy()
        home_rows = home_rows.sort_values("GAME_DATE", ascending=False)

        model = _load_model()
        stats = _load_stats_by_name()

        # Build a map from GAME_ID to away row for score lookup
        away_rows = df[df["MATCHUP"].str.contains(" @ ", na=False)].set_index("GAME_ID")

        log: list[dict] = []
        for _, row in home_rows.iterrows():
            parts = row["MATCHUP"].split(" vs. ")
            if len(parts) != 2:
                continue
            home_abbr, away_abbr = parts[0].strip(), parts[1].strip()
            home_team = abbr_to_team.get(home_abbr)
            away_team = abbr_to_team.get(away_abbr)
            if not home_team or not away_team:
                continue
            if home_team not in stats.index or away_team not in stats.index:
                continue
            try:
                p_away = _game_prob(model, stats, away_team, home_team, team_a_is_home=False)
            except Exception:
                continue
            predicted_winner = away_team if p_away >= 0.5 else home_team
            predicted_prob   = round((p_away if p_away >= 0.5 else 1 - p_away) * 100, 1)
            actual_winner    = home_team if row["WL"] == "W" else away_team
            home_score = int(row["PTS"]) if "PTS" in row.index and pd.notna(row["PTS"]) else None
            away_score = None
            game_id    = str(row["GAME_ID"]) if "GAME_ID" in row.index else ""
            if game_id and game_id in away_rows.index:
                away_row   = away_rows.loc[game_id]
                away_score = int(away_row["PTS"]) if "PTS" in away_row.index and pd.notna(away_row["PTS"]) else None
            log.append({
                "game_id":          game_id,
                "date":             row["GAME_DATE"],
                "away_team":        away_team,
                "home_team":        home_team,
                "predicted_winner": predicted_winner,
                "predicted_prob":   predicted_prob,
                "actual_winner":    actual_winner,
                "correct":          predicted_winner == actual_winner,
                "away_score":       away_score,
                "home_score":       home_score,
                "away_win_prob":    round(p_away * 100, 1),
                "home_win_prob":    round((1 - p_away) * 100, 1),
                "round":            ROUND_NAMES.get(_playoff_round(game_id), "Playoffs"),
            })
            if len(log) >= n:
                break

        result = {"log": log}
        _predictions_log_cache = result
        _predictions_log_cache_time = now
        return result
    except Exception:
        return {"log": []}


@app.get("/api/stats")
def get_model_stats():
    """Return model accuracy, training data info, and feature importance."""
    model     = _load_model()
    estimator = model.named_steps["clf"]
    if hasattr(estimator, "feature_importances_"):
        coefs = [round(float(c), 4) for c in estimator.feature_importances_]
    elif hasattr(estimator, "coef_"):
        coefs = [round(float(c), 4) for c in estimator.coef_[0]]
    else:
        coefs = []

    cv_acc = 0.0
    metrics_path = ROOT / "models" / "metrics.txt"
    if metrics_path.exists():
        for line in metrics_path.read_text().split("\n"):
            if "Cross-val accuracy" in line:
                try:
                    cv_acc = float(line.split(":")[1].split("±")[0].strip())
                except Exception:
                    pass

    n_games = n_seasons = 0
    training_path = ROOT / "data" / "processed" / "training_data.csv"
    if training_path.exists():
        df = pd.read_csv(training_path)
        n_games   = len(df) // 2
        n_seasons = int(df["season"].nunique()) if "season" in df.columns else 0

    return {
        "accuracy":     round(cv_acc * 100, 1),
        "n_games":      n_games,
        "n_seasons":    n_seasons,
        "features":     FEATURES,
        "coefficients": coefs,
    }
