"""NHL: model, today's games (probable goalies, odds), frozen picks, live win probability,
game page, standings, season simulation, predictions log."""

import pickle
import time as _time_mod

from fastapi import FastAPI, HTTPException
import numpy as np
import pandas as pd

from api.common import (
    ROOT,
    _serve_stale,
    app,
)
from api.espn import (
    _espn_json,
    _norm_name,
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


# ═══════════════════════════════════════════════════════════════════════════════
#  NHL — today's games, game page, standings, predictions log, model
# ═══════════════════════════════════════════════════════════════════════════════
# Data: nhl/pipeline.py (team state + leak-free pre-game rows of this season's games),
# live scores from ESPN's public site API.

NHL_MODEL_PATH = ROOT / "models" / "nhl_logistic_regression.pkl"
NHL_STATE_PATH = ROOT / "data" / "nhl" / "nhl_team_state.csv"
NHL_GAME_FEATURES_PATH = ROOT / "data" / "nhl" / "nhl_game_features_current.csv"
NHL_BASE = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl"
# Order must match nhl/train.py FEATURES exactly
NHL_FEATURES = ["home", "rest_diff", "b2b", "opp_b2b", "elo_diff", "margin_ewm_diff", "shot_share_diff", "sv_pct_diff",
                "goalie_sv_diff"]
NHL_GOALIES_PATH = ROOT / "data" / "nhl" / "nhl_goalies.csv"
NHL_LEAGUE_SV = 0.905     # a goalie with no NHL history (as in nhl/pipeline.py)
NHL_MAX_REST = 4
NHL_GOALS_PER_60 = 3.0    # goals per team per 60 minutes, for the live win probability
NHL_FRANCHISE_IDS = {"24": "129764"}   # Arizona Coyotes → Utah (as in nhl/pipeline.py)

NHL_FROZEN_PREDS_PATH = ROOT / "data" / "nhl" / "nhl_frozen_predictions.json"

_nhl_model_cache = None
_nhl_file_cache: dict[str, tuple[float, object]] = {}


class FrozenPredictions:
    """Pre-game predictions written down before the game starts ({game id: entry}), kept in a
    JSON file. The server adds to it as games are served; the freeze workflow commits it, and
    merges in what the deployed server stored (a redeploy wipes the server's disk). For a game
    in two copies, the later freeze wins."""

    def __init__(self, path):
        self.path = path
        self.preds: dict[str, dict] = self._load()
        self._mtime = 0.0

    def _load(self) -> dict[str, dict]:
        import json as _json
        try:
            return _json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    @staticmethod
    def merge(into: dict[str, dict], other: dict[str, dict]) -> None:
        for gid, entry in other.items():
            mine = into.get(gid)
            if not mine or entry.get("frozen_at", "") > mine.get("frozen_at", ""):
                into[gid] = entry

    def save(self) -> None:
        import json as _json
        try:
            self.merge(self.preds, self._load())
            self.path.write_text(_json.dumps(self.preds, indent=1, sort_keys=True), encoding="utf-8")
        except Exception:
            pass

    def refresh(self) -> None:
        """Pick up entries written to the file by someone else (a pulled commit)."""
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return
        if mtime != self._mtime:
            self._mtime = mtime
            self.merge(self.preds, self._load())

    def get(self, game_id) -> dict | None:
        self.refresh()
        return self.preds.get(str(game_id)) if game_id else None

    def record(self, game_id: str, entry: dict) -> None:
        """Write down (or refresh) the pre-game prediction of a game that has not started."""
        old = self.preds.get(str(game_id))
        if old and all(old.get(k) == v for k, v in entry.items()):
            return
        self.preds[str(game_id)] = {**entry, "frozen_at": _time_mod.strftime("%Y-%m-%dT%H:%M:%SZ", _time_mod.gmtime())}
        self.save()


_nhl_frozen = FrozenPredictions(NHL_FROZEN_PREDS_PATH)


@app.get("/api/nhl/frozen_predictions")
def get_nhl_frozen_predictions() -> dict[str, dict]:
    """Every frozen NHL pre-game prediction (read by the workflows so a redeploy loses none)."""
    _nhl_frozen.refresh()
    return _nhl_frozen.preds


def _load_nhl_model():
    global _nhl_model_cache
    if _nhl_model_cache is None:
        import pickle
        with open(NHL_MODEL_PATH, "rb") as f:
            _nhl_model_cache = pickle.load(f)
    return _nhl_model_cache


def _nhl_cached_file(path, build):
    """Parse a data file once per version on disk (the daily refresh replaces it)."""
    mtime = path.stat().st_mtime if path.exists() else 0.0
    hit = _nhl_file_cache.get(str(path))
    if hit is None or hit[0] != mtime:
        hit = (mtime, build() if mtime else {})
        _nhl_file_cache[str(path)] = hit
    return hit[1]


def _load_nhl_state() -> dict[str, dict]:
    """{team name: team state row} from nhl/pipeline.py."""
    return _nhl_cached_file(NHL_STATE_PATH, lambda: {
        r["team_name"]: r for r in pd.read_csv(NHL_STATE_PATH).to_dict("records")})


def _load_nhl_game_features() -> dict[str, dict[str, dict]]:
    """{game id: {team name: pre-game row}} for this season's games."""
    def build():
        out: dict[str, dict[str, dict]] = {}
        for r in pd.read_csv(NHL_GAME_FEATURES_PATH).to_dict("records"):
            out.setdefault(str(r["game_id"]), {})[r["team"]] = r
        return out
    return _nhl_cached_file(NHL_GAME_FEATURES_PATH, build)


def _load_nhl_goalies() -> dict[str, dict]:
    """{normalized name: goalie rating row} from nhl/pipeline.py."""
    return _nhl_cached_file(NHL_GOALIES_PATH, lambda: {
        _norm_name(r["name"]): r for r in pd.read_csv(NHL_GOALIES_PATH).to_dict("records")})


def _nhl_goalie_sv(name: str | None) -> float | None:
    if not name:
        return None
    r = _load_nhl_goalies().get(_norm_name(name))
    return float(r["sv_rating"]) if r else NHL_LEAGUE_SV


def _nhl_team_names() -> dict[str, str]:
    """{ESPN team id: team name}, old franchise ids included."""
    names = {str(r["team_id"]): name for name, r in _load_nhl_state().items()}
    for old, new in NHL_FRANCHISE_IDS.items():
        if new in names:
            names[old] = names[new]
    return names


def _nhl_rest(last_game: str, date: str) -> int:
    import datetime
    if not isinstance(last_game, str) or not last_game:
        return NHL_MAX_REST
    try:
        days = (datetime.date.fromisoformat(date) - datetime.date.fromisoformat(last_game)).days
    except ValueError:
        return NHL_MAX_REST
    return max(1, min(days, NHL_MAX_REST)) if days > 0 else NHL_MAX_REST


def _nhl_state_rows(home: str, away: str, date: str, neutral: bool = False) -> tuple[dict, dict] | None:
    """Feature rows for a game from today's team state."""
    state = _load_nhl_state()
    h, a = state.get(home), state.get(away)
    if h is None or a is None:
        return None
    rh, ra = _nhl_rest(h.get("last_game_date"), date), _nhl_rest(a.get("last_game_date"), date)

    def row(t: dict, o: dict, is_home: int, r_t: int, r_o: int) -> dict:
        return {"home": int(is_home and not neutral), "rest_diff": r_t - r_o, "b2b": int(r_t == 1),
                "opp_b2b": int(r_o == 1), "elo_diff": t["elo"] - o["elo"],
                "margin_ewm_diff": t["margin_ewm"] - o["margin_ewm"],
                "shot_share_diff": t["shot_share"] - o["shot_share"], "sv_pct_diff": t["sv_pct"] - o["sv_pct"],
                "goalie_sv": t["goalie_sv"], "opp_goalie_sv": o["goalie_sv"],
                "goalie_sv_diff": t["goalie_sv"] - o["goalie_sv"], "goalie": t.get("goalie", "")}
    return row(h, a, 1, rh, ra), row(a, h, 0, ra, rh)


def _nhl_pair_prob(row_h: dict, row_a: dict) -> float:
    """P(home wins) from the two mirrored rows, normalized like training."""
    X = pd.DataFrame([row_h, row_a])[NHL_FEATURES]
    p_h, p_a = (float(v) for v in _load_nhl_model().predict_proba(X)[:, 1])
    return p_h / (p_h + p_a)


def _nhl_with_goalies(rows: tuple[dict, dict], home_goalie: str | None, away_goalie: str | None) -> tuple[dict, dict]:
    """The rows with the goalie gap recomputed for the announced starters."""
    h, a = dict(rows[0]), dict(rows[1])
    sv_h = _nhl_goalie_sv(home_goalie) or float(h["goalie_sv"])
    sv_a = _nhl_goalie_sv(away_goalie) or float(a["goalie_sv"])
    h.update(goalie_sv=sv_h, opp_goalie_sv=sv_a, goalie_sv_diff=sv_h - sv_a, goalie=home_goalie or h.get("goalie", ""),
             goalie_probable=int(bool(home_goalie)))
    a.update(goalie_sv=sv_a, opp_goalie_sv=sv_h, goalie_sv_diff=sv_a - sv_h, goalie=away_goalie or a.get("goalie", ""),
             goalie_probable=int(bool(away_goalie)))
    return h, a


def _nhl_pregame(game_id: str, home: str, away: str, date: str, neutral: bool = False,
                 goalies: tuple[str | None, str | None] | None = None) -> tuple[float, str, tuple[dict, dict]] | None:
    """(P(home wins), source, rows): the pipeline's pre-game rows when it has the game
    ("pregame"), otherwise today's team state ("current" — for a finished game that knows
    the result, so the predictions log leaves it out of the record). `goalies` = ESPN's
    probable starters (home, away) for an upcoming game."""
    known = _load_nhl_game_features().get(str(game_id), {})
    if home in known and away in known:
        rows, source = (known[home], known[away]), "pregame"
    else:
        rows = _nhl_state_rows(home, away, date, neutral)
        if rows is None:
            return None
        source = "current"
    if goalies and any(goalies):
        rows = _nhl_with_goalies(rows, *goalies)
        return _nhl_pair_prob(*rows), "pregame", rows
    frozen = _nhl_frozen.get(game_id)
    if frozen and {frozen["home_team"], frozen["away_team"]} == {home, away}:
        # Written down before puck drop (with the announced goalies): that's the pre-game pick
        rows = _nhl_with_goalies(rows, frozen.get("home_goalie"), frozen.get("away_goalie"))
        return frozen["home_win_prob"] / 100, "frozen", rows
    return _nhl_pair_prob(*rows), source, rows


def _nhl_strength(p_home: float) -> float:
    """Log strength gap s that makes the goal model below give the pre-game probability."""
    lo, hi = -2.0, 2.0
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if _nhl_goal_model(mid, p_home, 1.0, 0) < p_home else (lo, mid)
    return (lo + hi) / 2


def _nhl_goal_model(s: float, p_home: float, frac: float, home_margin: int) -> float:
    """P(home wins) with `frac` of regulation left: goals to come are two Poisson processes
    (Skellam difference) with means NHL_GOALS_PER_60·frac·e^(±s); a tie at the end goes to
    overtime / shootout, won with a probability halfway between a coin flip and the pre-game one."""
    import math
    from scipy.stats import skellam
    q = 0.5 + (p_home - 0.5) / 2
    lam = NHL_GOALS_PER_60 * frac
    mu_h, mu_a = lam * math.exp(s), lam * math.exp(-s)
    return float(skellam.sf(-home_margin, mu_h, mu_a) + q * skellam.pmf(-home_margin, mu_h, mu_a))


def _nhl_live_prob(p_home: float, home_margin: int, minutes_left: float, overtime: bool = False,
                   strength: float | None = None) -> float:
    """Win probability during a game (see _nhl_goal_model). `strength`: _nhl_strength(p_home),
    when the caller already has it."""
    if overtime or minutes_left <= 0:
        if home_margin != 0:
            return 1.0 if home_margin > 0 else 0.0
        return 0.5 + (p_home - 0.5) / 2
    s = _nhl_strength(p_home) if strength is None else strength
    p = _nhl_goal_model(s, p_home, min(minutes_left / 60, 1.0), home_margin)
    return min(max(p, 0.001), 0.999)


def _nhl_minutes_left(period: int, clock: str) -> float:
    """Regulation minutes left from the period and the period clock ("12:34")."""
    try:
        mm, ss = (clock or "0:00").split(":")
        in_period = int(mm) + int(ss) / 60
    except ValueError:
        in_period = 0.0
    if period <= 0:
        return 60.0
    if period > 3:
        return 0.0
    return (3 - period) * 20 + in_period


def _nhl_parse_event(ev: dict) -> dict | None:
    """One scoreboard / summary event → our game dict (teams by current name)."""
    import datetime, zoneinfo
    comp = (ev.get("competitions") or [{}])[0]
    sides = {c.get("homeAway"): c for c in comp.get("competitors", [])}
    if "home" not in sides or "away" not in sides:
        return None
    names = _nhl_team_names()
    status = comp.get("status") or ev.get("status") or {}
    st = status.get("type", {})
    state = st.get("state", "pre")

    def side(c: dict) -> dict:
        t = c.get("team", {})
        tid = str(t.get("id"))
        try:
            score = int(c["score"]) if c.get("score") not in (None, "") else None
        except (TypeError, ValueError):
            score = None
        rec = next((r.get("summary") for r in c.get("records", []) or c.get("record", []) or []
                    if r.get("type") == "total" or r.get("name") == "overall"), None)
        probable = next(((x.get("athlete") or {}).get("displayName") for x in c.get("probables", []) or []
                         if x.get("name") == "probableStartingGoalie"), None)
        return {"name": names.get(NHL_FRANCHISE_IDS.get(tid, tid), t.get("displayName", "")),
                "abbr": t.get("abbreviation", ""), "id": tid, "score": score, "record": rec, "probable": probable,
                "logo": t.get("logo") or ((t.get("logos") or [{}])[0].get("href")),
                "color": "#" + (t.get("color") or "555555")}

    start = ev.get("date", "")
    try:
        date = datetime.datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(
            zoneinfo.ZoneInfo("America/New_York")).date().isoformat()
    except ValueError:
        date = ""
    season = ev.get("season") or {}
    return {
        "game_id": str(ev.get("id")), "start_utc": start, "date": date,
        "state": state, "status": {"pre": "Scheduled", "in": "Live", "post": "Final"}.get(state, "Scheduled"),
        "detail": st.get("shortDetail", ""), "period": int(status.get("period") or 0),
        "clock": status.get("displayClock", ""), "neutral": bool(comp.get("neutralSite")),
        "season_type": int(season.get("type") or 2),
        "venue": (comp.get("venue") or {}).get("fullName", ""),
        "home": side(sides["home"]), "away": side(sides["away"]),
    }


def _nhl_with_probs(g: dict) -> dict:
    """Adds our pre-game probabilities (and live ones while the game is on) to a game."""
    home, away = g["home"]["name"], g["away"]["name"]
    goalies = (g["home"].get("probable"), g["away"].get("probable")) if g["state"] == "pre" else None
    pre = _nhl_pregame(g["game_id"], home, away, g["date"], g["neutral"], goalies)
    out = {**g, "home_win_prob": None, "away_win_prob": None, "predicted_winner": None,
           "live_home_prob": None, "live_away_prob": None, "source": None}
    if pre is None:
        return out
    p_home, source, rows = pre
    if g["state"] == "pre" and source != "current":
        _nhl_frozen.record(g["game_id"], {
            "away_team": away, "home_team": home,
            "home_win_prob": round(p_home * 100, 1), "away_win_prob": round((1 - p_home) * 100, 1),
            "predicted_winner": home if p_home >= 0.5 else away, "puck_drop": g["start_utc"],
            "home_goalie": g["home"].get("probable"), "away_goalie": g["away"].get("probable")})
    # Starting goalies the pick used: announced (probable), or the team's last starter
    for side, row in (("home", rows[0]), ("away", rows[1])):
        name = row.get("goalie") if isinstance(row.get("goalie"), str) else ""
        out[side] = {**out[side], "goalie": {
            "name": name, "sv": round(float(row["goalie_sv"]), 3),
            "status": "started" if int(row.get("goalie_confirmed", 0) or 0) == 1 else
                      "probable" if row.get("goalie_probable") else "last start"} if name else None}
    out.update(home_win_prob=round(p_home * 100, 1), away_win_prob=round((1 - p_home) * 100, 1),
               predicted_winner=home if p_home >= 0.5 else away, source=source)
    hs, as_ = g["home"]["score"], g["away"]["score"]
    if g["state"] == "in" and hs is not None and as_ is not None:
        live = _nhl_live_prob(p_home, hs - as_, _nhl_minutes_left(g["period"], g["clock"]), g["period"] > 3)
        out.update(live_home_prob=round(live * 100, 1), live_away_prob=round((1 - live) * 100, 1))
    return out


_nhl_day_cache: dict[str, tuple[float, list[dict]]] = {}
_NHL_DAY_TTL = 20.0


def _nhl_day(date: str) -> list[dict]:
    """Every NHL game of an ET date (YYYY-MM-DD) with our probabilities."""
    hit = _nhl_day_cache.get(date)
    ttl = _NHL_DAY_TTL if date >= _nhl_today() else 3600.0
    if hit and _time_mod.time() - hit[0] < ttl:
        return hit[1]
    data = _espn_json(f"{NHL_BASE}/scoreboard?dates={date.replace('-', '')}&limit=100")
    parsed = [g for g in (_nhl_parse_event(ev) for ev in data.get("events", []))
              if g and g["season_type"] in (2, 3) and "Postponed" not in g["detail"]]
    odds = _fetch_odds_today("icehockey_nhl", [g["start_utc"] for g in parsed if g["state"] == "pre"])
    games = []
    for g in parsed:
        g = _nhl_with_probs(g)
        line = _game_odds_for(odds, g["away"]["name"], g["home"]["name"], g["start_utc"], g["state"] == "post")
        g.update(away_odds=line.get("away_odds"), home_odds=line.get("home_odds"))
        if g["away_win_prob"] is not None:
            g.update(_value_bet(g["away_win_prob"], g["home_win_prob"], g["away_odds"], g["home_odds"]))
        games.append(g)
    games.sort(key=lambda g: (g["start_utc"], g["game_id"]))
    _nhl_day_cache[date] = (_time_mod.time(), games)
    return games


def _nhl_today() -> str:
    import datetime, zoneinfo
    return datetime.datetime.now(zoneinfo.ZoneInfo("America/New_York")).date().isoformat()


@app.get("/api/nhl/today")
def get_nhl_today(date: str | None = None):
    """Today's NHL games (ET) with our pre-game win probabilities, live ones while playing."""
    day = date or _nhl_today()
    try:
        return {"date": day, "games": _nhl_day(day)}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"ESPN scoreboard unavailable: {e}")


