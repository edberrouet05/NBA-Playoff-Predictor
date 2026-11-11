"""Today across every sport: each league's games of the day in one shape, for the home page
(live first, the most confident picks, value picks, then upcoming and finished games)."""
import datetime
import urllib.parse
import zoneinfo

import time

from api.common import _game_day, _parallel, app
from api.mlb import get_mlb_predictions_log, get_mlb_today
from api.nba import _fetch_day, _load_model, _load_stats_by_name, get_predictions_log, get_today_games
from api.nfl import get_nfl_predictions_log, get_nfl_week
from api.nhl import get_nhl_predictions_log, get_nhl_today
from api.teams import _resolve_espn_team

_ET = zoneinfo.ZoneInfo("America/New_York")


def _team(league: str, name: str, score) -> dict:
    """Name, abbreviation and logo from ESPN's team list (cached), and the score."""
    try:
        t = _resolve_espn_team(league, name) or {}
    except Exception:
        t = {}
    logos = t.get("logos") or []
    return {"name": name, "abbr": t.get("abbreviation") or name.split()[-1][:3].upper(),
            "logo": logos[0]["href"] if logos else None, "score": score}


def _game(sport: str, game_id, state: str, start_utc: str, status_text: str, away: dict, home: dict,
          g: dict, href: str, live_away=None) -> dict:
    return {
        "sport": sport, "game_id": str(game_id), "href": href, "state": state,
        "start_utc": start_utc, "status_text": status_text, "away": away, "home": home,
        "away_prob": g.get("away_win_prob"), "home_prob": g.get("home_win_prob"),
        "live_away_prob": live_away, "predicted_winner": g.get("predicted_winner"),
        "away_odds": g.get("away_odds"), "home_odds": g.get("home_odds"),
        "value_side": g.get("value_side"), "value_edge": g.get("value_edge"),
        "value_ev": g.get("value_ev"), "value_underdog": g.get("value_underdog"),
    }


def _nba(day: str) -> list[dict]:
    out = []
    if day == _game_day().isoformat():
        games = get_today_games()["games"]
    else:
        y, m, d = day.split("-")
        games = _fetch_day(f"{m}/{d}/{y}", _load_model(), _load_stats_by_name())["games"]
    for g in games:
        state = {"Live": "in", "Final": "post"}.get(g["status"], "pre")
        q = {"away": g["away_team"], "home": g["home_team"], "time": g["status_text"], "status": g["status"],
             "away_prob": g["away_win_prob"], "home_prob": g["home_win_prob"], "winner": g["predicted_winner"],
             "away_score": g["away_score"] if g["away_score"] is not None else "",
             "home_score": g["home_score"] if g["home_score"] is not None else ""}
        out.append(_game("nba", g["game_id"], state, g.get("start_utc", ""), g["status_text"],
                         _team("nba", g["away_team"], g["away_score"]), _team("nba", g["home_team"], g["home_score"]),
                         g, f"/game/{g['game_id']}?{urllib.parse.urlencode(q)}", g.get("live_away_prob")))
    return out


def _nhl(day: str) -> list[dict]:
    out = []
    for g in get_nhl_today(date=day)["games"]:
        a, h = g["away"], g["home"]
        out.append(_game("nhl", g["game_id"], g["state"], g["start_utc"], g["detail"],
                         {"name": a["name"], "abbr": a["abbr"], "logo": a.get("logo"), "score": a.get("score")},
                         {"name": h["name"], "abbr": h["abbr"], "logo": h.get("logo"), "score": h.get("score")},
                         g, f"/nhl/game/{g['game_id']}", g.get("live_away_prob")))
    return out


def _nfl(today: str) -> list[dict]:
    out = []
    for g in get_nfl_week()["games"]:
        start = g.get("game_time_utc") or ""
        try:
            day = datetime.datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(_ET).date().isoformat()
        except ValueError:
            continue
        if day != today:
            continue
        q = {"away": g["away_team"], "home": g["home_team"], "status": g["status"],
             "away_prob": g["away_win_prob"], "home_prob": g["home_win_prob"], "winner": g["predicted_winner"],
             "away_score": g["away_score"] if g["away_score"] is not None else "",
             "home_score": g["home_score"] if g["home_score"] is not None else ""}
        out.append(_game("nfl", g["game_id"], g.get("status_state", "pre"), start, g["status"],
                         _team("nfl", g["away_team"], g["away_score"]), _team("nfl", g["home_team"], g["home_score"]),
                         g, f"/nfl/game/{g['game_id']}?{urllib.parse.urlencode(q)}"))
    return out


def _mlb(day: str) -> list[dict]:
    out = []
    if day != _game_day().isoformat():   # the MLB feed here covers today only
        return out
    for g in get_mlb_today()["games"]:
        status = g["status"]
        state = "post" if status in ("Final", "Game Over", "Completed") else "in" if status in ("In Progress", "Live") else "pre"
        q = {"away": g["away_team"], "home": g["home_team"], "status": status}
        out.append(_game("mlb", g["game_id"], state, g.get("game_time_utc", ""), status,
                         _team("mlb", g["away_team"], g.get("away_score")), _team("mlb", g["home_team"], g.get("home_score")),
                         g, f"/mlb/game/{g['game_id']}?{urllib.parse.urlencode(q)}"))
    return out


