"""
MLB endpoints for the backend router.
Logic ported from api/main.py.
"""

import os
import pickle
import time
import json
import threading
import urllib.request
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException

router = APIRouter()

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT          = Path(__file__).parent.parent.parent.parent
MLB_MODEL_PATH = ROOT / "models" / "mlb_logistic_regression.pkl"
MLB_STATS_PATH = ROOT / "data" / "mlb" / "mlb_stats_current.csv"

ODDS_API_KEY = os.getenv("ODDS_API_KEY", "09bb7105d888c7ad840a18fdc316b0c8")

MLB_FEATURES = [
    "sp_era", "opp_sp_era",
    "era_diff", "whip_diff", "fip_diff",
    "k_per9", "bb_per9",
    "ops_diff", "run_diff_diff",
    "home", "rest_days", "win_pct_last10", "park_factor",
    "run_diff_last15", "opp_run_diff_last15",
]

# ── Model / stats caches ──────────────────────────────────────────────────────
_mlb_model_cache = None
_mlb_stats_cache: pd.DataFrame | None = None

_mlb_today_cache: dict | None = None
_mlb_today_cache_date: str = ""
_mlb_today_cache_time: float = 0.0
_MLB_TODAY_TTL = 120.0

_mlb_standings_cache: dict | None = None
_mlb_standings_cache_time: float = 0.0
_MLB_STANDINGS_TTL = 300.0

_mlb_pred_log_cache: dict | None = None
_mlb_pred_log_cache_time: float = 0.0
_MLB_PRED_LOG_TTL = 300.0

_mlb_game_detail_cache: dict[str, dict] = {}
_mlb_game_detail_cache_time: dict[str, float] = {}
_MLB_GAME_DETAIL_TTL_LIVE  = 30.0
_MLB_GAME_DETAIL_TTL_FINAL = 3600.0

# ── Pitcher ERA cache ─────────────────────────────────────────────────────────
_pitcher_era_cache: dict[int, float | None] = {}
_pitcher_era_cache_date: str = ""

# ── Odds caches ───────────────────────────────────────────────────────────────
_odds_cache:      dict[str, dict] = {}
_odds_cache_time: dict[str, float] = {}
_ODDS_TTL = 1800.0

_PREGAME_ODDS_FILE = ROOT / "data" / "pregame_odds.json"
_pregame_odds: dict[str, dict] = {}

try:
    _pregame_odds = json.loads(_PREGAME_ODDS_FILE.read_text(encoding="utf-8"))
except Exception:
    pass

_BOOKMAKER_PRIORITY = [
    "pinnacle", "draftkings", "fanduel", "betmgm", "williamhill",
    "betrivers", "bovada", "unibet_us", "unibet_uk", "paddypower",
    "coral", "ladbrokes_uk", "betway", "marathonbet", "betsson",
]


# ── Loaders ───────────────────────────────────────────────────────────────────

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


# ── Odds helpers ──────────────────────────────────────────────────────────────

def _normalize_team(name: str) -> str:
    return name.lower().strip()


def _save_pregame_odds(data: dict) -> None:
    try:
        _PREGAME_ODDS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _PREGAME_ODDS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


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


# ── Pitcher ERA batch fetch ────────────────────────────────────────────────────

def _fetch_pitcher_eras_batch(pitcher_ids: list[int], season: int = 2026) -> dict[int, float]:
    import datetime as _dt
    global _pitcher_era_cache, _pitcher_era_cache_date

    today = _dt.date.today().isoformat()
    if _pitcher_era_cache_date != today:
        _pitcher_era_cache.clear()
        _pitcher_era_cache_date = today

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

        for pid in uncached:
            if pid not in _pitcher_era_cache:
                _pitcher_era_cache[pid] = None

    return {pid: _pitcher_era_cache[pid] for pid in pitcher_ids if _pitcher_era_cache.get(pid) is not None}


# ── Win probability ───────────────────────────────────────────────────────────

