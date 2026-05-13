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
]
# Features read directly from the stats CSV (home + per-game context injected separately)
STAT_FEATURES = [f for f in FEATURES if f not in ("home", "back_to_back", "travel_km", "prev_margin")]
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
    df["rest_days"]    = 5
    df["back_to_back"] = 0
    df["travel_km"]    = 0.0
    df["prev_margin"]  = 0.0
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


def _load_stats_by_name() -> pd.DataFrame:
    df = pd.read_csv(STATS_PATH)
    df = _merge_playoff_stats(df)
    return _add_context_defaults(df).set_index("team_name")


def _load_stats_by_id() -> pd.DataFrame:
    df = pd.read_csv(STATS_PATH)
    df = _merge_playoff_stats(df)
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
    ctx_a: dict | None = None,
    ctx_b: dict | None = None,
) -> float:
    """Return P(team_a wins a single game) via normalized logistic scores.

    ctx_a / ctx_b override contextual features (back_to_back, travel_km, prev_margin).
    """
    defaults = {"back_to_back": 0, "travel_km": 0.0, "prev_margin": 0.0}

    a = stats.loc[team_a, STAT_FEATURES].to_dict()
    a["home"] = 1 if team_a_is_home else 0
    a.update(defaults)
    if ctx_a:
        a.update(ctx_a)

    b = stats.loc[team_b, STAT_FEATURES].to_dict()
    b["home"] = 0 if team_a_is_home else 1
    b.update(defaults)
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


def _simulate_series(game_probs: list, n: int = 10_000, seed: int = 42) -> list:
    """Monte Carlo simulation using per-game probabilities (2-2-1-1-1 schedule)."""
    rng = np.random.default_rng(seed)
    buckets = {"4-0": [0, 0], "4-1": [0, 0], "4-2": [0, 0], "4-3": [0, 0]}
    for _ in range(n):
        wa = wb = game_idx = 0
        while wa < 4 and wb < 4:
            if rng.random() < game_probs[game_idx]:
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


def _sample_series(game_probs: list, team_a: str, team_b: str, seed: int = 7) -> list:
    """Draw one representative series using per-game probabilities."""
    rng = np.random.default_rng(seed)
    games, wa, wb, game_idx = [], 0, 0, 0
    while wa < 4 and wb < 4:
        p = game_probs[game_idx]
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
    # team_a is assumed to have home court (higher seed); 2-2-1-1-1 schedule
    game_probs = [
        _adjust_for_injuries(
            _game_prob(model, stats_by_name, team_a, team_b, team_a_is_home=h),
            injury_a, injury_b,
        )
        for h in HOME_SCHEDULE
    ]
    avg_p = sum(game_probs) / len(game_probs)
    outcomes = _simulate_series(game_probs)
    series_a = sum(o["team_a_pct"] for o in outcomes)
    series_b = sum(o["team_b_pct"] for o in outcomes)
    return {
        "team_a": team_a,
        "team_b": team_b,
        "team_a_series_prob": round(series_a, 1),
        "team_b_series_prob": round(series_b, 1),
        "team_a_game_prob": round(avg_p * 100, 1),
        "team_b_game_prob": round((1 - avg_p) * 100, 1),
        "predicted_winner": team_a if series_a >= series_b else team_b,
        "games": _sample_series(game_probs, team_a, team_b),
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
    return df[["PLAYER_NAME", "TEAM_ABBREVIATION", "MIN", "PTS"]].copy()


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
    team_df   = player_minutes[player_minutes["TEAM_ABBREVIATION"] == abbr].copy()
    top8      = team_df.nlargest(8, "MIN")
    top8_names = set(top8["PLAYER_NAME"].str.lower())
    total_min  = float(top8["MIN"].sum())
    name_to_min = {r["PLAYER_NAME"].lower(): float(r["MIN"]) for _, r in team_df.iterrows()}
    name_to_pts = {r["PLAYER_NAME"].lower(): float(r["PTS"]) for _, r in team_df.iterrows()}

    missing_min = 0.0
    affected: list[dict] = []

    for inj in injuries:
        name   = inj.get("athlete", {}).get("displayName", "")
        status = inj.get("status", "")
        weight = STATUS_WEIGHTS.get(status, 0.0)
        if not name or weight == 0.0:
            continue

        mpg = name_to_min.get(name.lower())
        ppg = name_to_pts.get(name.lower())

        # Only count impact for top-8 players but show all injured players
        if mpg is not None and name.lower() in top8_names and total_min > 0:
            missing_min += mpg * weight

        affected.append({
            "name":         name,
            "status":       status,
            "pts_per_game": round(ppg, 1) if ppg is not None else None,
        })

    factor = max(0.40, round(1.0 - missing_min / total_min, 3)) if total_min > 0 else 1.0
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
                    factor, _ = _compute_injury_factor(inj, name, player_minutes)
                    injury_factors[name] = factor

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

        try:
            p_raw = _game_prob(
                model, stats_by_name, away_name, home_name,
                team_a_is_home=False, ctx_a=ctx_away, ctx_b=ctx_home,
            )
            p_away = _adjust_for_injuries(
                p_raw,
                injury_factors.get(away_name, 1.0),
                injury_factors.get(home_name, 1.0),
            )
        except Exception:
            continue

        results.append({
            "game_id":          g["gameId"],
            "status":           STATUS.get(g["gameStatus"], "Scheduled"),
            "status_text":      g.get("gameStatusText", "TBD"),
            "away_team":        away_name,
            "home_team":        home_name,
            "away_score":       away.get("score"),
            "home_score":       home.get("score"),
            "away_win_prob":    round(p_away * 100, 1),
            "home_win_prob":    round((1 - p_away) * 100, 1),
            "predicted_winner": away_name if p_away >= 0.5 else home_name,
        })

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


@app.get("/api/stats")
def get_model_stats():
    """Return model accuracy, training data info, and feature importance."""
    model = _load_model()
    coefs = [round(float(c), 4) for c in model.named_steps["clf"].coef_[0]]

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
