"""
NBA schedule endpoint for the backend router.
Logic ported from api/main.py.
"""

import os
import pickle
import threading
import time
import json
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException

router = APIRouter()

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT               = Path(__file__).parent.parent.parent.parent
MODEL_PATH         = ROOT / "models" / "logistic_regression.pkl"
STATS_PATH         = ROOT / "data" / "raw" / "reg_season_2025_26.csv"
PLAYOFF_STATS_PATH = ROOT / "data" / "raw" / "playoff_stats_2024_25.csv"

ODDS_API_KEY = os.getenv("ODDS_API_KEY", "09bb7105d888c7ad840a18fdc316b0c8")

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
STAT_FEATURES = [f for f in FEATURES if f not in _CONTEXT_FEATURES]

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

STATUS_WEIGHTS: dict[str, float] = {
    "Out": 1.0, "Doubtful": 0.75, "Questionable": 0.5, "Day-To-Day": 0.25,
}

ROUND_NAMES = {1: "First Round", 2: "Conference Semifinals", 3: "Conference Finals", 4: "NBA Finals"}


def _playoff_round(game_id: str) -> int:
    try:
        s = str(int(game_id))
        if len(s) == 8:
            return int(s[5])
        if len(s) == 10:
            return int(s[7])
        return 0
    except Exception:
        return 0


# ── Caches ────────────────────────────────────────────────────────────────────
_odds_cache:      dict[str, dict] = {}
_odds_cache_time: dict[str, float] = {}
_ODDS_TTL = 1800.0

_predictions_log_cache: dict | None = None
_predictions_log_cache_time: float = 0.0
_PREDICTIONS_LOG_TTL = 300.0

_PREGAME_ODDS_FILE = ROOT / "data" / "pregame_odds.json"
_pregame_odds: dict[str, dict] = {}
try:
    _pregame_odds = json.loads(_PREGAME_ODDS_FILE.read_text(encoding="utf-8"))
except Exception:
    pass

_BOOKMAKER_PRIORITY = [
    "pinnacle", "draftkings", "fanduel", "betmgm", "williamhill",
    "betrivers", "bovada", "unibet_us",
]

_player_minutes_cache: pd.DataFrame | None = None
_injuries_cache: dict[str, list[dict]] | None = None
_injuries_cache_time: float = 0.0
_INJURIES_TTL = 3600.0

_completed_series_cache: set | None = None
_completed_series_cache_time: float = 0.0
_COMPLETED_SERIES_TTL = 900.0


# ── Loaders ───────────────────────────────────────────────────────────────────

def _load_model():
    with open(MODEL_PATH, "rb") as f:
        return pickle.load(f)


def _merge_playoff_stats(df: pd.DataFrame) -> pd.DataFrame:
    if PLAYOFF_STATS_PATH.exists():
        playoff = pd.read_csv(PLAYOFF_STATS_PATH)[["team_id", "playoff_net_rtg"]]
        df = df.merge(playoff, on="team_id", how="left")
        df["playoff_net_rtg"] = df["playoff_net_rtg"].fillna(0.0)
    else:
        df["playoff_net_rtg"] = 0.0
    return df


def _fill_optional_stats(df: pd.DataFrame) -> pd.DataFrame:
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


def _add_context_defaults(df: pd.DataFrame) -> pd.DataFrame:
    df["rest_days"]        = 5
    df["back_to_back"]     = 0
    df["travel_km"]        = 0.0
    df["prev_margin"]      = 0.0
    df["series_wins"]      = 0
    df["elimination_game"] = 0
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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


def _team_travel_km(away_name: str, home_name: str) -> float:
    a = TEAM_TO_ABBR.get(away_name, "")
    h = TEAM_TO_ABBR.get(home_name, "")
    if a in ARENA_COORDS and h in ARENA_COORDS and a != h:
        return round(_haversine_km(*ARENA_COORDS[a], *ARENA_COORDS[h]), 1)
    return 0.0


def _normalize_team(name: str) -> str:
    return name.lower().strip()


def _save_pregame_odds(data: dict) -> None:
    try:
        _PREGAME_ODDS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _PREGAME_ODDS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


# ── Game probability ──────────────────────────────────────────────────────────

def _game_prob(
    model, stats: pd.DataFrame,
    team_a: str, team_b: str,
    team_a_is_home: bool,
    wins_a: int = 0, wins_b: int = 0,
    ctx_a: dict | None = None,
    ctx_b: dict | None = None,
) -> float:
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
    if injury_a == injury_b == 1.0:
        return p
    p_adj = (p * injury_a) / (p * injury_a + (1 - p) * injury_b)
    return max(0.01, min(0.99, p_adj))


# ── Injury helpers ────────────────────────────────────────────────────────────

def _get_player_minutes() -> pd.DataFrame:
    from nba_api.stats.endpoints import leaguedashplayerstats
    time.sleep(0.6)
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
            _player_minutes_cache = pd.DataFrame(columns=["PLAYER_NAME", "TEAM_ABBREVIATION", "MIN", "PTS"])
    return _player_minutes_cache