def _mlb_win_prob(
    model, stats: pd.DataFrame,
    team: str, opp: str, is_home: int,
    sp_era_override: float | None = None,
    opp_sp_era_override: float | None = None,
) -> float:
    def _row(t, o, home, sp_era_ov, opp_sp_era_ov):
        ts = stats.loc[t]
        os_ = stats.loc[o]
        return {
            "era":          float(ts.get("era",         4.50)),
            "whip":         float(ts.get("whip",        1.30)),
            "k_per9":       float(ts.get("k_per9",      8.0)),
            "bb_per9":      float(ts.get("bb_per9",     3.2)),
            "sp_era":       sp_era_ov if sp_era_ov is not None else float(ts.get("sp_era", 4.50)),
            "batting_avg":  float(ts.get("batting_avg", 0.250)),
            "ops":          float(ts.get("ops",         0.700)),
            "obp":          float(ts.get("obp",         0.320)),
            "slg":          float(ts.get("slg",         0.420)),
            "run_diff":     float(ts.get("run_diff",    0)),
            "opp_era":      float(os_.get("era",         4.50)),
            "opp_whip":     float(os_.get("whip",        1.30)),
            "opp_ops":      float(os_.get("ops",         0.700)),
            "opp_run_diff": float(os_.get("run_diff",    0)),
            "opp_sp_era":   opp_sp_era_ov if opp_sp_era_ov is not None else float(os_.get("sp_era", 4.50)),
            "era_diff":     float(ts.get("era",     4.50))  - float(os_.get("era",     4.50)),
            "whip_diff":    float(ts.get("whip",    1.30))  - float(os_.get("whip",    1.30)),
            "fip_diff":     float(ts.get("fip",     4.20))  - float(os_.get("fip",     4.20)),
            "ops_diff":     float(ts.get("ops",     0.700)) - float(os_.get("ops",     0.700)),
            "run_diff_diff":float(ts.get("run_diff", 0))    - float(os_.get("run_diff", 0)),
            "home":               home,
            "rest_days":          4,
            "win_pct_last10":     float(ts.get("win_pct_last10",    0.5)),
            "park_factor":        float(ts.get("park_factor",       1.0)),
            "run_diff_last15":    float(ts.get("run_diff_last15",   0.0)),
            "opp_run_diff_last15": float(os_.get("run_diff_last15",  0.0)),
        }

    r_team = _row(team, opp, is_home,     sp_era_override,     opp_sp_era_override)
    r_opp  = _row(opp, team, 1 - is_home, opp_sp_era_override, sp_era_override)
    p_t = float(model.predict_proba(pd.DataFrame([r_team])[MLB_FEATURES])[0][1])
    p_o = float(model.predict_proba(pd.DataFrame([r_opp ])[MLB_FEATURES])[0][1])
    return p_t / (p_t + p_o)


# ── Today fetch ───────────────────────────────────────────────────────────────

def _fetch_mlb_today() -> dict:
    import datetime as _dt

    today_iso = _dt.date.today().isoformat()
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

        away_score = away_info.get("score")
        home_score = home_info.get("score")

        def _pitcher_name(side_info: dict) -> str:
            p = side_info.get("probablePitcher", {})
            return p.get("fullName", "TBD") if p else "TBD"

        away_sp    = _pitcher_name(away_info)
        home_sp    = _pitcher_name(home_info)
        away_sp_id = away_info.get("probablePitcher", {}).get("id")
        home_sp_id = home_info.get("probablePitcher", {}).get("id")

        away_sp_era = starter_eras.get(away_sp_id) if away_sp_id else None
        home_sp_era = starter_eras.get(home_sp_id) if home_sp_id else None

        if away_name not in stats.index or home_name not in stats.index:
            continue

        try:
            p_away = _mlb_win_prob(
                model, stats, away_name, home_name, is_home=0,
                sp_era_override=away_sp_era,
                opp_sp_era_override=home_sp_era,
            )
        except Exception:
            p_away = 0.5

        game_odds = _get_game_odds(mlb_odds, away_name, home_name)

        is_done  = status in ("Final", "Game Over", "Completed")
        game_key = f"{_normalize_team(away_name)}|{_normalize_team(home_name)}"
        if is_done and game_key not in _pregame_odds:
            game_odds = {}

        results.append({
            "game_id":          game_id,
            "status":           status,
            "game_time_utc":    game_time,
            "venue":            venue,
            "away_team":        away_name,
            "home_team":        home_name,
            "away_score":       away_score,
            "home_score":       home_score,
            "away_win_prob":    round(p_away * 100, 1),
            "home_win_prob":    round((1 - p_away) * 100, 1),
            "predicted_winner": away_name if p_away >= 0.5 else home_name,
            "away_pitcher":     away_sp,
            "home_pitcher":     home_sp,
            "away_sp_era":      round(away_sp_era, 2) if away_sp_era is not None else None,
            "home_sp_era":      round(home_sp_era, 2) if home_sp_era is not None else None,
            "away_odds":        game_odds.get("away_odds"),
            "home_odds":        game_odds.get("home_odds"),
        })

    return {"date": today_iso, "games": results}