def _nhl_explain(row_h: dict, row_a: dict) -> list[dict]:
    """Each feature's push toward the home team (coefficient × standardized difference)."""
    pipe = _load_nhl_model()
    scaler, clf = pipe.named_steps["scaler"], pipe.named_steps["clf"]
    labels = {"elo_diff": "Elo rating", "margin_ewm_diff": "Recent goal differential",
              "shot_share_diff": "Shot share", "sv_pct_diff": "Goaltending (save %)",
              "home": "Home ice", "rest_diff": "Rest", "b2b": "Back-to-back", "goalie_sv_diff": "Starting goalies"}
    impacts: dict[str, float] = {}
    for i, f in enumerate(NHL_FEATURES):
        d = (float(row_h[f]) - float(row_a[f])) / scaler.scale_[i]
        # "b2b" and "opp_b2b" are the same fact seen from each side: one factor
        key = "b2b" if f == "opp_b2b" else f
        impacts[key] = impacts.get(key, 0.0) + float(clf.coef_[0][i]) * d / 2
    out = [{"feature": f, "label": labels[f], "impact": round(v, 4)} for f, v in impacts.items()]
    return sorted(out, key=lambda x: -abs(x["impact"]))


@app.get("/api/nhl/game/{game_id}")
def get_nhl_game(game_id: str):
    """One game: score by period, live / pre-game probabilities, why the model leans the way it
    does, team stats, scoring summary, goalies and top skaters."""
    if not game_id.isdigit():
        raise HTTPException(status_code=404, detail="Unknown game")
    try:
        data = _espn_json(f"{NHL_BASE}/summary?event={game_id}")
    except Exception:
        raise HTTPException(status_code=404, detail="Game not found")
    header = data.get("header", {})
    comp = (header.get("competitions") or [{}])[0]
    ev = {"id": game_id, "date": comp.get("date", ""), "season": header.get("season"),
          "competitions": [{**comp, "venue": (data.get("gameInfo") or {}).get("venue")}]}
    g = _nhl_parse_event(ev)
    if g is None:
        raise HTTPException(status_code=404, detail="Game not found")
    if g["state"] == "pre":
        # The summary doesn't list probable starting goalies; the day's scoreboard does
        try:
            day_game = next((x for x in _nhl_day(g["date"]) if x["game_id"] == game_id), None)
        except Exception:
            day_game = None
        if day_game:
            for side in ("home", "away"):
                g[side]["probable"] = day_game[side].get("probable")
    g = _nhl_with_probs(g)
    home, away = g["home"]["name"], g["away"]["name"]
    pre = _nhl_pregame(game_id, home, away, g["date"], g["neutral"],
                       (g["home"].get("probable"), g["away"].get("probable")) if g["state"] == "pre" else None)

    # Score by period
    lines = {c.get("homeAway"): [int(float(x.get("displayValue") or 0)) for x in c.get("linescores", [])]
             for c in comp.get("competitors", [])}

    # Team stats side by side
    wanted = ["shotsTotal", "powerPlayGoals", "powerPlayOpportunities", "faceoffPercent", "hits",
              "blockedShots", "takeaways", "giveaways", "penaltyMinutes"]
    team_stats: dict[str, dict[str, str]] = {}
    labels: dict[str, str] = {}
    for t in (data.get("boxscore") or {}).get("teams", []):
        tid = str(t.get("team", {}).get("id"))
        side = "home" if tid == g["home"]["id"] else "away"
        for s in t.get("statistics", []):
            if s.get("name") in wanted:
                team_stats.setdefault(s["name"], {})[side] = s.get("displayValue", "")
                labels[s["name"]] = s.get("label", s["name"])
    stats = [{"key": k, "label": labels[k], "away": team_stats[k].get("away", ""), "home": team_stats[k].get("home", "")}
             for k in wanted if k in team_stats]

    # Players: goalies and the skaters who did the most
    goalies, skaters = [], {"home": [], "away": []}
    for team in (data.get("boxscore") or {}).get("players", []):
        tid = str(team.get("team", {}).get("id"))
        side = "home" if tid == g["home"]["id"] else "away"
        for grp in team.get("statistics", []):
            keys = grp.get("keys", [])
            for a in grp.get("athletes", []):
                st = dict(zip(keys, a.get("stats", [])))
                ath = a.get("athlete", {})
                base = {"id": str(ath.get("id")), "name": ath.get("displayName", ""), "side": side,
                        "position": (ath.get("position") or {}).get("abbreviation", ""),
                        "headshot": (ath.get("headshot") or {}).get("href")}
                if grp.get("name") == "goalies":
                    goalies.append({**base, "saves": st.get("saves"), "shots_against": st.get("shotsAgainst"),
                                    "save_pct": st.get("savePct"), "toi": st.get("timeOnIce")})
                else:
                    num = lambda k: int(float(st.get(k) or 0)) if str(st.get(k) or "0").lstrip("-").replace(".", "").isdigit() else 0
                    skaters[side].append({**base, "goals": num("goals"), "assists": num("assists"),
                                          "shots": num("shotsTotal"), "plus_minus": st.get("plusMinus"),
                                          "toi": st.get("timeOnIce"), "hits": num("hits")})
    for side in skaters:
        skaters[side].sort(key=lambda p: (-(p["goals"] + p["assists"]), -p["goals"], -p["shots"]))
        skaters[side] = skaters[side][:6]

    # Scoring summary and the three stars
    team_side = {g["home"]["id"]: "home", g["away"]["id"]: "away"}
    goals = [{"period": (p.get("period") or {}).get("displayValue", ""), "clock": (p.get("clock") or {}).get("displayValue", ""),
              "side": team_side.get(str((p.get("team") or {}).get("id")), ""), "text": p.get("text", ""),
              "strength": (p.get("strength") or {}).get("text", ""),
              "away_score": p.get("awayScore"), "home_score": p.get("homeScore")}
             for p in data.get("plays", []) if p.get("scoringPlay")]
    # Win probability through the game: one point per play (score and clock at that moment),
    # goals marked with the side that scored
    timeline = []
    if pre and g["state"] != "pre":
        p_home = pre[0]
        strength = _nhl_strength(p_home)
        timeline.append({"t": 0.0, "home": round(p_home * 100, 1)})
        prev_margin = 0
        for play in data.get("plays", []):
            period = int((play.get("period") or {}).get("number") or 0)
            try:
                mm, ss = ((play.get("clock") or {}).get("displayValue") or "0:00").split(":")
                in_period = int(mm) + int(ss) / 60
            except ValueError:
                continue
            if period < 1 or play.get("homeScore") is None or play.get("awayScore") is None:
                continue
            t = round((period - 1) * 20 + in_period, 2)
            margin = int(play["homeScore"]) - int(play["awayScore"])
            point = {"t": t, "home": round(_nhl_live_prob(p_home, margin, max(60 - t, 0.0), period > 3, strength) * 100, 1)}
            if play.get("scoringPlay") and margin != prev_margin:
                point["goal"] = "home" if margin > prev_margin else "away"
            prev_margin = margin
            if timeline[-1]["t"] == t and "goal" not in timeline[-1]:
                timeline[-1] = point
            else:
                timeline.append(point)
        if g["state"] == "post" and g["home"]["score"] is not None:
            final = {"t": timeline[-1]["t"], "home": 100.0 if g["home"]["score"] > g["away"]["score"] else 0.0}
            if "goal" in timeline[-1]:
                timeline.append(final)
            else:
                timeline[-1] = final

    stars = [{"label": f.get("displayName", ""), "id": str((f.get("athlete") or {}).get("id", "")),
              "name": (f.get("athlete") or {}).get("displayName", ""),
              "headshot": ((f.get("athlete") or {}).get("headshot") or {}).get("href")}
             for f in comp.get("status", {}).get("featuredAthletes", []) if f.get("name", "").endswith("Star")]

    state = _load_nhl_state()

    def form(team: str) -> dict | None:
        r = state.get(team)
        if r is None:
            return None
        return {"record": f"{r['wins']}-{r['losses']}-{r['otl']}", "points": int(r["points"]),
                "goal_diff": int(r["goal_diff"]), "streak": int(r["win_streak"]), "elo": r["elo"],
                "gf": r["gf_ewm"], "ga": r["ga_ewm"], "shot_share": r["shot_share"], "sv_pct": r["sv_pct"]}

    return {**g, "lines": lines, "stats": stats, "goalies": goalies, "skaters": skaters,
            "goals": goals, "stars": stars, "timeline": timeline,
            "explanation": _nhl_explain(*pre[2]) if pre else [],
            "form": {"home": form(home), "away": form(away)}}