def _fetch_all_espn_injuries() -> dict[str, list[dict]]:
    global _injuries_cache, _injuries_cache_time

    now = time.time()
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
        _injuries_cache      = result
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


# ── Odds helpers ──────────────────────────────────────────────────────────────

def _fetch_odds_today(sport_key: str) -> dict[str, dict]:
    from datetime import datetime, timezone
    global _pregame_odds

    if not ODDS_API_KEY:
        return {}

    now = time.time()
    if sport_key in _odds_cache and (now - _odds_cache_time.get(sport_key, 0)) < _ODDS_TTL:
        return _odds_cache[sport_key]

    url = (
        f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
        f"?apiKey={ODDS_API_KEY}&regions=us,eu,uk&markets=h2h&oddsFormat=decimal"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CourtEdge/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            games = json.loads(resp.read())

        now_dt = datetime.now(timezone.utc)
        result: dict[str, dict] = {}
        for g in games:
            away     = g.get("away_team", "")
            home     = g.get("home_team", "")
            game_key = f"{_normalize_team(away)}|{_normalize_team(home)}"

            try:
                commence_dt = datetime.fromisoformat(g.get("commence_time", "").replace("Z", "+00:00"))
                game_started = commence_dt <= now_dt
            except Exception:
                game_started = False

            if game_key in _pregame_odds:
                result[game_key] = _pregame_odds[game_key]
                continue

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
                        _pregame_odds[game_key] = odds_data
                    result[game_key] = odds_data
                break

        _save_pregame_odds(_pregame_odds)
        _odds_cache[sport_key]      = result
        _odds_cache_time[sport_key] = now
        return result
    except Exception:
        return {}


def _get_game_odds(odds: dict, away: str, home: str) -> dict:
    key = f"{_normalize_team(away)}|{_normalize_team(home)}"
    return odds.get(key, {})


# ── Completed series ──────────────────────────────────────────────────────────

def _get_completed_series() -> set:
    global _completed_series_cache, _completed_series_cache_time

    now = time.time()
    if _completed_series_cache is not None and (now - _completed_series_cache_time) < _COMPLETED_SERIES_TTL:
        return _completed_series_cache

    try:
        from nba_api.stats.endpoints import leaguegamelog
        time.sleep(0.6)
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
        _completed_series_cache      = completed
        _completed_series_cache_time = now
        return completed
    except Exception:
        return _completed_series_cache if _completed_series_cache is not None else set()


# ── Day fetch ─────────────────────────────────────────────────────────────────

def _fetch_day(
    date_str: str, model, stats_by_id, stats_by_name,
    played_yesterday: set | None = None,
    fetch_injuries: bool = False,
) -> dict:
    from nba_api.stats.endpoints import scoreboardv3
    time.sleep(0.6)
    board = scoreboardv3.ScoreboardV3(game_date=date_str)
    data  = board.get_dict()
    games = data["scoreboard"]["games"]
    date  = data["scoreboard"]["gameDate"]

    STATUS = {1: "Scheduled", 2: "Live", 3: "Final"}

    injury_factors: dict[str, float] = {}
    injury_players: dict[str, list]  = {}
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
        })

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


# Pre-warm player minutes in background
threading.Thread(target=_get_player_minutes_cached, daemon=True).start()


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.get("/schedule")
def get_schedule(days: int = 7):
    import datetime
    days = min(days, 14)
    model         = _load_model()
    stats_by_id   = _load_stats_by_id()
    stats_by_name = _load_stats_by_name()

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
                fetch_injuries=(i == 0),
            )
            if day["games"]:
                schedule.append(day)
            played_yesterday = {g["away_team"] for g in day["games"]} | {g["home_team"] for g in day["games"]}
        except Exception:
            played_yesterday = set()
            continue

    return {"schedule": schedule}


@router.get("/predictions_log")
def get_predictions_log(n: int = 5):
    global _predictions_log_cache, _predictions_log_cache_time

    now = time.time()
    if _predictions_log_cache is not None and (now - _predictions_log_cache_time) < _PREDICTIONS_LOG_TTL:
        cached = _predictions_log_cache.get("log", [])
        return {"log": cached[:n]}

    try:
        from nba_api.stats.endpoints import leaguegamelog
        abbr_to_team = {v: k for k, v in TEAM_TO_ABBR.items()}
        model         = _load_model()
        stats_by_name = _load_stats_by_name()

        log: list[dict] = []

        for season_type in ("Playoffs", "Regular Season"):
            time.sleep(0.6)
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
                if home_team not in stats_by_name.index or away_team not in stats_by_name.index:
                    continue
                try:
                    p_away = _game_prob(model, stats_by_name, away_team, home_team, team_a_is_home=False)
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

                round_label = ROUND_NAMES.get(_playoff_round(game_id), "Playoffs") if season_type == "Playoffs" else "Regular Season"

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

        _predictions_log_cache      = {"log": log}
        _predictions_log_cache_time = now
        return {"log": log[:n]}
    except Exception:
        return {"log": []}
