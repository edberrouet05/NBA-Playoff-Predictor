"""MLB: model, today's games, predictions log, standings, game page, season recap."""

import pickle

from fastapi import FastAPI, HTTPException
import pandas as pd

from api.common import (
    ODDS_API_KEY,
    ROOT,
    _serve_stale,
    app,
)
from api.odds import (
    _fetch_odds_today,
    _game_odds_for,
    _value_bet,
)
from api.record import (
    _model_stats_payload,
    _performance_payload,
    _sport_season_label,
)


@app.get("/api/mlb/performance")
def get_mlb_performance():
    return _performance_payload("mlb", get_mlb_predictions_log(n=100_000)["log"])


_mlb_recap_cache: dict | None = None
_mlb_recap_cache_time: float = 0.0
_MLB_RECAP_TTL = 6 * 3600.0
_MLB_ROUNDS = {"F": "Wild Card", "D": "Division Series", "L": "Championship Series", "W": "World Series"}


def _mlb_postseason_series(season: int) -> list[dict]:
    """Every postseason series of a season, in round order: winner, loser, games won."""
    import json, urllib.request
    url = f"https://statsapi.mlb.com/api/v1/schedule/postseason/series?season={season}&sportId=1"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=15) as r:
        data = json.loads(r.read())
    out = []
    for s in data.get("series", []):
        games = [g for g in s.get("games", []) if g.get("status", {}).get("abstractGameState") == "Final"]
        if not games:
            continue
        last = games[-1]
        sides = [last["teams"]["away"], last["teams"]["home"]]
        rec = [x.get("leagueRecord", {}) for x in sides]
        need = (last.get("gamesInSeries", 7) // 2) + 1
        done = max(r.get("wins", 0) for r in rec) >= need
        w, l = (0, 1) if rec[0].get("wins", 0) >= rec[1].get("wins", 0) else (1, 0)
        desc = last.get("seriesDescription", "")
        out.append({"round": _MLB_ROUNDS.get(last.get("gameType"), desc), "name": desc,
                    "league": "AL" if desc.startswith("AL") else "NL" if desc.startswith("NL") else None,
                    "winner": sides[w]["team"]["name"], "loser": sides[l]["team"]["name"],
                    "wins": rec[w].get("wins", 0), "losses": rec[l].get("wins", 0), "complete": done})
    order = list(_MLB_ROUNDS.values())
    return sorted(out, key=lambda s: (order.index(s["round"]) if s["round"] in order else 9, s["league"] or ""))


@app.get("/api/mlb/season_recap")
def get_mlb_season_recap():
    """The finished season at a glance, for the offseason: champion and postseason series,
    best records, and how the model's fair pre-game picks did (overall, by month, by team,
    best calls and biggest upsets)."""
    import time as _t
    global _mlb_recap_cache, _mlb_recap_cache_time
    if _mlb_recap_cache is not None and (_t.time() - _mlb_recap_cache_time < _MLB_RECAP_TTL or _serve_stale("mlb_recap", get_mlb_season_recap)):
        return _mlb_recap_cache

    season = int(_sport_season_label("mlb"))
    try:
        series = _mlb_postseason_series(season)
    except Exception:
        series = []
    final = next((s for s in series if s["round"] == "World Series"), None)
    complete = bool(final and final["complete"])

    log = get_mlb_predictions_log(n=100_000)["log"]
    games = [g for g in log if g.get("source", "pregame") != "current"]
    perf = _performance_payload("mlb", log)

    months: dict[str, list[int]] = {}
    teams: dict[str, list[int]] = {}
    for g in sorted(games, key=lambda g: g["date"]):
        months.setdefault(g["month"], [0, 0])
        months[g["month"]][0] += g["correct"]
        months[g["month"]][1] += 1
        for t in (g["away_team"], g["home_team"]):
            teams.setdefault(t, [0, 0])
            teams[t][0] += g["correct"]
            teams[t][1] += 1
    by_team = sorted(({"team": t, "n": n, "accuracy": round(c / n, 4)} for t, (c, n) in teams.items()),
                     key=lambda r: -r["accuracy"])

    def pick(g: dict) -> dict:
        return {k: g[k] for k in ("game_id", "date", "away_team", "home_team", "predicted_winner",
                                  "predicted_prob", "actual_winner", "away_score", "home_score")}

    by_prob = sorted(games, key=lambda g: -g["predicted_prob"])
    try:
        standings = get_mlb_standings()
        rows = [t for lg in ("al", "nl") for div in standings.get(lg, []) for t in div["teams"]]
    except Exception:
        rows = []
    best = max(rows, key=lambda t: t["w"], default=None)
    best_diff = max(rows, key=lambda t: t["run_diff"], default=None)

    result = {
        "season": season, "complete": complete,
        "champion": final if complete else None,
        "series": series,
        "best_record": {"team": best["name"], "w": best["w"], "l": best["l"]} if best else None,
        "best_run_diff": {"team": best_diff["name"], "run_diff": best_diff["run_diff"]} if best_diff else None,
        "model": {
            "n_games": perf["n_games"], "correct": perf["correct"], "accuracy": perf["accuracy"],
            "expected_accuracy": perf["expected_accuracy"], "log_loss": perf["log_loss"],
            "by_confidence": perf["by_confidence"],
            "by_month": [{"month": m, "n": n, "accuracy": round(c / n, 4)} for m, (c, n) in months.items()],
            "best_read": by_team[:3], "worst_read": by_team[-3:][::-1],
            "best_calls": [pick(g) for g in by_prob if g["correct"]][:4],
            "biggest_upsets": [pick(g) for g in by_prob if not g["correct"]][:4],
        },
    }
    _mlb_recap_cache, _mlb_recap_cache_time = result, _t.time()
    return result


#  MLB endpoints
# ═══════════════════════════════════════════════════════════════════════════════

MLB_MODEL_PATH = ROOT / "models" / "mlb_logistic_regression.pkl"
MLB_STATS_PATH = ROOT / "data" / "mlb" / "mlb_stats_current.csv"

MLB_PITCHER_RATINGS_PATH = ROOT / "data" / "mlb" / "mlb_pitcher_ratings.csv"
# Pre-game rows of this season's played games (mlb/pipeline.py), keyed by gamePk
MLB_GAME_FEATURES_PATH = ROOT / "data" / "mlb" / "mlb_game_features_current.csv"
_mlb_game_features_cache: dict[str, dict[str, dict]] | None = None


def _load_mlb_game_features() -> dict[str, dict[str, dict]]:
    """{gamePk: {team name: model row}} — the state of both teams before each played game."""
    global _mlb_game_features_cache
    if _mlb_game_features_cache is None:
        out: dict[str, dict[str, dict]] = {}
        if MLB_GAME_FEATURES_PATH.exists():
            for r in pd.read_csv(MLB_GAME_FEATURES_PATH).to_dict("records"):
                out.setdefault(str(r["game_pk"]), {})[r["team_name"]] = r
        _mlb_game_features_cache = out
    return _mlb_game_features_cache
MLB_SP_UNKNOWN = 4.40  # FIP for a starter with no history (matches mlb/pipeline.py SP_UNKNOWN)
# Regular season + postseason (F wild card, D division series, L LCS, W World Series)
MLB_GAME_TYPES = "R,F,D,L,W"

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
        f"&gameType={MLB_GAME_TYPES}"
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
        if g.get("gameType", "R") in MLB_GAME_TYPES.split(",")
    ]
    pitcher_ids: list[int] = []
    for g in all_games:
        for side in ("away", "home"):
            pid = g.get("teams", {}).get(side, {}).get("probablePitcher", {}).get("id")
            if pid:
                pitcher_ids.append(pid)
    starter_eras: dict[int, float] = _fetch_pitcher_eras_batch(list(set(pitcher_ids)))

    mlb_odds = _fetch_odds_today("baseball_mlb", [
        g.get("gameDate", "") for g in all_games
        if (g.get("status") or {}).get("abstractGameState") == "Preview"])
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

            # Finished games only show the stored pre-game line (not distorted post-game odds)
            is_done = status in ("Final", "Game Over", "Completed")
            game_odds = _game_odds_for(mlb_odds, away_name, home_name, game_time, is_done)

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
_MLB_PRED_LOG_TTL = 1800.0  # results only change once games end