@app.get("/api/nhl/standings")
def get_nhl_standings():
    """Standings by division from the season's results (W-L-OTL, points), with each team's Elo."""
    state = _load_nhl_state()
    divisions: dict[str, list[dict]] = {}
    for name, r in state.items():
        gp = int(r["games_played"])
        divisions.setdefault(r["division"], []).append({
            "team": name, "abbr": r["abbr"], "conference": r["conference"], "gp": gp,
            "w": int(r["wins"]), "l": int(r["losses"]), "otl": int(r["otl"]), "pts": int(r["points"]),
            "pts_pct": round(r["points"] / (2 * gp), 3) if gp else 0.0,
            "goal_diff": int(r["goal_diff"]), "streak": int(r["win_streak"]), "elo": r["elo"]})
    order = ["Atlantic", "Metropolitan", "Central", "Pacific"]
    out = []
    for div in order:
        teams = sorted(divisions.get(div, []), key=lambda t: (-t["pts"], t["gp"], -t["w"], -t["goal_diff"]))
        for i, t in enumerate(teams):
            t["rank"] = i + 1
        out.append({"division": div, "conference": "East" if div in ("Atlantic", "Metropolitan") else "West",
                    "teams": teams})
    elo_rank = sorted(state, key=lambda n: -state[n]["elo"])
    for d in out:
        for t in d["teams"]:
            t["elo_rank"] = elo_rank.index(t["team"]) + 1
    return {"season": _sport_season_label("nhl"), "divisions": out}


