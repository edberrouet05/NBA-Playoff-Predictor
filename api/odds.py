"""Betting odds (The Odds API): today's lines, stored pre-game lines, value bets."""

import time as _time_mod

from api.common import (
    ODDS_API_KEY,
    ROOT,
    app,
)


# ═══════════════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════════
#  Betting odds (The Odds API — Bet365)
# ═══════════════════════════════════════════════════════════════════════════════

_odds_cache:      dict[str, dict] = {}
_odds_cache_time: dict[str, float] = {}
# The Odds API free plan is 500 credits / month and each call costs one credit per region,
# so: one region, refresh every 2 h — every 15 min once a game is within the hour (closing
# line) — never call for a sport with no game left to start, and back off when nearly out.
_ODDS_TTL = 2 * 3600.0
_ODDS_TTL_NEAR_START = 15 * 60.0
_ODDS_NEAR_START = 3600.0
_ODDS_REGIONS = "eu"            # includes Pinnacle, the sharpest book in _BOOKMAKER_PRIORITY
_ODDS_MIN_REMAINING = 5         # credits kept in reserve; below this, pause until the pause ends
_ODDS_PAUSE = 6 * 3600.0
_odds_paused_until: float = 0.0

_PREGAME_ODDS_FILE = ROOT / "data" / "pregame_odds.json"


