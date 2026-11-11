"""NBA: model, today's games, predictions log, frozen picks, live win probability, game page,
standings, season simulation, bracket."""

import pickle
import threading as _threading
import time as _time_mod

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import numpy as np
import pandas as pd

from api.common import (
    ROOT,
    _game_day,
    _nba_season_year,
    _parallel,
    _serve_stale,
    app,
)
from api.espn import (
    _espn_athlete_id,
    _espn_json,
    _espn_score,
    _stat_num,
    _team_roster,
)
from api.odds import (
    _fetch_odds_today,
    _game_odds_for,
    _value_bet,
)
from api.record import (
    _model_stats_payload,
    _performance_payload,
)


MODEL_PATH          = ROOT / "models" / "nba_logistic_regression.pkl"
# Live team table written by nba/pipeline.py: model state (Elo, recent margin) + display stats
STATS_PATH          = ROOT / "data" / "nba" / "nba_team_state.csv"
# Pre-game feature rows for every current-season game (played → pre-game values)
NBA_GAME_FEATURES_PATH = ROOT / "data" / "nba" / "nba_game_features_current.csv"
# Order must match nba/train.py FEATURES exactly
FEATURES = ["home", "rest_diff", "b2b", "opp_b2b", "elo_diff", "margin_ewm_diff", "roster_diff"]
NBA_REST_DEFAULT = 2   # rest days assumed when the schedule is unknown (no back-to-back)
NBA_MAX_REST = 4       # matches nba/pipeline.py MAX_REST
# 2-2-1-1-1 format: True = team_a (higher seed) is home
HOME_SCHEDULE = [True, True, False, False, True, False, True]

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


_nba_model_cache = None
_nba_stats_cache: pd.DataFrame | None = None


def _load_model():
    global _nba_model_cache
    if _nba_model_cache is None:
        with open(MODEL_PATH, "rb") as f:
            _nba_model_cache = pickle.load(f)
    return _nba_model_cache


def _load_stats_by_name() -> pd.DataFrame:
    """Team table from nba/pipeline.py, indexed by team name (read-only: it is cached)."""
    global _nba_stats_cache
    if _nba_stats_cache is None:
        df = pd.read_csv(STATS_PATH)
        for col in ("tov_pct", "oreb_pct"):   # ESPN season stats, missing if the fetch failed
            df[col] = df[col].fillna(df[col].median()).fillna(0.0)
        _nba_stats_cache = df.set_index("team_name")
    return _nba_stats_cache


def _load_stats_by_id() -> pd.DataFrame:
    return _load_stats_by_name().reset_index().set_index("team_id")


def _nba_row_from(row: dict, opp_row: dict, is_home: bool) -> dict:
    """Model input for one side of a game. Rest is even here; _nba_set_rest fills it in."""
    return {
        "home": int(is_home), "rest_diff": 0, "b2b": 0, "opp_b2b": 0,
        "elo_diff":        float(row["elo"]) - float(opp_row["elo"]),
        "margin_ewm_diff": float(row["margin_ewm"]) - float(opp_row["margin_ewm"]),
        "roster_diff":     float(row["roster"]) - float(opp_row["roster"]),
    }


def _nba_feature_rows(stats: pd.DataFrame, games: list[tuple[str, str, bool]]) -> list[dict]:
    """Model rows for many (team, opponent, is_home) at once, reading the table once."""
    lookup = stats[["elo", "margin_ewm", "roster"]].to_dict("index")
    return [_nba_row_from(lookup[t], lookup[o], h) for t, o, h in games]


def _nba_set_rest(a: dict, b: dict, rest_a: int, rest_b: int) -> None:
    """Fill the rest features of a mirrored pair of rows (1 day = second night of a back-to-back)."""
    a["rest_diff"], b["rest_diff"] = rest_a - rest_b, rest_b - rest_a
    a["b2b"] = b["opp_b2b"] = int(rest_a == 1)
    b["b2b"] = a["opp_b2b"] = int(rest_b == 1)


def _ctx_rest(ctx: dict | None) -> int:
    """Rest days from a context dict: {"rest_days": n}, or {"back_to_back": 1} from older callers."""
    if not ctx:
        return NBA_REST_DEFAULT
    if "rest_days" in ctx:
        return int(ctx["rest_days"])
    return 1 if ctx.get("back_to_back") else NBA_REST_DEFAULT


def _game_prob(
    model, stats: pd.DataFrame,
    team_a: str, team_b: str,
    team_a_is_home: bool,
    wins_a: int = 0, wins_b: int = 0,
    ctx_a: dict | None = None,
    ctx_b: dict | None = None,
) -> float:
    """Return P(team_a wins a single game) via normalized logistic scores.

    wins_a / wins_b (the series score) are accepted from the playoff callers, but the model
    has no series features. ctx_a / ctx_b carry rest ({"rest_days": n} or {"back_to_back": 1}).
    """
    a, b = _nba_feature_rows(stats, [(team_a, team_b, team_a_is_home), (team_b, team_a, not team_a_is_home)])
    _nba_set_rest(a, b, _ctx_rest(ctx_a), _ctx_rest(ctx_b))
    return float(_nba_pair_probs(model, [a], [b])[0])


def _nba_pair_probs(model, rows_a: list[dict], rows_b: list[dict]) -> np.ndarray:
    """P(side a wins) for many games in one model call — same normalisation as _game_prob."""
    if not rows_a:
        return np.array([])
    raw = model.predict_proba(pd.DataFrame(rows_a + rows_b)[FEATURES])[:, 1]
    p_a, p_b = raw[:len(rows_a)], raw[len(rows_a):]
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
    """Monte Carlo simulation of a best-of-7 (team_a has home court)."""
    rng = np.random.default_rng(seed)
    buckets = {"4-0": [0, 0], "4-1": [0, 0], "4-2": [0, 0], "4-3": [0, 0]}
    # The model has no series-score features: one probability at home, one on the road
    p_at = {h: _adjust_for_injuries(_game_prob(model, stats, team_a, team_b, h), injury_a, injury_b)
            for h in (True, False)}
    for _ in range(n):
        wa = wb = game_idx = 0
        while wa < 4 and wb < 4:
            p = p_at[HOME_SCHEDULE[game_idx]]
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

_compare_cache: dict[str, dict] = {}
_compare_cache_time: dict[str, float] = {}
_COMPARE_CACHE_TTL = 1800.0


# ── Injury helpers ────────────────────────────────────────────────────────────

_player_minutes_cache: pd.DataFrame | None = None
_player_minutes_cache_time: float = 0.0
_PLAYER_MINUTES_TTL = 12 * 3600.0   # averages move with each night of games
_injuries_cache: dict[str, list[dict]] | None = None
_injuries_cache_time: float = 0.0
_INJURIES_TTL = 3600.0  # re-fetch after 1 hour


# ESPN team abbreviations that differ from ours (TEAM_TO_ABBR)
_ESPN_NBA_ABBR = {"GS": "GSW", "NY": "NYK", "NO": "NOP", "SA": "SAS", "UTAH": "UTA", "WSH": "WAS"}


_PLAYER_MIN_GAMES = 5   # games this season before his own averages replace last season's


def _espn_player_averages(season: int) -> dict[str, dict]:
    """{player name: per-game averages + team} for one season (ESPN: stats.nba.com blocks cloud hosts)."""
    import json, urllib.request
    url = ("https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/statistics/byathlete"
           f"?isqualified=false&limit=1000&season={season}&seasontype=2&sort=general.avgMinutes:desc")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read())
    names = {c["name"]: c.get("names", []) for c in data.get("categories", [])}

    def stat(a: dict, cat: str, name: str) -> float:
        for c in a.get("categories", []):
            if c.get("name") == cat and name in names.get(cat, []):
                try:
                    return float(str(c["totals"][names[cat].index(name)]).replace(",", ""))
                except (ValueError, IndexError):
                    return 0.0
        return 0.0

    out = {}
    for a in data.get("athletes", []):
        ath = a.get("athlete", {})
        abbr = ath.get("teamShortName", "")
        out[ath.get("displayName", "")] = {
            "ID": str(ath.get("id", "")),
            "SEASON": season,
            "TEAM_ABBREVIATION": _ESPN_NBA_ABBR.get(abbr, abbr),
            "GP": stat(a, "general", "gamesPlayed"),
            "MIN": stat(a, "general", "avgMinutes"),
            "PTS": stat(a, "offensive", "avgPoints"),
            "AST": stat(a, "offensive", "avgAssists"),
            "REB": stat(a, "general", "avgRebounds"),
            "STL": stat(a, "defensive", "avgSteals"),
            "BLK": stat(a, "defensive", "avgBlocks"),
        }
    return out