@app.get("/api/mlb/predictions_log")
def get_mlb_predictions_log(n: int = 500):
    """Return completed MLB regular-season games with model prediction vs actual result.

    Fetches from Opening Day 2026 → yesterday so the full season log is available.
    Results are cached 30 minutes; n= slices the returned list.
    """
    import time as _t, datetime, json, urllib.request, calendar
    global _mlb_pred_log_cache, _mlb_pred_log_cache_time

    now = _t.time()
    if _mlb_pred_log_cache is not None and ((now - _mlb_pred_log_cache_time) < _MLB_PRED_LOG_TTL or _serve_stale("mlb_log", get_mlb_predictions_log)):
        cached_log = _mlb_pred_log_cache["log"]
        return {"log": cached_log[:n]}

    try:
        # Full 2026 season (regular season + postseason) from Opening Day
        start_date = datetime.date(2026, 3, 25)
        end_date   = datetime.date.today()

        url = (
            "https://statsapi.mlb.com/api/v1/schedule"
            f"?sportId=1&startDate={start_date.isoformat()}&endDate={end_date.isoformat()}"
            f"&gameType={MLB_GAME_TYPES}&limit=2500"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "CourtEdge/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        model = _load_mlb_model()
        stats = _load_mlb_stats()
        features = _load_mlb_game_features()

        log: list[dict] = []
        pending: list[tuple[dict, dict, dict]] = []   # (log entry, away row, home row) scored in one batch
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
                known   = features.get(gid_str, {})
                actual_winner = away_name if away_score > home_score else home_name
                entry = {
                    "game_id": game_id, "date": date_str, "month": month_name,
                    "away_team": away_name, "home_team": home_name, "actual_winner": actual_winner,
                    "away_score": away_score, "home_score": home_score,
                }
                if not cached and away_name in known and home_name in known:
                    # The pipeline's pre-game rows (actual starters, state before the game)
                    entry["source"] = "pregame"
                    pending.append((entry, known[away_name], known[home_name]))
                    log.append(entry)
                    continue
                if cached:
                    away_win_prob    = cached["away_win_prob"]
                    home_win_prob    = cached["home_win_prob"]
                    predicted_winner = cached["predicted_winner"]
                    source           = "pregame"   # served before the game by this server
                else:
                    source = "current"   # recomputed with today's ratings: not a fair pre-game pick
                    away_sp_id  = away_info.get("probablePitcher", {}).get("id")
                    home_sp_id  = home_info.get("probablePitcher", {}).get("id")
                    try:
                        p_away = _mlb_win_prob(model, stats, away_name, home_name, is_home=0,
                                               sp_id=away_sp_id,
                                               opp_sp_id=home_sp_id)
                    except Exception:
                        continue
                    away_win_prob    = round(p_away * 100, 1)
                    home_win_prob    = round((1 - p_away) * 100, 1)
                    predicted_winner = away_name if p_away >= 0.5 else home_name

                entry.update(away_win_prob=away_win_prob, home_win_prob=home_win_prob,
                             predicted_winner=predicted_winner, source=source)
                log.append(entry)

        # One model call for every queued game: rows alternate away, home
        if pending:
            X = pd.DataFrame([r for _, a, h in pending for r in (a, h)])[MLB_FEATURES]
            probs = model.predict_proba(X)[:, 1]
            for i, (entry, _, _) in enumerate(pending):
                p_a, p_h = float(probs[2 * i]), float(probs[2 * i + 1])
                p_away = p_a / (p_a + p_h)
                entry["away_win_prob"] = round(p_away * 100, 1)
                entry["home_win_prob"] = round((1 - p_away) * 100, 1)
                entry["predicted_winner"] = entry["away_team"] if p_away >= 0.5 else entry["home_team"]

        # Same key order as before for every entry
        for i, e in enumerate(log):
            predicted = e["predicted_winner"]
            log[i] = {
                "game_id": e["game_id"], "date": e["date"], "month": e["month"],
                "away_team": e["away_team"], "home_team": e["home_team"],
                "predicted_winner": predicted,
                "predicted_prob": e["away_win_prob"] if predicted == e["away_team"] else e["home_win_prob"],
                "actual_winner": e["actual_winner"], "correct": predicted == e["actual_winner"],
                "away_score": e["away_score"], "home_score": e["home_score"],
                "away_win_prob": e["away_win_prob"], "home_win_prob": e["home_win_prob"],
                "source": e["source"],
            }

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
    if _mlb_standings_cache is not None and ((now - _mlb_standings_cache_time) < _MLB_STANDINGS_TTL or _serve_stale("mlb_standings", get_mlb_standings)):
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