def _load_pregame_odds() -> dict[str, dict]:
    import json as _json
    try:
        return _json.loads(_PREGAME_ODDS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _merge_pregame_odds(into: dict[str, dict], other: dict[str, dict]) -> None:
    """Add `other`'s lines to `into`; for a game in both, the later save (closer to the start) wins.
    Keys without a date are from the old format, which mixed up the games of a series: dropped."""
    for key, entry in other.items():
        if key.count("|") != 2:
            continue
        mine = into.get(key)
        if not mine or entry.get("saved_at", "") > mine.get("saved_at", ""):
            into[key] = entry


def _save_pregame_odds(data: dict) -> None:
    """Write the stored lines, first merging in whatever is on disk (seed, pulled commit…)."""
    import json as _json
    try:
        _merge_pregame_odds(data, _load_pregame_odds())
        for key in [k for k in data if k.count("|") != 2]:
            del data[key]
        _PREGAME_ODDS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _PREGAME_ODDS_FILE.write_text(_json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    except Exception:
        pass


_pregame_odds: dict[str, dict] = {}
_merge_pregame_odds(_pregame_odds, _load_pregame_odds())


@app.get("/api/pregame_odds")
def get_pregame_odds() -> dict[str, dict]:
    """Every stored pre-game line (read by the workflows so a redeploy loses none)."""
    _merge_pregame_odds(_pregame_odds, _load_pregame_odds())
    return _pregame_odds


# Odds API names that differ from ESPN's beyond accents and periods
_ODDS_TEAM_ALIASES = {"utah hockey club": "utah mammoth"}


def _normalize_team(name: str) -> str:
    """Team name as a key shared by ESPN and the Odds API: lowercase, no accents, no periods
    ('Montréal Canadiens' = 'Montreal Canadiens', 'St Louis Blues' = 'St. Louis Blues')."""
    import unicodedata
    n = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower().replace(".", "")
    n = " ".join(n.split())
    return _ODDS_TEAM_ALIASES.get(n, n)


_BOOKMAKER_PRIORITY = [
    "pinnacle", "draftkings", "fanduel", "betmgm", "williamhill",
    "betrivers", "bovada", "unibet_us", "unibet_uk", "paddypower",
    "coral", "ladbrokes_uk", "betway", "marathonbet", "betsson",
]


def _fetch_odds_today(sport_key: str, starts: list[str] | None = None) -> dict[str, dict]:
    """Return {away_team|home_team: {away_odds, home_odds}} using the sharpest available bookmaker.

    `starts`: ISO start times of the caller's games that have not started. Empty = nothing left
    to price, so no API call (finished games read the stored line via _game_odds_for).
    For games not yet started: returns current market odds and caches them in _pregame_odds.
    For games already in progress: returns the pre-game odds stored before tip-off/first pitch.
    Falls back to empty dict silently on any error or missing key.
    """
    import json, time as _t, urllib.request
    from datetime import datetime, timezone
    global _odds_paused_until

    if not ODDS_API_KEY:
        return {}

    now = _t.time()
    cached = _odds_cache.get(sport_key)
    if starts is not None and not starts:
        return cached or {}
    # Closer to the start, refresh more often so the stored line is the closing line
    ttl = _ODDS_TTL
    for s in starts or []:
        try:
            until = datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() - now
        except ValueError:
            continue
        if 0 < until < _ODDS_NEAR_START:
            ttl = _ODDS_TTL_NEAR_START
            break
    if cached is not None and (now - _odds_cache_time.get(sport_key, 0)) < ttl:
        return cached
    if now < _odds_paused_until:
        return cached or {}

    url = (
        f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
        f"?apiKey={ODDS_API_KEY}"
        f"&regions={_ODDS_REGIONS}"
        f"&markets=h2h"
        f"&oddsFormat=decimal"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CourtEdge/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            games = json.loads(resp.read())
            remaining = resp.headers.get("x-requests-remaining")
        if remaining is not None and float(remaining) < _ODDS_MIN_REMAINING:
            _odds_paused_until = now + _ODDS_PAUSE   # keep the last credits; retry later

        now_dt = datetime.now(timezone.utc)
        result: dict[str, dict] = {}
        for g in games:
            away = g.get("away_team", "")
            home = g.get("home_team", "")
            game_key = f"{_normalize_team(away)}|{_normalize_team(home)}"

            # Determine if game has already started
            try:
                commence_dt = datetime.fromisoformat(g.get("commence_time", "").replace("Z", "+00:00"))
                game_started = commence_dt <= now_dt
            except Exception:
                game_started = False
            stored_key = _pregame_odds_key(away, home, g.get("commence_time", ""))

            # Started: keep showing the last pre-game line we stored (live lines are distorted)
            if game_started and stored_key in _pregame_odds:
                result[game_key] = {k: _pregame_odds[stored_key][k] for k in ("away_odds", "home_odds")}
                continue

            # Extract odds from best available bookmaker
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
                        # Only persist pre-game odds, refreshed up to the start (closing line)
                        _pregame_odds[stored_key] = {
                            **odds_data, "saved_at": _time_mod.strftime("%Y-%m-%dT%H:%M:%SZ", _time_mod.gmtime())}
                    result[game_key] = odds_data
                break

        _save_pregame_odds(_pregame_odds)
        _odds_cache[sport_key]      = result
        _odds_cache_time[sport_key] = now
        return result
    except urllib.error.HTTPError as e:
        if e.code in (401, 429):                     # bad key or quota used up: stop asking
            _odds_paused_until = now + _ODDS_PAUSE
        return cached or {}
    except Exception:
        return cached or {}


VALUE_EDGE_MIN = 5.0  # model must beat the no-vig market probability by ≥ 5 points


def _value_bet(away_prob_pct: float, home_prob_pct: float,
               away_odds: float | None, home_odds: float | None) -> dict:
    """Compare model probabilities with the bookmaker's (decimal odds, vig removed).

    value_side is the side where the model's probability exceeds the market's by
    at least VALUE_EDGE_MIN points; value_ev is the expected return per unit staked.
    """
    empty = {"away_market_prob": None, "home_market_prob": None,
             "value_side": None, "value_edge": None, "value_ev": None}
    if not away_odds or not home_odds or away_odds <= 1 or home_odds <= 1:
        return empty
    ia, ih = 1 / away_odds, 1 / home_odds
    mkt_away, mkt_home = ia / (ia + ih) * 100, ih / (ia + ih) * 100
    edges = {"away": away_prob_pct - mkt_away, "home": home_prob_pct - mkt_home}
    side = max(edges, key=edges.get)
    out = {**empty, "away_market_prob": round(mkt_away, 1), "home_market_prob": round(mkt_home, 1)}
    if edges[side] >= VALUE_EDGE_MIN:
        prob, odds = (away_prob_pct, away_odds) if side == "away" else (home_prob_pct, home_odds)
        out.update(value_side=side, value_edge=round(edges[side], 1),
                   value_ev=round(prob / 100 * odds - 1, 3))
    return out


def _get_game_odds(odds: dict, away: str, home: str) -> dict:
    """Look up odds for a game, trying normalized team names."""
    key = f"{_normalize_team(away)}|{_normalize_team(home)}"
    return odds.get(key, {})


def _pregame_odds_key(away: str, home: str, start: str) -> str:
    """'away|home|YYYY-MM-DD' (Eastern date) — the date tells apart the games of a series.
    `start` is an ISO datetime (UTC) or an already-Eastern 'YYYY-MM-DD'."""
    import datetime, zoneinfo
    day = (start or "")[:10]
    if len(start or "") > 10:
        try:
            day = datetime.datetime.fromisoformat(start.replace("Z", "+00:00")) \
                .astimezone(zoneinfo.ZoneInfo("America/New_York")).date().isoformat()
        except ValueError:
            pass
    return f"{_normalize_team(away)}|{_normalize_team(home)}|{day}"


def _game_odds_for(odds: dict, away: str, home: str, start: str, finished: bool) -> dict:
    """Odds to show for a game: the last pre-game line we stored, else the current market line
    for a game not finished yet (never a live / post-game line for a finished game)."""
    stored = _pregame_odds.get(_pregame_odds_key(away, home, start))
    if stored:
        return stored
    return {} if finished else _get_game_odds(odds, away, home)