def _get_player_minutes() -> pd.DataFrame:
    """Per-game averages for every player: this season's once he has _PLAYER_MIN_GAMES games,
    else last season's (early in the season, and for players injured since opening night).
    His team is this season's when he has played for it, else last season's."""
    season = _nba_season_year()
    cur = _espn_player_averages(season)
    try:
        prev = _espn_player_averages(season - 1)
    except Exception:
        prev = {}
    rows = []
    for name in set(cur) | set(prev):
        c, p = cur.get(name), prev.get(name)
        stats = c if c and (c["GP"] >= _PLAYER_MIN_GAMES or not p) else p
        rows.append({**stats, "PLAYER_NAME": name, "TEAM_ABBREVIATION": (c or p)["TEAM_ABBREVIATION"],
                     "ID": (c or p)["ID"]})
    df = pd.DataFrame(rows)
    df["IMPACT"] = (
        df.get("PTS", 0) * 1.0
        + df.get("AST", 0) * 1.5
        + df.get("REB", 0) * 1.2
        + df.get("STL", 0) * 2.0
        + df.get("BLK", 0) * 2.0
    )
    return df


def _get_player_minutes_cached() -> pd.DataFrame:
    global _player_minutes_cache, _player_minutes_cache_time
    if _player_minutes_cache is None or _time_mod.time() - _player_minutes_cache_time > _PLAYER_MINUTES_TTL:
        try:
            _player_minutes_cache = _get_player_minutes()
            _player_minutes_cache_time = _time_mod.time()
        except Exception:
            if _player_minutes_cache is None:
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
            "id":           _espn_athlete_id(inj.get("athlete", {})),
            "name":         name,
            "status":       status,
            "pts_per_game": round(ppg, 1) if ppg is not None else None,
        })

    factor = max(0.40, round(1.0 - missing_impact / total_impact, 3)) if total_impact > 0 else 1.0
    return factor, affected


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/api/health")
def get_health() -> dict:
    """Cheap liveness check: the keep-alive workflow and the home page ping it to wake the server."""
    return {"ok": True}


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
                f"/teams/{espn_id}/schedule?season={_nba_season_year()}&seasontype=3"
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


# ── NBA games from ESPN ───────────────────────────────────────────────────────
# stats.nba.com (nba_api) blocks cloud hosts such as Render, so live NBA data comes from ESPN.
NBA_ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
_nba_month_cache: dict[tuple[int, int], tuple[float, list[dict]]] = {}
_NBA_MONTH_TTL = 600.0


def _nba_round_from_note(note: str) -> int:
    """'East 1st Round - Game 6' → 1, 'West Semifinals' → 2, 'East Finals' → 3, 'NBA Finals' → 4."""
    n = note.lower()
    if "nba finals" in n:
        return 4
    if "1st round" in n or "first round" in n:
        return 1
    if "semifinal" in n:
        return 2
    if "finals" in n:
        return 3
    return 0


def _parse_espn_nba_event(ev: dict) -> dict | None:
    import datetime, zoneinfo
    comp = (ev.get("competitions") or [{}])[0]
    cs = comp.get("competitors", [])
    home = next((c for c in cs if c.get("homeAway") == "home"), None)
    away = next((c for c in cs if c.get("homeAway") == "away"), None)
    if not home or not away:
        return None
    st = comp.get("status", {}).get("type", {})
    note = ((comp.get("notes") or [{}])[0]).get("headline", "")
    try:
        start = datetime.datetime.fromisoformat(ev.get("date", "").replace("Z", "+00:00"))
        et = start.astimezone(zoneinfo.ZoneInfo("America/New_York"))
    except ValueError:
        et = None

    def score(c):
        try:
            return int(c.get("score")) if c.get("score") not in (None, "") else None
        except (TypeError, ValueError):
            return None

    return {
        "game_id":     str(ev.get("id")),
        "date":        et.date().isoformat() if et else ev.get("date", "")[:10],
        "time_et":     (et.strftime("%I:%M %p").lstrip("0") + " ET") if et else "",
        "start_utc":   ev.get("date", ""),
        "season_type": int((ev.get("season") or {}).get("type") or 2),   # 2 regular, 3 playoffs, 5 play-in
        "round":       _nba_round_from_note(note),
        "home_team":   home.get("team", {}).get("displayName", ""),
        "away_team":   away.get("team", {}).get("displayName", ""),
        "home_score":  score(home),
        "away_score":  score(away),
        "state":       st.get("state", "pre"),                              # pre / in / post
        "completed":   bool(st.get("completed")),
        "detail":      st.get("shortDetail", ""),
        "period":      int(comp.get("status", {}).get("period") or 0),
        "clock":       comp.get("status", {}).get("displayClock", ""),
    }


def _espn_nba_scoreboard(dates: str) -> list[dict]:
    import json, urllib.request
    req = urllib.request.Request(f"{NBA_ESPN_SCOREBOARD}?dates={dates}&limit=500",
                                 headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read())
    return [g for g in (_parse_espn_nba_event(e) for e in data.get("events", [])) if g]


def _espn_nba_month(year: int, month: int) -> list[dict]:
    """All games in a month (ESPN rejects date ranges but accepts YYYYMM). Past months cached for good."""
    import datetime
    key = (year, month)
    today = datetime.date.today()
    past = (year, month) < (today.year, today.month)
    hit = _nba_month_cache.get(key)
    if hit and (past or _time_mod.time() - hit[0] < _NBA_MONTH_TTL):
        return hit[1]
    games = _espn_nba_scoreboard(f"{year}{month:02d}")
    _nba_month_cache[key] = (_time_mod.time(), games)
    return games


def _espn_nba_season_games(season: int | None = None) -> list[dict]:
    """Every game of a season (default: the current one) ESPN lists so far — regular season,
    play-in, playoffs — oldest first."""
    import datetime
    today = datetime.date.today()
    year = season or _nba_season_year()
    months = [(y, m) for y, m in [(year - 1, m) for m in (10, 11, 12)] + [(year, m) for m in range(1, 7)]
              if (y, m) <= (today.year, today.month)]

    def month(y: int, m: int) -> list[dict]:
        try:
            return _espn_nba_month(y, m)
        except Exception:
            return []

    out = [g for lst in _parallel(*(lambda y=y, m=m: month(y, m) for y, m in months)) for g in lst] if months else []
    return sorted(out, key=lambda g: (g["date"], g["game_id"]))


def _nba_playoff_series() -> dict[tuple[int, tuple[str, str]], dict]:
    """(round, sorted team pair) → series state, from completed playoff games of the latest
    playoffs (last season's until this season's begin)."""
    series: dict[tuple[int, tuple[str, str]], dict] = {}
    games = _espn_nba_season_games()
    if not any(g["season_type"] == 3 for g in games):
        games = _espn_nba_season_games(_nba_season_year() - 1)
    for g in games:
        if g["season_type"] != 3 or not g["completed"] or not g["round"]:
            continue
        if g["home_score"] is None or g["away_score"] is None:
            continue
        pair = tuple(sorted([g["home_team"], g["away_team"]]))
        s = series.setdefault((g["round"], pair), {"round": g["round"], "team_a": pair[0], "team_b": pair[1],
                                                   "team_a_wins": 0, "team_b_wins": 0})
        winner = g["home_team"] if g["home_score"] > g["away_score"] else g["away_team"]
        s["team_a_wins" if winner == pair[0] else "team_b_wins"] += 1
    return series


def _get_completed_series() -> set:
    """Return set of frozenset(abbr_a, abbr_b) for playoff series where one team has 4 wins."""
    global _completed_series_cache, _completed_series_cache_time
    now = _time_mod.time()
    if _completed_series_cache is not None and (now - _completed_series_cache_time) < _COMPLETED_SERIES_TTL:
        return _completed_series_cache
    try:
        completed = {frozenset([TEAM_TO_ABBR.get(s["team_a"], ""), TEAM_TO_ABBR.get(s["team_b"], "")])
                     for s in _nba_playoff_series().values() if max(s["team_a_wins"], s["team_b_wins"]) >= 4}
        _completed_series_cache, _completed_series_cache_time = completed, now
        return completed
    except Exception:
        return _completed_series_cache if _completed_series_cache is not None else set()


@app.get("/api/bracket")
def get_bracket():
    """Return all playoff series grouped by round with current score and win probability."""
    global _bracket_cache, _bracket_cache_time

    now = _time_mod.time()
    if _bracket_cache is not None and ((now - _bracket_cache_time) < _BRACKET_CACHE_TTL or _serve_stale("bracket", get_bracket)):
        return _bracket_cache

    try:
        model = _load_model()
        stats = _load_stats_by_name()

        rounds_data: dict[int, list] = {}
        for (round_num, _pair), s in _nba_playoff_series().items():
            if s["team_a"] not in stats.index or s["team_b"] not in stats.index:
                continue
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
        if rounds:
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