@app.get("/api/today_all")
def get_today_all(day: str = "today"):
    """Every league's games on today's game day (ET, turning over at 5 am), in one shape; with
    day=tomorrow, the next day's (the home page shows their picks once today's have all started).
    A league that fails to answer is left out rather than failing the page."""
    today = (_game_day() + datetime.timedelta(days=1 if day == "tomorrow" else 0)).isoformat()

    def safe(fn):
        def run():
            try:
                return fn(today)
            except Exception:
                return []
        return run

    leagues = _parallel(safe(_nba), safe(_nhl), safe(_nfl), safe(_mlb))
    games = [g for league in leagues for g in league]
    games.sort(key=lambda g: (g["start_utc"] or "9999", g["sport"]))
    return {"date": today, "games": games}


SUMMARY_DAYS = 14
SURE_PICK = 70          # "when we are very sure": picks at this probability or more
_SUMMARY_TTL = 300.0    # results change only as games end
_summary_cache: tuple[float, dict] | None = None


@app.get("/api/home_summary")
def get_home_summary():
    """Our record for the home page, every sport together: day by day over the last two weeks,
    yesterday, and the season by sport. Fair picks only, as on the Record pages (frozen before the
    game or from pre-game rows, never recomputed after it)."""
    global _summary_cache
    if _summary_cache and time.time() - _summary_cache[0] < _SUMMARY_TTL:
        return _summary_cache[1]
    today = _game_day()
    since = (today - datetime.timedelta(days=SUMMARY_DAYS - 1)).isoformat()
    yesterday = (today - datetime.timedelta(days=1)).isoformat()

    def log(fn, **kw):
        def run():
            try:
                return [g for g in fn(**kw)["log"] if g.get("source", "pregame") != "current"]
            except Exception:
                return []
        return run

    logs = dict(zip(("nba", "nfl", "nhl", "mlb"), _parallel(
        log(get_predictions_log, n=100_000), log(get_nfl_predictions_log, n=100_000),
        log(get_nhl_predictions_log, n=100_000), log(get_mlb_predictions_log, n=100_000))))

    days = {(today - datetime.timedelta(days=i)).isoformat(): {"correct": 0, "n": 0, "by_sport": {}}
            for i in range(SUMMARY_DAYS)}
    sports = []
    for sport, games in logs.items():
        if not games:
            continue
        recent = [g for g in games if g["date"] >= since]
        # In season: a pick in the last two weeks (the MLB after the World Series is not)
        sure = [g for g in games if g["predicted_prob"] >= SURE_PICK]
        sports.append({"sport": sport, "n": len(games), "correct": sum(bool(g["correct"]) for g in games),
                       "in_season": bool(recent),
                       # Picks we gave SURE_PICK% or more, and how they did
                       "sure": {"n": len(sure), "correct": sum(bool(g["correct"]) for g in sure)}})
        for g in recent:
            d = days.get(g["date"])
            if d is None:
                continue
            ok = int(bool(g["correct"]))
            d["correct"] += ok
            d["n"] += 1
            s = d["by_sport"].setdefault(sport, {"correct": 0, "n": 0})
            s["correct"] += ok
            s["n"] += 1
    for s in sports:
        s["accuracy"] = round(s["correct"] / s["n"] * 100, 1)

    # Yesterday's games: our surest hit and our biggest miss (highest-confidence wrong pick)
    def brief(sport: str, g: dict) -> dict:
        return {"sport": sport, "game_id": str(g["game_id"]), "pick": g["predicted_winner"],
                "prob": g["predicted_prob"], "correct": bool(g["correct"]),
                "away_team": g["away_team"], "home_team": g["home_team"],
                "away_score": g.get("away_score"), "home_score": g.get("home_score")}
    played = [(s, g) for s, games in logs.items() for g in games if g["date"] == yesterday]
    hits = sorted((x for x in played if x[1]["correct"]), key=lambda x: -x[1]["predicted_prob"])
    misses = sorted((x for x in played if not x[1]["correct"]), key=lambda x: -x[1]["predicted_prob"])
    by_sport_yday = {}
    for s, g in played:
        r = by_sport_yday.setdefault(s, {"correct": 0, "n": 0})
        r["correct"] += int(bool(g["correct"]))
        r["n"] += 1

    result = {
        "today": today.isoformat(),
        "days": [{"date": d, **v} for d, v in sorted(days.items())],
        "yesterday": {"date": yesterday, **{k: days[yesterday][k] for k in ("correct", "n")},
                      "by_sport": by_sport_yday,
                      "best": [brief(s, g) for s, g in hits[:2]],
                      "misses": [brief(s, g) for s, g in misses[:2]]},
        "sure_pick": SURE_PICK,
        "sports": sports,
    }
    _summary_cache = (time.time(), result)
    return result