# ── Inning win probability ────────────────────────────────────────────────────

def _mlb_inning_win_prob(
    pre_game_home_prob: float,
    home_runs: int,
    away_runs: int,
    inning: float,
    total_innings: float = 9.0,
) -> float:
    import math
    score_diff        = home_runs - away_runs
    innings_remaining = max(0.3, total_innings - inning)
    run_rate = 0.46
    std_net  = math.sqrt(2.0 * run_rate * innings_remaining)
    z        = score_diff / (std_net * math.sqrt(2.0))
    cur_prob = 0.5 * (1.0 + math.erf(z))
    progress = min(0.95, inning / total_innings)
    p = (1.0 - progress) * pre_game_home_prob + progress * cur_prob
    return max(0.02, min(0.98, p))


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/today")
def get_mlb_today():
    import datetime as _dt
    global _mlb_today_cache, _mlb_today_cache_date, _mlb_today_cache_time

    today = _dt.date.today().isoformat()
    now   = time.time()

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


@router.get("/teams")
def get_mlb_teams() -> list[str]:
    return sorted(_load_mlb_stats().index.tolist())


@router.get("/predictions_log")
def get_mlb_predictions_log(n: int = 500):
    import datetime as _dt, calendar as _cal
    global _mlb_pred_log_cache, _mlb_pred_log_cache_time

    now = time.time()
    if _mlb_pred_log_cache is not None and (now - _mlb_pred_log_cache_time) < _MLB_PRED_LOG_TTL:
        return {"log": _mlb_pred_log_cache["log"][:n]}

    try:
        start_date = _dt.date(2026, 3, 25)
        end_date   = _dt.date.today()

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
            try:
                month_num  = int(date_str.split("-")[1])
                month_name = _cal.month_name[month_num]
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

                away_sp_id  = away_info.get("probablePitcher", {}).get("id")
                home_sp_id  = home_info.get("probablePitcher", {}).get("id")
                away_sp_era = starter_eras.get(away_sp_id) if away_sp_id else None
                home_sp_era = starter_eras.get(home_sp_id) if home_sp_id else None

                try:
                    p_away = _mlb_win_prob(model, stats, away_name, home_name, is_home=0,
                                           sp_era_override=away_sp_era,
                                           opp_sp_era_override=home_sp_era)
                except Exception:
                    continue

                predicted_winner = away_name if p_away >= 0.5 else home_name
                predicted_prob   = round((p_away if p_away >= 0.5 else 1 - p_away) * 100, 1)
                actual_winner    = away_name if away_score > home_score else home_name

                log.append({
                    "game_id":          g.get("gamePk"),
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
                    "away_win_prob":    round(p_away * 100, 1),
                    "home_win_prob":    round((1 - p_away) * 100, 1),
                })

        result = {"log": log}
        _mlb_pred_log_cache      = result
        _mlb_pred_log_cache_time = now
        return {"log": log[:n]}
    except Exception:
        return {"log": []}


@router.get("/standings")
def get_mlb_standings():
    global _mlb_standings_cache, _mlb_standings_cache_time

    now = time.time()
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

        DIV_DISPLAY = {
            "American League East":    "AL East",
            "American League Central": "AL Central",
            "American League West":    "AL West",
            "National League East":    "NL East",
            "National League Central": "NL Central",
            "National League West":    "NL West",
        }

        for record in data.get("records", []):
            league_id = record.get("league", {}).get("id")
            div_name  = record.get("division", {}).get("name", "")
            display_name = DIV_DISPLAY.get(div_name, div_name)

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


