"""NFL: model, this week's games, frozen picks, live win probability, game page, standings,
power index, season simulation."""

import pickle
import time as _time_mod

from fastapi import FastAPI, HTTPException
import numpy as np
import pandas as pd

from api.common import (
    NFL_CURRENT_SEASON,
    ROOT,
    _serve_stale,
    app,
)
from api.espn import (
    _espn_athlete_id,
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


@app.get("/api/nfl/performance")
def get_nfl_performance():
    return _performance_payload("nfl", get_nfl_predictions_log(n=100_000)["log"])


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
    "inj_total_diff",
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

# Pre-game predictions written down before kickoff, so a played game is never re-predicted with
# later data (today's injury report, refreshed features). Refreshed while the game is upcoming,
# frozen once it starts. Committed to the repo by the freeze workflow so redeploys keep it.
NFL_FROZEN_PREDS_PATH = ROOT / "data" / "nfl" / "nfl_frozen_predictions.json"


def _load_nfl_frozen_preds() -> dict[str, dict]:
    import json as _json
    try:
        return _json.loads(NFL_FROZEN_PREDS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _merge_nfl_frozen_preds(into: dict[str, dict], other: dict[str, dict]) -> None:
    """Add `other`'s entries to `into`; for a game in both, the later freeze wins."""
    for gid, entry in other.items():
        mine = into.get(gid)
        if not mine or entry.get("frozen_at", "") > mine.get("frozen_at", ""):
            into[gid] = entry


def _save_nfl_frozen_preds() -> None:
    """Write the frozen predictions, first merging in whatever is on disk (another process or a
    seed may have written entries this one never loaded)."""
    import json as _json
    try:
        _merge_nfl_frozen_preds(_nfl_frozen_preds, _load_nfl_frozen_preds())
        NFL_FROZEN_PREDS_PATH.write_text(_json.dumps(_nfl_frozen_preds, indent=1, sort_keys=True), encoding="utf-8")
    except Exception:
        pass


_nfl_frozen_preds: dict[str, dict] = _load_nfl_frozen_preds()
_nfl_frozen_mtime: float = 0.0


def _refresh_nfl_frozen_preds() -> None:
    """Pick up entries written to the file by someone else (a seed, a pulled commit)."""
    global _nfl_frozen_mtime
    try:
        mtime = NFL_FROZEN_PREDS_PATH.stat().st_mtime
    except OSError:
        return
    if mtime != _nfl_frozen_mtime:
        _nfl_frozen_mtime = mtime
        _merge_nfl_frozen_preds(_nfl_frozen_preds, _load_nfl_frozen_preds())


def _nfl_known_pred(game_id) -> dict | None:
    """The pre-game prediction we showed for this game: frozen copy first, then this process's cache."""
    _refresh_nfl_frozen_preds()
    return _nfl_frozen_preds.get(str(game_id)) or _nfl_game_pred_cache.get(str(game_id))


@app.get("/api/nfl/frozen_predictions")
def get_nfl_frozen_predictions() -> dict[str, dict]:
    """Every frozen pre-game prediction (read by the freeze workflow so a redeploy loses none)."""
    _refresh_nfl_frozen_preds()
    return _nfl_frozen_preds


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


# ── Non-QB injuries (same definition as nfl/pipeline.py) ──────────────────────
NFL_PLAYER_ROLES_PATH = ROOT / "data" / "nfl" / "nfl_player_roles.csv"
NFL_INJURY_WEIGHT = {"Out": 1.0, "Doubtful": 0.8, "Questionable": 0.25}  # matches pipeline INJURY_WEIGHT
_nfl_roles_cache: tuple[float, dict[str, dict[str, float]]] | None = None
_nfl_injury_report_cache: dict[str, list[tuple[str, str]]] | None = None
_nfl_injury_report_time: float = 0.0
_NFL_INJURY_TTL = 900.0  # 15 minutes


def _nfl_player_key(name: str) -> str:
    """Same name key as nfl/pipeline.py player_key."""
    import re
    s = re.sub(r"[^a-z ]", "", str(name).lower())
    return " ".join(w for w in s.split() if w not in ("jr", "sr", "ii", "iii", "iv", "v"))


def _load_nfl_roles() -> dict[str, dict[str, float]]:
    """{team: {player key: snap share (off + def) over the team's last 4 games}}."""
    global _nfl_roles_cache
    if not NFL_PLAYER_ROLES_PATH.exists():
        return {}
    mtime = NFL_PLAYER_ROLES_PATH.stat().st_mtime
    if _nfl_roles_cache is None or _nfl_roles_cache[0] != mtime:
        df = pd.read_csv(NFL_PLAYER_ROLES_PATH)
        roles: dict[str, dict[str, float]] = {}
        for r in df.itertuples(index=False):
            roles.setdefault(r.team, {})[r.key] = float(r.offense_pct) + float(r.defense_pct)
        _nfl_roles_cache = (mtime, roles)
    return _nfl_roles_cache[1]


_nfl_injury_status_by_id: dict[str, str] = {}   # ESPN athlete id → injury status (all positions)


def _fetch_nfl_injury_report() -> dict[str, list[tuple[str, str]]] | None:
    """{team: [(player key, status)]} for non-QBs listed Out / Doubtful / Questionable on ESPN.
    None when ESPN is unreachable (callers then keep the pipeline's value)."""
    import json, urllib.request
    global _nfl_injury_report_cache, _nfl_injury_report_time
    now = _time_mod.time()
    if _nfl_injury_report_cache is not None and now - _nfl_injury_report_time < _NFL_INJURY_TTL:
        return _nfl_injury_report_cache
    try:
        req = urllib.request.Request(f"{NFL_BASE}/injuries", headers=NFL_UA)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception:
        return _nfl_injury_report_cache
    out: dict[str, list[tuple[str, str]]] = {}
    _nfl_injury_status_by_id.clear()
    for team in data.get("injuries", []):
        rows = []
        for inj in team.get("injuries", []):
            ath = inj.get("athlete", {})
            status = str(inj.get("status", "")).title()
            aid = _espn_athlete_id(ath)
            if aid:
                _nfl_injury_status_by_id[aid] = status
            if status in NFL_INJURY_WEIGHT and (ath.get("position") or {}).get("abbreviation") != "QB":
                rows.append((_nfl_player_key(ath.get("displayName", "")), status))
        out[team.get("displayName", "")] = rows
    _nfl_injury_report_cache, _nfl_injury_report_time = out, now
    return out


def _nfl_live_injury_loss(team: str) -> float | None:
    """Status-weighted snap share of the team's injured non-QBs (≈ starters missing)."""
    report = _fetch_nfl_injury_report()
    if report is None:
        return None
    roles = _load_nfl_roles().get(team, {})
    return sum(NFL_INJURY_WEIGHT[status] * roles.get(key, 0.0) for key, status in report.get(team, []))


def _nfl_live_injury_diff(team: str, opp: str) -> float | None:
    lt, lo = _nfl_live_injury_loss(team), _nfl_live_injury_loss(opp)
    return None if lt is None or lo is None else lt - lo


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

    # Upcoming games: today's ESPN injury report; played games keep the pipeline's pre-game value
    import datetime
    upcoming = str(r_t.get("game_date", ""))[:10] >= datetime.date.today().isoformat()
    live = _nfl_live_injury_diff(team, opp) if upcoming else None
    base = r_t.get("inj_total_diff")
    inj = live if live is not None else (float(base) if base == base and base is not None else 0.0)
    r_t["inj_total_diff"], r_o["inj_total_diff"] = inj, -inj
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
            "inj_total_diff": inj if t == team else -inj,
        }
    inj = _nfl_live_injury_diff(team, opp) or 0.0
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
    _refresh_nfl_frozen_preds()
    data  = _fetch_nfl_scoreboard()
    model = _load_nfl_model()
    stats = _load_nfl_stats()
    nfl_odds = _fetch_odds_today("americanfootball_nfl", [
        ev.get("date", "") for ev in data.get("events", [])
        if ((ev.get("competitions") or [{}])[0].get("status") or {}).get("type", {}).get("state") == "pre"])

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

        gid_str = str(game_id)
        frozen  = _nfl_frozen_preds.get(gid_str)
        if status.get("state", "pre") != "pre" and frozen:
            # Started or played: show what we predicted before kickoff, never a re-prediction
            away_wp, home_wp, pred_winner = frozen["away_win_prob"], frozen["home_win_prob"], frozen["predicted_winner"]
        else:
            pred = _predict_nfl_game(model, stats, away_name, home_name, game_id)
            if pred is None:
                continue
            away_wp, home_wp, pred_winner = pred
            if status.get("state", "pre") == "pre":
                entry = {"away_team": away_name, "home_team": home_name, "kickoff": ev.get("date", ""),
                         "away_win_prob": away_wp, "home_win_prob": home_wp, "predicted_winner": pred_winner}
                if not frozen or any(frozen.get(k) != v for k, v in entry.items()):
                    _nfl_frozen_preds[gid_str] = {**entry, "frozen_at": _time_mod.strftime("%Y-%m-%dT%H:%M:%SZ", _time_mod.gmtime())}
                    _save_nfl_frozen_preds()

        status_desc = status.get("description", "Scheduled")
        is_done = bool(status.get("completed", False))
        game_odds = _game_odds_for(nfl_odds, away_name, home_name, ev.get("date", ""), is_done)

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
    if _nfl_pred_log_cache is not None and ((now - _nfl_pred_log_cache_time) < _NFL_PRED_LOG_TTL or _serve_stale("nfl_log", get_nfl_predictions_log)):
        cached_log = _nfl_pred_log_cache["log"]
        return {"log": cached_log[:n]}

    try:
        model = _load_nfl_model()
        stats = _load_nfl_stats()

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
                cached  = _nfl_known_pred(gid_str)
                if cached:
                    away_win_prob    = cached["away_win_prob"]
                    home_win_prob    = cached["home_win_prob"]
                    predicted_winner = cached["predicted_winner"]
                else:
                    pred = _predict_nfl_game(model, stats, away_name, home_name, gid_str)
                    if pred is None:
                        continue
                    away_win_prob, home_win_prob, predicted_winner = pred
                # frozen before kickoff / pipeline's pre-game rows / today's team state
                source = ("frozen" if gid_str in _nfl_frozen_preds
                          else "pregame" if cached or gid_str in _load_nfl_game_features() else "current")

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
                    "source":           source,
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
    if _nfl_proj_cache is not None and ((now - _nfl_proj_cache_time) < _NFL_PROJ_TTL or _serve_stale("nfl_proj", get_nfl_projections)):
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
    if _nfl_power_cache is not None and ((now - _nfl_power_cache_time) < _NFL_PROJ_TTL or _serve_stale("nfl_power", get_nfl_power)):
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
    if _nfl_standings_cache is not None and ((now - _nfl_standings_cache_time) < _NFL_STANDINGS_TTL or _serve_stale("nfl_standings", get_nfl_standings)):
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


# Healthiest first: players most likely to play are listed at the top
_NFL_INJURY_ORDER = {"day-to-day": 0, "questionable": 1, "doubtful": 2, "suspension": 3,
                     "out": 4, "physically unable to perform": 5, "injured reserve": 5}


def _nfl_parse_injuries(summary: dict) -> dict[str, list[dict]]:
    """{team displayName: [injured players]} from an ESPN game summary, healthiest first."""
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
                "id":          _espn_athlete_id(ath),
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


# ── Play-by-play in-game win probability (our model) ─────────────────────────
# Starts from our pre-game prediction and updates on every play using score,
# clock, possession, field position, down and distance. Two regimes:
#   • Normal approximation of the final margin (most of the game)
#   • discrete drive-outcome model (TD / FG / no score) in the final minutes,
#     blended in over the last 4 minutes of regulation/OT.

_NFL_FINAL_MARGIN_SD = 13.5   # std of an NFL final margin
_NFL_POSS_SD         = 3.5    # extra uncertainty from how the current possession ends
# Expected points for 1st & 10 by yards to the end zone (net of the opponent's next drive)
_NFL_EP_TABLE = [(1, 6.0), (5, 5.3), (10, 4.8), (20, 4.0), (30, 3.3), (40, 2.7), (50, 2.0),
                 (60, 1.4), (70, 0.9), (80, 0.4), (90, -0.2), (99, -0.6)]
# FG make rate by kick distance
_NFL_FG_TABLE = [(20, 0.99), (30, 0.96), (40, 0.88), (50, 0.72), (55, 0.58), (60, 0.35), (65, 0.1)]
# Drive outcomes with ample time, 1st & 10 at `yte`: P(TD), P(reach FG range)
_NFL_TD_TABLE    = [(2, 0.80), (5, 0.70), (10, 0.60), (20, 0.50), (35, 0.40), (50, 0.33),
                    (65, 0.26), (75, 0.22), (90, 0.17)]
_NFL_REACH_TABLE = [(35, 0.92), (50, 0.75), (65, 0.60), (75, 0.52), (90, 0.42)]


def _interp(table: list[tuple[float, float]], x: float) -> float:
    if x <= table[0][0]:
        return table[0][1]
    for (x0, y0), (x1, y1) in zip(table, table[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return table[-1][1]


def _nfl_expected_points(yte: float, down: int, dist: float) -> float:
    v = _interp(_NFL_EP_TABLE, max(1, min(99, yte)))
    if down == 2:
        v -= 0.35 + 0.03 * max(0, dist - 7)
    elif down == 3:
        v -= 0.9 + 0.06 * max(0, dist - 4)
    elif down == 4:
        v -= 1.6 + 0.08 * max(0, dist - 2)
    return v


def _nfl_late_win_prob(m: float, yte: float, down: int, dist: float, secs: float,
                       ot_p: float, depth: int = 0) -> float:
    """Win prob for the team WITH the ball, leading by `m`, in the final minutes."""
    from statistics import NormalDist
    norm = NormalDist()
    if secs <= 0 or depth > 3:
        return 1.0 if m > 0 else 0.0 if m < 0 else ot_p

    if m >= 1:  # leader tries to run out the clock
        p_conv = {1: 0.62, 2: 0.48, 3: max(0.15, 0.5 - 0.04 * dist), 4: 0.0}.get(down, 0.6)
        burn = 28 * (4 - down) + 6
        if secs <= burn:
            return 0.99
        keep = (_nfl_late_win_prob(m, max(1, yte - 12), 1, 10, secs - burn, ot_p, depth + 1)
                if depth < 3 else 0.99)
        punt_to = max(20, min(85, 100 - yte + 40)) if yte > 40 else 75
        give = 1 - _nfl_late_win_prob(-m, punt_to, 1, 10, secs - burn, 1 - ot_p, depth + 1)
        return p_conv * keep + (1 - p_conv) * give

    down_f = {1: 1.0, 2: 0.93 - 0.015 * max(0, dist - 10),
              3: max(0.4, 0.85 - 0.03 * dist), 4: max(0.15, 0.55 - 0.05 * dist)}.get(down, 1.0)

    def in_time(need: float) -> float:
        return norm.cdf((secs - need) / (0.35 * need + 6))

    plays_cap = min(1.0, 0.25 + 0.75 * (1 + secs / 7.0) / (3 + yte / 7.0))
    p_td = _interp(_NFL_TD_TABLE, yte) * down_f * in_time(2 + max(0, yte - 15) * 0.9) * plays_cap
    if yte <= 35:
        p_fg = (0.92 - p_td) * _interp(_NFL_FG_TABLE, yte + 17) * in_time(3)
    else:
        p_fg = max(0.0, _interp(_NFL_REACH_TABLE, yte) * down_f * in_time(4 + (yte - 35)) - p_td) * 0.85
    if m > 3 or m < -3:
        p_fg *= 0.6 if m < -3 else 0.4   # a FG alone doesn't change the outcome much
    p_none = max(0.0, 1 - p_td - p_fg)

    def opp_turn(new_m: float, opp_yte: float, used: float) -> float:
        after = max(0.0, secs - used)
        return 1 - _nfl_late_win_prob(-new_m, opp_yte, 1, 10, after, 1 - ot_p, depth + 1)

    t_drive = min(secs, 6 + yte * 0.8)
    return (p_td * opp_turn(m + 7, 75, t_drive + 5)
            + p_fg * opp_turn(m + 3, 75, min(secs, t_drive) + 5)
            + p_none * opp_turn(m, max(30, min(80, 100 - yte + 10)), min(secs, 25)))


def _nfl_live_win_prob(pre_home: float, margin: float, secs_left: float,
                       home_poss: bool | None, yte: float, down: int, dist: float) -> float:
    """Home win probability given the game state, anchored on our pre-game prob."""
    import math
    from statistics import NormalDist
    norm = NormalDist()
    ot_home = 0.5 + (pre_home - 0.5) * 0.5
    if secs_left <= 0:
        if margin:
            return 1.0 if margin > 0 else 0.0
        return ot_home

    f   = secs_left / 3600.0
    mu0 = _NFL_FINAL_MARGIN_SD * norm.inv_cdf(min(0.99, max(0.01, pre_home)))
    e   = 0.0
    if home_poss is not None:
        e = _nfl_expected_points(yte, down, dist)
        if yte > 35:   # out of FG range: the drive needs time
            e *= min(1.0, (secs_left + 20) / 150)
        if not home_poss:
            e = -e
    sd = math.sqrt(_NFL_FINAL_MARGIN_SD ** 2 * f
                   + (_NFL_POSS_SD ** 2 if home_poss is not None else 0) + 0.25)
    p = norm.cdf((margin + mu0 * f + e) / sd)

    if home_poss is not None and secs_left <= 240:
        if home_poss:
            q = _nfl_late_win_prob(margin, yte, down, dist, secs_left, ot_home)
        else:
            q = 1 - _nfl_late_win_prob(-margin, yte, down, dist, secs_left, 1 - ot_home)
        w = 1.0 if secs_left <= 120 else (240 - secs_left) / 120
        p = w * q + (1 - w) * p
    return min(0.999, max(0.001, p))


def _nfl_play_win_probs(data: dict, home_id: str, away_id: str, pre_home: float) -> list[dict]:
    """Run our live model over every play in an ESPN summary payload."""
    drives = data.get("drives", {})
    drive_list = list(drives.get("previous", []))
    cur = drives.get("current")
    if cur and cur.get("id") not in {d.get("id") for d in drive_list}:
        drive_list.append(cur)

    def clock_secs(s: str) -> int:
        try:
            mm, ss = s.split(":")
            return int(mm) * 60 + int(ss)
        except (ValueError, AttributeError):
            return 0

    state: tuple | None = None   # (possession team id, yards to end zone, down, distance)
    hs = as_ = 0
    out: list[dict] = []
    for drive in drive_list:
        for play in drive.get("plays", []):
            period = (play.get("period") or {}).get("number") or 1
            clock  = clock_secs((play.get("clock") or {}).get("displayValue", "0:00"))
            left   = (4 - period) * 900 + clock if period <= 4 else clock
            end    = play.get("end") or {}
            tid    = (end.get("team") or {}).get("id")
            dn, yte = end.get("down"), end.get("yardsToEndzone")
            typ    = (play.get("type") or {}).get("text", "")

            pat = 0.0
            if play.get("scoringPlay"):
                scorer = ((play.get("start") or {}).get("team") or {}).get("id") or tid
                if "Touchdown" in typ:   # extra point not yet on the board
                    pat = 0.95 if scorer == home_id else -0.95
                state = (away_id if scorer == home_id else home_id, 75, 1, 10)
            elif dn in (1, 2, 3, 4) and yte and 1 <= yte <= 99 and tid:
                state = (tid, yte, dn, end.get("distance") or 10)

            # ESPN occasionally reports 0-0 on administrative plays; scores never go down
            hs  = max(hs, play.get("homeScore") or 0)
            as_ = max(as_, play.get("awayScore") or 0)
            if typ == "End of Game" or (period >= 4 and clock == 0 and typ.startswith("End")):
                left = 0
            elif left <= 0:
                left = 1

            home_poss = None if state is None else state[0] == home_id
            p = _nfl_live_win_prob(pre_home, hs - as_ + pat, left, home_poss,
                                   *(state[1:] if state else (75, 1, 10)))
            out.append({"play": play, "period": period, "home_prob": p * 100})
    return out


@app.get("/api/nfl/game/{game_id}")
def get_nfl_game_detail(game_id: str):
    """Return box score, quarter-by-quarter score, and team stat comparison for one game."""
    import json, urllib.request
    try:
        url = f"{NFL_BASE}/summary?event={game_id}"
        req = urllib.request.Request(url, headers=NFL_UA)
        # ESPN's TLS handshake sometimes times out on a cold start (while /week fires
        # its own batch of requests) — retry before giving up.
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read())
                break
            except (urllib.error.URLError, TimeoutError):
                if attempt == 2:
                    raise
                _time_mod.sleep(0.5 * (attempt + 1))

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
        cached_pred = _nfl_known_pred(game_id)
        if cached_pred:
            away_wp = cached_pred["away_win_prob"]
            home_wp = cached_pred["home_win_prob"]
        else:
            model = _load_nfl_model()
            stats = _load_nfl_stats()
            pred  = _predict_nfl_game(model, stats, away_name, home_name, game_id)
            away_wp, home_wp = pred[0:2] if pred else (50.0, 50.0)

        # ── Play-by-play win probability (our live model, from our pre-game prob) ──
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

        play_probs = _nfl_play_win_probs(
            data, str(home.get("team", {}).get("id", "")), str(away.get("team", {}).get("id", "")),
            p_home_pre,
        )

        if play_probs:
            last_period = None
            for i, pp in enumerate(play_probs):
                play       = pp["play"]
                period_num = pp["period"]
                home_pct   = pp["home_prob"]

                label = ""
                if period_num != last_period:
                    label = f"Q{period_num}" if period_num <= 4 else f"OT{period_num - 4}"
                    last_period = period_num

                history.append({
                    "idx":          i + 1,
                    "label":        label,
                    "away_prob":    round(100.0 - home_pct, 1),
                    "home_prob":    round(home_pct, 1),
                    "scoring_play": bool(play.get("scoringPlay", False)),
                    "away_score":   play.get("awayScore"),
                    "home_score":   play.get("homeScore"),
                })
        else:
            # Fallback: coarse quarter-by-quarter estimate when ESPN has no
            # play-by-play data for this game (e.g. very old games).
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
            "h2h":           _nfl_head_to_head(away_name, home_name, comp.get("date", ""),
                                               game_id, bool(comp.get("neutralSite"))),
            "leaders":       _nfl_parse_leaders(data),
            # ESPN returns game leaders once the game starts, season leaders before
            "leaders_scope": "season" if status.get("state") == "pre" else "game",
        }
        return result

    except Exception as e:
        raise HTTPException(status_code=502, detail=f"NFL game detail fetch failed: {e}")


# ── Top performers ────────────────────────────────────────────────────────────

_NFL_LEADER_CATEGORIES = {
    "passingYards": "Passing", "rushingYards": "Rushing", "receivingYards": "Receiving",
    "sacks": "Sacks", "totalTackles": "Tackles",
}


def _nfl_parse_leaders(data: dict) -> dict[str, list[dict]]:
    """{team displayName: [{category, label, name, position, value, headshot}]} from an ESPN summary."""
    out: dict[str, list[dict]] = {}
    for team_block in data.get("leaders", []):
        team = team_block.get("team", {}).get("displayName", "")
        rows = []
        for cat in team_block.get("leaders", []):
            key = cat.get("name")
            if key not in _NFL_LEADER_CATEGORIES or not cat.get("leaders"):
                continue
            top = cat["leaders"][0]
            ath = top.get("athlete", {})
            rows.append({
                "category": key,
                "label":    _NFL_LEADER_CATEGORIES[key],
                "id":       _espn_athlete_id(ath),
                "name":     ath.get("displayName", ""),
                "position": (ath.get("position") or {}).get("abbreviation", ""),
                "value":    top.get("displayValue", ""),
                "headshot": (ath.get("headshot") or {}).get("href"),
            })
        if team:
            out[team] = rows
    return out


# ── Head-to-head history ──────────────────────────────────────────────────────

NFL_GAMES_HISTORY_PATH = ROOT / "data" / "nfl" / "nfl_games_history.csv"
_nfl_history_cache: tuple[float, pd.DataFrame] | None = None


def _load_nfl_history() -> pd.DataFrame | None:
    """Completed games since 1999 (written by nfl/pipeline.py), reloaded when the file changes."""
    global _nfl_history_cache
    if not NFL_GAMES_HISTORY_PATH.exists():
        return None
    mtime = NFL_GAMES_HISTORY_PATH.stat().st_mtime
    if _nfl_history_cache is None or _nfl_history_cache[0] != mtime:
        h = pd.read_csv(NFL_GAMES_HISTORY_PATH, dtype={"espn": "string"})
        h["winner"] = np.where(h["home_score"] > h["away_score"], h["home_team"],
                               np.where(h["away_score"] > h["home_score"], h["away_team"], ""))
        _nfl_history_cache = (mtime, h)
    return _nfl_history_cache[1]


def _nfl_streak(winners: list[str]) -> tuple[str, int]:
    """Current streak from a chronological list of winners ('' = tie): (team, length)."""
    if not winners or not winners[-1]:
        return "", 0
    team, n = winners[-1], 0
    for w in reversed(winners):
        if w != team:
            break
        n += 1
    return team, n


def _nfl_head_to_head(away: str, home: str, game_time_utc: str, game_id: str,
                      neutral: bool = False) -> dict | None:
    """Series history between two teams, using only games played before this one."""
    import datetime, zoneinfo
    h = _load_nfl_history()
    if h is None:
        return None
    try:
        game_day = (datetime.datetime.fromisoformat(game_time_utc.replace("Z", "+00:00"))
                    .astimezone(zoneinfo.ZoneInfo("America/New_York")).date().isoformat())
    except ValueError:
        game_day = datetime.date.today().isoformat()

    pair = h[((h["away_team"] == away) & (h["home_team"] == home))
             | ((h["away_team"] == home) & (h["home_team"] == away))]
    this_game = pair[pair["espn"] == str(game_id)]
    past = pair[pair["gameday"] < game_day]
    if past.empty:
        return {"since": int(h["season"].min()), "games": 0, "notes": [], "last_meetings": []}

    nick = {away: away.split()[-1], home: home.split()[-1]}

    def record(df: pd.DataFrame) -> dict:
        return {"games": int(len(df)),
                "away_wins": int((df["winner"] == away).sum()),
                "home_wins": int((df["winner"] == home).sum()),
                "ties": int((df["winner"] == "").sum())}

    # Games hosted by today's home team (true home games, not neutral sites)
    at_home = past[(past["home_team"] == home) & (past["location"] == "Home")]
    playoffs = past[past["game_type"] != "REG"]
    streak_team, streak_n = _nfl_streak(past["winner"].tolist())
    venue_team, venue_n = _nfl_streak(at_home["winner"].tolist())

    # Starting QBs: actual starters for a completed game, else the projected starters
    qbs: dict[str, str] = {}
    if not this_game.empty:
        r = this_game.iloc[0]
        qbs = {away: r["away_qb_name"], home: r["home_qb_name"]}
    else:
        stats = _load_nfl_stats()
        if "qb_name" in stats.columns:
            qbs = {t: stats.at[t, "qb_name"] for t in (away, home) if t in stats.index}

    def qb_record(team: str, qb: str) -> tuple[int, int, int]:
        side = past[((past["away_team"] == team) & (past["away_qb_name"] == qb))
                    | ((past["home_team"] == team) & (past["home_qb_name"] == qb))]
        return (int((side["winner"] == team).sum()),
                int(((side["winner"] != team) & (side["winner"] != "")).sum()),
                int((side["winner"] == "").sum()))

    def fmt(w: int, l: int, t: int) -> str:
        return f"{w}–{l}" + (f"–{t}" if t else "")

    notes: list[str] = []
    overall = record(past)
    lead, trail = (away, home) if overall["away_wins"] >= overall["home_wins"] else (home, away)
    lw = overall["away_wins"] if lead == away else overall["home_wins"]
    tw = overall["home_wins"] if lead == away else overall["away_wins"]
    if lw == tw:
        notes.append(f"The series is tied {fmt(lw, tw, overall['ties'])} since {int(past['season'].min())}.")
    else:
        notes.append(f"{nick[lead]} lead the series {fmt(lw, tw, overall['ties'])} since {int(past['season'].min())}.")

    if streak_n >= 3:
        notes.append(f"{nick[streak_team]} have won the last {streak_n} meetings.")

    if not neutral and len(at_home) >= 3:
        away_wins_there = at_home[at_home["winner"] == away]
        if away_wins_there.empty:
            notes.append(f"{nick[away]} have never won at {nick[home]} home since {int(at_home['season'].min())} "
                         f"(0–{(at_home['winner'] == home).sum()}).")
        elif venue_team == home and venue_n >= 3:
            last = away_wins_there.iloc[-1]
            notes.append(f"{nick[home]} have won {venue_n} straight home games vs the {nick[away]}; "
                         f"{nick[away]}' last win there was {_nfl_month_year(last['gameday'])}.")
        elif venue_team == away and venue_n >= 3:
            notes.append(f"{nick[away]} have won {venue_n} straight road games vs the {nick[home]}.")
        home_wins_there = at_home[at_home["winner"] == home]
        if home_wins_there.empty:
            notes.append(f"{nick[home]} have never beaten the {nick[away]} at home since "
                         f"{int(at_home['season'].min())} (0–{(at_home['winner'] == away).sum()}).")

    if not playoffs.empty:
        pr = record(playoffs)
        notes.append(f"{len(playoffs)} playoff meeting{'s' if len(playoffs) > 1 else ''}: "
                     f"{nick[away]} {pr['away_wins']}, {nick[home]} {pr['home_wins']}.")

    for team, qb in qbs.items():
        if isinstance(qb, str) and qb:
            w, l, t = qb_record(team, qb)
            if w + l + t >= 2:
                opp = home if team == away else away
                notes.append(f"{qb} is {fmt(w, l, t)} as a starter vs the {nick[opp]}.")

    # What this game's result did to the streaks (completed games only)
    result_notes: list[str] = []
    if not this_game.empty and this_game.iloc[0]["winner"]:
        g = this_game.iloc[0]
        won, lost = g["winner"], (home if g["winner"] == away else away)
        n_all = _nfl_streak(past["winner"].tolist() + [won])[1]
        if streak_team == lost and streak_n >= 3:
            result_notes.append(f"{nick[won]} snapped a {streak_n}-game losing streak against the {nick[lost]}.")
        elif n_all >= 3:
            result_notes.append(f"With this win, {nick[won]} have won {n_all} straight meetings.")
        if not neutral and g["location"] == "Home":
            n_home = _nfl_streak(at_home["winner"].tolist() + [won])[1]
            if won == home and n_home >= 3:
                result_notes.append(f"{nick[home]} extended their home streak vs the {nick[away]} to {n_home}.")
            elif won == away and venue_team == home and venue_n >= 3:
                result_notes.append(f"{nick[away]} ended a {venue_n}-game losing streak at {nick[home]} home.")

    last = past.tail(10).iloc[::-1]
    return {
        "since":    int(past["season"].min()),
        **overall,
        "result_notes": result_notes,
        "at_home":  {**record(at_home), "neutral": neutral},
        "playoffs": record(playoffs),
        "streak":   {"team": streak_team, "count": streak_n},
        "home_streak": {"team": venue_team, "count": venue_n},
        "avg_points": {away: round(float(np.where(past["away_team"] == away, past["away_score"], past["home_score"]).mean()), 1),
                       home: round(float(np.where(past["home_team"] == home, past["home_score"], past["away_score"]).mean()), 1)},
        "notes": notes,
        "last_meetings": [
            {"date": r["gameday"], "season": int(r["season"]), "game_type": r["game_type"],
             "away_team": r["away_team"], "home_team": r["home_team"],
             "away_score": int(r["away_score"]), "home_score": int(r["home_score"]),
             "winner": r["winner"], "neutral": r["location"] != "Home", "overtime": bool(r["overtime"] == 1)}
            for _, r in last.iterrows()
        ],
    }


def _nfl_month_year(iso_day: str) -> str:
    import datetime
    try:
        return datetime.date.fromisoformat(iso_day).strftime("%b %Y")
    except ValueError:
        return iso_day
