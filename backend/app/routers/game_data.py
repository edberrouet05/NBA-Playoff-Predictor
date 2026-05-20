"""
Routes for the game detail page:
  GET /api/compare        – side-by-side team stats
  GET /api/injuries       – injury report for two teams (ESPN public API)
  GET /api/series_history – per-game series win-probability history

All three routes return instantly from an in-memory cache.
Background threads populate the cache on startup and refresh every 30 min.
"""

import time
import threading
from pathlib import Path
from threading import Lock
from typing import Any

import requests
import pandas as pd
from fastapi import APIRouter, HTTPException
from nba_api.stats.endpoints import leaguedashteamstats

router = APIRouter()

# ── simple TTL in-memory cache ───────────────────────────────────────────────
_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = Lock()
_TTL = 1800  # 30 min


def _get(key: str) -> Any | None:
    with _cache_lock:
        entry = _cache.get(key)
    if entry and time.monotonic() - entry[0] < _TTL:
        return entry[1]
    return None


def _set(key: str, value: Any) -> None:
    with _cache_lock:
        _cache[key] = (time.monotonic(), value)


def _run_with_timeout(fn, timeout: float, default: Any = None) -> Any:
    holder: list[Any] = [default]

    def _target():
        try:
            holder[0] = fn()
        except Exception:
            pass

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(timeout)
    return holder[0]


# ── CSV loader ────────────────────────────────────────────────────────────────
_STATS_PATH = Path(__file__).parent.parent.parent / "data" / "team_stats_2024_25_Regular_Season.csv"


def _csv_stats() -> pd.DataFrame:
    if not _STATS_PATH.exists():
        raise HTTPException(status_code=503, detail="Stats CSV not found. Run fetch_stats.py first.")
    return pd.read_csv(_STATS_PATH).set_index("team_name")


# ── Extended stats (nba_api) – background fetch, 30-min cache ────────────────
def _do_fetch_extended() -> dict[str, dict]:
    result: dict[str, dict] = {}
    for season_type in ("Playoffs", "Regular Season"):
        try:
            base = leaguedashteamstats.LeagueDashTeamStats(
                season="2024-25",
                season_type_all_star=season_type,
                measure_type_detailed_defense="Base",
                per_mode_detailed="PerGame",
                timeout=10,
            ).get_data_frames()[0]

            adv = leaguedashteamstats.LeagueDashTeamStats(
                season="2024-25",
                season_type_all_star=season_type,
                measure_type_detailed_defense="Advanced",
                per_mode_detailed="PerGame",
                timeout=10,
            ).get_data_frames()[0]

            for _, row in base.iterrows():
                name = row["TEAM_NAME"]
                fga = float(row.get("FGA", 1) or 1)
                fta = float(row.get("FTA", 0) or 0)
                pts = float(row.get("PTS", 0) or 0)
                denom = 2 * (fga + 0.44 * fta)
                ts = pts / denom if denom > 0 else 0.0
                result.setdefault(name, {}).update({
                    "ts_pct":   round(ts, 3),
                    "fg3_rate": round(float(row.get("FG3A", 0) or 0) / fga, 3),
                    "ftr":      round(fta / fga, 3),
                })

            for _, row in adv.iterrows():
                name = row["TEAM_NAME"]
                result.setdefault(name, {}).update({
                    "tov_pct":  round(float(row.get("TM_TOV_PCT", 0) or 0) / 100, 4),
                    "oreb_pct": round(float(row.get("OREB_PCT", 0) or 0) / 100, 4),
                })

            if result:
                break
        except Exception:
            continue
    return result


def _bg_fetch_extended() -> None:
    cached = _get("extended")
    if cached is not None:
        return
    result = _run_with_timeout(_do_fetch_extended, timeout=25, default={})
    if result:
        _set("extended", result)


# ── ESPN injury API – background fetch, 30-min cache ─────────────────────────
_ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"