@router.get("/stats")
def get_mlb_model_stats():
    model     = _load_mlb_model()
    estimator = model.named_steps["clf"]
    coefs     = [round(float(c), 6) for c in estimator.coef_[0]] if hasattr(estimator, "coef_") else []

    cv_acc   = 0.0
    cv_std   = 0.0
    cv_folds: list[float] = []
    n_rows   = 0
    seasons: list[int] = []

    metrics_path = ROOT / "models" / "mlb_metrics.txt"
    if metrics_path.exists():
        for line in metrics_path.read_text().split("\n"):
            if "Cross-val accuracy" in line:
                try:
                    parts = line.split(":")[1].split("+/-")
                    cv_acc = float(parts[0].strip())
                    cv_std = float(parts[1].strip()) if len(parts) > 1 else 0.0
                except Exception:
                    pass
            if "Per-fold" in line:
                try:
                    raw = line.split(":")[1].strip().strip("[]")
                    cv_folds = [
                        float(x.replace("np.float64(","").replace(")","").strip())
                        for x in raw.split(",") if x.strip()
                    ]
                except Exception:
                    pass
            if "Training rows" in line:
                try:
                    n_rows = int(line.split(":")[1].strip().replace(",", ""))
                except Exception:
                    pass

    training_path = ROOT / "data" / "processed" / "mlb_training_data.csv"
    if training_path.exists():
        df = pd.read_csv(training_path, usecols=["season"])
        seasons = sorted(int(s) for s in df["season"].unique())
        if n_rows == 0:
            n_rows = len(df)

    return {
        "accuracy":     round(cv_acc * 100, 2),
        "cv_std":       round(cv_std * 100, 2),
        "cv_folds":     [round(f * 100, 1) for f in cv_folds],
        "n_rows":       n_rows,
        "seasons":      seasons,
        "features":     MLB_FEATURES,
        "coefficients": coefs,
    }


