"""Today across every sport: each league's games of the day in one shape, for the home page
(live first, the most confident picks, value picks, then upcoming and finished games)."""
import datetime
import urllib.parse
import zoneinfo

from api.common import _game_day, _parallel, app
from api.mlb import get_mlb_today
from api.nba import get_today_games
from api.nfl import get_nfl_week
from api.nhl import get_nhl_today
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
    }


def _nba(today: str) -> list[dict]:
    out = []
    for g in get_today_games()["games"]:
        state = {"Live": "in", "Final": "post"}.get(g["status"], "pre")
        q = {"away": g["away_team"], "home": g["home_team"], "time": g["status_text"], "status": g["status"],
             "away_prob": g["away_win_prob"], "home_prob": g["home_win_prob"], "winner": g["predicted_winner"],
             "away_score": g["away_score"] if g["away_score"] is not None else "",
             "home_score": g["home_score"] if g["home_score"] is not None else ""}
        out.append(_game("nba", g["game_id"], state, g.get("start_utc", ""), g["status_text"],
                         _team("nba", g["away_team"], g["away_score"]), _team("nba", g["home_team"], g["home_score"]),
                         g, f"/game/{g['game_id']}?{urllib.parse.urlencode(q)}", g.get("live_away_prob")))
    return out


def _nhl(today: str) -> list[dict]:
    out = []
    for g in get_nhl_today()["games"]:
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


def _mlb(today: str) -> list[dict]:
    out = []
    for g in get_mlb_today()["games"]:
        status = g["status"]
        state = "post" if status in ("Final", "Game Over", "Completed") else "in" if status in ("In Progress", "Live") else "pre"
        q = {"away": g["away_team"], "home": g["home_team"], "status": status}
        out.append(_game("mlb", g["game_id"], state, g.get("game_time_utc", ""), status,
                         _team("mlb", g["away_team"], g.get("away_score")), _team("mlb", g["home_team"], g.get("home_score")),
                         g, f"/mlb/game/{g['game_id']}?{urllib.parse.urlencode(q)}"))
    return out


@app.get("/api/today_all")
def get_today_all():
    """Every league's games on today's game day (ET, turning over at 5 am), in one shape.
    A league that fails to answer is left out rather than failing the page."""
    today = _game_day().isoformat()

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