NHL_SIMS = 5_000     # enough for ±0.7-point chances; the free server is slow
NHL_OT_RATE = 0.23        # share of regular-season games that reach overtime (loser gets a point)
# Today's ratings overstate the gaps for games weeks away (hot and cold teams cool off), and a
# team's true level is uncertain: future games use the model's log-odds × NHL_FUTURE_SHRINK, and
# each simulated season draws every team a hidden strength offset (log-odds, SD NHL_TEAM_SD)
NHL_FUTURE_SHRINK = 0.5
NHL_TEAM_SD = 0.3
_nhl_proj_cache: tuple[float, dict] | None = None
_NHL_PROJ_TTL = 3600.0


@app.get("/api/nhl/projections")
def get_nhl_projections():
    """Season simulation: the rest of the regular season played NHL_SIMS times with our game
    probabilities (overtime losses give a point), then the playoffs (top 3 of each division +
    2 wild cards per conference, best-of-7 series). Per team: projected points, playoff, division
    and Stanley Cup chances."""
    import numpy as np
    global _nhl_proj_cache
    if _nhl_proj_cache is not None and (_time_mod.time() - _nhl_proj_cache[0] < _NHL_PROJ_TTL
                                        or _serve_stale("nhl_proj", get_nhl_projections)):
        return _nhl_proj_cache[1]

    state = _load_nhl_state()
    teams = sorted(state)
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    rng = np.random.default_rng()

    # Remaining regular-season games, priced with the pipeline's latest rows
    remaining = []
    for gid, rows in _load_nhl_game_features().items():
        if len(rows) != 2:
            continue
        h, a = rows.values()
        if int(h["completed"]) == 0 and int(h["season_type"]) == 2 and h["team"] in idx and a["team"] in idx:
            remaining.append((h, a))
    points = np.tile(np.array([float(state[t]["points"]) for t in teams]), (NHL_SIMS, 1))
    wins = np.tile(np.array([float(state[t]["wins"]) for t in teams]), (NHL_SIMS, 1))
    if remaining:
        X = pd.DataFrame([r for h, a in remaining for r in (h, a)])[NHL_FEATURES]
        probs = _load_nhl_model().predict_proba(X)[:, 1]
        p0 = probs[0::2] / (probs[0::2] + probs[1::2])
        hi = np.array([idx[h["team"]] for h, _ in remaining])
        ai = np.array([idx[a["team"]] for _, a in remaining])
        offset = rng.normal(0.0, NHL_TEAM_SD, (NHL_SIMS, n))
        base = NHL_FUTURE_SHRINK * np.log(p0 / (1 - p0))
        # A few dozen games at a time: sims × all games arrays would not fit the server's memory
        for lo in range(0, len(remaining), 50):
            g_hi, g_ai = hi[lo:lo + 50], ai[lo:lo + 50]
            p_home = 1 / (1 + np.exp(-(base[lo:lo + 50] + offset[:, g_hi] - offset[:, g_ai])))
            # Overtime: a near coin flip (halfway to the pre-game pick); regulation carries the rest
            q = 0.5 + (p_home - 0.5) / 2
            p_reg = np.clip((p_home - NHL_OT_RATE * q) / (1 - NHL_OT_RATE), 0.0, 1.0)
            ot = rng.random(p_home.shape) < NHL_OT_RATE
            home_wins = np.where(ot, rng.random(ot.shape) < q, rng.random(ot.shape) < p_reg)
            # Spread each game's points to its two teams: (sims × games) @ (games × teams)
            # (a team can play twice in a batch; the product adds both)
            k = len(g_hi)
            to_home, to_away = np.zeros((k, n)), np.zeros((k, n))
            to_home[np.arange(k), g_hi] = 1.0
            to_away[np.arange(k), g_ai] = 1.0
            points += np.where(home_wins, 2.0, ot) @ to_home + np.where(home_wins, ot, 2.0) @ to_away
            wins += home_wins @ to_home + (~home_wins) @ to_away

    # Standings order: points, then wins, then a coin toss
    score = points * 1000 + wins + rng.random(points.shape) * 0.5
    division = np.array([state[t]["division"] for t in teams])
    conference = np.array([state[t]["conference"] for t in teams])

    # Game log-odds for every pair (team i at home vs team j), shrunk like future games
    import datetime as _dt
    today = _dt.date.today().isoformat()
    pair_logit = np.zeros((n, n))
    rows_h, rows_a, pairs = [], [], []
    for i, ti in enumerate(teams):
        for j, tj in enumerate(teams):
            if i != j:
                r = _nhl_state_rows(ti, tj, today)
                if r:
                    rows_h.append(r[0]); rows_a.append(r[1]); pairs.append((i, j))
    X = pd.DataFrame(rows_h + rows_a)[NHL_FEATURES]
    pr = _load_nhl_model().predict_proba(X)[:, 1]
    m = len(pairs)
    for k, (i, j) in enumerate(pairs):
        p = pr[k] / (pr[k] + pr[m + k])
        pair_logit[i, j] = NHL_FUTURE_SHRINK * np.log(p / (1 - p))
    home_games = [True, True, False, False, True, False, True]     # 2-2-1-1-1 for the higher seed

    made = np.zeros(n); div_win = np.zeros(n); conf_win = np.zeros(n); cup = np.zeros(n)
    rounds_won = np.zeros((n, 4))

    def play(a: int, b: int, sc: np.ndarray, off: np.ndarray) -> int:
        """A best-of-7, game by game; the higher seed has home ice."""
        hi_, lo = (a, b) if sc[a] >= sc[b] else (b, a)
        edge = off[hi_] - off[lo]
        p_home = 1 / (1 + np.exp(-(pair_logit[hi_, lo] + edge)))
        p_road = 1 / (1 + np.exp(pair_logit[lo, hi_] - edge))
        w = l = 0
        for at_home in home_games:
            if rng.random() < (p_home if at_home else p_road):
                w += 1
            else:
                l += 1
            if w == 4 or l == 4:
                break
        return hi_ if w == 4 else lo

    team_offset = offset if remaining else rng.normal(0.0, NHL_TEAM_SD, (NHL_SIMS, n))
    for sim in range(NHL_SIMS):
        sc, off = score[sim], team_offset[sim]
        champs = []
        for conf in ("East", "West"):
            divs = sorted({d for d, c in zip(division, conference) if c == conf})
            tops, rest = {}, []
            for d in divs:
                members = sorted(np.where(division == d)[0], key=lambda t: -sc[t])
                tops[d] = members[:3]
                rest += members[3:]
                div_win[members[0]] += 1
            wild = sorted(rest, key=lambda t: -sc[t])[:2]
            for t in [x for d in divs for x in tops[d]] + wild:
                made[t] += 1
            # Better division winner plays the 2nd wild card; the other one the 1st
            d1, d2 = sorted(divs, key=lambda d: -sc[tops[d][0]])
            brackets = []
            for d, wc in ((d1, wild[1]), (d2, wild[0])):
                w1 = play(tops[d][0], wc, sc, off)
                w2 = play(tops[d][1], tops[d][2], sc, off)
                rounds_won[w1, 0] += 1; rounds_won[w2, 0] += 1
                dw = play(w1, w2, sc, off)
                rounds_won[dw, 1] += 1
                brackets.append(dw)
            cw = play(brackets[0], brackets[1], sc, off)
            rounds_won[cw, 2] += 1
            conf_win[cw] += 1
            champs.append(cw)
        winner = play(champs[0], champs[1], sc, off)
        cup[winner] += 1

    out = []
    for i, t in enumerate(teams):
        out.append({"team": t, "abbr": state[t]["abbr"], "conference": state[t]["conference"],
                    "division": state[t]["division"], "points": int(state[t]["points"]),
                    "projected_points": round(float(points[:, i].mean()), 1),
                    "playoff_pct": round(100 * made[i] / NHL_SIMS, 1),
                    "division_pct": round(100 * div_win[i] / NHL_SIMS, 1),
                    "second_round_pct": round(100 * rounds_won[i, 0] / NHL_SIMS, 1),
                    "conf_final_pct": round(100 * rounds_won[i, 1] / NHL_SIMS, 1),
                    "final_pct": round(100 * conf_win[i] / NHL_SIMS, 1),
                    "cup_pct": round(100 * cup[i] / NHL_SIMS, 1)})
    out.sort(key=lambda r: -r["projected_points"])
    result = {"simulations": NHL_SIMS, "remaining_games": len(remaining), "teams": out}
    _nhl_proj_cache = (_time_mod.time(), result)
    return result