@router.get("/game/{game_id}")
def get_mlb_game_detail(game_id: int):
    global _mlb_game_detail_cache, _mlb_game_detail_cache_time

    cache_key = str(game_id)
    now       = time.time()

    if cache_key in _mlb_game_detail_cache:
        cached  = _mlb_game_detail_cache[cache_key]
        st      = cached.get("status", "")
        is_done = "Final" in st or "Over" in st or "Completed" in st
        ttl     = _MLB_GAME_DETAIL_TTL_FINAL if is_done else _MLB_GAME_DETAIL_TTL_LIVE
        if (now - _mlb_game_detail_cache_time.get(cache_key, 0.0)) < ttl:
            return cached

    try:
        ls_url = f"https://statsapi.mlb.com/api/v1/game/{game_id}/linescore"
        req    = urllib.request.Request(ls_url, headers={"User-Agent": "CourtEdge/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            linescore = json.loads(resp.read())

        sc_url = (
            f"https://statsapi.mlb.com/api/v1/schedule"
            f"?gamePk={game_id}&hydrate=probablePitcher,venue"
        )
        req2 = urllib.request.Request(sc_url, headers={"User-Agent": "CourtEdge/1.0"})
        with urllib.request.urlopen(req2, timeout=10) as resp2:
            sched = json.loads(resp2.read())

        game_dates = sched.get("dates", [])
        g_info    = game_dates[0].get("games", [{}])[0] if game_dates else {}
        t_info    = g_info.get("teams", {})
        away_info = t_info.get("away", {})
        home_info = t_info.get("home", {})

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

        try:
            mlb_model = _load_mlb_model()
            mlb_stats = _load_mlb_stats()
            if away_name in mlb_stats.index and home_name in mlb_stats.index:
                p_away = _mlb_win_prob(mlb_model, mlb_stats, away_name, home_name, is_home=0)
            else:
                p_away = 0.5
        except Exception:
            p_away = 0.5
        p_home = 1.0 - p_away

        innings = linescore.get("innings", [])
        history: list[dict] = [{"label": "Pre", "away_prob": round(p_away * 100, 1), "home_prob": round(p_home * 100, 1)}]
        home_total = away_total = 0

        for inn in innings:
            inn_num    = inn.get("num", 0)
            away_r_val = inn.get("away", {}).get("runs")
            home_r_val = inn.get("home", {}).get("runs")

            if away_r_val is None:
                break

            away_total += int(away_r_val)

            if home_r_val is None:
                p_h = _mlb_inning_win_prob(p_home, home_total, away_total, inn_num - 0.5)
                history.append({"label": f"{inn_num}T", "away_prob": round((1.0 - p_h) * 100, 1), "home_prob": round(p_h * 100, 1)})
                break

            home_total += int(home_r_val)
            p_h = _mlb_inning_win_prob(p_home, home_total, away_total, float(inn_num))
            history.append({"label": str(inn_num), "away_prob": round((1.0 - p_h) * 100, 1), "home_prob": round(p_h * 100, 1)})

        if is_final and len(history) > 1:
            if home_score > away_score:
                history[-1]["home_prob"] = 100.0
                history[-1]["away_prob"] = 0.0
            elif away_score > home_score:
                history[-1]["home_prob"] = 0.0
                history[-1]["away_prob"] = 100.0

        inning_rows = [
            {"num": i.get("num"), "away_r": i.get("away", {}).get("runs"), "home_r": i.get("home", {}).get("runs")}
            for i in innings
        ]

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

        _mlb_game_detail_cache[cache_key]      = result
        _mlb_game_detail_cache_time[cache_key] = now
        return result

    except Exception as e:
        raise HTTPException(status_code=502, detail=f"MLB game detail fetch failed: {e}")


# ── Daily rolling-stats refresh ───────────────────────────────────────────────

def _refresh_mlb_rolling_stats() -> None:
    """Recompute win_pct_last10 / run_diff_last15 for each team from the last
    30 days of completed games and update mlb_stats_current.csv in place."""
    import datetime as _dt

    try:
        age = time.time() - MLB_STATS_PATH.stat().st_mtime
    except FileNotFoundError:
        age = float("inf")

    if age < 82800:          # skip if refreshed within 23 h
        return

    end_date   = _dt.date.today()
    start_date = end_date - _dt.timedelta(days=30)
    url = (
        f"https://statsapi.mlb.com/api/v1/schedule"
        f"?sportId=1&gameType=R"
        f"&startDate={start_date}&endDate={end_date}"
        f"&limit=600"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CourtEdge/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        print(f"[MLB refresh] schedule fetch failed: {exc}")
        return

    team_history: dict[str, list[dict]] = {}
    for date_entry in data.get("dates", []):
        for g in date_entry.get("games", []):
            if g.get("status", {}).get("codedGameState", "") not in ("F", "O"):
                continue
            t     = g.get("teams", {})
            hname = t.get("home", {}).get("team", {}).get("name", "")
            aname = t.get("away", {}).get("team", {}).get("name", "")
            hs    = int(t.get("home", {}).get("score", 0) or 0)
            as_   = int(t.get("away", {}).get("score", 0) or 0)
            gd    = g.get("gameDate", "")[:10]
            for name, won, rd in [(hname, hs > as_, hs - as_), (aname, as_ > hs, as_ - hs)]:
                if name:
                    team_history.setdefault(name, []).append({"date": gd, "won": won, "run_diff": rd})

    if not team_history:
        return

    rolling: dict[str, dict] = {}
    for tname, hist in team_history.items():
        hist = sorted(hist, key=lambda h: h["date"])
        r20  = hist[-20:]
        r15  = hist[-15:]
        if r20:
            weights = [0.88 ** i for i in range(len(r20) - 1, -1, -1)]
            ww = sum(w * (1.0 if h["won"] else 0.0) for w, h in zip(weights, r20))
            win_pct = ww / sum(weights)
        else:
            win_pct = 0.5
        rdl15 = sum(h["run_diff"] for h in r15) / len(r15) if r15 else 0.0
        rolling[tname] = {
            "win_pct_last10":  round(win_pct, 3),
            "run_diff_last15": round(rdl15,   2),
        }

    try:
        df = pd.read_csv(MLB_STATS_PATH)
        for idx, row in df.iterrows():
            tname = row.get("team_name", "")
            if tname in rolling:
                df.at[idx, "win_pct_last10"]  = rolling[tname]["win_pct_last10"]
                df.at[idx, "run_diff_last15"] = rolling[tname]["run_diff_last15"]
        df.to_csv(MLB_STATS_PATH, index=False)
        global _mlb_stats_cache
        _mlb_stats_cache = None          # force reload on next request
        print(f"[MLB refresh] updated rolling stats for {len(rolling)} teams")
    except Exception as exc:
        print(f"[MLB refresh] CSV update failed: {exc}")


def _mlb_refresh_loop() -> None:
    while True:
        try:
            _refresh_mlb_rolling_stats()
        except Exception as exc:
            print(f"[MLB refresh] unexpected error: {exc}")
        time.sleep(3600)          # wake up every hour, skip if < 23 h old


threading.Thread(target=_mlb_refresh_loop, daemon=True).start()