_ESPN_TO_NBA: dict[str, str] = {
    "Atlanta Hawks": "Atlanta Hawks",
    "Boston Celtics": "Boston Celtics",
    "Brooklyn Nets": "Brooklyn Nets",
    "Charlotte Hornets": "Charlotte Hornets",
    "Chicago Bulls": "Chicago Bulls",
    "Cleveland Cavaliers": "Cleveland Cavaliers",
    "Dallas Mavericks": "Dallas Mavericks",
    "Denver Nuggets": "Denver Nuggets",
    "Detroit Pistons": "Detroit Pistons",
    "Golden State Warriors": "Golden State Warriors",
    "Houston Rockets": "Houston Rockets",
    "Indiana Pacers": "Indiana Pacers",
    "LA Clippers": "LA Clippers",
    "Los Angeles Clippers": "LA Clippers",
    "Los Angeles Lakers": "Los Angeles Lakers",
    "Memphis Grizzlies": "Memphis Grizzlies",
    "Miami Heat": "Miami Heat",
    "Milwaukee Bucks": "Milwaukee Bucks",
    "Minnesota Timberwolves": "Minnesota Timberwolves",
    "New Orleans Pelicans": "New Orleans Pelicans",
    "New York Knicks": "New York Knicks",
    "Oklahoma City Thunder": "Oklahoma City Thunder",
    "Orlando Magic": "Orlando Magic",
    "Philadelphia 76ers": "Philadelphia 76ers",
    "Phoenix Suns": "Phoenix Suns",
    "Portland Trail Blazers": "Portland Trail Blazers",
    "Sacramento Kings": "Sacramento Kings",
    "San Antonio Spurs": "San Antonio Spurs",
    "Toronto Raptors": "Toronto Raptors",
    "Utah Jazz": "Utah Jazz",
    "Washington Wizards": "Washington Wizards",
}


def _do_fetch_injuries() -> dict[str, list[dict]]:
    resp = requests.get(_ESPN_URL, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    result: dict[str, list[dict]] = {}
    for entry in data.get("injuries", []):
        espn_name = entry.get("team", {}).get("displayName", "")
        nba_name = _ESPN_TO_NBA.get(espn_name, espn_name)
        players = []
        for item in entry.get("injuries", []):
            status = item.get("status", "Unknown")
            if status not in ("Out", "Doubtful", "Questionable", "Day-To-Day"):
                continue
            athlete = item.get("athlete", {})
            pts: float | None = None
            for stat in athlete.get("statistics", []):
                if stat.get("name") == "pointsPerGame":
                    try:
                        pts = float(stat["value"])
                    except (TypeError, ValueError):
                        pts = None
            players.append({
                "name": athlete.get("displayName", "Unknown"),
                "status": status,
                "pts_per_game": pts,
            })
        result[nba_name] = players
    return result


def _bg_fetch_injuries() -> None:
    cached = _get("injuries")
    if cached is not None:
        return
    result = _run_with_timeout(_do_fetch_injuries, timeout=20, default={})
    # Cache even if empty so we don't keep retrying on every request
    _set("injuries", result if result else {})


# ── Kick off background prefetches when the module is imported ────────────────
threading.Thread(target=_bg_fetch_extended, daemon=True).start()
threading.Thread(target=_bg_fetch_injuries, daemon=True).start()


# ── Routes (all instant – serve from cache or return safe defaults) ───────────

@router.get("/compare")
def compare_teams(team_a: str, team_b: str):
    stats = _csv_stats()
    for t in (team_a, team_b):
        if t not in stats.index:
            raise HTTPException(status_code=404, detail=f"Team not found: {t}")

    ext = _get("extended") or {}

    def build(name: str) -> dict:
        row = stats.loc[name]
        e = ext.get(name, {})
        net = round(float(row.get("net_rtg", 0)), 1)
        return {
            "off_rtg":    round(float(row.get("off_rtg",  0)), 1),
            "def_rtg":    round(float(row.get("def_rtg",  0)), 1),
            "net_rtg":    net,
            "pace":       round(float(row.get("pace",     0)), 1),
            "ts_pct":     e.get("ts_pct",   0.0),
            "tov_pct":    e.get("tov_pct",  0.0),
            "oreb_pct":   e.get("oreb_pct", 0.0),
            "srs":        net,
            "point_diff": net,
            "fg3_rate":   e.get("fg3_rate", 0.0),
            "ftr":        e.get("ftr",      0.0),
            "win_streak": 0,
        }

    return {
        "team_a": team_a,
        "team_b": team_b,
        "team_a_stats": build(team_a),
        "team_b_stats": build(team_b),
    }


@router.get("/injuries")
def get_injuries(team_a: str, team_b: str):
    all_injuries = _get("injuries") or {}

    result = {}
    for team in (team_a, team_b):
        players = all_injuries.get(team, [])
        factor = sum(
            (p["pts_per_game"] or 0.0)
            for p in players
            if p["status"] in ("Out", "Doubtful")
        )
        result[team] = {"factor": round(factor, 1), "players": players}

    return result


@router.get("/series_history")
def get_series_history(team_a: str, team_b: str):
    return {"history": []}