def _fetch_day(
    date_str: str, model, stats_by_name,
    fetch_injuries: bool = False,
) -> dict:
    """Fetch one day's games (ESPN) and attach predictions. `date_str` is MM/DD/YYYY.

    Games that have started show the prediction frozen before tip-off; with `fetch_injuries`
    (today), upcoming games get the injury report and their prediction is written down."""
    import datetime
    day = datetime.datetime.strptime(date_str, "%m/%d/%Y").date()
    # Only regular-season / play-in / playoff games our model knows both teams of
    games = [g for g in _espn_nba_scoreboard(day.strftime("%Y%m%d"))
             if g["season_type"] in (2, 3, 5)
             and g["home_team"] in stats_by_name.index and g["away_team"] in stats_by_name.index]
    date = day.isoformat()

    STATUS = {"pre": "Scheduled", "in": "Live", "post": "Final"}

    # Fetch all injuries in one ESPN request, then look up each playing team
    injury_factors: dict[str, float] = {}
    injury_players: dict[str, list] = {}
    if fetch_injuries:
        all_injuries   = _fetch_all_espn_injuries()
        player_minutes = _get_player_minutes_cached()
        for g in games:
            for name in (g["home_team"], g["away_team"]):
                if name not in injury_factors:
                    inj = all_injuries.get(name, [])
                    factor, players = _compute_injury_factor(inj, name, player_minutes)
                    injury_factors[name] = factor
                    injury_players[name] = players

    nba_odds = _fetch_odds_today("basketball_nba", [g.get("start_utc", "") for g in games if g["state"] == "pre"])
    known = _load_nba_game_features()
    play_dates = _nba_season_play_dates() if any(g["game_id"] not in known for g in games) else {}
    results = []
    for g in games:
        home_name = g["home_team"]
        away_name = g["away_team"]

        inj_away = injury_factors.get(away_name, 1.0)
        inj_home = injury_factors.get(home_name, 1.0)

        frozen = _nba_known_pred(g["game_id"]) if g["state"] != "pre" else None
        if frozen and (frozen["away_team"], frozen["home_team"]) == (away_name, home_name):
            p_raw = p_away = frozen["away_win_prob"] / 100   # injuries already in it
            inj_away = inj_home = 1.0
        else:
            try:
                a, b = _nba_game_rows(stats_by_name, away_name, home_name, g["date"], g["game_id"], play_dates)
                p_raw = float(_nba_pair_probs(model, [a], [b])[0])
                p_away = _adjust_for_injuries(p_raw, inj_away, inj_home)
            except Exception:
                continue
            if fetch_injuries and g["state"] == "pre":
                _nba_record_pred(g["game_id"], away_name, home_name, p_away, g["start_utc"],
                                 (_nba_projected_score(away_name, home_name, 1 - p_away) or {}).get("total"))

        away_impact = round((_adjust_for_injuries(p_raw, inj_away, 1.0) - p_raw) * 100, 1) if inj_away != 1.0 else 0.0
        home_impact = round((p_raw - _adjust_for_injuries(p_raw, 1.0, inj_home)) * 100, 1) if inj_home != 1.0 else 0.0

        nba_status   = STATUS.get(g["state"], "Scheduled")
        # Finished games only show the stored pre-game line
        game_odds    = _game_odds_for(nba_odds, away_name, home_name, g["date"], nba_status == "Final")

        # During the game: our live probability (same formula as the game page)
        live_away = None
        if g["state"] == "in" and g["away_score"] is not None and g["home_score"] is not None:
            _, left = _nba_clock_minutes(g["period"] or 1, g["clock"])
            live_away = round((1 - _nba_live_prob(1 - p_away, g["home_score"] - g["away_score"], left)) * 100, 1)

        results.append({
            "game_id":             g["game_id"],
            "status":              nba_status,
            "live_away_prob":      live_away,
            "live_home_prob":      None if live_away is None else round(100 - live_away, 1),
            "status_text":         g["time_et"] if g["state"] == "pre" else (g["detail"] or nba_status),
            "away_team":           away_name,
            "home_team":           home_name,
            "away_score":          g["away_score"] if g["state"] != "pre" else None,
            "home_score":          g["home_score"] if g["state"] != "pre" else None,
            "away_win_prob":       round(p_away * 100, 1),
            "home_win_prob":       round((1 - p_away) * 100, 1),
            "predicted_winner":    away_name if p_away >= 0.5 else home_name,
            # Before tip-off today's projection; after, only the one frozen before the game
            "projected_total":     ((_nba_projected_score(away_name, home_name, 1 - p_away) or {}).get("total")
                                    if g["state"] == "pre" else (frozen or {}).get("projected_total")),
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
    if results and any(g["season_type"] == 3 for g in games):
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


def _nba_today():
    """Today's NBA game day in Eastern time (the server clock is UTC: after 8 pm ET it is
    already tomorrow there, mid-slate). Late games stay on it past midnight."""
    return _game_day()


@app.get("/api/today")
def get_today_games():
    try:
        return _fetch_day(_nba_today().strftime("%m/%d/%Y"), _load_model(), _load_stats_by_name(),
                          fetch_injuries=True)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


_schedule_cache: dict[int, tuple[float, dict]] = {}
_SCHEDULE_TTL = 15.0   # live scores stay fresh; repeated loads skip ESPN


@app.get("/api/schedule")
def get_schedule(days: int = 7):
    """Return the next `days` days of games with predictions (max 14)."""
    import datetime
    days = min(days, 14)
    hit = _schedule_cache.get(days)
    if hit and _time_mod.time() - hit[0] < _SCHEDULE_TTL:
        return hit[1]
    model, stats_by_name = _load_model(), _load_stats_by_name()
    schedule = []
    for i in range(days):
        d = (_nba_today() + datetime.timedelta(days=i)).strftime("%m/%d/%Y")
        try:
            day = _fetch_day(d, model, stats_by_name,
                             fetch_injuries=(i == 0))  # only fetch injuries for today
            if day["games"]:
                schedule.append(day)
        except Exception:
            continue

    result = {"schedule": schedule}
    _schedule_cache[days] = (_time_mod.time(), result)
    return result




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
    """Completed games of the current season (playoffs first, then the play-in and the regular
    season, newest first) with the model's pre-game pick vs the actual result. The pick is the
    one frozen before tip-off when we have it, else the model on the pipeline's pre-game rows."""
    global _predictions_log_cache, _predictions_log_cache_time

    now = _time_mod.time()
    if _predictions_log_cache is not None and ((now - _predictions_log_cache_time) < _PREDICTIONS_LOG_TTL or _serve_stale("nba_log", get_predictions_log)):
        return {"log": _predictions_log_cache["log"][:n]}

    try:
        model = _load_model()
        stats = _load_stats_by_name()
        games = [g for g in _espn_nba_season_games()
                 if g["completed"] and g["season_type"] in (2, 3, 5)
                 and g["home_score"] is not None and g["away_score"] is not None
                 and g["home_team"] in stats.index and g["away_team"] in stats.index]
        # Playoffs first, then play-in / regular season; newest first within each
        games.sort(key=lambda g: (g["season_type"] == 3, g["date"], g["game_id"]), reverse=True)

        known = _load_nba_game_features()
        play_dates = _nba_season_play_dates() if any(g["game_id"] not in known for g in games) else {}
        p_away_of: dict[str, float] = {}
        source_of: dict[str, str] = {}
        rows_a, rows_b, todo = [], [], []
        for g in games:
            frozen = _nba_known_pred(g["game_id"])
            if frozen and (frozen["away_team"], frozen["home_team"]) == (g["away_team"], g["home_team"]):
                p_away_of[g["game_id"]] = frozen["away_win_prob"] / 100
                source_of[g["game_id"]] = "frozen"
                continue
            source_of[g["game_id"]] = "pregame" if g["game_id"] in known else "current"
            a, b = _nba_game_rows(stats, g["away_team"], g["home_team"], g["date"], g["game_id"], play_dates)
            rows_a.append(a)
            rows_b.append(b)
            todo.append(g["game_id"])
        p_away_of.update(zip(todo, (float(p) for p in _nba_pair_probs(model, rows_a, rows_b))))

        log: list[dict] = []
        for g in games:
            away_team, home_team = g["away_team"], g["home_team"]
            p_away = p_away_of[g["game_id"]]
            predicted_winner = away_team if p_away >= 0.5 else home_team
            predicted_prob   = round((p_away if p_away >= 0.5 else 1 - p_away) * 100, 1)
            actual_winner    = home_team if g["home_score"] > g["away_score"] else away_team
            log.append({
                "game_id":          g["game_id"],
                "date":             g["date"],
                "away_team":        away_team,
                "home_team":        home_team,
                "predicted_winner": predicted_winner,
                "predicted_prob":   predicted_prob,
                "actual_winner":    actual_winner,
                "correct":          predicted_winner == actual_winner,
                "away_score":       g["away_score"],
                "home_score":       g["home_score"],
                "away_win_prob":    round(p_away * 100, 1),
                "home_win_prob":    round((1 - p_away) * 100, 1),
                "round":            (ROUND_NAMES.get(g["round"], "Playoffs") if g["season_type"] == 3
                                     else "Play-In" if g["season_type"] == 5 else "Regular Season"),
                "source":           source_of[g["game_id"]],
            })

        if log:
            _predictions_log_cache = {"log": log}
            _predictions_log_cache_time = now
        return {"log": log[:n]}
    except Exception:
        return {"log": []}


@app.get("/api/nba/performance")
def get_nba_performance():
    return _performance_payload("nba", get_predictions_log(n=100_000)["log"])


# ═══════════════════════════════════════════════════════════════════════════════
#  NBA season — power index, season simulation, per-game win probabilities
#  (team and player pages)
# ═══════════════════════════════════════════════════════════════════════════════

NBA_SIMS = 10_000
NBA_MARGIN_SD = 12.0   # SD of NBA final margins — converts win probability <-> point margin
NBA_HCA_PTS = 2.5      # home-court edge in points for simulated play-in / playoff games
NBA_GAMES = 82
_NBA_EAST = {
    "Atlanta Hawks", "Boston Celtics", "Brooklyn Nets", "Charlotte Hornets", "Chicago Bulls",
    "Cleveland Cavaliers", "Detroit Pistons", "Indiana Pacers", "Miami Heat", "Milwaukee Bucks",
    "New York Knicks", "Orlando Magic", "Philadelphia 76ers", "Toronto Raptors", "Washington Wizards",
}
_nba_proj_cache: dict | None = None
_nba_proj_cache_time: float = 0.0
_NBA_PROJ_TTL = 600.0


def _nba_et_date(iso: str) -> str:
    """Eastern 'YYYY-MM-DD' of an ESPN UTC datetime."""
    import datetime, zoneinfo
    try:
        dt = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso[:10]
    return dt.astimezone(zoneinfo.ZoneInfo("America/New_York")).date().isoformat()


def _nba_team_from_espn_abbr(abbr: str) -> str | None:
    """'GS' / 'GSW' → 'Golden State Warriors' (the name used in the stats table)."""
    ours = _ESPN_NBA_ABBR.get(abbr.upper(), abbr.upper())
    names = [n for n, a in TEAM_TO_ABBR.items() if a == ours]
    stats = _load_stats_by_name()
    return next((n for n in names if n in stats.index), names[0] if names else None)


def _nba_current_season_games(types: tuple[int, ...] = (2,)) -> list[dict]:
    """Every game of the current season of the given season types (2 regular season, 3 playoffs,
    5 play-in), played or not, oldest first. Raises when a month can't be fetched: a partial
    schedule would skew the simulation."""
    year = _nba_season_year()
    months = [(year - 1, m) for m in (10, 11, 12)] + [(year, m) for m in range(1, 7)]
    by_id: dict[str, dict] = {}
    for y, m in months:
        for g in _espn_nba_month(y, m):
            if g["season_type"] in types:
                by_id[g["game_id"]] = g
    return sorted(by_id.values(), key=lambda g: (g["date"], g["game_id"]))


def _nba_play_dates(games: list[dict]) -> dict[str, list[str]]:
    """{team: sorted Eastern dates it plays} — for rest days."""
    out: dict[str, set[str]] = {}
    for g in games:
        out.setdefault(g["home_team"], set()).add(g["date"])
        out.setdefault(g["away_team"], set()).add(g["date"])
    return {t: sorted(d) for t, d in out.items()}


def _nba_season_play_dates() -> dict[str, list[str]]:
    """Play dates of every current-season game (all phases); empty if ESPN is unreachable."""
    try:
        return _nba_play_dates(_nba_current_season_games((2, 3, 5)))
    except Exception:
        return {}


def _nba_rest(team: str, date: str, play_dates: dict[str, list[str]]) -> int:
    """Days since the team's previous scheduled game, capped like nba/pipeline.py
    (opening night counts as fully rested; unknown schedule → NBA_REST_DEFAULT)."""
    import bisect, datetime
    dates = play_dates.get(team)
    if not dates:
        return NBA_REST_DEFAULT
    i = bisect.bisect_left(dates, date)
    if i == 0:
        return NBA_MAX_REST
    days = (datetime.date.fromisoformat(date) - datetime.date.fromisoformat(dates[i - 1])).days
    return max(1, min(days, NBA_MAX_REST))


_nba_game_features_cache: dict[str, dict[str, dict]] | None = None


def _load_nba_game_features() -> dict[str, dict[str, dict]]:
    """{ESPN game id: {team name: model row}} for every current-season game, written by
    nba/pipeline.py: pre-game values for played games, the latest state for the others."""
    global _nba_game_features_cache
    if _nba_game_features_cache is None:
        out: dict[str, dict[str, dict]] = {}
        if NBA_GAME_FEATURES_PATH.exists():
            df = pd.read_csv(NBA_GAME_FEATURES_PATH, dtype={"game_id": str})
            for r in df.to_dict("records"):
                out.setdefault(r["game_id"], {})[r["team"]] = {f: r[f] for f in FEATURES}
        _nba_game_features_cache = out
    return _nba_game_features_cache


def _nba_game_rows(stats: pd.DataFrame, away: str, home: str, date: str, game_id: str | None = None,
                   play_dates: dict[str, list[str]] | None = None) -> tuple[dict, dict]:
    """Model rows (away, home) for one game: the pipeline's pre-game rows when it has the game
    (so a played game is never re-predicted with later data), else the current team table with
    rest from the schedule."""
    known = _load_nba_game_features().get(str(game_id)) if game_id else None
    if known and away in known and home in known:
        return dict(known[away]), dict(known[home])
    a, b = _nba_feature_rows(stats, [(away, home, False), (home, away, True)])
    pd_ = play_dates or {}
    _nba_set_rest(a, b, _nba_rest(away, date, pd_), _nba_rest(home, date, pd_))
    return a, b


def _nba_injury_factors(*teams: str) -> list[float]:
    injuries, minutes = _fetch_all_espn_injuries(), _get_player_minutes_cached()
    return [_compute_injury_factor(injuries.get(t, []), t, minutes)[0] for t in teams]


def _nba_game_probs(team: str, games: list[dict]) -> list[float | None]:
    """Our win probability (%) for `team` in each game ({game_id, opponent, home, date, completed}),
    the same number as the home page and the predictions log: the frozen pre-game prediction when
    there is one, else the model on the pipeline's pre-game rows, with today's injury report for
    a game today that has not started."""
    import datetime
    model, stats = _load_model(), _load_stats_by_name()
    out: list[float | None] = [None] * len(games)
    if team not in stats.index:
        return out
    today = _nba_et_date(datetime.datetime.now(datetime.timezone.utc).isoformat())
    known = _load_nba_game_features()
    play_dates: dict[str, list[str]] | None = None
    rows_a, rows_b, meta = [], [], []
    for i, g in enumerate(games):
        if g["opponent"] not in stats.index:
            continue
        away, home = (g["opponent"], team) if g["home"] else (team, g["opponent"])
        gid = str(g.get("game_id") or "")
        frozen = _nba_known_pred(gid)
        if frozen and {frozen["away_team"], frozen["home_team"]} == {away, home}:
            out[i] = frozen["away_win_prob"] if team == frozen["away_team"] else frozen["home_win_prob"]
            continue
        date = _nba_et_date(g["date"])
        if play_dates is None and gid not in known:
            play_dates = _nba_season_play_dates()
        a, b = _nba_game_rows(stats, away, home, date, gid, play_dates)
        rows_a.append(a)
        rows_b.append(b)
        meta.append((i, away, home, not g["completed"] and date == today))
    for (i, away, home, is_today), p in zip(meta, _nba_pair_probs(model, rows_a, rows_b)):
        if is_today:
            p = _adjust_for_injuries(float(p), *_nba_injury_factors(away, home))
        out[i] = round(float(p if team == away else 1 - p) * 100, 1)
    return out


# Pre-game predictions written down before tip-off, so a played game is never re-predicted with
# later data (the injury report changes after it). Refreshed while the game is upcoming, frozen
# once it starts. Same scheme as the NFL: the deployed API records them as the home page is
# served, the freeze workflow records the night's slate and commits the file.
NBA_FROZEN_PREDS_PATH = ROOT / "data" / "nba" / "nba_frozen_predictions.json"


def _load_nba_frozen_preds() -> dict[str, dict]:
    import json as _json
    try:
        return _json.loads(NBA_FROZEN_PREDS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _merge_nba_frozen_preds(into: dict[str, dict], other: dict[str, dict]) -> None:
    """Add `other`'s entries to `into`; for a game in both, the later freeze wins."""
    for gid, entry in other.items():
        mine = into.get(gid)
        if not mine or entry.get("frozen_at", "") > mine.get("frozen_at", ""):
            into[gid] = entry


def _save_nba_frozen_preds() -> None:
    import json as _json
    try:
        _merge_nba_frozen_preds(_nba_frozen_preds, _load_nba_frozen_preds())
        NBA_FROZEN_PREDS_PATH.write_text(_json.dumps(_nba_frozen_preds, indent=1, sort_keys=True), encoding="utf-8")
    except Exception:
        pass


_nba_frozen_preds: dict[str, dict] = _load_nba_frozen_preds()
_nba_frozen_mtime: float = 0.0


def _refresh_nba_frozen_preds() -> None:
    """Pick up entries written to the file by someone else (a pulled commit)."""
    global _nba_frozen_mtime
    try:
        mtime = NBA_FROZEN_PREDS_PATH.stat().st_mtime
    except OSError:
        return
    if mtime != _nba_frozen_mtime:
        _nba_frozen_mtime = mtime
        _merge_nba_frozen_preds(_nba_frozen_preds, _load_nba_frozen_preds())


def _nba_known_pred(game_id) -> dict | None:
    _refresh_nba_frozen_preds()
    return _nba_frozen_preds.get(str(game_id)) if game_id else None


def _nba_record_pred(game_id: str, away: str, home: str, p_away: float, tipoff: str,
                     total: int | None = None) -> None:
    """Write down (or refresh) the pre-game prediction of a game that has not started, with
    its projected total."""
    away_pct = round(p_away * 100, 1)
    old = _nba_frozen_preds.get(str(game_id))
    if old and old.get("away_win_prob") == away_pct and old.get("projected_total") == total:
        return
    _nba_frozen_preds[str(game_id)] = {
        "away_team": away, "home_team": home,
        "away_win_prob": away_pct, "home_win_prob": round(100 - away_pct, 1),
        "predicted_winner": away if away_pct >= 50 else home, "projected_total": total,
        "tipoff": tipoff, "frozen_at": _time_mod.strftime("%Y-%m-%dT%H:%M:%SZ", _time_mod.gmtime()),
    }
    _save_nba_frozen_preds()


@app.get("/api/nba/frozen_predictions")
def get_nba_frozen_predictions() -> dict[str, dict]:
    """Every frozen pre-game prediction (read by the workflows so a redeploy loses none)."""
    _refresh_nba_frozen_preds()
    return _nba_frozen_preds


# ── In-game win probability ────────────────────────────────────────────────────

_nba_live_cache: dict[str, tuple[float, dict]] = {}
_NBA_LIVE_TTL = 20.0          # while the game is on
_NBA_LIVE_FINAL_TTL = 3600.0  # a finished game no longer changes


def _nba_clock_minutes(period: int, clock: str) -> tuple[float, float]:
    """(minutes played, minutes left) at a game clock: 4 × 12-minute quarters, 5-minute overtimes.
    In overtime, minutes left is what is left of that overtime."""
    try:
        if ":" in clock:
            m, s = clock.split(":", 1)
            on_clock = int(m) + float(s) / 60
        else:
            on_clock = float(clock or 0) / 60
    except ValueError:
        on_clock = 0.0
    if period <= 4:
        left = (4 - period) * 12 + on_clock
        return 48 - left, left
    return 48 + (period - 5) * 5 + (5 - on_clock), on_clock


# Uncertainty of the rest of a game: a Student t (fat tails: comebacks happen more often than a
# normal curve allows) with scale NBA_MARGIN_SD × √(share left), widened late in the game by up to
# NBA_LIVE_LATE_SD (intentional fouls, threes). Both vanish at tip-off, so a 0-0 game starts at
# the pre-game probability exactly. A 24-point halftime deficit stays ~2-3 %, a 10-point lead
# with 2 minutes left ~95 %.
NBA_LIVE_DF = 5
NBA_LIVE_LATE_SD = 3.0


def _nba_live_prob(p_home_pregame: float, home_margin: float, minutes_left: float) -> float:
    """P(home wins) during a game. The pre-game edge, as an expected point margin, only applies to
    the time left; the current score margin is in the bag."""
    import math
    from scipy.stats import t as student_t
    if minutes_left <= 0:
        return 1.0 if home_margin > 0 else 0.0 if home_margin < 0 else 0.5
    root = math.sqrt(min(minutes_left / 48, 1.0))
    edge = NBA_MARGIN_SD * float(student_t.ppf(min(max(p_home_pregame, 1e-4), 1 - 1e-4), NBA_LIVE_DF))
    scale = NBA_MARGIN_SD * root + NBA_LIVE_LATE_SD * (1 - root)
    p = float(student_t.cdf((home_margin + edge * root ** 2) / scale, NBA_LIVE_DF))
    return min(max(p, 0.001), 0.999)   # never 100 % before the final buzzer


# Team box-score stats shown on the game page (ESPN names → our keys), in display order
_NBA_TEAM_BOX = [
    ("fieldGoalsMade-fieldGoalsAttempted", "fg"), ("fieldGoalPct", "fg_pct"),
    ("threePointFieldGoalsMade-threePointFieldGoalsAttempted", "fg3"), ("threePointFieldGoalPct", "fg3_pct"),
    ("freeThrowsMade-freeThrowsAttempted", "ft"), ("totalRebounds", "reb"), ("offensiveRebounds", "oreb"),
    ("assists", "ast"), ("turnovers", "tov"), ("steals", "stl"), ("blocks", "blk"),
    ("pointsInPaint", "paint"), ("fastBreakPoints", "fast_break"), ("largestLead", "largest_lead"),
]
# Player box-score columns kept (ESPN key → ours)
_NBA_PLAYER_BOX = {"minutes": "min", "points": "pts", "rebounds": "reb", "assists": "ast",
                   "fieldGoalsMade-fieldGoalsAttempted": "fg",
                   "threePointFieldGoalsMade-threePointFieldGoalsAttempted": "fg3",
                   "steals": "stl", "blocks": "blk", "turnovers": "tov", "plusMinus": "pm"}


def _nba_explain(a: dict, b: dict) -> list[dict]:
    """Per-feature contribution to the away-vs-home log-odds gap of the logistic regression
    (positive favours the away team): coef · (z_away − z_home), so the terms add up to the tilt.
    `a` / `b` are the away / home model rows."""
    model = _load_model()
    scaler, clf = model.named_steps["scaler"], model.named_steps["clf"]
    impacts = {f: float(clf.coef_[0][i]) * (float(a[f]) - float(b[f])) / float(scaler.scale_[i])
               for i, f in enumerate(FEATURES)}
    out = []
    for f, impact in impacts.items():
        if f.startswith("opp_") and f[4:] in impacts:
            continue   # mirror of f[4:] (opp_b2b) — folded into that feature
        out.append({"feature": f, "away_value": round(float(a[f]), 4), "home_value": round(float(b[f]), 4),
                    "impact": round(impact + impacts.get(f"opp_{f}", 0.0), 4)})
    return sorted(out, key=lambda r: abs(r["impact"]), reverse=True)


def _nba_box_players(team_box: dict) -> list[dict]:
    """One team's players from an ESPN box score, starters first, then by minutes."""
    out = []
    for group in team_box.get("statistics", []):
        keys = group.get("keys") or []
        for a in group.get("athletes", []):
            ath = a.get("athlete") or {}
            st = a.get("stats") or []
            row = {ours: (st[keys.index(k)] if k in keys and keys.index(k) < len(st) else "")
                   for k, ours in _NBA_PLAYER_BOX.items()}
            out.append({
                "id": str(ath.get("id", "")), "name": ath.get("shortName") or ath.get("displayName", ""),
                "position": (ath.get("position") or {}).get("abbreviation", ""),
                "headshot": (ath.get("headshot") or {}).get("href"),
                "starter": bool(a.get("starter")), "dnp": bool(a.get("didNotPlay")) or not st,
                **row,
            })
    return sorted(out, key=lambda r: (not r["starter"], r["dnp"], -(_stat_num(r["min"]) or 0)))


def _nba_team_form(team: str, games: list[dict], before: str) -> dict:
    """Record, current streak and last 5 results of a team this season, games before `before`
    (an ISO start time) — so a game's page shows the form going into it."""
    done = [g for g in games if g["completed"] and g["season_type"] == 2 and g["start_utc"] < before
            and team in (g["home_team"], g["away_team"]) and g["home_score"] is not None]
    results = []
    for g in done:
        home = g["home_team"] == team
        mine, theirs = (g["home_score"], g["away_score"]) if home else (g["away_score"], g["home_score"])
        results.append({"date": g["date"], "opponent": g["away_team"] if home else g["home_team"], "home": home,
                        "result": "W" if mine > theirs else "L", "score": f"{mine}-{theirs}"})
    wins = sum(r["result"] == "W" for r in results)
    streak = 0
    for r in reversed(results):
        if streak == 0 or (streak > 0) == (r["result"] == "W"):
            streak += 1 if r["result"] == "W" else -1
        else:
            break
    return {"record": f"{wins}-{len(results) - wins}", "streak": streak, "last5": results[-5:][::-1]}


def _nba_head_to_head(away: str, home: str, game_id: str) -> list[dict]:
    """Meetings of the two teams this season and last season (all phases), newest first."""
    year = _nba_season_year()
    out = []
    for season in (year, year - 1):
        try:
            games = _espn_nba_season_games(season)
        except Exception:
            continue
        for g in games:
            if (g["completed"] and g["game_id"] != game_id and {g["home_team"], g["away_team"]} == {away, home}
                    and g["home_score"] is not None):
                out.append({"date": g["date"], "season": f"{season - 1}-{str(season)[-2:]}",
                            "home_team": g["home_team"], "away_team": g["away_team"],
                            "home_score": g["home_score"], "away_score": g["away_score"],
                            "playoffs": g["season_type"] == 3})
    return sorted(out, key=lambda r: r["date"], reverse=True)


def _nba_projected_score(away: str, home: str, p_home: float) -> dict | None:
    """Expected final score: the margin from our pre-game probability (so it agrees with the
    pick), the total from both teams' pace and ratings (points per 100 possessions)."""
    from statistics import NormalDist
    stats = _load_stats_by_name()
    if away not in stats.index or home not in stats.index:
        return None
    a, h = stats.loc[away], stats.loc[home]
    pace = (float(a["pace"]) + float(h["pace"])) / 2
    total = pace * (float(a["off_rtg"]) + float(h["def_rtg"]) + float(h["off_rtg"]) + float(a["def_rtg"])) / 200
    margin = NBA_MARGIN_SD * NormalDist().inv_cdf(min(max(p_home, 1e-4), 1 - 1e-4))
    return {"away": round((total - margin) / 2), "home": round((total + margin) / 2),
            "total": round(total), "margin": round(margin, 1), "pace": round(pace, 1)}


def _nba_game_projection(game_id: str, away: str, home: str, p_home: float, state: str) -> dict | None:
    """The game page's projected score: today's before tip-off; once the game has started, the
    total frozen before it (none for older games without one), split by the pre-game pick."""
    pr = _nba_projected_score(away, home, p_home)
    if pr is None or state == "pre":
        return pr
    frozen = _nba_known_pred(game_id)
    total = (frozen or {}).get("projected_total")
    if total is None or (frozen["away_team"], frozen["home_team"]) != (away, home):
        return None
    return {**pr, "away": round((total - pr["margin"]) / 2), "home": round((total + pr["margin"]) / 2), "total": total}


_nba_roster_cache: dict[str, tuple[float, set[str]]] = {}
_NBA_ROSTER_TTL = 6 * 3600.0


def _nba_roster_ids(team: str) -> set[str]:
    """ESPN athlete ids on the team's current roster (cached a few hours)."""
    hit = _nba_roster_cache.get(team)
    if hit and _time_mod.time() - hit[0] < _NBA_ROSTER_TTL:
        return hit[1]
    tid = ESPN_TEAM_IDS.get(team)
    ids = set(_team_roster("basketball", "nba", str(tid))[1]) if tid else set()
    if ids:
        _nba_roster_cache[team] = (_time_mod.time(), ids)
    return ids


def _nba_key_players(team: str, also_ids: set[str] | None = None, n: int = 3) -> list[dict]:
    """The top scorers on the team's current roster (plus `also_ids`, e.g. the players in this
    game's box score) — season averages: this season once a player has 5 games, else last
    season's — with today's injury status."""
    table = _get_player_minutes_cached()
    if table.empty or "ID" not in table.columns:
        return []
    injuries = {(i.get("athlete") or {}).get("displayName", ""): i.get("status", "")
                for i in _fetch_all_espn_injuries().get(team, [])}
    ids = _nba_roster_ids(team) | (also_ids or set())
    mine = table[table["ID"].isin(ids)] if ids else table[table["TEAM_ABBREVIATION"] == TEAM_TO_ABBR.get(team, "")]
    top = mine.sort_values("PTS", ascending=False).head(n)
    year = _nba_season_year()
    return [{"id": r["ID"], "name": r["PLAYER_NAME"],
             "headshot": f"https://a.espncdn.com/i/headshots/nba/players/full/{r['ID']}.png" if r["ID"] else None,
             "pts": round(float(r["PTS"]), 1), "reb": round(float(r["REB"]), 1), "ast": round(float(r["AST"]), 1),
             "games": int(r["GP"]), "this_season": int(r.get("SEASON", year)) == year,
             "status": injuries.get(r["PLAYER_NAME"]) or None}
            for _, r in top.iterrows()]


@app.get("/api/nba/game/{game_id}")
@app.get("/api/nba/game/{game_id}/live")
def get_nba_game_live(game_id: str):
    """Everything for an NBA game page: score by quarter, clock, our win probability through the
    game (after each basket, from the pre-game prediction — the frozen one when we have it), why
    the model leans that way, team box-score stats and the players' stats in the game."""
    if not game_id.isdigit():
        raise HTTPException(status_code=404, detail="Unknown game")
    hit = _nba_live_cache.get(game_id)
    if hit and _time_mod.time() < hit[0]:
        return hit[1]
    try:
        data = _espn_json(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={game_id}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"ESPN summary fetch failed: {e}")

    comp = ((data.get("header") or {}).get("competitions") or [{}])[0]
    sides = {c.get("homeAway"): c for c in comp.get("competitors", [])}
    if "home" not in sides or "away" not in sides:
        raise HTTPException(status_code=404, detail="Game not found")
    away = sides["away"].get("team", {}).get("displayName", "")
    home = sides["home"].get("team", {}).get("displayName", "")
    st = comp.get("status", {})
    state = st.get("type", {}).get("state", "pre")
    season_type = int(((data.get("header") or {}).get("season") or {}).get("type") or 2)

    stats = _load_stats_by_name()
    if away not in stats.index or home not in stats.index:
        raise HTTPException(status_code=404, detail="Teams not rated")
    date = _nba_et_date(comp.get("date", ""))
    known = _load_nba_game_features()
    a, b = _nba_game_rows(stats, away, home, date, game_id,
                          None if game_id in known else _nba_season_play_dates())
    frozen = _nba_known_pred(game_id)
    if frozen and (frozen["away_team"], frozen["home_team"]) == (away, home):
        p_home = frozen["home_win_prob"] / 100
    else:
        p_home = 1 - float(_nba_pair_probs(_load_model(), [a], [b])[0])

    def point(period: int, clock: str, away_score: int, home_score: int, label: str) -> dict:
        played, left = _nba_clock_minutes(period, clock)
        p = _nba_live_prob(p_home, home_score - away_score, left)
        return {"minute": round(played, 2), "label": label, "away_score": away_score, "home_score": home_score,
                "away_prob": round((1 - p) * 100, 1), "home_prob": round(p * 100, 1)}

    timeline = [{"minute": 0.0, "label": "Tip-off", "away_score": 0, "home_score": 0,
                 "away_prob": round((1 - p_home) * 100, 1), "home_prob": round(p_home * 100, 1)}]
    last = (0, 0)
    for play in data.get("plays", []):
        period = int((play.get("period") or {}).get("number") or 1)
        clock = (play.get("clock") or {}).get("displayValue", "")
        score = (int(play.get("awayScore") or 0), int(play.get("homeScore") or 0))
        if score != last or play.get("type", {}).get("text") == "End Period":
            q = f"Q{period}" if period <= 4 else f"OT{period - 4 if period > 5 else ''}"
            timeline.append(point(period, clock, *score, f"{q} {clock}"))
            last = score

    away_score = int(sides["away"].get("score") or 0)
    home_score = int(sides["home"].get("score") or 0)

    def quarters(c: dict) -> list[int | None]:
        return [_espn_score({"score": q.get("displayValue")}) for q in c.get("linescores") or []]

    try:
        season_games = _espn_nba_season_games()
    except Exception:
        season_games = []

    box = data.get("boxscore") or {}
    team_stats: dict[str, dict] = {}
    for t in box.get("teams", []):
        vals = {s.get("name"): s.get("displayValue") for s in t.get("statistics", [])}
        team_stats[(t.get("team") or {}).get("displayName", "")] = {
            ours: vals[k] for k, ours in _NBA_TEAM_BOX if vals.get(k) not in (None, "")}
    players = {(t.get("team") or {}).get("displayName", ""): _nba_box_players(t) for t in box.get("players", [])}
    if state == "in":
        timeline.append(point(int(st.get("period") or 1), st.get("displayClock", "0:00"),
                              away_score, home_score, "Now"))
    elif state == "post":
        home_won = home_score > away_score
        timeline.append({"minute": max(48.0, timeline[-1]["minute"]), "label": "Final",
                         "away_score": away_score, "home_score": home_score,
                         "away_prob": 0.0 if home_won else 100.0, "home_prob": 100.0 if home_won else 0.0})
    result = {
        "game_id": game_id, "season_type": season_type, "state": state,
        "status": st.get("type", {}).get("shortDetail", ""),
        "away_team": away, "home_team": home, "away_score": away_score, "home_score": home_score,
        "pregame_away_prob": round((1 - p_home) * 100, 1), "pregame_home_prob": round(p_home * 100, 1),
        "away_prob": timeline[-1]["away_prob"], "home_prob": timeline[-1]["home_prob"],
        "timeline": timeline,
        "away_quarters": quarters(sides["away"]), "home_quarters": quarters(sides["home"]),
        "away_stats": team_stats.get(away, {}), "home_stats": team_stats.get(home, {}),
        "away_players": players.get(away, []), "home_players": players.get(home, []),
        "explanation": _nba_explain(a, b),
        "projection": _nba_game_projection(game_id, away, home, p_home, state),
        "form": {side: _nba_team_form(t, season_games, comp.get("date", "") or "9999")
                 for side, t in (("away", away), ("home", home))},
        "h2h": _nba_head_to_head(away, home, game_id),
        "key_players": {side: _nba_key_players(t, {pl["id"] for pl in players.get(t, []) if pl["id"]})
                        for side, t in (("away", away), ("home", home))},
        "venue": ((data.get("gameInfo") or {}).get("venue") or {}).get("fullName", ""),
        "start_utc": comp.get("date", ""),
    }
    ttl = _NBA_LIVE_FINAL_TTL if state == "post" else _NBA_LIVE_TTL
    _nba_live_cache[game_id] = (_time_mod.time() + ttl, result)
    return result


def _nba_power_ratings(model, stats: pd.DataFrame) -> pd.Series:
    """Expected point margin vs an average team on a neutral floor, from the model.

    Each team plays the 29 others on a neutral floor with even rest; its mean win probability
    is converted to points via NBA_MARGIN_SD."""
    from statistics import NormalDist
    teams = list(stats.index)
    pairs = [(a, b) for a in teams for b in teams if a != b]
    p = _nba_pair_probs(model, _nba_feature_rows(stats, [(a, b, False) for a, b in pairs]),
                        _nba_feature_rows(stats, [(b, a, False) for a, b in pairs]))
    mean_p = pd.Series(p, index=[a for a, _ in pairs]).groupby(level=0).mean().reindex(teams)
    nd = NormalDist()
    return mean_p.clip(1e-4, 1 - 1e-4).map(lambda x: NBA_MARGIN_SD * nd.inv_cdf(float(x)))


def _nba_series_prob(p_home: np.ndarray, p_road: np.ndarray) -> np.ndarray:
    """P(the team with home court wins a best-of-7, 2-2-1-1-1) from its home / road game odds."""
    state = {(0, 0): np.ones_like(p_home)}
    win = np.zeros_like(p_home)
    for at_home in HOME_SCHEDULE:
        p = p_home if at_home else p_road
        nxt: dict[tuple[int, int], np.ndarray] = {}
        for (a, b), pr in state.items():
            if a + 1 == 4:
                win = win + pr * p
            else:
                nxt[(a + 1, b)] = nxt.get((a + 1, b), 0) + pr * p
            if b + 1 < 4:
                nxt[(a, b + 1)] = nxt.get((a, b + 1), 0) + pr * (1 - p)
        state = nxt
    return win


_nba_standings_cache: dict | None = None
_nba_standings_cache_time: float = 0.0
_NBA_STANDINGS_TTL = 300.0


@app.get("/api/nba/standings")
def get_nba_standings():
    """Conference standings (ESPN's seeds) and the divisions inside each conference, with games
    behind the conference leader, home / road records, last 10, streak and point differential."""
    global _nba_standings_cache, _nba_standings_cache_time
    now = _time_mod.time()
    if _nba_standings_cache is not None and (now - _nba_standings_cache_time < _NBA_STANDINGS_TTL or _serve_stale("nba_standings", get_nba_standings)):
        return _nba_standings_cache
    year = _nba_season_year()
    try:
        data = _espn_json(f"https://site.api.espn.com/apis/v2/sports/basketball/nba/standings?season={year}&level=3")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"NBA standings fetch failed: {e}")

    def team_row(entry: dict) -> dict:
        st = {s.get("name"): s for s in entry.get("stats", [])}
        def num(k: str) -> float:
            try:
                return float(st.get(k, {}).get("value") or 0)
            except (TypeError, ValueError):
                return 0.0
        def disp(k: str) -> str:
            return st.get(k, {}).get("displayValue", "-")
        t = entry.get("team", {})
        return {"name": t.get("displayName", ""), "abbr": t.get("abbreviation", ""),
                "seed": int(num("playoffSeed")) or None, "w": int(num("wins")), "l": int(num("losses")),
                "pct": disp("winPercent"), "home": disp("Home"), "road": disp("Road"),
                "last10": disp("Last Ten Games"), "streak": disp("streak"),
                "diff": round(num("avgPointsFor") - num("avgPointsAgainst"), 1)}

    conferences = []
    for conf in data.get("children", []):
        divisions, teams = [], []
        for div in conf.get("children", []):
            rows = [team_row(e) for e in div.get("standings", {}).get("entries", [])]
            divisions.append({"name": div.get("name", ""),
                              "teams": sorted(rows, key=lambda r: (-(r["w"] - r["l"]), -r["w"], r["name"]))})
            teams += rows
        teams.sort(key=lambda r: (r["seed"] or 99, r["name"]))
        if teams:
            lead = max(teams, key=lambda r: r["w"] - r["l"])
            for r in teams:   # games behind the conference leader
                r["gb"] = ((lead["w"] - r["w"]) + (r["l"] - lead["l"])) / 2
        conferences.append({"name": "East" if "East" in conf.get("name", "") else "West",
                            "teams": teams, "divisions": divisions})
    result = {"season": f"{year - 1}-{str(year)[-2:]}", "conferences": conferences}
    _nba_standings_cache, _nba_standings_cache_time = result, now
    return result


@app.get("/api/nba/projections")
def get_nba_projections():
    """Monte Carlo of the rest of the NBA regular season, the play-in and the playoffs.

    Regular season: records from completed games; every remaining game uses the model's
    probability with the home page's context (home court, rest, back-to-backs), held fixed.
    Seeding: top 6 per conference, then the play-in (7 v 8 → 7th seed; its loser hosts the
    9 v 10 winner for the 8th seed); ties in the win column are broken at random. Play-in
    games and best-of-7 series are decided from power ratings, the higher seed having home
    court (the better record in the Finals)."""
    global _nba_proj_cache, _nba_proj_cache_time
    from scipy.special import ndtr
    now = _time_mod.time()
    if _nba_proj_cache is not None and ((now - _nba_proj_cache_time) < _NBA_PROJ_TTL or _serve_stale("nba_proj", get_nba_projections)):
        return _nba_proj_cache

    model, stats = _load_model(), _load_stats_by_name()
    teams = list(stats.index)
    idx = {t: i for i, t in enumerate(teams)}
    n_t = len(teams)
    try:
        games = [g for g in _nba_current_season_games() if g["home_team"] in idx and g["away_team"] in idx]
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"NBA schedule fetch failed: {e}")
    play_dates = _nba_play_dates(games)

    wins0, losses0 = np.zeros(n_t), np.zeros(n_t)
    played, remaining = [], []
    for g in games:
        if g["completed"] and g["home_score"] is not None and g["away_score"] is not None:
            home_won = g["home_score"] > g["away_score"]
            wins0[idx[g["home_team"] if home_won else g["away_team"]]] += 1
            losses0[idx[g["away_team"] if home_won else g["home_team"]]] += 1
            played.append(g)
        else:
            remaining.append(g)

    rows_a = _nba_feature_rows(stats, [(g["away_team"], g["home_team"], False) for g in remaining])
    rows_b = _nba_feature_rows(stats, [(g["home_team"], g["away_team"], True) for g in remaining])
    for g, a, b in zip(remaining, rows_a, rows_b):
        _nba_set_rest(a, b, _nba_rest(g["away_team"], g["date"], play_dates),
                      _nba_rest(g["home_team"], g["date"], play_dates))
    p_away = _nba_pair_probs(model, rows_a, rows_b).astype(np.float32)
    power = _nba_power_ratings(model, stats)
    pw = power.to_numpy()

    rng = np.random.default_rng()
    wins = np.tile(wins0, (NBA_SIMS, 1))
    scheduled = wins0 + losses0
    if remaining:
        n_g = len(remaining)
        away_hot = np.zeros((n_g, n_t), np.float32)
        home_hot = np.zeros((n_g, n_t), np.float32)
        away_hot[np.arange(n_g), [idx[g["away_team"]] for g in remaining]] = 1
        home_hot[np.arange(n_g), [idx[g["home_team"]] for g in remaining]] = 1
        scheduled = scheduled + away_hot.sum(axis=0) + home_hot.sum(axis=0)
        # In chunks: ~1,200 games × 10,000 seasons would not fit in memory at once
        for s in range(0, NBA_SIMS, 2000):
            m = min(2000, NBA_SIMS - s)
            away_won = (rng.random((m, n_g), dtype=np.float32) < p_away).astype(np.float32)
            wins[s:s + m] += away_won @ away_hot + (1 - away_won) @ home_hot
    # ESPN lists the NBA Cup knockout-week games only once the groups are decided (80 of 82 in
    # the fall): games not on the schedule yet are played vs an average team on a neutral floor
    missing = np.clip(NBA_GAMES - scheduled, 0, None).astype(int)
    if missing.any():
        wins += rng.binomial(missing, ndtr(pw / NBA_MARGIN_SD), size=(NBA_SIMS, n_t))
    noisy = wins + rng.random(wins.shape) * 1e-3   # random tiebreak

    rows_ix = np.arange(NBA_SIMS)

    def game(home: np.ndarray, away: np.ndarray) -> np.ndarray:
        p = ndtr((pw[home] - pw[away] + NBA_HCA_PTS) / NBA_MARGIN_SD)
        return np.where(rng.random(NBA_SIMS) < p, home, away)

    def series(high: np.ndarray, low: np.ndarray) -> np.ndarray:
        d = pw[high] - pw[low]
        p = _nba_series_prob(ndtr((d + NBA_HCA_PTS) / NBA_MARGIN_SD), ndtr((d - NBA_HCA_PTS) / NBA_MARGIN_SD))
        return np.where(rng.random(NBA_SIMS) < p, high, low)

    made = np.zeros((NBA_SIMS, n_t), bool)
    top6 = np.zeros((NBA_SIMS, n_t), bool)
    top_seed = np.zeros((NBA_SIMS, n_t), bool)
    conf_champ = np.zeros((NBA_SIMS, n_t), bool)
    champs = []
    for conf in (True, False):   # East, West
        c = np.array([idx[t] for t in teams if (t in _NBA_EAST) == conf])
        order = c[np.argsort(-noisy[:, c], axis=1)]                       # (sims, 15), best record first
        top_seed[rows_ix, order[:, 0]] = True
        top6[rows_ix[:, None], order[:, :6]] = True
        seed7 = game(order[:, 6], order[:, 7])
        loser78 = np.where(seed7 == order[:, 6], order[:, 7], order[:, 6])
        seed8 = game(loser78, game(order[:, 8], order[:, 9]))
        seeds = np.column_stack([order[:, :6], seed7, seed8])             # (sims, 8)
        made[rows_ix[:, None], seeds] = True

        # Bracket on seed positions (0 = #1 seed); the higher seed has home court
        def matchup(p1: np.ndarray, p2: np.ndarray, seeds=seeds) -> np.ndarray:
            hi, lo = np.minimum(p1, p2), np.maximum(p1, p2)
            winner = series(seeds[rows_ix, hi], seeds[rows_ix, lo])
            return np.where(winner == seeds[rows_ix, hi], hi, lo)
        full = lambda k: np.full(NBA_SIMS, k)
        r1 = [matchup(full(0), full(7)), matchup(full(3), full(4)),
              matchup(full(2), full(5)), matchup(full(1), full(6))]
        champ = seeds[rows_ix, matchup(matchup(r1[0], r1[1]), matchup(r1[2], r1[3]))]
        conf_champ[rows_ix, champ] = True
        champs.append(champ)

    east, west = champs
    east_hosts = noisy[rows_ix, east] >= noisy[rows_ix, west]
    winner = series(np.where(east_hosts, east, west), np.where(east_hosts, west, east))
    title = np.zeros((NBA_SIMS, n_t), bool)
    title[rows_ix, winner] = True

    # Strength of schedule: mean opponent power, ranked (1 = toughest)
    opp_played: dict[str, list[float]] = {t: [] for t in teams}
    opp_left: dict[str, list[float]] = {t: [] for t in teams}
    for lst, bucket in ((played, opp_played), (remaining, opp_left)):
        for g in lst:
            bucket[g["home_team"]].append(float(power[g["away_team"]]))
            bucket[g["away_team"]].append(float(power[g["home_team"]]))
    sos_rank = pd.Series({t: np.mean(v) if v else np.nan for t, v in opp_played.items()}).rank(ascending=False, method="min")
    rem_rank = pd.Series({t: np.mean(v) if v else np.nan for t, v in opp_left.items()}).rank(ascending=False, method="min")
    power_rank = power.rank(ascending=False, method="first")
    off_rank = stats["off_rtg"].rank(ascending=False, method="min")
    def_rank = stats["def_rtg"].rank(ascending=True, method="min")   # points allowed: lower is better
    roster_rank = stats["roster"].rank(ascending=False, method="min")

    def pct(a: np.ndarray, i: int) -> float:
        return round(float(a[:, i].mean()) * 100, 1)

    out = [{
        "team":           t,
        "abbr":           str(stats.at[t, "abbr"]),
        "conference":     "East" if t in _NBA_EAST else "West",
        "wins":           int(wins0[i]),
        "losses":         int(losses0[i]),
        "power":          round(float(pw[i]), 1),
        "power_rank":     int(power_rank[t]),
        "elo":            round(float(stats.at[t, "elo"])),
        # Recency-weighted, per 100 estimated possessions (nba/pipeline.py)
        "off_rtg":        round(float(stats.at[t, "off_rtg"]), 1),
        "def_rtg":        round(float(stats.at[t, "def_rtg"]), 1),
        "net_rtg":        round(float(stats.at[t, "net_rtg"]), 1),
        "pace":           round(float(stats.at[t, "pace"]), 1),
        "off_rank":       int(off_rank[t]),
        "def_rank":       int(def_rank[t]),
        "roster_rank":    int(roster_rank[t]),
        "sos_rank":       None if pd.isna(sos_rank[t]) else int(sos_rank[t]),
        "rem_sos_rank":   None if pd.isna(rem_rank[t]) else int(rem_rank[t]),
        "projected_wins": round(float(wins[:, i].mean()), 1),
        "playoff_pct":    pct(made, i),
        "top6_pct":       pct(top6, i),
        "top_seed_pct":   pct(top_seed, i),
        "conf_pct":       pct(conf_champ, i),
        "title_pct":      pct(title, i),
    } for t, i in idx.items()]
    out.sort(key=lambda r: (-r["title_pct"], -r["playoff_pct"]))

    year = _nba_season_year()
    result = {"season": f"{year - 1}-{str(year)[-2:]}", "simulations": NBA_SIMS,
              "games_remaining": len(remaining), "teams": out}
    _nba_proj_cache, _nba_proj_cache_time = result, now
    return result


@app.get("/api/stats")
def get_model_stats():
    """NBA model card: leave-one-season-out metrics written by nba/train.py."""
    return _model_stats_payload("nba", FEATURES)