_nhl_log_cache: tuple[float, list[dict]] | None = None
_NHL_LOG_TTL = 600.0


@app.get("/api/nhl/predictions_log")
def get_nhl_predictions_log(n: int = 500):
    """This season's finished games with our pre-game pick (the pipeline's pre-game rows, plus
    games finished since the last refresh), newest first."""
    import calendar, datetime
    global _nhl_log_cache
    if _nhl_log_cache is not None and (_time_mod.time() - _nhl_log_cache[0] < _NHL_LOG_TTL
                                       or _serve_stale("nhl_log", get_nhl_predictions_log)):
        return {"log": _nhl_log_cache[1][:n]}

    log: dict[str, dict] = {}
    rows = _load_nhl_game_features()
    pending = []
    for gid, teams in rows.items():
        if len(teams) != 2:
            continue
        home, away = teams.values()      # the pipeline writes the home team's row first
        if int(home["completed"]) == 1:
            pending.append((gid, home, away))
    if pending:
        X = pd.DataFrame([r for _, h, a in pending for r in (h, a)])[NHL_FEATURES]
        probs = _load_nhl_model().predict_proba(X)[:, 1]
        for i, (gid, h, a) in enumerate(pending):
            p_home = float(probs[2 * i]) / (float(probs[2 * i]) + float(probs[2 * i + 1]))
            frozen = _nhl_frozen.get(gid)
            source = "pregame"
            if frozen and frozen["home_team"] == h["team"]:
                p_home, source = frozen["home_win_prob"] / 100, "frozen"
            log[gid] = {"game_id": gid, "date": h["game_date"], "home_team": h["team"], "away_team": a["team"],
                        "home_score": int(h["team_score"]), "away_score": int(a["team_score"]),
                        "p_home": p_home, "source": source, "season_type": int(h["season_type"])}

    # Games finished since the pipeline last ran (today, yesterday)
    today = datetime.date.fromisoformat(_nhl_today())
    for back in (0, 1):
        day = (today - datetime.timedelta(days=back)).isoformat()
        try:
            games = _nhl_day(day)
        except Exception:
            continue
        for g in games:
            if g["state"] != "post" or g["game_id"] in log or g["home_win_prob"] is None:
                continue
            if g["home"]["score"] is None or g["away"]["score"] is None:
                continue
            log[g["game_id"]] = {"game_id": g["game_id"], "date": g["date"], "home_team": g["home"]["name"],
                                 "away_team": g["away"]["name"], "home_score": g["home"]["score"],
                                 "away_score": g["away"]["score"], "p_home": g["home_win_prob"] / 100,
                                 "source": g["source"], "season_type": g["season_type"]}

    out = []
    for e in log.values():
        p_home = e["p_home"]
        home_prob, away_prob = round(p_home * 100, 1), round((1 - p_home) * 100, 1)
        predicted = e["home_team"] if p_home >= 0.5 else e["away_team"]
        actual = e["home_team"] if e["home_score"] > e["away_score"] else e["away_team"]
        out.append({"game_id": e["game_id"], "date": e["date"],
                    "month": calendar.month_name[int(e["date"][5:7])],
                    "away_team": e["away_team"], "home_team": e["home_team"],
                    "predicted_winner": predicted, "predicted_prob": max(home_prob, away_prob),
                    "actual_winner": actual, "correct": predicted == actual,
                    "away_score": e["away_score"], "home_score": e["home_score"],
                    "away_win_prob": away_prob, "home_win_prob": home_prob, "source": e["source"],
                    "round": "Playoffs" if e["season_type"] == 3 else "Regular Season"})
    out.sort(key=lambda e: (e["date"], e["game_id"]), reverse=True)
    _nhl_log_cache = (_time_mod.time(), out)
    return {"log": out[:n]}


@app.get("/api/nhl/performance")
def get_nhl_performance():
    return _performance_payload("nhl", get_nhl_predictions_log(n=100_000)["log"])


@app.get("/api/nhl/stats")
def get_nhl_model_stats():
    return _model_stats_payload("nhl", NHL_FEATURES)
