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

ROOT          = Path(__file__).parent.parent
MODEL_PATH    = ROOT / "models" / "logistic_regression.pkl"
STATS_PATH    = ROOT / "data" / "raw" / "reg_season_2025_26.csv"
# Order must match train.py FEATURES exactly
FEATURES = [
    "off_rtg", "def_rtg", "net_rtg", "pace", "rest_days",
    "ts_pct", "tov_pct", "oreb_pct", "home",
    "win_streak", "srs", "point_diff", "fg3_rate", "ftr",
    "back_to_back", "travel_km", "prev_margin",
]
# Features read directly from the stats CSV (home + context injected separately)
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


def _load_stats_by_name() -> pd.DataFrame:
    df = pd.read_csv(STATS_PATH)
    return _add_context_defaults(df).set_index("team_name")


def _load_stats_by_id() -> pd.DataFrame:
    df = pd.read_csv(STATS_PATH)
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
    a = stats.loc[team_a, STAT_FEATURES].to_dict()
    a["home"] = 1 if team_a_is_home else 0
    if ctx_a:
        a.update(ctx_a)

    b = stats.loc[team_b, STAT_FEATURES].to_dict()
    b["home"] = 0 if team_a_is_home else 1
    if ctx_b:
        b.update(ctx_b)

    p_a = float(model.predict_proba(pd.DataFrame([a])[FEATURES])[0][1])
    p_b = float(model.predict_proba(pd.DataFrame([b])[FEATURES])[0][1])
    return p_a / (p_a + p_b)


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


def _build_prediction(model, stats_by_name, team_a: str, team_b: str) -> dict:
    # team_a is assumed to have home court (higher seed); 2-2-1-1-1 schedule
    game_probs = [
        _game_prob(model, stats_by_name, team_a, team_b, team_a_is_home=h)
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


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/api/teams")
def get_teams() -> list[str]:
    return sorted(_load_stats_by_name().index.tolist())


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
    results = []

    for g in games:
        home    = g["homeTeam"]
        away    = g["awayTeam"]
        home_id = home["teamId"]
        away_id = away["teamId"]

        if home_id not in stats_by_id.index or away_id not in stats_by_id.index:
            continue

        home_name = stats_by_id.loc[home_id, "team_name"]
        away_name = stats_by_id.loc[away_id, "team_name"]

        # Contextual features for this specific game
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
            p_away = _game_prob(
                model, stats_by_name, away_name, home_name,
                team_a_is_home=False, ctx_a=ctx_away, ctx_b=ctx_home,
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
            day = _fetch_day(d, model, stats_by_id, stats_by_name, played_yesterday)
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
