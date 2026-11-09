"""Team pages (all leagues), live-game indicator, and the search bar (teams + player index)."""

import threading as _threading
import time as _time_mod

from fastapi import FastAPI, HTTPException

from api.common import (
    _parallel,
    app,
)
from api.espn import (
    _espn_athlete_id,
    _espn_json,
    _espn_score,
    _norm_name,
    _team_roster,
)
from api.nba import (
    _nba_et_date,
    _nba_game_probs,
    get_nba_projections,
)
from api.nfl import (
    _load_nfl_model,
    _load_nfl_stats,
    _nfl_known_pred,
    _predict_nfl_game,
    get_nfl_power,
    get_nfl_projections,
)
from api.nhl import (
    _load_nhl_state,
    _nhl_pregame,
    get_nhl_projections,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  Team pages (NFL / MLB / NBA) — ESPN data + our model where we have one
# ═══════════════════════════════════════════════════════════════════════════════

_TEAM_LEAGUES = {
    "nfl": {
        "sport": "football", "unit": "pts", "close": 8, "blowout": 17,
        # (ESPN stat category, stat name, label, per_game)
        "stats": [
            ("scoring", "totalPointsPerGame", "Points / game", False),
            ("passing", "yardsPerGame", "Yards / game", False),
            ("passing", "netPassingYardsPerGame", "Pass yards / game", False),
            ("rushing", "rushingYardsPerGame", "Rush yards / game", False),
            ("rushing", "yardsPerRushAttempt", "Yards / carry", False),
            ("miscellaneous", "thirdDownConvPct", "3rd down %", False),
            ("miscellaneous", "redzoneTouchdownPct", "Red zone TD %", False),
            ("miscellaneous", "turnOverDifferential", "Turnover diff.", False),
            ("defensive", "sacks", "Sacks (defense)", False),
            ("defensiveInterceptions", "interceptions", "Interceptions", False),
            ("defensive", "tacklesForLoss", "Tackles for loss", False),
            ("kicking", "fieldGoalPct", "Field goal %", False),
        ],
        "leaders": [("passingYards", "Passing"), ("rushingYards", "Rushing"), ("receivingYards", "Receiving"),
                    ("sacks", "Sacks"), ("totalTackles", "Tackles"), ("interceptions", "Interceptions")],
    },
    "mlb": {
        "sport": "baseball", "unit": "runs", "close": 1, "blowout": 5,
        "stats": [
            ("batting", "avg", "Batting avg", False),
            ("batting", "onBasePct", "On-base %", False),
            ("batting", "OPS", "OPS", False),
            ("batting", "homeRuns", "Home runs", False),
            ("batting", "runs", "Runs scored", False),
            ("batting", "stolenBases", "Stolen bases", False),
            ("pitching", "ERA", "ERA", False),
            ("pitching", "WHIP", "WHIP", False),
            ("pitching", "strikeoutsPerNineInnings", "K / 9", False),
            ("pitching", "saves", "Saves", False),
            ("pitching", "qualityStarts", "Quality starts", False),
            ("fielding", "fieldingPct", "Fielding %", False),
        ],
        "leaders": [("avg", "Batting avg"), ("homeRuns", "Home runs"), ("RBIs", "RBI"), ("OPS", "OPS"),
                    ("ERA", "ERA"), ("wins", "Wins"), ("strikeouts", "Strikeouts"), ("saves", "Saves")],
    },
    "nba": {
        "sport": "basketball", "unit": "pts", "close": 5, "blowout": 15,
        "stats": [
            ("offensive", "fieldGoalPct", "Field goal %", False),
            ("offensive", "threePointPct", "3-point %", False),
            ("offensive", "freeThrowPct", "Free throw %", False),
            ("offensive", "trueShootingPct", "True shooting %", False),
            ("offensive", "threePointFieldGoalsMade", "3-pointers / game", True),
            ("offensive", "assists", "Assists / game", True),
            ("offensive", "offensiveRebounds", "Off. rebounds / game", True),
            ("defensive", "defensiveRebounds", "Def. rebounds / game", True),
            ("defensive", "steals", "Steals / game", True),
            ("defensive", "blocks", "Blocks / game", True),
            ("offensive", "turnovers", "Turnovers / game", True),
            ("offensive", "paceFactor", "Pace", False),
        ],
        "leaders": [("pointsPerGame", "Points"), ("reboundsPerGame", "Rebounds"), ("assistsPerGame", "Assists"),
                    ("stealsPerGame", "Steals"), ("blocksPerGame", "Blocks"), ("3PointMadePerGame", "3-pointers")],
    },
    "nhl": {
        "sport": "hockey", "unit": "goals", "close": 1, "blowout": 3,
        "stats": [
            ("offensive", "avgGoals", "Goals / game", False),
            ("defensive", "avgGoalsAgainst", "Goals against / game", False),
            ("offensive", "avgShots", "Shots / game", False),
            ("defensive", "avgShotsAgainst", "Shots against / game", False),
            ("offensive", "shootingPct", "Shooting %", False),
            ("defensive", "savePct", "Save %", False),
            ("offensive", "powerPlayPct", "Power play %", False),
            ("defensive", "penaltyKillPct", "Penalty kill %", False),
            ("offensive", "faceoffPercent", "Faceoff %", False),
            ("defensive", "hits", "Hits", True),
            ("defensive", "blockedShots", "Blocked shots", True),
            ("defensive", "shutouts", "Shutouts", False),
        ],
        "leaders": [("points", "Points"), ("goals", "Goals"), ("assists", "Assists"), ("plusMinus", "Plus / minus"),
                    ("savePct", "Save %"), ("wins", "Goalie wins")],
    },
}
# Our abbreviations (frontend) → ESPN's
_TEAM_ABBR_ALIASES = {
    "nba": {"gsw": "gs", "nyk": "ny", "nop": "no", "sas": "sa", "uta": "utah", "was": "wsh"},
    "mlb": {"cws": "chw", "oak": "ath"},
    "nfl": {"was": "wsh", "la": "lar"},
}
_team_list_cache: dict[str, list[dict]] = {}
_team_page_cache: dict[tuple[str, str], tuple[float, dict]] = {}
_TEAM_PAGE_TTL = 600.0


def _resolve_espn_team(league: str, key: str) -> dict | None:
    """Match an abbreviation (ours or ESPN's), a slug or a full team name to an ESPN team."""
    sport = _TEAM_LEAGUES[league]["sport"]
    if league not in _team_list_cache:
        data = _espn_json(f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams")
        _team_list_cache[league] = [t["team"] for t in data["sports"][0]["leagues"][0]["teams"]]
    k = key.strip().lower().replace("-", " ")
    k = _TEAM_ABBR_ALIASES.get(league, {}).get(k, k)
    for t in _team_list_cache[league]:
        if k in (t["abbreviation"].lower(), t["displayName"].lower(), t.get("slug", "").replace("-", " "),
                 t.get("shortDisplayName", "").lower(), t.get("name", "").lower()):
            return t
    return None


def _team_schedule(sport: str, league: str, team_id: str, season: int, season_type: int) -> list[dict]:
    try:
        data = _espn_json(f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams/{team_id}"
                          f"/schedule?season={season}&seasontype={season_type}")
    except Exception:
        return []
    games = []
    for ev in data.get("events", []):
        comp = ev.get("competitions", [{}])[0]
        cs = comp.get("competitors", [])
        me  = next((c for c in cs if str(c.get("team", {}).get("id")) == str(team_id)), None)
        opp = next((c for c in cs if c is not me), None)
        if not me or not opp:
            continue
        if int((ev.get("seasonType") or {}).get("type") or season_type) != season_type:
            continue   # ESPN can return other phases' games for a season type
        st = comp.get("status", {}).get("type", {})
        if st.get("name") in ("STATUS_POSTPONED", "STATUS_CANCELED"):
            continue
        ts, os_ = _espn_score(me), _espn_score(opp)
        done = bool(st.get("completed")) and ts is not None and os_ is not None
        games.append({
            "game_id":       ev.get("id"),
            "date":          ev.get("date", ""),
            "season_type":   "post" if season_type == 3 else "reg",
            "label":         (ev.get("week") or {}).get("text", ""),
            "home":          me.get("homeAway") == "home",
            "neutral":       bool(comp.get("neutralSite")),
            "opponent":      opp.get("team", {}).get("displayName", ""),
            "opponent_abbr": opp.get("team", {}).get("abbreviation", ""),
            "team_score":    ts if done else None,
            "opp_score":     os_ if done else None,
            "result":        ("W" if ts > os_ else "L" if ts < os_ else "T") if done else None,
            "completed":     done,
            "status":        st.get("shortDetail") or st.get("description", ""),
        })
    return games


def _record_str(games: list[dict]) -> str:
    w = sum(g["result"] == "W" for g in games)
    l = sum(g["result"] == "L" for g in games)
    t = sum(g["result"] == "T" for g in games)
    return f"{w}-{l}" + (f"-{t}" if t else "")


def _team_facts(games: list[dict], cfg: dict) -> dict:
    """Splits, streaks and notable games from completed regular-season games."""
    done = [g for g in games if g["completed"]]
    if not done:
        return {}
    margins = [g["team_score"] - g["opp_score"] for g in done]
    res = [g["result"] for g in done]

    def longest(r: str) -> int:
        best = cur = 0
        for x in res:
            cur = cur + 1 if x == r else 0
            best = max(best, cur)
        return best

    cur_r, cur_n = res[-1], 0
    for x in reversed(res):
        if x != cur_r:
            break
        cur_n += 1

    close   = [g for g, m in zip(done, margins) if abs(m) <= cfg["close"]]
    blowout = [g for g, m in zip(done, margins) if abs(m) >= cfg["blowout"]]
    after_loss = [done[i] for i in range(1, len(done)) if done[i - 1]["result"] == "L"]
    best  = max(zip(margins, done), key=lambda x: x[0])
    worst = min(zip(margins, done), key=lambda x: x[0])

    def game_ref(m: int, g: dict) -> dict:
        return {"game_id": g["game_id"], "date": g["date"], "opponent": g["opponent"], "home": g["home"],
                "team_score": g["team_score"], "opp_score": g["opp_score"], "margin": m}

    n = len(done)
    facts = {
        "games":               n,
        "record":              _record_str(done),
        "home":                _record_str([g for g in done if g["home"] and not g["neutral"]]),
        "road":                _record_str([g for g in done if not g["home"] and not g["neutral"]]),
        "last10":              _record_str(done[-10:]),
        "streak":              f"{cur_r}{cur_n}",
        "longest_win_streak":  longest("W"),
        "longest_loss_streak": longest("L"),
        "points_for":          round(sum(g["team_score"] for g in done) / n, 1),
        "points_against":      round(sum(g["opp_score"] for g in done) / n, 1),
        "differential":        round(sum(margins) / n, 1),
        "close":               {"record": _record_str(close), "threshold": cfg["close"]},
        "blowouts":            {"record": _record_str(blowout), "threshold": cfg["blowout"]},
        "after_loss":          _record_str(after_loss),
        "best_win":            game_ref(*best) if best[0] > 0 else None,
        "worst_loss":          game_ref(*worst) if worst[0] < 0 else None,
        "unit":                cfg["unit"],
    }
    # Record by month for long seasons
    if len(done) > 30:
        by_month: dict[str, list[dict]] = {}
        for g in done:
            by_month.setdefault(g["date"][:7], []).append(g)
        facts["by_month"] = [{"month": m, "record": _record_str(gs),
                              "differential": round(sum(x["team_score"] - x["opp_score"] for x in gs) / len(gs), 1)}
                             for m, gs in sorted(by_month.items())]
    return facts


def _team_stats(sport: str, league: str, team_id: str, season: int, cfg: dict) -> list[dict]:
    try:
        data = _espn_json(f"https://sports.core.api.espn.com/v2/sports/{sport}/leagues/{league}"
                          f"/seasons/{season}/types/2/teams/{team_id}/statistics")
    except Exception:
        return []
    cats = {c["name"]: {s["name"]: s for s in c.get("stats", [])}
            for c in data.get("splits", {}).get("categories", [])}
    games = None
    for c in cats.values():
        if "gamesPlayed" in c:
            games = c["gamesPlayed"].get("value")
            break
    out = []
    for cat, name, label, per_game in cfg["stats"]:
        s = cats.get(cat, {}).get(name)
        if not s or s.get("value") is None:
            continue
        display = f"{s['value'] / games:.1f}" if per_game and games else s.get("displayValue", "")
        out.append({"label": label, "value": display, "rank": s.get("rank"),
                    "rank_display": s.get("rankDisplayValue")})
    return out


def _team_leaders(sport: str, league: str, team_id: str, season: int, cfg: dict,
                  roster: dict[str, dict]) -> list[dict]:
    try:
        data = _espn_json(f"https://sports.core.api.espn.com/v2/sports/{sport}/leagues/{league}"
                          f"/seasons/{season}/types/2/teams/{team_id}/leaders")
    except Exception:
        return []
    # Names / headshots come from the roster; anyone no longer on it is fetched individually

    cats = {c["name"]: c for c in data.get("categories", [])}
    out = []
    for name, label in cfg["leaders"]:
        c = cats.get(name)
        if not c or not c.get("leaders"):
            continue
        top = c["leaders"][0]
        ref = (top.get("athlete") or {}).get("$ref", "")
        aid = ref.split("/athletes/")[-1].split("?")[0] if "/athletes/" in ref else ""
        ath = roster.get(aid)
        if ath is None and ref:
            try:
                ath = _espn_json(ref)
            except Exception:
                ath = {}
        ath = ath or {}
        out.append({
            "label":    label,
            "id":       aid or _espn_athlete_id(ath),
            "name":     ath.get("displayName", ""),
            "position": (ath.get("position") or {}).get("abbreviation", ""),
            "value":    top.get("displayValue", ""),
            "headshot": (ath.get("headshot") or {}).get("href"),
        })
    return [x for x in out if x["name"]]


def _team_model_block(league: str, team_name: str) -> dict | None:
    """Our model's view of the team (NFL / NBA: power index + season simulation; NHL: season
    simulation)."""
    if league == "nhl":
        try:
            r = next((t for t in get_nhl_projections()["teams"] if t["team"] == team_name), None)
        except Exception:
            return None
        return {k: r[k] for k in ("projected_points", "playoff_pct", "division_pct", "final_pct", "cup_pct")} if r else None
    if league == "nba":
        try:
            r = next((t for t in get_nba_projections()["teams"] if t["team"] == team_name), None)
        except Exception:
            return None
        return {k: r[k] for k in ("power", "power_rank", "off_rank", "def_rank", "roster_rank", "sos_rank", "rem_sos_rank",
                                  "projected_wins", "playoff_pct", "top6_pct", "top_seed_pct",
                                  "conf_pct", "title_pct")} if r else None
    if league != "nfl":
        return None
    out: dict = {}
    try:
        p = next((t for t in get_nfl_power()["teams"] if t["team"] == team_name), None)
        if p:
            out.update({"power": p["power"], "power_rank": p["rank"], "trend": p["trend"],
                        "off_rank": p.get("off_epa_rank"), "def_rank": p.get("def_epa_rank"),
                        "qb_name": p.get("qb_name"), "qb_rank": p.get("qb_rank"),
                        "sos_rank": p.get("sos_rank"), "rem_sos_rank": p.get("rem_sos_rank")})
    except Exception:
        pass
    try:
        pr = next((t for t in get_nfl_projections()["teams"] if t["team"] == team_name), None)
        if pr:
            out.update({k: pr[k] for k in ("projected_wins", "playoff_pct", "division_pct",
                                           "top_seed_pct", "conf_pct", "sb_win_pct")})
    except Exception:
        pass
    return out or None


def _team_next_game_prob(league: str, game: dict, team_name: str) -> float | None:
    """Our pre-game win probability for the team's next game, when we can produce one."""
    if league == "nhl":
        try:
            home, away = (team_name, game["opponent"]) if game["home"] else (game["opponent"], team_name)
            pre = _nhl_pregame(game["game_id"], home, away, _nba_et_date(game["date"]))
            return None if pre is None else round((pre[0] if game["home"] else 1 - pre[0]) * 100, 1)
        except Exception:
            return None
    if league == "nba":
        try:
            return _nba_game_probs(team_name, [{**game, "completed": False}])[0]
        except Exception:
            return None
    if league != "nfl":
        return None
    try:
        cached = _nfl_known_pred(game["game_id"])
        if cached:
            away_wp, home_wp = cached["away_win_prob"], cached["home_win_prob"]
        else:
            away, home = (game["opponent"], team_name) if game["home"] else (team_name, game["opponent"])
            pred = _predict_nfl_game(_load_nfl_model(), _load_nfl_stats(), away, home, game["game_id"])
            if not pred:
                return None
            away_wp, home_wp = pred[0], pred[1]
        return home_wp if game["home"] else away_wp
    except Exception:
        return None


_search_cache: dict[str, tuple[float, dict]] = {}
_SEARCH_TTL = 600.0
_SEARCH_LEAGUES = ("nba", "nfl", "mlb", "nhl")


def _search_teams(q: str) -> list[dict]:
    """Teams of the three leagues whose name, nickname, city or abbreviation matches."""
    for league in _SEARCH_LEAGUES:
        if league not in _team_list_cache:
            _resolve_espn_team(league, "")   # fills the league's team list
    hits = []
    for league in _SEARCH_LEAGUES:
        for t in _team_list_cache.get(league, []):
            names = [t["displayName"], t.get("name", ""), t.get("location", ""), t.get("shortDisplayName", "")]
            words = [w.lower() for n in names for w in n.split()]
            # Best first: exact abbreviation, then a word starting with the query, then anywhere
            if q == t["abbreviation"].lower():
                rank = 0
            elif any(w.startswith(q) for w in words) or t["displayName"].lower().startswith(q):
                rank = 1
            elif len(q) >= 3 and q in t["displayName"].lower():
                rank = 2
            else:
                continue
            logos = t.get("logos") or []
            hits.append((rank, {"type": "team", "league": league, "id": t["id"], "name": t["displayName"],
                                "abbr": t["abbreviation"], "logo": logos[0]["href"] if logos else None}))
    return [h for _, h in sorted(hits, key=lambda h: (h[0], h[1]["name"]))]


def _search_players(q: str, league: str) -> list[dict]:
    """Active players of one league from ESPN's search, most relevant first."""
    import urllib.parse
    sport = _TEAM_LEAGUES[league]["sport"]
    url = ("https://site.web.api.espn.com/apis/common/v3/search?type=player&limit=6"
           f"&sport={sport}&league={league}&query={urllib.parse.quote(q)}")
    out = []
    for it in _espn_json(url, timeout=8).get("items", []):
        pos = it.get("position")
        pos = pos.get("abbreviation") if isinstance(pos, dict) else pos
        # Skip inactive players and ESPN's placeholder entries (position "UN")
        if it.get("league") != league or it.get("isActive") is False or pos == "UN":
            continue
        team = ((it.get("teamRelationships") or [{}])[0].get("core") or {})
        head = it.get("headshot")
        out.append({"type": "player", "league": league, "id": str(it["id"]), "name": it.get("displayName", ""),
                    "team": team.get("abbreviation"), "team_name": team.get("displayName"),
                    "position": pos,
                    "headshot": head.get("href") if isinstance(head, dict) else head,
                    "relevance": float(it.get("relevance") or 0)})
    return out


_live_now_cache: tuple[float, dict] | None = None
_LIVE_NOW_TTL = 30.0


@app.get("/api/live_now")
def get_live_now():
    """Which leagues have a game in progress right now (red dot next to the sport in the header)."""
    global _live_now_cache
    if _live_now_cache and _time_mod.time() - _live_now_cache[0] < _LIVE_NOW_TTL:
        return _live_now_cache[1]

    def live(league: str) -> bool:
        sport = _TEAM_LEAGUES[league]["sport"]
        try:
            data = _espn_json(f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard", timeout=8)
        except Exception:
            return False
        return any(((e.get("status") or {}).get("type") or {}).get("state") == "in" for e in data.get("events", []))

    result = dict(zip(_SEARCH_LEAGUES, _parallel(*(lambda lg=lg: live(lg) for lg in _SEARCH_LEAGUES))))
    _live_now_cache = (_time_mod.time(), result)
    return result


# ── Player index: every rostered player of the four leagues, for fuzzy search ──

_player_index: list[dict] | None = None
_player_index_time: float = 0.0
_PLAYER_INDEX_TTL = 12 * 3600.0
_player_index_lock = _threading.Lock()


def _league_stars(league: str) -> dict[str, float]:
    """{athlete id: star score}: how high a player sits in the league's stat leaderboards
    (top 50 of each category, this season or the last one)."""
    import datetime, re
    sport = _TEAM_LEAGUES[league]["sport"]
    year = datetime.date.today().year
    for season in (year + 1, year, year - 1):
        try:
            data = _espn_json(f"https://sports.core.api.espn.com/v2/sports/{sport}/leagues/{league}"
                              f"/seasons/{season}/types/2/leaders?limit=50")
        except Exception:
            continue
        stars: dict[str, float] = {}
        for cat in data.get("categories", []):
            for rank, entry in enumerate(cat.get("leaders", [])):
                m = re.search(r"/athletes/(\d+)", (entry.get("athlete") or {}).get("$ref", ""))
                if m:
                    stars[m.group(1)] = stars.get(m.group(1), 0.0) + (50 - rank) / 50
        if stars:
            return stars
    return {}


def _build_player_index() -> list[dict]:
    from concurrent.futures import ThreadPoolExecutor
    for league in _SEARCH_LEAGUES:
        if league not in _team_list_cache:
            _resolve_espn_team(league, "")   # fills the league's team list
    jobs = [(league, t) for league in _SEARCH_LEAGUES for t in _team_list_cache.get(league, [])]
    with ThreadPoolExecutor(max_workers=16) as pool:
        rosters = list(pool.map(lambda j: _team_roster(_TEAM_LEAGUES[j[0]]["sport"], j[0], j[1]["id"])[0], jobs))
        stars = dict(zip(_SEARCH_LEAGUES, pool.map(_league_stars, _SEARCH_LEAGUES)))
    index = []
    for (league, team), groups in zip(jobs, rosters):
        for g in groups:
            for pl in g["players"]:
                norm = _norm_name(pl["name"])
                if not norm:
                    continue
                index.append({"league": league, "id": pl["id"], "name": pl["name"], "norm": norm,
                              "tokens": norm.split(), "team": team["abbreviation"], "team_name": team["displayName"],
                              "position": pl["position"] or None, "headshot": pl["headshot"],
                              "star": stars[league].get(pl["id"], 0.0)})
    return index


def _get_player_index() -> list[dict] | None:
    """The index if built (rebuilt in the background every 12 h); None until the first build ends."""
    global _player_index, _player_index_time

    def build():
        global _player_index, _player_index_time
        try:
            index = _build_player_index()
            if index:
                _player_index, _player_index_time = index, _time_mod.time()
        finally:
            _player_index_lock.release()

    stale = _player_index is None or _time_mod.time() - _player_index_time > _PLAYER_INDEX_TTL
    if stale and _player_index_lock.acquire(blocking=False):
        _threading.Thread(target=build, daemon=True).start()
    return _player_index


def _token_score(q: str, name_tokens: list[str]) -> float:
    """How well one query word matches a name: 3 whole word, 2 start of a word, up to 1 for a
    close spelling (typos), 0 for no match."""
    from difflib import SequenceMatcher
    best = 0.0
    for t in name_tokens:
        if t == q:
            return 3.0
        if t.startswith(q):
            best = max(best, 2.0)
        elif len(q) >= 4:
            # Compare with the word cut to about the typed length, so "jamar" ~ "jamarr", "mahomse" ~ "mahomes"
            r = SequenceMatcher(None, q, t[:len(q) + 1]).ratio()
            if r >= 0.75:
                best = max(best, r)
    return best


def _search_index(q: str, index: list[dict]) -> list[dict]:
    words = _norm_name(q).split()
    if not words:
        return []
    scored = []
    for pl in index:
        total = 0.0
        for w in words:
            sc = _token_score(w, pl["tokens"])
            if sc == 0:
                break
            total += sc
        else:
            # "first last" is the usual order when both are typed; stars break ties between similar names
            if len(words) > 1 and _token_score(words[0], pl["tokens"][:1]) >= 2:
                total += 0.5
            # Star bonus up to 1.5: enough to lift Ja'Marr Chase above other "Jamar…" names,
            # not enough to beat a real match with a typo-level one
            scored.append((total + min(pl["star"], 4.0) / 4 * 1.5, pl))
    scored.sort(key=lambda x: -x[0])
    return [{"type": "player", **{k: pl[k] for k in ("league", "id", "name", "team", "team_name", "position", "headshot")}}
            for _, pl in scored[:8]]


@app.get("/api/search")
def search(q: str = ""):
    """Teams and players (NBA, NFL, MLB) matching a name, for the search bar."""
    q = " ".join(q.lower().split())[:40]
    if len(q) < 2:
        return {"query": q, "teams": [], "players": []}
    hit = _search_cache.get(q)
    if hit and _time_mod.time() - hit[0] < _SEARCH_TTL:
        return hit[1]

    index = _get_player_index()
    if index:
        teams, found = _search_teams(q), _search_index(q, index)
    else:
        # Index still building (just after a restart): ESPN's own player search
        def players(league: str) -> list[dict]:
            try:
                return _search_players(q, league)
            except Exception:
                return []

        teams, *by_league = _parallel(lambda: _search_teams(q), *(lambda lg=lg: players(lg) for lg in _SEARCH_LEAGUES))
        found = [p for lst in by_league for p in lst][:8]
        for p in found:
            p.pop("relevance", None)
    result = {"query": q, "teams": teams[:5], "players": found}
    if index:
        if len(_search_cache) > 500:
            _search_cache.clear()
        _search_cache[q] = (_time_mod.time(), result)
    return result


@app.get("/api/team/{league}/{team}")
def get_team_page(league: str, team: str):
    """Everything for a team page: record, schedule, key stats with league ranks,
    player leaders, splits / notable facts and (NFL) our model's projections."""
    import datetime
    league = league.lower()
    if league not in _TEAM_LEAGUES:
        raise HTTPException(status_code=404, detail=f"Unknown league: {league}")
    cfg = _TEAM_LEAGUES[league]
    sport = cfg["sport"]

    t = _resolve_espn_team(league, team)
    if t is None:
        raise HTTPException(status_code=404, detail=f"Team not found: {team}")
    key = (league, t["id"])
    hit = _team_page_cache.get(key)
    if hit and _time_mod.time() - hit[0] < _TEAM_PAGE_TTL:
        return hit[1]

    tid = t["id"]
    base = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams/{tid}"
    info, sched, (roster_groups, roster_by_id) = _parallel(
        lambda: _espn_json(base).get("team", {}),
        lambda: _espn_json(f"{base}/schedule"),
        lambda: _team_roster(sport, league, tid))
    cur = sched.get("season") or {}
    cur_year = int(cur.get("year") or datetime.date.today().year)

    # Use the latest season with completed regular-season games (e.g. NBA preseason → last season)
    season = cur_year
    cur_reg, post = _parallel(lambda: _team_schedule(sport, league, tid, season, 2),
                              lambda: _team_schedule(sport, league, tid, season, 3))
    games = cur_reg
    if not any(g["completed"] for g in games):
        prev, prev_post = _parallel(lambda: _team_schedule(sport, league, tid, season - 1, 2),
                                    lambda: _team_schedule(sport, league, tid, season - 1, 3))
        if any(g["completed"] for g in prev):
            season, games, post = season - 1, prev, prev_post
    if league == "nhl":
        for lst in (games, post):
            for g in lst:
                g["win_prob"] = _team_next_game_prob(league, g, t["displayName"])
    if league == "nba":
        # Every NBA game gets our probability: the NBA game page is built from it
        for lst in (games, post):
            try:
                for g, p in zip(lst, _nba_game_probs(t["displayName"], lst)):
                    g["win_prob"] = p
            except Exception:
                pass

    soon =(datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M")
    upcoming = sorted((g for g in cur_reg + post if not g["completed"] and g["date"] >= soon),
                      key=lambda g: g["date"])
    next_game = upcoming[0] if upcoming else None
    if next_game:
        next_game = {**next_game, "win_prob": _team_next_game_prob(league, next_game, t["displayName"])}

    stats, leaders, model_block = _parallel(
        lambda: _team_stats(sport, league, tid, season, cfg),
        lambda: _team_leaders(sport, league, tid, season, cfg, roster_by_id),
        lambda: _team_model_block(league, t["displayName"]))
    logos = info.get("logos") or t.get("logos") or []
    record = ({i.get("type"): i.get("summary") for i in (info.get("record") or {}).get("items", [])}
              if season == cur_year else {})
    if not record.get("total") or record.get("total") == "0-0":
        record = {"total": _record_str([g for g in games if g["completed"]])}
    if league == "nhl" and season == cur_year:
        # Wins-losses-overtime losses, from the season's results
        st = _load_nhl_state().get(t["displayName"])
        if st is not None and st["games_played"]:
            record = {**record, "total": f"{st['wins']}-{st['losses']}-{st['otl']}"}

    result = {
        "league": league,
        "team": {
            "id": tid, "abbr": t["abbreviation"], "name": t["displayName"],
            "nickname": t.get("name") or t.get("shortDisplayName"), "location": t.get("location", ""),
            "color": "#" + (info.get("color") or t.get("color") or "555555"),
            "alt_color": "#" + (info.get("alternateColor") or t.get("alternateColor") or "999999"),
            "logo": logos[0]["href"] if logos else None,
            "standing": info.get("standingSummary", "") if season == cur_year else "",
        },
        "season": {"year": season, "is_current": season == cur_year,
                   "label": f"{season - 1}-{str(season)[-2:]}" if league in ("nba", "nhl") else str(season)},
        "record": record,
        "next_game": next_game,
        "facts": _team_facts(games, cfg),
        "stats": stats,
        # ESPN ranks NBA team stats within the division, other leagues league-wide
        "stats_rank_scope": "division" if league == "nba" else "league",
        "leaders": leaders,
        "roster": roster_groups,
        "model": model_block,
        "games": games,
        "postseason": post,
    }
    _team_page_cache[key] = (_time_mod.time(), result)
    return result
