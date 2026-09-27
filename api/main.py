"""
NBA Playoff Predictor API

Endpoints:
  GET  /api/teams          — list of 30 teams
  GET  /api/today          — today's games with auto-predictions
  POST /api/predict        — series + game-by-game prediction for any matchup

Usage:
    uvicorn api.main:app --reload --reload-dir api
"""

import os
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

ODDS_API_KEY = os.getenv("ODDS_API_KEY", "09bb7105d888c7ad840a18fdc316b0c8")

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


# ── Compare cache (keyed by team pair, 30-min TTL) ───────────────────────────
import threading as _threading
import time as _time_mod

_compare_cache: dict[str, dict] = {}
_compare_cache_time: dict[str, float] = {}
_COMPARE_CACHE_TTL = 1800.0


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


# Pre-warm player minutes on startup so the first /api/injuries request is instant.
_threading.Thread(target=_get_player_minutes_cached, daemon=True).start()


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


def _build_series_history(team_a: str, team_b: str) -> dict:
    """Compute series win-probability history. Runs in a background thread."""
    try:
        _model = _load_model()
        stats  = _load_stats_by_name()
        p_game = _game_prob(_model, stats, team_a, team_b, team_a_is_home=True)
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

    # Fetch game results from ESPN (fast, < 3s) instead of nba_api
    try:
        import urllib.request, json as _json
        espn_id = ESPN_TEAM_IDS.get(team_a)
        if espn_id:
            url = (
                f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
                f"/teams/{espn_id}/schedule?season=2026&seasontype=3"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = _json.loads(resp.read())

            wa, wb = 0, 0
            for event in data.get("events", []):
                competition = event.get("competitions", [{}])[0]
                # Skip games that haven't been played yet
                status = competition.get("status", {})
                if not status.get("type", {}).get("completed", False):
                    continue
                competitors = competition.get("competitors", [])
                opponent_names = {
                    c.get("team", {}).get("displayName", "")
                    for c in competitors
                }
                if team_b not in opponent_names:
                    continue
                # Find team_a's result
                for c in competitors:
                    if c.get("team", {}).get("displayName", "") == team_a:
                        won = c.get("winner", False)
                        if won:
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
                        break
    except Exception:
        pass

    return {"team_a": team_a, "team_b": team_b, "history": history}


@app.get("/api/series_history")
def get_series_history(team_a: str, team_b: str):
    """Return series win probability after each game played so far.

    Returns instantly from cache. If not cached yet, kicks off a background
    fetch and returns only the pre-series probability so the page isn't blocked.
    """
    import time as _time

    cache_key = f"{team_a}|{team_b}"
    now = _time.time()
    if cache_key in _series_cache and (now - _series_cache_time.get(cache_key, 0.0)) < _SERIES_CACHE_TTL:
        return _series_cache[cache_key]

    # Not cached yet — kick off background fetch and return minimal response.
    def _fetch_and_cache():
        result = _build_series_history(team_a, team_b)
        _series_cache[cache_key] = result
        _series_cache_time[cache_key] = _time.time()

    _threading.Thread(target=_fetch_and_cache, daemon=True).start()

    # Return pre-series probability immediately using a fast model call.
    try:
        _model = _load_model()
        stats  = _load_stats_by_name()
        p = _game_prob(_model, stats, team_a, team_b, team_a_is_home=True)
        pre = round(p * 100, 1)
    except Exception:
        pre = 50.0

    return {
        "team_a": team_a,
        "team_b": team_b,
        "history": [{"game": "Pre", "team_a_prob": pre, "team_b_prob": round(100 - pre, 1), "series": "0-0"}],
    }


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

    nba_odds = _fetch_odds_today("basketball_nba")
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

        game_odds    = _get_game_odds(nba_odds, away_name, home_name)
        nba_status   = STATUS.get(g["gameStatus"], "Scheduled")

        # For finished games, only show confirmed pre-game odds
        nba_game_key = f"{_normalize_team(away_name)}|{_normalize_team(home_name)}"
        if nba_status == "Final" and nba_game_key not in _pregame_odds:
            game_odds = {}

        results.append({
            "game_id":             g["gameId"],
            "status":              nba_status,
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
            "away_odds":           game_odds.get("away_odds"),
            "home_odds":           game_odds.get("home_odds"),
            **_value_bet(round(p_away * 100, 1), round((1 - p_away) * 100, 1),
                         game_odds.get("away_odds"), game_odds.get("home_odds")),
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


@app.get("/api/predict")
def predict_get(team_a: str, team_b: str, injury_a: float = 1.0, injury_b: float = 1.0):
    injury_a = max(0.1, min(1.0, injury_a))
    injury_b = max(0.1, min(1.0, injury_b))
    model = _load_model()
    stats = _load_stats_by_name()
    for t in (team_a, team_b):
        if t not in stats.index:
            raise HTTPException(status_code=404, detail=f"Team not found: {t}")
    return _build_prediction(model, stats, team_a, team_b, injury_a, injury_b)


@app.get("/api/compare")
def compare_teams(
    team_a: str, team_b: str,
    injury_a: float = 1.0, injury_b: float = 1.0,
):
    """Return side-by-side stats + series prediction for two teams.

    injury_a / injury_b: health factor 0.5–1.0 (1.0 = full health, 0.7 = key starter out).
    """
    injury_a = max(0.1, min(1.0, injury_a))
    injury_b = max(0.1, min(1.0, injury_b))
    cache_key = f"{team_a}|{team_b}|{injury_a}|{injury_b}"
    now = _time_mod.time()

    if cache_key in _compare_cache and (now - _compare_cache_time.get(cache_key, 0.0)) < _COMPARE_CACHE_TTL:
        return _compare_cache[cache_key]

    stats = _load_stats_by_name()
    for t in (team_a, team_b):
        if t not in stats.index:
            raise HTTPException(status_code=404, detail=f"Team not found: {t}")

    display = [
        "off_rtg", "def_rtg", "net_rtg", "pace", "ts_pct",
        "tov_pct", "oreb_pct", "srs", "point_diff", "fg3_rate", "ftr", "win_streak",
    ]

    def team_stats(name: str) -> dict:
        row = stats.loc[name]
        return {col: round(float(row[col]), 3) for col in display if col in stats.columns}

    result = {
        "team_a":       team_a,
        "team_b":       team_b,
        "team_a_stats": team_stats(team_a),
        "team_b_stats": team_stats(team_b),
    }
    _compare_cache[cache_key] = result
    _compare_cache_time[cache_key] = now
    return result


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
        abbr_to_team = {v: k for k, v in TEAM_TO_ABBR.items()}
        model = _load_model()
        stats = _load_stats_by_name()

        log: list[dict] = []

        for season_type in ("Playoffs", "Regular Season"):
            _time.sleep(0.6)
            df = leaguegamelog.LeagueGameLog(
                season="2025-26", season_type_all_star=season_type
            ).get_data_frames()[0]

            home_rows = df[df["MATCHUP"].str.contains(" vs. ", na=False)].copy()
            home_rows = home_rows.sort_values("GAME_DATE", ascending=False)
            away_rows = df[df["MATCHUP"].str.contains(" @ ", na=False)].set_index("GAME_ID")

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

                if season_type == "Playoffs":
                    round_label = ROUND_NAMES.get(_playoff_round(game_id), "Playoffs")
                else:
                    round_label = "Regular Season"

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
                    "round":            round_label,
                })

        result = {"log": log}
        _predictions_log_cache = result
        _predictions_log_cache_time = now
        return {"log": log[:n]}
    except Exception:
        return {"log": []}


# ═══════════════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════════
#  Betting odds (The Odds API — Bet365)
# ═══════════════════════════════════════════════════════════════════════════════

_odds_cache:      dict[str, dict] = {}
_odds_cache_time: dict[str, float] = {}
_ODDS_TTL = 1800.0  # 30 minutes

_PREGAME_ODDS_FILE = ROOT / "data" / "pregame_odds.json"


def _load_pregame_odds() -> dict[str, dict]:
    import json as _json
    try:
        return _json.loads(_PREGAME_ODDS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_pregame_odds(data: dict) -> None:
    import json as _json
    try:
        _PREGAME_ODDS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _PREGAME_ODDS_FILE.write_text(_json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


_pregame_odds: dict[str, dict] = _load_pregame_odds()


def _normalize_team(name: str) -> str:
    return name.lower().strip()


_BOOKMAKER_PRIORITY = [
    "pinnacle", "draftkings", "fanduel", "betmgm", "williamhill",
    "betrivers", "bovada", "unibet_us", "unibet_uk", "paddypower",
    "coral", "ladbrokes_uk", "betway", "marathonbet", "betsson",
]


def _fetch_odds_today(sport_key: str) -> dict[str, dict]:
    """Return {away_team|home_team: {away_odds, home_odds}} using the sharpest available bookmaker.

    For games not yet started: returns current market odds and caches them in _pregame_odds.
    For games already in progress: returns the pre-game odds stored before tip-off/first pitch.
    Falls back to empty dict silently on any error or missing key.
    """
    import json, time as _t, urllib.request
    from datetime import datetime, timezone

    if not ODDS_API_KEY:
        return {}

    now = _t.time()
    if sport_key in _odds_cache and (now - _odds_cache_time.get(sport_key, 0)) < _ODDS_TTL:
        return _odds_cache[sport_key]

    url = (
        f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
        f"?apiKey={ODDS_API_KEY}"
        f"&regions=us,eu,uk"
        f"&markets=h2h"
        f"&oddsFormat=decimal"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CourtEdge/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            games = json.loads(resp.read())

        now_dt = datetime.now(timezone.utc)
        result: dict[str, dict] = {}
        for g in games:
            away = g.get("away_team", "")
            home = g.get("home_team", "")
            game_key = f"{_normalize_team(away)}|{_normalize_team(home)}"

            # Determine if game has already started
            try:
                commence_dt = datetime.fromisoformat(g.get("commence_time", "").replace("Z", "+00:00"))
                game_started = commence_dt <= now_dt
            except Exception:
                game_started = False

            # If we have cached pre-game odds, always prefer them
            if game_key in _pregame_odds:
                result[game_key] = _pregame_odds[game_key]
                continue

            # Extract odds from best available bookmaker
            bookmakers = g.get("bookmakers", [])
            bm_map = {bm["key"]: bm for bm in bookmakers}
            chosen_bm = None
            for bk in _BOOKMAKER_PRIORITY:
                if bk in bm_map:
                    chosen_bm = bm_map[bk]
                    break
            if chosen_bm is None and bookmakers:
                chosen_bm = bookmakers[0]
            if chosen_bm is None:
                continue

            for market in chosen_bm.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                prices = {_normalize_team(o["name"]): o["price"] for o in market.get("outcomes", [])}
                a_odds = prices.get(_normalize_team(away))
                h_odds = prices.get(_normalize_team(home))
                if a_odds and h_odds:
                    odds_data = {"away_odds": round(a_odds, 2), "home_odds": round(h_odds, 2)}
                    if not game_started:
                        # Only persist pre-game odds, not live or post-game
                        _pregame_odds[game_key] = odds_data
                    result[game_key] = odds_data
                break

        _save_pregame_odds(_pregame_odds)
        _odds_cache[sport_key]      = result
        _odds_cache_time[sport_key] = now
        return result
    except Exception:
        return {}


VALUE_EDGE_MIN = 5.0  # model must beat the no-vig market probability by ≥ 5 points


def _value_bet(away_prob_pct: float, home_prob_pct: float,
               away_odds: float | None, home_odds: float | None) -> dict:
    """Compare model probabilities with the bookmaker's (decimal odds, vig removed).

    value_side is the side where the model's probability exceeds the market's by
    at least VALUE_EDGE_MIN points; value_ev is the expected return per unit staked.
    """
    empty = {"away_market_prob": None, "home_market_prob": None,
             "value_side": None, "value_edge": None, "value_ev": None}
    if not away_odds or not home_odds or away_odds <= 1 or home_odds <= 1:
        return empty
    ia, ih = 1 / away_odds, 1 / home_odds
    mkt_away, mkt_home = ia / (ia + ih) * 100, ih / (ia + ih) * 100
    edges = {"away": away_prob_pct - mkt_away, "home": home_prob_pct - mkt_home}
    side = max(edges, key=edges.get)
    out = {**empty, "away_market_prob": round(mkt_away, 1), "home_market_prob": round(mkt_home, 1)}
    if edges[side] >= VALUE_EDGE_MIN:
        prob, odds = (away_prob_pct, away_odds) if side == "away" else (home_prob_pct, home_odds)
        out.update(value_side=side, value_edge=round(edges[side], 1),
                   value_ev=round(prob / 100 * odds - 1, 3))
    return out


def _get_game_odds(odds: dict, away: str, home: str) -> dict:
    """Look up odds for a game, trying normalized team names."""
    key = f"{_normalize_team(away)}|{_normalize_team(home)}"
    return odds.get(key, {})


#  MLB endpoints
# ═══════════════════════════════════════════════════════════════════════════════

MLB_MODEL_PATH = ROOT / "models" / "mlb_logistic_regression.pkl"
MLB_STATS_PATH = ROOT / "data" / "mlb" / "mlb_stats_current.csv"

MLB_PITCHER_RATINGS_PATH = ROOT / "data" / "mlb" / "mlb_pitcher_ratings.csv"
MLB_SP_UNKNOWN = 4.40  # FIP for a starter with no history (matches mlb/pipeline.py SP_UNKNOWN)

# Order must match mlb/train.py FEATURES exactly
MLB_FEATURES = [
    "home",
    "elo_diff",
    "sp_fip_diff",
    "ops_diff", "run_diff_ewm_diff",
    "bullpen_era_diff", "bullpen_ip3_diff",
]

_mlb_model_cache = None
_mlb_stats_cache: pd.DataFrame | None = None

_mlb_today_cache: dict | None = None
_mlb_today_cache_date: str = ""
_mlb_today_cache_time: float = 0.0
_MLB_TODAY_TTL = 120.0   # 2 minutes — refresh statuts en cours de journée

_mlb_standings_cache: dict | None = None
_mlb_standings_cache_time: float = 0.0
_MLB_STANDINGS_TTL = 300.0  # 5 minutes

_mlb_game_pred_cache: dict[str, dict] = {}  # str(game_id) → {away_win_prob, home_win_prob, predicted_winner}


def _load_mlb_model():
    global _mlb_model_cache
    if _mlb_model_cache is None:
        with open(MLB_MODEL_PATH, "rb") as f:
            _mlb_model_cache = pickle.load(f)
    return _mlb_model_cache


def _load_mlb_stats() -> pd.DataFrame:
    global _mlb_stats_cache
    if _mlb_stats_cache is None:
        _mlb_stats_cache = pd.read_csv(MLB_STATS_PATH).set_index("team_name")
    return _mlb_stats_cache


# ── Per-game pitcher ERA cache ─────────────────────────────────────────────────
# Keyed by pitcher_id (int). Busted each calendar day alongside the today cache.
_pitcher_era_cache: dict[int, float | None] = {}
_pitcher_era_cache_date: str = ""


def _fetch_pitcher_eras_batch(pitcher_ids: list[int], season: int = 2026) -> dict[int, float]:
    """Return {pitcher_id: era} for a list of IDs in a single MLB Stats API call.

    Falls back to an empty dict on any error — callers use team sp_era as default.
    """
    import json, urllib.request, datetime
    global _pitcher_era_cache, _pitcher_era_cache_date

    today = datetime.date.today().isoformat()
    if _pitcher_era_cache_date != today:
        _pitcher_era_cache.clear()
        _pitcher_era_cache_date = today

    # Only fetch IDs we haven't cached yet
    uncached = [pid for pid in pitcher_ids if pid not in _pitcher_era_cache]
    if uncached:
        ids_str = ",".join(str(p) for p in uncached)
        url = (
            f"https://statsapi.mlb.com/api/v1/people"
            f"?personIds={ids_str}"
            f"&hydrate=stats(group=%5Bpitching%5D,type=%5Bseason%5D,season={season},gameType=R)"
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "CourtEdge/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            for person in data.get("people", []):
                pid = person.get("id")
                era_val = None
                for stat_group in person.get("stats", []):
                    for split in stat_group.get("splits", []):
                        era_str = split.get("stat", {}).get("era", "")
                        if era_str and era_str not in ("-.--", "--", ""):
                            try:
                                era_val = float(era_str)
                                break
                            except (ValueError, TypeError):
                                pass
                    if era_val is not None:
                        break
                if pid is not None:
                    _pitcher_era_cache[pid] = era_val
        except Exception:
            pass

        # Mark unfound IDs so we don't re-request them
        for pid in uncached:
            if pid not in _pitcher_era_cache:
                _pitcher_era_cache[pid] = None

    return {pid: _pitcher_era_cache[pid] for pid in pitcher_ids if _pitcher_era_cache.get(pid) is not None}


_mlb_pitcher_ratings_cache: dict[int, float] | None = None


def _load_mlb_pitcher_ratings() -> dict[int, float]:
    """{pitcher_id: FIP rating to date} written by mlb/pipeline.py."""
    global _mlb_pitcher_ratings_cache
    if _mlb_pitcher_ratings_cache is None:
        _mlb_pitcher_ratings_cache = {}
        if MLB_PITCHER_RATINGS_PATH.exists():
            df = pd.read_csv(MLB_PITCHER_RATINGS_PATH)
            _mlb_pitcher_ratings_cache = dict(zip(df["pitcher_id"].astype(int), df["sp_fip"].astype(float)))
    return _mlb_pitcher_ratings_cache


def _mlb_win_prob(
    model, stats: pd.DataFrame,
    team: str, opp: str, is_home: int,
    sp_id: int | None = None,
    opp_sp_id: int | None = None,
) -> float:
    """Return P(team wins) using the MLB logistic regression.

    sp_id / opp_sp_id: today's probable starters, rated by FIP to date; an unknown or
    unannounced starter gets a slightly below-average rating. Bullpen fatigue in the
    team table is measured relative to the pipeline's run date, so it's ignored
    (treated as even) when the table is from an earlier day.
    """
    import datetime, zoneinfo
    ratings = _load_mlb_pitcher_ratings()
    today = datetime.datetime.now(zoneinfo.ZoneInfo("America/New_York")).date().isoformat()

    def _row(t, o, home, t_sp, o_sp):
        ts, os_ = stats.loc[t], stats.loc[o]
        fresh = str(ts.get("state_date", "")) == today
        return {
            "home":              home,
            "elo_diff":          float(ts.get("elo", 1500)) - float(os_.get("elo", 1500)),
            "sp_fip_diff":       ratings.get(t_sp, MLB_SP_UNKNOWN) - ratings.get(o_sp, MLB_SP_UNKNOWN),
            "ops_diff":          float(ts.get("ops_ewm", 0.72)) - float(os_.get("ops_ewm", 0.72)),
            "run_diff_ewm_diff": float(ts.get("run_diff_ewm", 0.0)) - float(os_.get("run_diff_ewm", 0.0)),
            "bullpen_era_diff":  float(ts.get("bullpen_era_ewm", 4.1)) - float(os_.get("bullpen_era_ewm", 4.1)),
            "bullpen_ip3_diff":  (float(ts.get("bullpen_ip3", 0.0)) - float(os_.get("bullpen_ip3", 0.0))) if fresh else 0.0,
        }

    X = pd.DataFrame([_row(team, opp, is_home, sp_id, opp_sp_id),
                      _row(opp, team, 1 - is_home, opp_sp_id, sp_id)])[MLB_FEATURES]
    p_t, p_o = (float(p) for p in model.predict_proba(X)[:, 1])
    return p_t / (p_t + p_o)   # normalise so home+away = 100 %


def _fetch_mlb_today() -> dict:
    """Fetch today's MLB games directly from statsapi.mlb.com (no third-party package needed)."""
    import datetime, json, urllib.request

    import zoneinfo
    today_iso = datetime.datetime.now(zoneinfo.ZoneInfo("America/New_York")).date().isoformat()

    url = (
        "https://statsapi.mlb.com/api/v1/schedule"
        f"?sportId=1&date={today_iso}"
        "&hydrate=probablePitcher,linescore,decisions"
        "&gameType=R"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "CourtEdge/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())

    model = _load_mlb_model()
    stats = _load_mlb_stats()

    # ── Collect all probable pitcher IDs, then batch-fetch their ERAs ────────
    all_games = [
        g
        for date_block in data.get("dates", [])
        for g in date_block.get("games", [])
        if g.get("gameType", "R") == "R"
    ]
    pitcher_ids: list[int] = []
    for g in all_games:
        for side in ("away", "home"):
            pid = g.get("teams", {}).get(side, {}).get("probablePitcher", {}).get("id")
            if pid:
                pitcher_ids.append(pid)
    starter_eras: dict[int, float] = _fetch_pitcher_eras_batch(list(set(pitcher_ids)))

    mlb_odds = _fetch_odds_today("baseball_mlb")
    results = []
    for g in all_games:
            teams     = g.get("teams", {})
            away_info = teams.get("away", {})
            home_info = teams.get("home", {})

            away_name = away_info.get("team", {}).get("name", "")
            home_name = home_info.get("team", {}).get("name", "")
            status    = g.get("status", {}).get("detailedState", "Scheduled")
            venue     = g.get("venue", {}).get("name", "")
            game_time = g.get("gameDate", "")
            game_id   = g.get("gamePk")

            # Scores (only present when in-progress or final)
            away_score = away_info.get("score")
            home_score = home_info.get("score")

            # Probable starters — name for display, ID for ERA lookup
            def _pitcher_name(side_info: dict) -> str:
                p = side_info.get("probablePitcher", {})
                return p.get("fullName", "TBD") if p else "TBD"

            away_sp    = _pitcher_name(away_info)
            home_sp    = _pitcher_name(home_info)
            away_sp_id = away_info.get("probablePitcher", {}).get("id")
            home_sp_id = home_info.get("probablePitcher", {}).get("id")

            # Game-specific starter ERA (falls back to team rotation ERA inside _mlb_win_prob)
            away_sp_era = starter_eras.get(away_sp_id) if away_sp_id else None
            home_sp_era = starter_eras.get(home_sp_id) if home_sp_id else None

            # Skip if team not in stats CSV
            if away_name not in stats.index or home_name not in stats.index:
                continue

            try:
                p_away = _mlb_win_prob(
                    model, stats, away_name, home_name, is_home=0,
                    sp_id=away_sp_id,
                    opp_sp_id=home_sp_id,
                )
            except Exception:
                p_away = 0.5

            game_odds = _get_game_odds(mlb_odds, away_name, home_name)

            # For finished games, only show odds if they're confirmed pre-game (not distorted post-game odds)
            is_done = status in ("Final", "Game Over", "Completed")
            game_key = f"{_normalize_team(away_name)}|{_normalize_team(home_name)}"
            has_pregame = game_key in _pregame_odds
            if is_done and not has_pregame:
                game_odds = {}

            away_wp     = round(p_away * 100, 1)
            home_wp     = round((1 - p_away) * 100, 1)
            pred_winner = away_name if p_away >= 0.5 else home_name

            gid_str = str(game_id)
            if gid_str not in _mlb_game_pred_cache:
                _mlb_game_pred_cache[gid_str] = {
                    "away_win_prob":    away_wp,
                    "home_win_prob":    home_wp,
                    "predicted_winner": pred_winner,
                }

            results.append({
                "game_id":          game_id,
                "status":           status,
                "game_time_utc":    game_time,
                "venue":            venue,
                "away_team":        away_name,
                "home_team":        home_name,
                "away_score":       away_score,
                "home_score":       home_score,
                "away_win_prob":    away_wp,
                "home_win_prob":    home_wp,
                "predicted_winner": pred_winner,
                "away_pitcher":     away_sp,
                "home_pitcher":     home_sp,
                "away_sp_era":      round(away_sp_era, 2) if away_sp_era is not None else None,
                "home_sp_era":      round(home_sp_era, 2) if home_sp_era is not None else None,
                "away_odds":        game_odds.get("away_odds"),
                "home_odds":        game_odds.get("home_odds"),
                **_value_bet(away_wp, home_wp, game_odds.get("away_odds"), game_odds.get("home_odds")),
            })

    return {
        "date":  today_iso,
        "games": results,
    }


@app.get("/api/mlb/today")
def get_mlb_today():
    """Return today's MLB games with win probabilities and pitcher matchups."""
    import time as _t
    global _mlb_today_cache, _mlb_today_cache_date, _mlb_today_cache_time
    import datetime

    import zoneinfo
    today = datetime.datetime.now(zoneinfo.ZoneInfo("America/New_York")).date().isoformat()
    now   = _t.time()

    # Serve cache si même jour ET TTL pas expiré
    if (
        _mlb_today_cache is not None
        and _mlb_today_cache_date == today
        and (now - _mlb_today_cache_time) < _MLB_TODAY_TTL
    ):
        return _mlb_today_cache

    try:
        result = _fetch_mlb_today()
        _mlb_today_cache      = result
        _mlb_today_cache_date = today
        _mlb_today_cache_time = now
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"MLB fetch failed: {e}")


@app.get("/api/mlb/teams")
def get_mlb_teams() -> list[str]:
    """Return sorted list of all MLB team names in the stats CSV."""
    return sorted(_load_mlb_stats().index.tolist())


_mlb_pred_log_cache: dict | None = None
_mlb_pred_log_cache_time: float = 0.0
_MLB_PRED_LOG_TTL = 300.0  # 5 minutes


@app.get("/api/mlb/predictions_log")
def get_mlb_predictions_log(n: int = 500):
    """Return completed MLB regular-season games with model prediction vs actual result.

    Fetches from Opening Day 2026 → yesterday so the full season log is available.
    Results are cached 5 minutes; n= slices the returned list.
    """
    import time as _t, datetime, json, urllib.request, calendar
    global _mlb_pred_log_cache, _mlb_pred_log_cache_time

    now = _t.time()
    if _mlb_pred_log_cache is not None and (now - _mlb_pred_log_cache_time) < _MLB_PRED_LOG_TTL:
        cached_log = _mlb_pred_log_cache["log"]
        return {"log": cached_log[:n]}

    try:
        # Full 2026 regular season from Opening Day
        start_date = datetime.date(2026, 3, 25)
        end_date   = datetime.date.today()

        url = (
            "https://statsapi.mlb.com/api/v1/schedule"
            f"?sportId=1&startDate={start_date.isoformat()}&endDate={end_date.isoformat()}"
            "&gameType=R&limit=2500"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "CourtEdge/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        model = _load_mlb_model()
        stats = _load_mlb_stats()

        # Batch-fetch pitcher ERAs for all games (same as the games endpoint)
        all_games_flat = [g for db in data.get("dates", []) for g in db.get("games", [])]
        pitcher_ids: list[int] = []
        for g in all_games_flat:
            for side in ("away", "home"):
                pid = g.get("teams", {}).get(side, {}).get("probablePitcher", {}).get("id")
                if pid:
                    pitcher_ids.append(pid)
        starter_eras: dict[int, float] = _fetch_pitcher_eras_batch(list(set(pitcher_ids)))

        log: list[dict] = []
        for date_block in reversed(data.get("dates", [])):
            date_str = date_block.get("date", "")
            # Derive month label
            try:
                month_num  = int(date_str.split("-")[1])
                month_name = calendar.month_name[month_num]
            except Exception:
                month_name = "Unknown"

            for g in date_block.get("games", []):
                state = g.get("status", {}).get("abstractGameState", "")
                if state != "Final":
                    continue
                teams      = g.get("teams", {})
                away_info  = teams.get("away", {})
                home_info  = teams.get("home", {})
                away_name  = away_info.get("team", {}).get("name", "")
                home_name  = home_info.get("team", {}).get("name", "")
                away_score = away_info.get("score")
                home_score = home_info.get("score")

                if away_name not in stats.index or home_name not in stats.index:
                    continue
                if away_score is None or home_score is None:
                    continue

                game_id = g.get("gamePk")
                gid_str = str(game_id)
                cached  = _mlb_game_pred_cache.get(gid_str)
                if cached:
                    away_win_prob    = cached["away_win_prob"]
                    home_win_prob    = cached["home_win_prob"]
                    predicted_winner = cached["predicted_winner"]
                else:
                    away_sp_id  = away_info.get("probablePitcher", {}).get("id")
                    home_sp_id  = home_info.get("probablePitcher", {}).get("id")
                    away_sp_era = starter_eras.get(away_sp_id) if away_sp_id else None
                    home_sp_era = starter_eras.get(home_sp_id) if home_sp_id else None
                    try:
                        p_away = _mlb_win_prob(model, stats, away_name, home_name, is_home=0,
                                               sp_id=away_sp_id,
                                               opp_sp_id=home_sp_id)
                    except Exception:
                        continue
                    away_win_prob    = round(p_away * 100, 1)
                    home_win_prob    = round((1 - p_away) * 100, 1)
                    predicted_winner = away_name if p_away >= 0.5 else home_name

                predicted_prob = away_win_prob if predicted_winner == away_name else home_win_prob
                actual_winner  = away_name if away_score > home_score else home_name

                log.append({
                    "game_id":          game_id,
                    "date":             date_str,
                    "month":            month_name,
                    "away_team":        away_name,
                    "home_team":        home_name,
                    "predicted_winner": predicted_winner,
                    "predicted_prob":   predicted_prob,
                    "actual_winner":    actual_winner,
                    "correct":          predicted_winner == actual_winner,
                    "away_score":       away_score,
                    "home_score":       home_score,
                    "away_win_prob":    away_win_prob,
                    "home_win_prob":    home_win_prob,
                })

        result = {"log": log}
        _mlb_pred_log_cache = result
        _mlb_pred_log_cache_time = now
        return {"log": log[:n]}
    except Exception:
        return {"log": []}


@app.get("/api/mlb/standings")
def get_mlb_standings():
    """Return AL and NL standings by division, enriched with ERA/OPS from the stats CSV."""
    import time as _t, json, urllib.request
    global _mlb_standings_cache, _mlb_standings_cache_time

    now = _t.time()
    if _mlb_standings_cache is not None and (now - _mlb_standings_cache_time) < _MLB_STANDINGS_TTL:
        return _mlb_standings_cache

    try:
        season = 2026
        url = (
            "https://statsapi.mlb.com/api/v1/standings"
            f"?leagueId=103,104&season={season}&standingsTypes=regularSeason"
            "&hydrate=team,division,league"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "CourtEdge/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        stats = _load_mlb_stats()

        al_divs: dict[str, list] = {}
        nl_divs: dict[str, list] = {}

        for record in data.get("records", []):
            league_id = record.get("league", {}).get("id")          # 103=AL 104=NL
            div_name  = record.get("division", {}).get("name", "")  # "AL East" etc.

            teams = []
            for tr in record.get("teamRecords", []):
                name     = tr.get("team", {}).get("name", "")
                w        = tr.get("wins", 0)
                l        = tr.get("losses", 0)
                pct      = tr.get("winningPercentage", ".000")
                gb       = tr.get("gamesBack", "-")
                streak   = tr.get("streak", {}).get("streakCode", "-")
                run_diff = tr.get("runDifferential", 0)

                splits   = tr.get("records", {}).get("splitRecords", [])
                home_r   = next((r for r in splits if r.get("type") == "home"),    {})
                away_r   = next((r for r in splits if r.get("type") == "away"),    {})
                last10_r = next((r for r in splits if r.get("type") == "lastTen"), {})

                era = ops = None
                if name in stats.index:
                    row = stats.loc[name]
                    era = round(float(row.get("era", 0)), 2)
                    ops = round(float(row.get("ops", 0)), 3)

                teams.append({
                    "name":     name,
                    "w":        w,
                    "l":        l,
                    "pct":      pct,
                    "gb":       gb,
                    "streak":   streak,
                    "run_diff": run_diff,
                    "home":     f"{home_r.get('wins',0)}-{home_r.get('losses',0)}",
                    "away":     f"{away_r.get('wins',0)}-{away_r.get('losses',0)}",
                    "last10":   f"{last10_r.get('wins',0)}-{last10_r.get('losses',0)}",
                    "era":      era,
                    "ops":      ops,
                })

            # MLB Stats API returns "American League East" — normalize to "AL East" etc.
            DIV_DISPLAY = {
                "American League East":    "AL East",
                "American League Central": "AL Central",
                "American League West":    "AL West",
                "National League East":    "NL East",
                "National League Central": "NL Central",
                "National League West":    "NL West",
            }
            display_name = DIV_DISPLAY.get(div_name, div_name)

            if league_id == 103:
                al_divs[display_name] = teams
            else:
                nl_divs[display_name] = teams

        div_order = ["East", "Central", "West"]
        al = [{"name": f"AL {d}", "teams": al_divs.get(f"AL {d}", [])} for d in div_order if f"AL {d}" in al_divs]
        nl = [{"name": f"NL {d}", "teams": nl_divs.get(f"NL {d}", [])} for d in div_order if f"NL {d}" in nl_divs]

        result = {"al": al, "nl": nl}
        _mlb_standings_cache      = result
        _mlb_standings_cache_time = now
        return result

    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Standings fetch failed: {e}")


@app.get("/api/mlb/stats")
def get_mlb_model_stats():
    """Return MLB model accuracy, calibration, features and coefficients."""
    return _model_stats_payload("mlb", MLB_FEATURES)


# ── MLB game detail ────────────────────────────────────────────────────────────

_mlb_game_detail_cache: dict[str, dict] = {}
_mlb_game_detail_cache_time: dict[str, float] = {}
_MLB_GAME_DETAIL_TTL_LIVE  = 30.0     # 30 s for in-progress games
_MLB_GAME_DETAIL_TTL_FINAL = 3600.0   # 1 h for finished games


def _mlb_inning_win_prob(
    pre_game_home_prob: float,
    home_runs: int,
    away_runs: int,
    inning: float,
    total_innings: float = 9.0,
) -> float:
    """Blended home-team win probability after `inning` completed innings.

    Blends the pre-game ML probability (prior) with a current-state estimate
    derived from a Normal approximation of remaining scoring differential.
    """
    import math
    score_diff        = home_runs - away_runs          # positive = home leading
    innings_remaining = max(0.3, total_innings - inning)
    run_rate = 0.46                                    # MLB avg ~4.1 R/game / 9
    std_net  = math.sqrt(2.0 * run_rate * innings_remaining)
    z        = score_diff / (std_net * math.sqrt(2.0))
    cur_prob = 0.5 * (1.0 + math.erf(z))
    progress = min(0.95, inning / total_innings)
    p = (1.0 - progress) * pre_game_home_prob + progress * cur_prob
    return max(0.02, min(0.98, p))


@app.get("/api/mlb/game/{game_id}")
def get_mlb_game_detail(game_id: int):
    """Return linescore, inning-by-inning win probability, and team stats for one game."""
    import time as _t, json, urllib.request
    global _mlb_game_detail_cache, _mlb_game_detail_cache_time

    cache_key = str(game_id)
    now       = _t.time()

    if cache_key in _mlb_game_detail_cache:
        cached   = _mlb_game_detail_cache[cache_key]
        st       = cached.get("status", "")
        is_done  = "Final" in st or "Over" in st or "Completed" in st
        ttl      = _MLB_GAME_DETAIL_TTL_FINAL if is_done else _MLB_GAME_DETAIL_TTL_LIVE
        if (now - _mlb_game_detail_cache_time.get(cache_key, 0.0)) < ttl:
            return cached

    try:
        # ── Linescore ───────────────────────────────────────────────────────
        ls_url = f"https://statsapi.mlb.com/api/v1/game/{game_id}/linescore"
        req    = urllib.request.Request(ls_url, headers={"User-Agent": "CourtEdge/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            linescore = json.loads(resp.read())

        # ── Schedule metadata (probable pitchers, status) ────────────────────
        sc_url = (
            f"https://statsapi.mlb.com/api/v1/schedule"
            f"?gamePk={game_id}&hydrate=probablePitcher,venue"
        )
        req2 = urllib.request.Request(sc_url, headers={"User-Agent": "CourtEdge/1.0"})
        with urllib.request.urlopen(req2, timeout=10) as resp2:
            sched = json.loads(resp2.read())

        game_dates = sched.get("dates", [])
        g_info     = game_dates[0].get("games", [{}])[0] if game_dates else {}
        t_info     = g_info.get("teams", {})
        away_info  = t_info.get("away", {})
        home_info  = t_info.get("home", {})

        away_name = away_info.get("team", {}).get("name", "")
        home_name = home_info.get("team", {}).get("name", "")
        status    = g_info.get("status", {}).get("detailedState", "Scheduled")
        venue     = g_info.get("venue", {}).get("name", "")
        game_time = g_info.get("gameDate", "")

        def _sp(side: dict) -> str:
            p = side.get("probablePitcher", {})
            return p.get("fullName", "TBD") if p else "TBD"

        away_pitcher = _sp(away_info)
        home_pitcher = _sp(home_info)

        ls_t        = linescore.get("teams", {})
        away_score  = ls_t.get("away", {}).get("runs")  or 0
        home_score  = ls_t.get("home", {}).get("runs")  or 0
        away_hits   = ls_t.get("away", {}).get("hits")  or 0
        home_hits   = ls_t.get("home", {}).get("hits")  or 0
        away_errors = ls_t.get("away", {}).get("errors") or 0
        home_errors = ls_t.get("home", {}).get("errors") or 0
        cur_inning  = linescore.get("currentInning",    0) or 0
        inn_state   = linescore.get("inningState",      "")
        is_final    = "Final" in status or "Over" in status or "Completed" in status

        # ── Pre-game win probability ─────────────────────────────────────────
        # Use cached value from schedule endpoint (computed with the probable starters)
        # so the chart's "Pre" point matches what the schedule card showed.
        cached_pred = _mlb_game_pred_cache.get(cache_key)
        if cached_pred:
            p_away = cached_pred["away_win_prob"] / 100.0
        else:
            away_sp_id2 = away_info.get("probablePitcher", {}).get("id")
            home_sp_id2 = home_info.get("probablePitcher", {}).get("id")
            try:
                mlb_model = _load_mlb_model()
                mlb_stats = _load_mlb_stats()
                if away_name in mlb_stats.index and home_name in mlb_stats.index:
                    p_away = _mlb_win_prob(mlb_model, mlb_stats, away_name, home_name, is_home=0,
                                           sp_id=away_sp_id2,
                                           opp_sp_id=home_sp_id2)
                else:
                    p_away = 0.5
            except Exception:
                p_away = 0.5
        p_home = 1.0 - p_away

        # ── Inning-by-inning win probability ─────────────────────────────────
        innings = linescore.get("innings", [])
        history: list[dict] = [{
            "label":     "Pre",
            "away_prob": round(p_away * 100, 1),
            "home_prob": round(p_home * 100, 1),
        }]
        home_total = away_total = 0

        for inn in innings:
            inn_num    = inn.get("num", 0)
            away_r_val = inn.get("away", {}).get("runs")
            home_r_val = inn.get("home", {}).get("runs")

            if away_r_val is None:
                break  # top of this inning not yet played

            away_total += int(away_r_val)

            if home_r_val is None:
                # Top half done, bottom in progress / skipped
                p_h = _mlb_inning_win_prob(p_home, home_total, away_total, inn_num - 0.5)
                history.append({
                    "label":     f"{inn_num}T",
                    "away_prob": round((1.0 - p_h) * 100, 1),
                    "home_prob": round(p_h * 100, 1),
                })
                break

            home_total += int(home_r_val)
            p_h = _mlb_inning_win_prob(p_home, home_total, away_total, float(inn_num))
            history.append({
                "label":     str(inn_num),
                "away_prob": round((1.0 - p_h) * 100, 1),
                "home_prob": round(p_h * 100, 1),
            })

        # Final games: snap last point to 100 / 0
        if is_final and len(history) > 1:
            if home_score > away_score:
                history[-1]["home_prob"] = 100.0
                history[-1]["away_prob"] = 0.0
            elif away_score > home_score:
                history[-1]["home_prob"] = 0.0
                history[-1]["away_prob"] = 100.0

        # ── Inning table rows ────────────────────────────────────────────────
        inning_rows = [
            {"num": i.get("num"), "away_r": i.get("away", {}).get("runs"),
             "home_r": i.get("home", {}).get("runs")}
            for i in innings
        ]

        # ── Team stats for comparison ─────────────────────────────────────────
        try:
            mlb_stats = _load_mlb_stats()
            def _s(name: str, col: str, default: float) -> float:
                if name in mlb_stats.index:
                    try:
                        return round(float(mlb_stats.loc[name].get(col, default)), 3)
                    except Exception:
                        pass
                return default
            stat_cols = ["era", "whip", "k_per9", "ops", "batting_avg", "run_diff"]
            away_stats_out = {c: _s(away_name, c, 0.0) for c in stat_cols}
            home_stats_out = {c: _s(home_name, c, 0.0) for c in stat_cols}
        except Exception:
            away_stats_out = home_stats_out = {}

        result = {
            "game_id":          game_id,
            "status":           status,
            "game_time_utc":    game_time,
            "venue":            venue,
            "away_team":        away_name,
            "home_team":        home_name,
            "away_score":       away_score,
            "home_score":       home_score,
            "away_hits":        away_hits,
            "home_hits":        home_hits,
            "away_errors":      away_errors,
            "home_errors":      home_errors,
            "current_inning":   cur_inning,
            "inning_state":     inn_state,
            "away_pitcher":     away_pitcher,
            "home_pitcher":     home_pitcher,
            "away_win_prob":    round(p_away * 100, 1),
            "home_win_prob":    round(p_home * 100, 1),
            "win_prob_history": history,
            "innings":          inning_rows,
            "away_stats":       away_stats_out,
            "home_stats":       home_stats_out,
        }

        _mlb_game_detail_cache[cache_key] = result
        _mlb_game_detail_cache_time[cache_key] = now
        return result

    except Exception as e:
        raise HTTPException(status_code=502, detail=f"MLB game detail fetch failed: {e}")


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


@app.get("/api/debug/odds")
def debug_odds(sport: str = "baseball_mlb"):
    """Debug: return raw odds data from The Odds API."""
    import json, urllib.request
    if not ODDS_API_KEY:
        return {"error": "No API key configured"}
    url = (
        f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
        f"?apiKey={ODDS_API_KEY}&regions=eu,us,uk&markets=h2h&oddsFormat=decimal"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CourtEdge/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        return {"count": len(data), "games": data[:3]}
    except Exception as e:
        return {"error": str(e)}


def _model_stats_payload(sport: str, features: list[str]) -> dict:
    """Model card for /api/{sport}/stats, read from models/{sport}_metrics.json
    (written by {sport}/train.py). Metrics are for the served logistic regression."""
    import json
    path = ROOT / "models" / f"{sport}_metrics.json"
    if not path.exists():
        raise HTTPException(status_code=503, detail=f"{sport} metrics not found — run {sport}/train.py")
    m = json.loads(path.read_text(encoding="utf-8"))
    lr = m.get("logistic_regression", {})
    per_season = lr.get("per_season", {})
    accs = list(per_season.values())
    return {
        "accuracy":     round(lr.get("accuracy", 0.0) * 100, 2),
        "cv_std":       round(float(np.std(accs)) * 100, 2) if accs else 0.0,
        "cv_folds":     [round(a * 100, 1) for a in accs],
        "n_rows":       m.get("n_rows", 0),
        "seasons":      m.get("seasons", []),
        "features":     features,
        "coefficients": m.get("coefficients", []),
        "log_loss":     lr.get("log_loss"),
        "brier":        lr.get("brier"),
        "calibration":  lr.get("calibration", []),
        "vegas":        lr.get("vegas"),
        "xgboost":      {k: m.get("xgboost", {}).get(k) for k in ("accuracy", "log_loss", "brier")},
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  NFL endpoints
# ═══════════════════════════════════════════════════════════════════════════════
# Data source: ESPN's public site API (site.api.espn.com). Its edge (Akamai)
# 403s "browser-ish but incomplete" User-Agents — the bare "Mozilla/5.0" string
# (same one already used by the NBA injuries fetcher above) passes fine.

NFL_MODEL_PATH   = ROOT / "models" / "nfl_logistic_regression.pkl"
NFL_STATS_PATH   = ROOT / "data" / "nfl" / "nfl_stats_current.csv"
NFL_GAME_FEATURES_PATH = ROOT / "data" / "nfl" / "nfl_game_features_current.csv"
NFL_QB_RATINGS_PATH    = ROOT / "data" / "nfl" / "nfl_qb_ratings.csv"
NFL_CURRENT_SEASON = 2026
NFL_BASE = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
NFL_STANDINGS_BASE = "https://site.api.espn.com/apis/v2/sports/football/nfl/standings"
NFL_UA = {"User-Agent": "Mozilla/5.0"}
# nflverse schedule — refreshed for projected starting QBs (injuries / benchings)
NFL_NFLVERSE_GAMES_URL = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"
NFL_QB_REPLACEMENT = -0.10  # EPA/dropback for a QB with no history (matches nfl/pipeline.py QB_PRIOR)

# Order must match nfl/train.py FEATURES exactly
NFL_FEATURES = [
    "home", "rest_diff", "off_bye", "opp_off_bye",
    "elo_diff",
    "net_epa_diff",
    "qb_epa_diff", "qb_changed", "opp_qb_changed",
]

NFL_ABBR: dict[str, str] = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL",
    "Buffalo Bills": "BUF", "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE", "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX",
    "Kansas City Chiefs": "KC", "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LAR", "Miami Dolphins": "MIA", "Minnesota Vikings": "MIN",
    "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT",
    "San Francisco 49ers": "SF", "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN", "Washington Commanders": "WSH",
}
NFL_COLORS: dict[str, str] = {
    "ARI": "#a40227", "ATL": "#a71930", "BAL": "#29126f", "BUF": "#00338d",
    "CAR": "#0085ca", "CHI": "#0b1c3a", "CIN": "#fb4f14", "CLE": "#472a08",
    "DAL": "#002a5c", "DEN": "#0a2343", "DET": "#0076b6", "GB":  "#204e32",
    "HOU": "#021018", "IND": "#003b75", "JAX": "#007487", "KC":  "#e31837",
    "LV":  "#000000", "LAC": "#0080c6", "LAR": "#003594", "MIA": "#008e97",
    "MIN": "#4f2683", "NE":  "#002a5c", "NO":  "#d3bc8d", "NYG": "#003c7f",
    "NYJ": "#115740", "PHI": "#06424d", "PIT": "#000000", "SF":  "#aa0000",
    "SEA": "#002a5c", "TB":  "#bd1c36", "TEN": "#4495d2", "WSH": "#5a1414",
}

_nfl_model_cache = None
_nfl_stats_cache: pd.DataFrame | None = None

_nfl_week_cache: dict | None = None
_nfl_week_cache_time: float = 0.0
_NFL_WEEK_TTL = 120.0  # 2 minutes

_nfl_standings_cache: dict | None = None
_nfl_standings_cache_time: float = 0.0
_NFL_STANDINGS_TTL = 300.0  # 5 minutes

_nfl_game_pred_cache: dict[str, dict] = {}  # str(event_id) → {away_win_prob, home_win_prob, predicted_winner}


def _load_nfl_model():
    global _nfl_model_cache
    if _nfl_model_cache is None:
        with open(NFL_MODEL_PATH, "rb") as f:
            _nfl_model_cache = pickle.load(f)
    return _nfl_model_cache


def _load_nfl_stats() -> pd.DataFrame:
    global _nfl_stats_cache
    if _nfl_stats_cache is None:
        _nfl_stats_cache = pd.read_csv(NFL_STATS_PATH).set_index("team_name")
    return _nfl_stats_cache


_nfl_game_features_cache: dict[str, dict[str, dict]] | None = None
_nfl_qb_ratings_cache: dict[str, float] | None = None
_nfl_live_qbs_cache: dict[str, dict[str, str]] | None = None
_nfl_live_qbs_cache_time: float = 0.0
_NFL_LIVE_QBS_TTL = 3600.0  # 1 hour


def _load_nfl_game_features() -> dict[str, dict[str, dict]]:
    """{espn_event_id: {team_name: feature row}} for every current-season game,
    precomputed by nfl/pipeline.py (pre-game values for played games)."""
    global _nfl_game_features_cache
    if _nfl_game_features_cache is None:
        out: dict[str, dict[str, dict]] = {}
        if NFL_GAME_FEATURES_PATH.exists():
            df = pd.read_csv(NFL_GAME_FEATURES_PATH, dtype={"espn_id": str})
            for r in df.to_dict("records"):
                out.setdefault(r["espn_id"], {})[r["team_name"]] = r
        _nfl_game_features_cache = out
    return _nfl_game_features_cache


def _load_nfl_qb_ratings() -> dict[str, float]:
    global _nfl_qb_ratings_cache
    if _nfl_qb_ratings_cache is None:
        _nfl_qb_ratings_cache = {}
        if NFL_QB_RATINGS_PATH.exists():
            df = pd.read_csv(NFL_QB_RATINGS_PATH)
            _nfl_qb_ratings_cache = dict(zip(df["qb_id"], df["qb_epa"].astype(float)))
    return _nfl_qb_ratings_cache


def _fetch_nfl_live_qbs() -> dict[str, dict[str, str]]:
    """{espn_event_id: {nflverse_abbr: starting/projected QB id}} from nflverse.
    Returns the last good copy (or {}) if the download fails."""
    import io, urllib.request
    global _nfl_live_qbs_cache, _nfl_live_qbs_cache_time
    now = _time_mod.time()
    if _nfl_live_qbs_cache is not None and (now - _nfl_live_qbs_cache_time) < _NFL_LIVE_QBS_TTL:
        return _nfl_live_qbs_cache
    try:
        req = urllib.request.Request(NFL_NFLVERSE_GAMES_URL, headers=NFL_UA)
        with urllib.request.urlopen(req, timeout=15) as resp:
            g = pd.read_csv(io.BytesIO(resp.read()), low_memory=False)
        g = g[(g["season"] == NFL_CURRENT_SEASON) & g["espn"].notna()]
        out: dict[str, dict[str, str]] = {}
        for r in g.itertuples(index=False):
            qbs = {}
            if isinstance(r.home_qb_id, str):
                qbs[r.home_team] = r.home_qb_id
            if isinstance(r.away_qb_id, str):
                qbs[r.away_team] = r.away_qb_id
            out[str(r.espn).split(".")[0]] = qbs
        _nfl_live_qbs_cache = out
    except Exception:
        if _nfl_live_qbs_cache is None:
            _nfl_live_qbs_cache = {}
    _nfl_live_qbs_cache_time = now
    return _nfl_live_qbs_cache


def _nfl_rows_for_game(game_id: str | None, team: str, opp: str) -> tuple[dict, dict] | None:
    """Precomputed feature rows for (team, opp) in this game, with the starting QBs
    refreshed from nflverse's latest projections."""
    if not game_id:
        return None
    game = _load_nfl_game_features().get(str(game_id))
    if not game or team not in game or opp not in game:
        return None
    r_t, r_o = dict(game[team]), dict(game[opp])

    live = _fetch_nfl_live_qbs().get(str(game_id), {})
    ratings = _load_nfl_qb_ratings()
    qb_epa, qb_changed = {}, {}
    for r in (r_t, r_o):
        qb_id = live.get(r["team"]) or r.get("qb_id")
        last = r.get("last_qb_id")
        qb_epa[r["team"]] = ratings.get(qb_id, NFL_QB_REPLACEMENT) if isinstance(qb_id, str) else NFL_QB_REPLACEMENT
        qb_changed[r["team"]] = int(isinstance(last, str) and isinstance(qb_id, str) and qb_id != last)
    for r, o in ((r_t, r_o), (r_o, r_t)):
        r["qb_epa_diff"]    = qb_epa[r["team"]] - qb_epa[o["team"]]
        r["qb_changed"]     = qb_changed[r["team"]]
        r["opp_qb_changed"] = qb_changed[o["team"]]
    return r_t, r_o


def _nfl_rows_from_team_state(stats: pd.DataFrame, team: str, opp: str, is_home: int) -> tuple[dict, dict]:
    """Fallback for games missing from the precomputed file (e.g. playoffs):
    team strength from the current team table, neutral context."""
    def _row(t, o, home):
        ts, os_ = stats.loc[t], stats.loc[o]
        return {
            "home": home, "rest_diff": 0, "off_bye": 0, "opp_off_bye": 0,
            "elo_diff":    float(ts.get("elo", 1505)) - float(os_.get("elo", 1505)),
            "net_epa_diff": (float(ts.get("off_epa", 0.0)) - float(ts.get("def_epa", 0.0)))
                            - (float(os_.get("off_epa", 0.0)) - float(os_.get("def_epa", 0.0))),
            "qb_epa_diff": float(ts.get("qb_epa", NFL_QB_REPLACEMENT)) - float(os_.get("qb_epa", NFL_QB_REPLACEMENT)),
            "qb_changed": 0, "opp_qb_changed": 0,
        }
    return _row(team, opp, is_home), _row(opp, team, 1 - is_home)


def _nfl_win_prob(model, stats: pd.DataFrame, team: str, opp: str, is_home: int,
                   game_id: str | None = None) -> float:
    """Return P(team wins) using the NFL logistic regression.

    Uses the game's precomputed features (rest, bye, starting QBs) when the
    ESPN event id is known, otherwise falls back to team-level strength only.
    """
    rows = _nfl_rows_for_game(game_id, team, opp) or _nfl_rows_from_team_state(stats, team, opp, is_home)
    X = pd.DataFrame(list(rows))[NFL_FEATURES]
    p_t, p_o = (float(p) for p in model.predict_proba(X)[:, 1])
    return p_t / (p_t + p_o)   # normalise so home+away = 100 %


def _nfl_explain(model, stats: pd.DataFrame, away: str, home: str, game_id: str | None) -> list[dict]:
    """Per-feature contribution to the away-vs-home log-odds gap.

    For the logistic regression, logit(away) − logit(home) = Σ coef·(z_away − z_home),
    so each term is that feature's exact share of the tilt (positive favours away).
    """
    if away not in stats.index or home not in stats.index:
        return []
    rows = _nfl_rows_for_game(game_id, away, home) or _nfl_rows_from_team_state(stats, away, home, 0)
    scaler, clf = model.named_steps["scaler"], model.named_steps["clf"]
    impacts = {f: float(clf.coef_[0][i]) * (float(rows[0][f]) - float(rows[1][f])) / float(scaler.scale_[i])
               for i, f in enumerate(NFL_FEATURES)}
    out = []
    for f, impact in impacts.items():
        if f.startswith("opp_") and f[4:] in impacts:
            continue  # mirror of f[4:] (e.g. opp_off_bye) — folded into that feature below
        impact += impacts.get(f"opp_{f}", 0.0)
        out.append({"feature": f, "away_value": round(float(rows[0][f]), 4),
                    "home_value": round(float(rows[1][f]), 4), "impact": round(impact, 4)})
    return sorted(out, key=lambda r: abs(r["impact"]), reverse=True)


def _fetch_nfl_scoreboard(season: int | None = None, week: int | None = None, seasontype: int = 2) -> dict:
    """Fetch a week's scoreboard. No args = ESPN's current week."""
    import json, urllib.request
    url = f"{NFL_BASE}/scoreboard"
    if season is not None and week is not None:
        url += f"?seasontype={seasontype}&week={week}&dates={season}"
    req = urllib.request.Request(url, headers=NFL_UA)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _predict_nfl_game(model, stats: pd.DataFrame, away_name: str, home_name: str,
                      game_id: str | None = None) -> tuple[float, float, str] | None:
    """Return (away_win_prob_pct, home_win_prob_pct, predicted_winner) or None if a team is unknown."""
    if away_name not in stats.index or home_name not in stats.index:
        return None
    try:
        p_away = _nfl_win_prob(model, stats, away_name, home_name, is_home=0, game_id=game_id)
    except Exception:
        return None
    away_wp = round(p_away * 100, 1)
    home_wp = round((1 - p_away) * 100, 1)
    winner  = away_name if p_away >= 0.5 else home_name
    return away_wp, home_wp, winner


def _fetch_nfl_week() -> dict:
    """Fetch the current NFL week's games with win probabilities and odds."""
    data  = _fetch_nfl_scoreboard()
    model = _load_nfl_model()
    stats = _load_nfl_stats()
    nfl_odds = _fetch_odds_today("americanfootball_nfl")

    season = data.get("season", {}).get("year", NFL_CURRENT_SEASON)
    week   = data.get("week", {}).get("number", 1)

    results = []
    for ev in data.get("events", []):
        comp   = ev.get("competitions", [{}])[0]
        status = comp.get("status", {}).get("type", {})
        competitors = comp.get("competitors", [])
        home = next((c for c in competitors if c.get("homeAway") == "home"), {})
        away = next((c for c in competitors if c.get("homeAway") == "away"), {})
        if not home or not away:
            continue

        away_name = away.get("team", {}).get("displayName", "")
        home_name = home.get("team", {}).get("displayName", "")
        game_id   = ev.get("id")

        def _score(side: dict) -> int | None:
            v = side.get("score")
            try:
                return int(v) if v not in (None, "") else None
            except (TypeError, ValueError):
                return None

        pred = _predict_nfl_game(model, stats, away_name, home_name, game_id)
        if pred is None:
            continue
        away_wp, home_wp, pred_winner = pred

        game_odds = _get_game_odds(nfl_odds, away_name, home_name)
        status_desc = status.get("description", "Scheduled")
        is_done = bool(status.get("completed", False))
        game_key = f"{_normalize_team(away_name)}|{_normalize_team(home_name)}"
        has_pregame = game_key in _pregame_odds
        if is_done and not has_pregame:
            game_odds = {}

        gid_str = str(game_id)
        if gid_str not in _nfl_game_pred_cache:
            _nfl_game_pred_cache[gid_str] = {
                "away_win_prob": away_wp, "home_win_prob": home_wp, "predicted_winner": pred_winner,
            }

        results.append({
            "game_id":          game_id,
            "status":           status_desc,
            "status_state":     status.get("state", "pre"),
            "game_time_utc":    ev.get("date", ""),
            "venue":            comp.get("venue", {}).get("fullName", ""),
            "away_team":        away_name,
            "home_team":        home_name,
            "away_score":       _score(away),
            "home_score":       _score(home),
            "away_win_prob":    away_wp,
            "home_win_prob":    home_wp,
            "predicted_winner": pred_winner,
            "away_odds":        game_odds.get("away_odds"),
            "home_odds":        game_odds.get("home_odds"),
            **_value_bet(away_wp, home_wp, game_odds.get("away_odds"), game_odds.get("home_odds")),
        })

    return {"season": season, "week": week, "games": results}


@app.get("/api/nfl/week")
def get_nfl_week():
    """Return the current NFL week's games with win probabilities and odds."""
    import time as _t
    global _nfl_week_cache, _nfl_week_cache_time
    now = _t.time()
    if _nfl_week_cache is not None and (now - _nfl_week_cache_time) < _NFL_WEEK_TTL:
        return _nfl_week_cache
    try:
        result = _fetch_nfl_week()
        _nfl_week_cache      = result
        _nfl_week_cache_time = now
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"NFL week fetch failed: {e}")


@app.get("/api/nfl/teams")
def get_nfl_teams() -> list[str]:
    return sorted(_load_nfl_stats().index.tolist())


_nfl_pred_log_cache: dict | None = None
_nfl_pred_log_cache_time: float = 0.0
_NFL_PRED_LOG_TTL = 300.0  # 5 minutes


@app.get("/api/nfl/predictions_log")
def get_nfl_predictions_log(n: int = 500):
    """Return completed NFL games this season with model prediction vs actual result."""
    import time as _t
    global _nfl_pred_log_cache, _nfl_pred_log_cache_time
    now = _t.time()
    if _nfl_pred_log_cache is not None and (now - _nfl_pred_log_cache_time) < _NFL_PRED_LOG_TTL:
        cached_log = _nfl_pred_log_cache["log"]
        return {"log": cached_log[:n]}

    try:
        model = _load_nfl_model()
        stats = _load_nfl_stats()
        nfl_odds = _fetch_odds_today("americanfootball_nfl")  # noqa: F841 (kept for parity/debug)

        log: list[dict] = []
        for week in range(1, 19):
            try:
                data = _fetch_nfl_scoreboard(season=NFL_CURRENT_SEASON, week=week)
            except Exception:
                continue
            for ev in data.get("events", []):
                comp   = ev.get("competitions", [{}])[0]
                status = comp.get("status", {}).get("type", {})
                if not status.get("completed", False):
                    continue
                competitors = comp.get("competitors", [])
                home = next((c for c in competitors if c.get("homeAway") == "home"), {})
                away = next((c for c in competitors if c.get("homeAway") == "away"), {})
                if not home or not away:
                    continue
                away_name = away.get("team", {}).get("displayName", "")
                home_name = home.get("team", {}).get("displayName", "")
                try:
                    away_score = int(away.get("score", 0) or 0)
                    home_score = int(home.get("score", 0) or 0)
                except (TypeError, ValueError):
                    continue
                if away_score == home_score:
                    continue  # ties aren't modeled

                game_id = ev.get("id")
                gid_str = str(game_id)
                cached  = _nfl_game_pred_cache.get(gid_str)
                if cached:
                    away_win_prob    = cached["away_win_prob"]
                    home_win_prob    = cached["home_win_prob"]
                    predicted_winner = cached["predicted_winner"]
                else:
                    pred = _predict_nfl_game(model, stats, away_name, home_name, gid_str)
                    if pred is None:
                        continue
                    away_win_prob, home_win_prob, predicted_winner = pred

                predicted_prob = away_win_prob if predicted_winner == away_name else home_win_prob
                actual_winner  = away_name if away_score > home_score else home_name

                log.append({
                    "game_id":          game_id,
                    "date":             (ev.get("date") or "")[:10],
                    "week":             week,
                    "away_team":        away_name,
                    "home_team":        home_name,
                    "predicted_winner": predicted_winner,
                    "predicted_prob":   predicted_prob,
                    "actual_winner":    actual_winner,
                    "correct":          predicted_winner == actual_winner,
                    "away_score":       away_score,
                    "home_score":       home_score,
                    "away_win_prob":    away_win_prob,
                    "home_win_prob":    home_win_prob,
                })

        log.reverse()  # most recent first
        result = {"log": log}
        _nfl_pred_log_cache = result
        _nfl_pred_log_cache_time = now
        return {"log": log[:n]}
    except Exception:
        return {"log": []}


_nfl_proj_cache: dict | None = None
_nfl_proj_cache_time: float = 0.0
_NFL_PROJ_TTL = 600.0  # 10 minutes
NFL_SIMS = 10_000
NFL_MARGIN_SD = 13.5   # SD of NFL final margins — converts win probability <-> point spread
NFL_HFA_PTS = 1.5      # home-field edge in points for simulated playoff games
NFL_POWER_HISTORY_PATH = ROOT / "data" / "nfl" / "nfl_power_history.csv"


def _nfl_fetch_standings() -> dict[str, dict]:
    """{team: {wins, losses, ties, conference, division}} from ESPN (live), falling back to
    the team table written by nfl/pipeline.py when ESPN is unreachable."""
    import json, urllib.request
    try:
        req = urllib.request.Request(f"{NFL_STANDINGS_BASE}?season={NFL_CURRENT_SEASON}&level=3", headers=NFL_UA)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception:
        stats = _load_nfl_stats()
        if "division" not in stats.columns:
            raise
        return {t: {"wins": int(r["wins"]), "losses": int(r["losses"]), "ties": int(r["ties"]),
                    "conference": r["conference"], "division": r["division"]}
                for t, r in stats.iterrows()}
    out: dict[str, dict] = {}
    for conf in data.get("children", []):
        conf_abbr = conf.get("abbreviation") or conf.get("name", "")
        for div in conf.get("children", []):
            for entry in div.get("standings", {}).get("entries", []):
                st = {x["name"]: float(x.get("value") or 0) for x in entry.get("stats", [])}
                out[entry.get("team", {}).get("displayName", "")] = {
                    "wins": int(st.get("wins", 0)), "losses": int(st.get("losses", 0)), "ties": int(st.get("ties", 0)),
                    "conference": conf_abbr, "division": div.get("name", ""),
                }
    return out


def _nfl_split_schedule() -> tuple[int, list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    """(current week, played, remaining) regular-season games as (event id, home, away).

    Earlier weeks count as played; this week's games are played once ESPN marks them final.
    """
    games = _load_nfl_game_features()
    try:
        week_data = get_nfl_week()
        cur_week = int(week_data.get("week", 1))
        done_this_week = {str(g["game_id"]) for g in week_data.get("games", []) if g.get("status_state") == "post"}
    except Exception:
        # ESPN unreachable: trust the results recorded by the last pipeline run
        done_this_week = {gid for gid, rows in games.items()
                          if not pd.isna(next(iter(rows.values())).get("win"))}
        pending = [int(next(iter(rows.values()))["week"]) for gid, rows in games.items() if gid not in done_this_week]
        cur_week = min(pending, default=18)
    played, remaining = [], []
    for gid, rows in games.items():
        r = next((x for x in rows.values() if x.get("home") == 1), None) or next(iter(rows.values()))
        game = (gid, r["team_name"], r["opp_name"])
        week = int(r.get("week", 0))
        if week < cur_week or (week == cur_week and gid in done_this_week):
            played.append(game)
        else:
            remaining.append(game)
    return cur_week, played, remaining


def _nfl_power_ratings(state: pd.DataFrame) -> pd.Series:
    """Expected point margin vs an average team on a neutral field, from the model.

    Each team is scored against a synthetic league-average opponent (mean Elo, EPA and
    QB rating); the head-to-head win probability is converted to points via NFL_MARGIN_SD.
    """
    from statistics import NormalDist
    model = _load_nfl_model()
    net = state["off_epa"] - state["def_epa"]
    zero = {f: 0.0 for f in NFL_FEATURES}
    rows = []
    for t in state.index:
        diff = {"elo_diff": state.at[t, "elo"] - state["elo"].mean(),
                "net_epa_diff": net[t] - net.mean(),
                "qb_epa_diff": state.at[t, "qb_epa"] - state["qb_epa"].mean()}
        rows.append({**zero, **diff})
        rows.append({**zero, **{k: -v for k, v in diff.items()}})
    raw = model.predict_proba(pd.DataFrame(rows)[NFL_FEATURES])[:, 1].reshape(-1, 2)
    p = np.clip(raw[:, 0] / raw.sum(axis=1), 1e-4, 1 - 1e-4)
    nd = NormalDist()
    return pd.Series([NFL_MARGIN_SD * nd.inv_cdf(float(x)) for x in p], index=state.index)


def _nfl_current_power() -> pd.Series:
    stats = _load_nfl_stats()
    return _nfl_power_ratings(stats[["elo", "off_epa", "def_epa", "qb_epa"]])


@app.get("/api/nfl/projections")
def get_nfl_projections():
    """Monte Carlo of the rest of the season and the playoffs.

    Regular season: current records from ESPN; every remaining game uses the model's
    pre-game probability (held fixed — ratings don't update mid-simulation). Seeding
    follows the NFL format (4 division winners + 3 wild cards per conference); ties in
    the win column are broken at random rather than by the official tiebreakers.
    Playoffs: single elimination, #1 seed bye, games decided from power ratings with a
    small home edge for the higher seed (Super Bowl neutral).
    """
    global _nfl_proj_cache, _nfl_proj_cache_time
    from scipy.special import ndtr
    now = _time_mod.time()
    if _nfl_proj_cache is not None and (now - _nfl_proj_cache_time) < _NFL_PROJ_TTL:
        return _nfl_proj_cache

    try:
        standings = _nfl_fetch_standings()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"NFL standings fetch failed: {e}")
    teams = list(standings)
    idx = {t: i for i, t in enumerate(teams)}
    conf_of = {t: s["conference"] for t, s in standings.items()}
    div_of = {t: s["division"] for t, s in standings.items()}

    cur_week, _, remaining_games = _nfl_split_schedule()
    model, stats = _load_nfl_model(), _load_nfl_stats()
    pairs, feat_rows = [], []
    for gid, home_name, away_name in remaining_games:
        if home_name not in idx or away_name not in idx:
            continue
        r_home, r_away = _nfl_rows_for_game(gid, home_name, away_name) or \
            _nfl_rows_from_team_state(stats, home_name, away_name, 1)
        pairs.append((idx[home_name], idx[away_name]))
        feat_rows += [r_home, r_away]

    rng = np.random.default_rng()
    n_t = len(teams)
    wins = np.tile(np.array([standings[t]["wins"] + 0.5 * standings[t]["ties"] for t in teams], float), (NFL_SIMS, 1))
    if pairs:
        raw = model.predict_proba(pd.DataFrame(feat_rows)[NFL_FEATURES])[:, 1].reshape(-1, 2)
        p_home = raw[:, 0] / raw.sum(axis=1)   # same head-to-head normalisation as _nfl_win_prob
        h_idx, a_idx = np.array([p[0] for p in pairs]), np.array([p[1] for p in pairs])
        home_won = rng.random((NFL_SIMS, len(pairs))) < p_home
        np.add.at(wins, (slice(None), h_idx), home_won.astype(float))
        np.add.at(wins, (slice(None), a_idx), (~home_won).astype(float))
    noisy = wins + rng.random(wins.shape) * 1e-3   # random tiebreak

    power = _nfl_current_power()
    pw = np.array([float(power.get(t, 0.0)) for t in teams])
    rows_ix = np.arange(NFL_SIMS)

    def play(home: np.ndarray, away: np.ndarray, hfa: float) -> np.ndarray:
        p = ndtr((pw[home] - pw[away] + hfa) / NFL_MARGIN_SD)
        return np.where(rng.random(NFL_SIMS) < p, home, away)

    made = np.zeros((NFL_SIMS, n_t), bool)
    div_win = np.zeros((NFL_SIMS, n_t), bool)
    top_seed = np.zeros((NFL_SIMS, n_t), bool)
    conf_champ = np.zeros((NFL_SIMS, n_t), bool)
    champs = []
    for conf in sorted(set(conf_of.values())):
        c_teams = [idx[t] for t in teams if conf_of[t] == conf]
        leaders = []
        for div in sorted({div_of[teams[i]] for i in c_teams}):
            d_teams = np.array([i for i in c_teams if div_of[teams[i]] == div])
            leader = d_teams[noisy[:, d_teams].argmax(axis=1)]
            div_win[rows_ix, leader] = True
            leaders.append(leader)
        leaders = np.stack(leaders, axis=1)                                   # (sims, 4)
        order = np.argsort(-noisy[rows_ix[:, None], leaders], axis=1)
        div_seeds = np.take_along_axis(leaders, order, axis=1)               # seeds 1-4
        c_arr = np.array(c_teams)
        wc_score = np.where(div_win[:, c_arr], -np.inf, noisy[:, c_arr])
        wc_seeds = c_arr[np.argsort(-wc_score, axis=1)[:, :3]]               # seeds 5-7
        seeds = np.concatenate([div_seeds, wc_seeds], axis=1)                # (sims, 7)
        made[rows_ix[:, None], seeds] = True
        top_seed[rows_ix, seeds[:, 0]] = True

        # Bracket on seed positions (0 = #1 seed); the higher seed hosts
        def game_pos(hp: np.ndarray, ap: np.ndarray, seeds=seeds) -> np.ndarray:
            winner = play(seeds[rows_ix, hp], seeds[rows_ix, ap], NFL_HFA_PTS)
            return np.where(winner == seeds[rows_ix, hp], hp, ap)
        full = lambda k: np.full(NFL_SIMS, k)
        wc = np.sort(np.stack([game_pos(full(1), full(6)), game_pos(full(2), full(5)),
                               game_pos(full(3), full(4))], axis=1), axis=1)
        d1 = game_pos(full(0), wc[:, 2])             # #1 seed hosts the lowest survivor
        d2 = game_pos(wc[:, 0], wc[:, 1])
        champ = seeds[rows_ix, game_pos(np.minimum(d1, d2), np.maximum(d1, d2))]
        conf_champ[rows_ix, champ] = True
        champs.append(champ)

    sb = play(champs[0], champs[1], 0.0)
    sb_win = np.zeros((NFL_SIMS, n_t), bool)
    sb_win[rows_ix, sb] = True

    out = [{
        "team":           t,
        "conference":     conf_of[t],
        "division":       div_of[t],
        "power":          round(float(pw[i]), 1),
        "projected_wins": round(float(wins[:, i].mean()), 1),
        "playoff_pct":    round(float(made[:, i].mean()) * 100, 1),
        "division_pct":   round(float(div_win[:, i].mean()) * 100, 1),
        "top_seed_pct":   round(float(top_seed[:, i].mean()) * 100, 1),
        "conf_pct":       round(float(conf_champ[:, i].mean()) * 100, 1),
        "sb_win_pct":     round(float(sb_win[:, i].mean()) * 100, 1),
    } for t, i in idx.items()]
    out.sort(key=lambda r: (-r["sb_win_pct"], -r["playoff_pct"]))

    result = {"season": NFL_CURRENT_SEASON, "week": cur_week, "simulations": NFL_SIMS,
              "games_remaining": len(pairs), "teams": out}
    _nfl_proj_cache, _nfl_proj_cache_time = result, now
    return result


_nfl_power_cache: dict | None = None
_nfl_power_cache_time: float = 0.0


@app.get("/api/nfl/power")
def get_nfl_power():
    """Power index: model-based rating (points vs an average team, neutral field), rank,
    rank change since the start of the latest week, EPA-based offense / defense /
    special-teams components, strength of schedule and efficiency stats."""
    global _nfl_power_cache, _nfl_power_cache_time
    now = _time_mod.time()
    if _nfl_power_cache is not None and (now - _nfl_power_cache_time) < _NFL_PROJ_TTL:
        return _nfl_power_cache

    try:
        standings = _nfl_fetch_standings()
    except Exception:
        standings = {}
    stats = _load_nfl_stats()
    power = _nfl_current_power()
    rank = power.rank(ascending=False, method="first").astype(int)

    prev_rank: pd.Series | None = None
    prev_week = None
    if NFL_POWER_HISTORY_PATH.exists():
        hist = pd.read_csv(NFL_POWER_HISTORY_PATH)
        if not hist.empty:
            prev_week = int(hist["week"].max())
            name_of = {str(stats.at[n, "abbr"]): n for n in stats.index}
            snap = hist[hist["week"] == prev_week].copy()
            snap["team_name"] = snap["team"].map(name_of)
            snap = snap.dropna(subset=["team_name"]).set_index("team_name")[["elo", "off_epa", "def_epa", "qb_epa"]]
            prev_rank = _nfl_power_ratings(snap).rank(ascending=False, method="first").astype(int)

    # Strength of schedule: mean opponent power, ranked (1 = toughest)
    _, played, remaining = _nfl_split_schedule()
    opp_played: dict[str, list[float]] = {t: [] for t in stats.index}
    opp_left: dict[str, list[float]] = {t: [] for t in stats.index}
    for games, bucket in ((played, opp_played), (remaining, opp_left)):
        for _, home, away in games:
            if home in bucket and away in power.index:
                bucket[home].append(float(power[away]))
            if away in bucket and home in power.index:
                bucket[away].append(float(power[home]))
    sos_rank = pd.Series({t: np.mean(v) if v else np.nan for t, v in opp_played.items()}).rank(ascending=False, method="min")
    rem_rank = pd.Series({t: np.mean(v) if v else np.nan for t, v in opp_left.items()}).rank(ascending=False, method="min")

    def rk(series: pd.Series, t: str, ascending: bool = False) -> int:
        return int(series.rank(ascending=ascending, method="min")[t])

    off_pts, def_pts, st_pts = stats["off_pts"], -stats["def_pts"], stats["st_pts"]
    teams = []
    for t in stats.index:
        rec = standings.get(t, {})
        teams.append({
            "team":   t,
            "wins":   rec.get("wins", int(stats.at[t, "wins"])),
            "losses": rec.get("losses", int(stats.at[t, "losses"])),
            "ties":   rec.get("ties", int(stats.at[t, "ties"])),
            "power":  round(float(power[t]), 1),
            "rank":   int(rank[t]),
            "trend":  None if prev_rank is None or t not in prev_rank.index else int(prev_rank[t] - rank[t]),
            "off":    round(float(off_pts[t]), 1),
            "def":    round(float(def_pts[t]), 1),
            "st":     round(float(st_pts[t]), 1),
            "sos_rank":     None if pd.isna(sos_rank[t]) else int(sos_rank[t]),
            "rem_sos_rank": None if pd.isna(rem_rank[t]) else int(rem_rank[t]),
            "elo":     round(float(stats.at[t, "elo"])),
            "qb_name": str(stats.at[t, "qb_name"]),
            "qb_epa":  round(float(stats.at[t, "qb_epa"]), 3),
            # Efficiencies (EPA per play; defense = EPA allowed, lower is better)
            "off_epa":      round(float(stats.at[t, "off_epa"]), 3),
            "def_epa":      round(float(stats.at[t, "def_epa"]), 3),
            "off_pass_epa": round(float(stats.at[t, "off_pass_epa"]), 3),
            "def_pass_epa": round(float(stats.at[t, "def_pass_epa"]), 3),
            "off_epa_rank":      rk(stats["off_epa"], t),
            "def_epa_rank":      rk(stats["def_epa"], t, ascending=True),
            "off_pass_epa_rank": rk(stats["off_pass_epa"], t),
            "def_pass_epa_rank": rk(stats["def_pass_epa"], t, ascending=True),
            "st_rank":           rk(st_pts, t),
            "qb_rank":           rk(stats["qb_epa"], t),
        })
    teams.sort(key=lambda r: r["rank"])
    result = {"season": NFL_CURRENT_SEASON, "trend_since_week": prev_week, "teams": teams}
    _nfl_power_cache, _nfl_power_cache_time = result, now
    return result


@app.get("/api/nfl/standings")
def get_nfl_standings():
    """Return AFC and NFC standings by division, enriched with rolling form."""
    import time as _t, json, urllib.request
    global _nfl_standings_cache, _nfl_standings_cache_time
    now = _t.time()
    if _nfl_standings_cache is not None and (now - _nfl_standings_cache_time) < _NFL_STANDINGS_TTL:
        return _nfl_standings_cache

    try:
        url  = f"{NFL_STANDINGS_BASE}?season={NFL_CURRENT_SEASON}&level=3"
        req  = urllib.request.Request(url, headers=NFL_UA)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        stats = _load_nfl_stats()

        def _build_conf(conf: dict) -> list[dict]:
            divs = []
            for div in conf.get("children", []):
                teams = []
                for entry in div.get("standings", {}).get("entries", []):
                    name  = entry.get("team", {}).get("displayName", "")
                    s     = {st["name"]: st for st in entry.get("stats", [])}
                    l5 = pd5 = None
                    if name in stats.index:
                        row = stats.loc[name]
                        l5  = round(float(row.get("win_pct_last5", 0.5)), 3)
                        pd5 = round(float(row.get("point_diff_last5", 0.0)), 1)
                    teams.append({
                        "name":     name,
                        "w":        int(s.get("wins", {}).get("value", 0) or 0),
                        "l":        int(s.get("losses", {}).get("value", 0) or 0),
                        "t":        int(s.get("ties", {}).get("value", 0) or 0),
                        "pct":      s.get("winPercent", {}).get("displayValue", ".000"),
                        "pf":       int(s.get("pointsFor", {}).get("value", 0) or 0),
                        "pa":       int(s.get("pointsAgainst", {}).get("value", 0) or 0),
                        "point_diff": int(s.get("pointDifferential", {}).get("value", 0) or 0),
                        "streak":   s.get("streak", {}).get("displayValue", "-"),
                        "win_pct_last5":    l5,
                        "point_diff_last5": pd5,
                    })
                teams.sort(key=lambda t: (-t["w"], t["l"]))
                divs.append({"name": div.get("name", ""), "teams": teams})
            return divs

        afc = nfc = []
        for conf in data.get("children", []):
            conf_name = conf.get("name", "")
            if "American" in conf_name:
                afc = _build_conf(conf)
            elif "National" in conf_name:
                nfc = _build_conf(conf)

        result = {"afc": afc, "nfc": nfc}
        _nfl_standings_cache      = result
        _nfl_standings_cache_time = now
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"NFL standings fetch failed: {e}")


@app.get("/api/nfl/stats")
def get_nfl_model_stats():
    """Return NFL model accuracy, calibration, Vegas comparison, features and coefficients."""
    return _model_stats_payload("nfl", NFL_FEATURES)


_NFL_INJURY_ORDER = {"out": 0, "injured reserve": 1, "physically unable to perform": 1, "suspension": 2,
                     "doubtful": 3, "questionable": 4, "day-to-day": 5}


def _nfl_parse_injuries(summary: dict) -> dict[str, list[dict]]:
    """{team displayName: [injured players]} from an ESPN game summary, most serious first."""
    out: dict[str, list[dict]] = {}
    for team in summary.get("injuries", []):
        name = team.get("team", {}).get("displayName", "")
        players = []
        for inj in team.get("injuries", []):
            ath = inj.get("athlete", {})
            det = inj.get("details", {})
            # ESPN mixes "Out" / "out" — normalise to title case
            status = (inj.get("type", {}).get("description") or inj.get("status") or "Unknown").title()
            detail = det.get("detail") or det.get("type") or ""
            players.append({
                "name":        ath.get("displayName", ""),
                "position":    ath.get("position", {}).get("abbreviation", ""),
                "status":      status,
                "injury":      "" if detail.lower() == "not specified" else detail,
                "return_date": (det.get("returnDate") or "")[:10] or None,
            })
        players.sort(key=lambda p: (_NFL_INJURY_ORDER.get(p["status"].lower(), 9), p["position"] != "QB", p["name"]))
        out[name] = players
    return out


_NFL_GAME_STAT_KEYS = ["totalYards", "netPassingYards", "rushingYards", "turnovers", "thirdDownEff", "totalPenaltiesYards", "possessionTime"]


def _nfl_quarter_win_prob(
    pre_game_home_prob: float,
    home_score: int,
    away_score: int,
    quarter: float,
    total_quarters: float = 4.0,
) -> float:
    """Blended home-team win probability after `quarter` completed quarters.

    Blends the pre-game ML probability (prior) with a current-state estimate
    derived from a Normal approximation of the remaining scoring differential.
    `full_game_std` (~13.5 pts) approximates the typical NFL final-score-diff spread.
    """
    import math
    score_diff        = home_score - away_score        # positive = home leading
    quarters_remaining = max(0.15, total_quarters - quarter)
    full_game_std = 13.5
    std_net  = full_game_std * math.sqrt(quarters_remaining / 4.0)
    z        = score_diff / std_net
    cur_prob = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    progress = min(0.95, quarter / total_quarters)
    p = (1.0 - progress) * pre_game_home_prob + progress * cur_prob
    return max(0.02, min(0.98, p))


@app.get("/api/nfl/game/{game_id}")
def get_nfl_game_detail(game_id: str):
    """Return box score, quarter-by-quarter score, and team stat comparison for one game."""
    import json, urllib.request
    try:
        url = f"{NFL_BASE}/summary?event={game_id}"
        req = urllib.request.Request(url, headers=NFL_UA)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        header = data.get("header", {})
        comp   = header.get("competitions", [{}])[0]
        status = comp.get("status", {}).get("type", {})
        competitors = comp.get("competitors", [])
        home = next((c for c in competitors if c.get("homeAway") == "home"), {})
        away = next((c for c in competitors if c.get("homeAway") == "away"), {})

        away_name = away.get("team", {}).get("displayName", "")
        home_name = home.get("team", {}).get("displayName", "")

        def _score(side: dict) -> int | None:
            v = side.get("score")
            try:
                return int(v) if v not in (None, "") else None
            except (TypeError, ValueError):
                return None

        def _quarters(side: dict) -> list[int | None]:
            out = []
            for q in side.get("linescores", []):
                v = q.get("displayValue")
                try:
                    out.append(int(v))
                except (TypeError, ValueError):
                    out.append(None)
            return out

        # Pre-game win probability — prefer the cached value from /api/nfl/week
        # so the detail page matches what the schedule card showed.
        cached_pred = _nfl_game_pred_cache.get(str(game_id))
        if cached_pred:
            away_wp = cached_pred["away_win_prob"]
            home_wp = cached_pred["home_win_prob"]
        else:
            model = _load_nfl_model()
            stats = _load_nfl_stats()
            pred  = _predict_nfl_game(model, stats, away_name, home_name, game_id)
            away_wp, home_wp = pred[0:2] if pred else (50.0, 50.0)

        # ── Play-by-play win probability (ESPN's own per-play model) ──────────
        away_q = _quarters(away)
        home_q = _quarters(home)
        p_home_pre = home_wp / 100.0
        is_final = "final" in status.get("description", "").lower()

        history: list[dict] = [{
            "idx":       0,
            "label":     "Pre",
            "away_prob": round(away_wp, 1),
            "home_prob": round(home_wp, 1),
        }]

        win_prob_plays = data.get("winprobability", [])
        play_map: dict[str, dict] = {
            play.get("id"): play
            for drive in data.get("drives", {}).get("previous", [])
            for play in drive.get("plays", [])
        }

        if win_prob_plays:
            last_period = None
            for i, wp in enumerate(win_prob_plays):
                play       = play_map.get(wp.get("playId"), {})
                period_num = (play.get("period") or {}).get("number")
                home_pct   = float(wp.get("homeWinPercentage", 0.5)) * 100
                tie_pct    = float(wp.get("tiePercentage", 0.0)) * 100
                away_pct   = max(0.0, 100.0 - home_pct - tie_pct)

                label = ""
                if period_num is not None and period_num != last_period:
                    label = f"Q{period_num}" if period_num <= 4 else f"OT{period_num - 4}"
                    last_period = period_num

                history.append({
                    "idx":          i + 1,
                    "label":        label,
                    "away_prob":    round(away_pct, 1),
                    "home_prob":    round(home_pct, 1),
                    "scoring_play": bool(play.get("scoringPlay", False)),
                    "away_score":   play.get("awayScore"),
                    "home_score":   play.get("homeScore"),
                })
        else:
            # Fallback: coarse quarter-by-quarter estimate when ESPN has no
            # play-by-play win probability for this game (e.g. very old games).
            home_total = away_total = 0
            for i in range(min(len(away_q), len(home_q))):
                a_val, h_val = away_q[i], home_q[i]
                if a_val is None or h_val is None:
                    break
                away_total += a_val
                home_total += h_val
                quarter_num = i + 1
                total_q     = float(max(4, quarter_num))
                p_h = _nfl_quarter_win_prob(p_home_pre, home_total, away_total, float(quarter_num), total_q)
                label = f"Q{quarter_num}" if quarter_num <= 4 else f"OT{quarter_num - 4}"
                history.append({
                    "idx":       i + 1,
                    "label":     label,
                    "away_prob": round((1.0 - p_h) * 100, 1),
                    "home_prob": round(p_h * 100, 1),
                })

            if is_final and len(history) > 1:
                away_final, home_final = _score(away), _score(home)
                if home_final is not None and away_final is not None:
                    if home_final > away_final:
                        history[-1]["home_prob"] = 100.0
                        history[-1]["away_prob"] = 0.0
                    elif away_final > home_final:
                        history[-1]["home_prob"] = 0.0
                        history[-1]["away_prob"] = 100.0

        # Team stat comparison
        box_teams = data.get("boxscore", {}).get("teams", [])
        away_stats_out: dict[str, str] = {}
        home_stats_out: dict[str, str] = {}
        for bt in box_teams:
            is_home = bt.get("homeAway") == "home"
            target  = home_stats_out if is_home else away_stats_out
            for s in bt.get("statistics", []):
                if s.get("name") in _NFL_GAME_STAT_KEYS:
                    target[s["name"]] = s.get("displayValue", "")

        injuries = _nfl_parse_injuries(data)
        result = {
            "game_id":       game_id,
            "status":        status.get("description", "Scheduled"),
            "game_time_utc": comp.get("date", ""),
            "venue":         data.get("gameInfo", {}).get("venue", {}).get("fullName", ""),
            "away_team":     away_name,
            "home_team":     home_name,
            "away_score":    _score(away),
            "home_score":    _score(home),
            "away_quarters": _quarters(away),
            "home_quarters": _quarters(home),
            "away_win_prob": away_wp,
            "home_win_prob": home_wp,
            "win_prob_history": history,
            "away_stats":    away_stats_out,
            "home_stats":    home_stats_out,
            "explanation":   _nfl_explain(_load_nfl_model(), _load_nfl_stats(), away_name, home_name, game_id),
            "away_injuries": injuries.get(away_name, []),
            "home_injuries": injuries.get(home_name, []),
        }
        return result

    except Exception as e:
        raise HTTPException(status_code=502, detail=f"NFL game detail fetch failed: {e}")
