"""Player pages (all leagues): bio, game log, trend charts with projections, splits, career."""

import time as _time_mod

from fastapi import FastAPI, HTTPException
import pandas as pd

from api.common import (
    NFL_CURRENT_SEASON,
    _parallel,
    app,
)
from api.espn import (
    _espn_json,
    _innings_to_float,
    _stat_num,
    _team_roster,
)
from api.nba import (
    _load_stats_by_name,
    _nba_game_probs,
    _nba_team_from_espn_abbr,
)
from api.nfl import (
    NFL_INJURY_WEIGHT,
    NFL_QB_REPLACEMENT,
    NFL_UA,
    _fetch_nfl_injury_report,
    _fetch_nfl_live_qbs,
    _load_nfl_qb_ratings,
    _load_nfl_stats,
    _nfl_injury_status_by_id,
    _nfl_player_key,
)
from api.teams import (
    _TEAM_LEAGUES,
    _resolve_espn_team,
    _team_next_game_prob,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  Player pages (NFL / MLB / NBA) — ESPN athlete data
# ═══════════════════════════════════════════════════════════════════════════════

# Stats to feature, by player type: (gamelog stat names, chart stat, chart kind)
_PLAYER_FOCUS = {
    "nfl_qb":  (["passingYards", "passingTouchdowns", "interceptions", "QBRating"], "passingYards", "bar"),
    "nfl_rb":  (["rushingYards", "rushingAttempts", "rushingTouchdowns", "receivingYards"], "rushingYards", "bar"),
    "nfl_rec": (["receivingYards", "receptions", "receivingTargets", "receivingTouchdowns"], "receivingYards", "bar"),
    "nfl_def": (["totalTackles", "sacks", "interceptions", "passesDefended"], "totalTackles", "bar"),
    "mlb_bat": (["hits", "homeRuns", "RBIs", "runs"], "OPS", "line"),
    "mlb_pit": (["innings", "strikeouts", "earnedRuns", "walks"], "strikeouts", "bar"),
    "nba":     (["points", "totalRebounds", "assists", "threePointFieldGoalsMade-threePointFieldGoalsAttempted"], "points", "bar"),
    "nhl_skater": (["goals", "assists", "points", "shotsTotal"], "points", "bar"),
    "nhl_goalie": (["saves", "goalsAgainst", "savePct", "shotsAgainst"], "saves", "bar"),
}
# Columns to show in split tables (names from ESPN's /splits payload)
_PLAYER_SPLIT_COLS = {
    "nfl_qb":  ["completions", "passingAttempts", "passingYards", "passingTouchdowns", "interceptions", "QBRating"],
    "nfl_rb":  ["rushingAttempts", "rushingYards", "yardsPerRushAttempt", "rushingTouchdowns", "receptions", "receivingYards"],
    "nfl_rec": ["receptions", "receivingTargets", "receivingYards", "yardsPerReception", "receivingTouchdowns"],
    "nfl_def": ["totalTackles", "soloTackles", "sacks", "interceptions", "passesDefended"],
    "mlb_bat": ["atBats", "hits", "homeRuns", "RBIs", "avg", "OPS"],
    "mlb_pit": ["ERA", "innings", "strikeouts", "walks", "opponentAvg"],
    "nba":     ["gamesPlayed", "avgPoints", "avgRebounds", "avgAssists", "fieldGoalPct", "threePointFieldGoalPct"],
    "nhl_skater": ["games", "goals", "assists", "points", "plusMinus", "shotsTotal"],
    "nhl_goalie": ["gameStarted", "wins", "losses", "overtimeLosses", "avgGoalsAgainst", "savePct"],
}
# Clear labels where ESPN's abbreviations collide (e.g. "YDS" for rushing and receiving)
_PLAYER_STAT_LABELS = {
    "shotsTotal": "SOG",
    "passingYards": "Pass YDS", "passingTouchdowns": "Pass TD", "interceptions": "INT", "QBRating": "Rating",
    "completions": "CMP", "passingAttempts": "ATT", "rushingYards": "Rush YDS", "rushingAttempts": "Carries",
    "rushingTouchdowns": "Rush TD", "yardsPerRushAttempt": "YPC", "receivingYards": "Rec YDS",
    "receptions": "Rec", "receivingTargets": "Targets", "receivingTouchdowns": "Rec TD",
    "yardsPerReception": "Y/Rec", "totalTackles": "Tackles", "soloTackles": "Solo", "sacks": "Sacks",
    "passesDefended": "PD", "hits": "H", "homeRuns": "HR", "RBIs": "RBI", "runs": "R", "innings": "IP",
    "strikeouts": "K", "earnedRuns": "ER", "walks": "BB", "points": "PTS", "totalRebounds": "REB",
    "assists": "AST", "threePointFieldGoalsMade-threePointFieldGoalsAttempted": "3PM",
}
_player_cache: dict[tuple[str, str], tuple[float, dict, float]] = {}
_PLAYER_TTL = 900.0
_PLAYER_LIVE_TTL = 60.0


def _player_kind(league: str, names: list[str]) -> str:
    if league == "nba":
        return "nba"
    if league == "nhl":
        return "nhl_goalie" if "saves" in names else "nhl_skater"
    if league == "mlb":
        return "mlb_bat" if "atBats" in names else "mlb_pit"
    first = names[0] if names else ""
    if first == "completions":
        return "nfl_qb"
    if first == "rushingAttempts":
        return "nfl_rb"
    if first == "receptions":
        return "nfl_rec"
    return "nfl_def"


# Opponent defense column that moves each projected NFL stat (higher EPA allowed = more yards)
_NFL_PROJ_DEF_COL = {"passingYards": "def_pass_epa", "receivingYards": "def_pass_epa", "rushingYards": "def_epa"}
_PROJ_DECAY = 0.85      # weight of each older game relative to the next one
_PROJ_PRIOR_GAMES = 4   # this many games of this season = as much weight as last season (per-game stats)
# Stat = volume × efficiency: (volume stat, volume label, efficiency label, league-average
# efficiency, volume worth of league average used to shrink efficiency, games of this season
# worth as much as last season's volume, game-script sensitivity of volume to our win prob)
_PROJ_VOLUME = {
    ("nfl", "receivingYards"): ("receivingTargets", "Targets",  "Y/Tgt",   7.6,  30,  2, -0.20),
    ("nfl", "rushingYards"):   ("rushingAttempts",  "Carries",  "YPC",     4.3,  80,  2,  0.30),
    ("nfl", "passingYards"):   ("passingAttempts",  "Attempts", "Y/A",     6.9,  150, 2, -0.20),
    ("nba", "points"):         ("minutes",          "Min",      "Pts/min", 0.47, 300, 3,  0.0),
    ("nba", "totalRebounds"):  ("minutes",          "Min",      "Reb/min", 0.18, 300, 3,  0.0),
    ("nba", "assists"):        ("minutes",          "Min",      "Ast/min", 0.11, 300, 3,  0.0),
}
# Stats the player page's trend chart can switch between (the first is the default)
_PLAYER_CHART_OPTIONS = {"nba": ["points", "totalRebounds", "assists"],
                         # Skaters (goalies keep saves: these columns aren't in their game log)
                         "nhl": ["points", "goals", "assists", "shotsTotal"]}
# ESPN's live boxscore names some stats differently from the game log
_LIVE_STAT_KEYS = {"totalRebounds": "rebounds"}
_PROJ_OUT_STATUSES = {"Out", "Injured Reserve", "Suspended", "Physically Unable To Perform"}
_NBA_B2B_HOURS = 30       # next game this soon after the last one = second night of a back-to-back
_NBA_B2B_ADJ = -0.04      # minutes lost on the second night


def _recency_avg(vals: list[float]) -> float:
    n = len(vals)
    weights = [_PROJ_DECAY ** (n - 1 - i) for i in range(n)]
    return sum(w * v for w, v in zip(weights, vals)) / sum(weights)


def _last_season_totals(career_cats: list[dict], stats: list[str], current_season: str) -> tuple[dict, str] | None:
    """({stat: total, 'gamesPlayed': n}, season label) for the latest season before the current one.
    Reads totals ('points') or per-game averages ('avgPoints' × games played)."""
    def column(names: list[str], stat: str) -> tuple[int, bool] | None:
        # Per-game column: 'points' → 'avgPoints'; NBA 'totalRebounds' → 'avgRebounds'
        avg = {"totalRebounds": "avgRebounds"}.get(stat, "avg" + stat[0].upper() + stat[1:])
        if stat in names:
            return names.index(stat), False
        return (names.index(avg), True) if avg in names else None

    cat = next((c for c in career_cats if "gamesPlayed" in (c.get("names") or [])
                and all(column(c["names"], s) for s in stats)), None)
    if not cat:
        return None
    names = cat["names"]
    cols = {s: column(names, s) for s in stats}
    for s in reversed(cat.get("statistics") or []):
        label = (s.get("season") or {}).get("displayName", "")
        row = s.get("stats") or []
        if label == current_season or len(row) < len(names):
            continue
        gp = _stat_num(row[names.index("gamesPlayed")])
        out: dict = {"gamesPlayed": gp}
        for stat, (i, is_avg) in cols.items():
            v = _stat_num(row[i])
            out[stat] = None if v is None or gp is None else v * gp if is_avg else v
        if gp and all(out[k] is not None for k in stats):
            return out, label
    return None


def _nba_matchup_adj(team: str, opponent: str) -> tuple[float, float]:
    """(pace, defense) scales for an NBA game: expected possessions vs league average, and
    points per possession the opponent allows (def rating z-score, ±8% max)."""
    stats = _load_stats_by_name()
    if team not in stats.index or opponent not in stats.index:
        return 0.0, 0.0
    pace, drtg = stats["pace"].astype(float), stats["def_rtg"].astype(float)
    game_pace = (float(pace[team]) + float(pace[opponent])) / 2
    z = (float(drtg[opponent]) - drtg.mean()) / (drtg.std() or 1.0)
    return float(game_pace / pace.mean() - 1), float(max(-0.08, min(0.08, 0.03 * z)))


NFL_PLAYER_WEEK_URL = ("https://github.com/nflverse/nflverse-data/releases/download/"
                       f"stats_player/stats_player_week_{NFL_CURRENT_SEASON}.csv")
_NFL_PLAYER_WEEK_TTL = 3 * 3600.0
_nfl_player_week_cache: pd.DataFrame | None = None
_nfl_player_week_time: float = 0.0
_NFL_PLAYER_WEEK_COLS = ["player_id", "player_display_name", "position_group", "week", "team", "opponent_team",
                         "attempts", "passing_yards", "carries", "rushing_yards", "targets", "receiving_yards"]
# Per chart stat: (volume column, yards column, prior volume used to shrink what a defense allows)
_NFL_DEF_VS_POS = {"receivingYards": ("targets", "receiving_yards", 40),
                   "rushingYards":   ("carries", "rushing_yards", 60),
                   "passingYards":   ("attempts", "passing_yards", 100)}
_NFL_VACATED_PASS_ON = 0.7   # share of an injured teammate's volume that reaches the remaining players
# How readily an injured player's volume flows to a teammate, by (teammate, injured) position group
_NFL_VOLUME_AFFINITY = {
    "targets": {("WR", "WR"): 1.0, ("TE", "TE"): 1.0, ("RB", "RB"): 1.0,
                ("WR", "TE"): 0.6, ("TE", "WR"): 0.6, ("RB", "WR"): 0.3, ("RB", "TE"): 0.4,
                ("WR", "RB"): 0.3, ("TE", "RB"): 0.4},
    "carries": {("RB", "RB"): 1.0, ("QB", "RB"): 0.15, ("WR", "RB"): 0.1},
}
# Yards per play per point of QB EPA/dropback, and the cap: receivers lean on the QB directly,
# runners only through lighter boxes
_NFL_QB_EFF = {"receivingYards": (1.5, 0.2), "rushingYards": (0.5, 0.08)}


def _load_nfl_player_weeks() -> pd.DataFrame | None:
    """nflverse weekly player stats for the current regular season (cached; last good copy on failure)."""
    import io, urllib.request
    global _nfl_player_week_cache, _nfl_player_week_time
    now = _time_mod.time()
    if _nfl_player_week_cache is not None and now - _nfl_player_week_time < _NFL_PLAYER_WEEK_TTL:
        return _nfl_player_week_cache
    try:
        req = urllib.request.Request(NFL_PLAYER_WEEK_URL, headers=NFL_UA)
        with urllib.request.urlopen(req, timeout=20) as resp:
            df = pd.read_csv(io.BytesIO(resp.read()), low_memory=False)
        df = df[df["season_type"] == "REG"][_NFL_PLAYER_WEEK_COLS].copy()
        df[_NFL_PLAYER_WEEK_COLS[6:]] = df[_NFL_PLAYER_WEEK_COLS[6:]].fillna(0).astype(float)
        df["key"] = df["player_display_name"].map(_nfl_player_key)
        _nfl_player_week_cache = df
    except Exception:
        pass
    _nfl_player_week_time = now
    return _nfl_player_week_cache


def _nfl_player_context(chart_stat: str, player_name: str, team: str, opponent: str, event_id: str) -> dict:
    """Matchup context from nflverse weekly stats:
    def_adj   — yards per play the opponent allows to the player's position group vs league
    vacated   — volume boost from injured teammates (Out / Doubtful…) who were playing recently,
                split by current share and position affinity
    qb_adj    — receivers and runners: projected starting QB vs the QBs he played with this season."""
    ctx: dict = {"def_adj": None, "position": None, "vacated": 0.0, "vacated_names": [],
                 "qb_adj": 0.0, "qb_from": None, "qb_to": None}
    w = _load_nfl_player_weeks()
    stats = _load_nfl_stats()
    spec = _NFL_DEF_VS_POS.get(chart_stat)
    if w is None or spec is None or team not in stats.index or opponent not in stats.index:
        return ctx
    abbr, opp_abbr = stats.at[team, "abbr"], stats.at[opponent, "abbr"]
    vol_col, yds_col, k = spec
    team_rows = w[w["team"] == abbr]
    me = team_rows[team_rows["key"] == _nfl_player_key(player_name)]
    if me.empty:
        return ctx
    pos = me["position_group"].mode().iat[0]
    ctx["position"] = pos

    # Defense vs position: shrink what the opponent allowed toward the league rate
    pos_rows = w[(w["position_group"] == pos) & (w[vol_col] > 0)]
    lg_vol, lg_yds = pos_rows[vol_col].sum(), pos_rows[yds_col].sum()
    if lg_vol > 0:
        lg_rate = lg_yds / lg_vol
        allowed = pos_rows[pos_rows["opponent_team"] == opp_abbr]
        rate = (allowed[yds_col].sum() + k * lg_rate) / (allowed[vol_col].sum() + k)
        ctx["def_adj"] = float(max(-0.2, min(0.2, rate / lg_rate - 1)))

    # Vacated volume: injured teammates who played the team's latest game leave their usual share.
    # It flows to the healthy teammates in proportion to share × position affinity.
    affinity = _NFL_VOLUME_AFFINITY.get(vol_col)
    if affinity:
        report = dict((_k, _s) for _k, _s in (_fetch_nfl_injury_report() or {}).get(team, []))
        last_week = team_rows["week"].max()
        team_vol_by_week = team_rows.groupby("week")[vol_col].sum()
        used = team_rows[team_rows[vol_col] > 0]
        shares = {}   # key → (position group, share of team volume in the weeks he played, played last week)
        for key, g in used.groupby("key"):
            shares[key] = (g["position_group"].mode().iat[0],
                           g[vol_col].sum() / team_vol_by_week.loc[g["week"]].sum(),
                           last_week in set(g["week"]), g["player_display_name"].iat[0])
        my_key = _nfl_player_key(player_name)
        healthy = {k: v for k, v in shares.items() if NFL_INJURY_WEIGHT.get(report.get(k, ""), 0.0) < 0.8}
        boost = 0.0
        for key, status in report.items():
            if key == my_key or key not in shares:
                continue
            m_pos, m_share, recent, m_name = shares[key]
            weight = NFL_INJURY_WEIGHT.get(status, 0.0)
            mine = affinity.get((pos, m_pos), 0.0)
            if not recent or m_share < 0.05 or not weight or not mine:
                continue
            pool = sum(s * affinity.get((p, m_pos), 0.0) for k, (p, s, _, _) in healthy.items() if k != key)
            if pool > 0:
                boost += weight * m_share * _NFL_VACATED_PASS_ON * mine / pool
                ctx["vacated_names"].append(f"{m_name} ({status})")
        ctx["vacated"] = float(min(0.5, boost))

    # QB change: attempts-weighted QB quality in the games he played vs the projected starter
    if chart_stat in _NFL_QB_EFF:
        qb_k, qb_cap = _NFL_QB_EFF[chart_stat]
        ratings = _load_nfl_qb_ratings()
        starter = _fetch_nfl_live_qbs().get(str(event_id), {}).get(abbr)
        qbs = team_rows[(team_rows["position_group"] == "QB") & (team_rows["attempts"] > 0)
                        & team_rows["week"].isin(me["week"])]
        if starter and not qbs.empty:
            epa = qbs["player_id"].map(lambda q: ratings.get(q, NFL_QB_REPLACEMENT))
            season_epa = float((epa * qbs["attempts"]).sum() / qbs["attempts"].sum())
            new_epa = ratings.get(starter, NFL_QB_REPLACEMENT)
            ctx["qb_adj"] = float(max(-qb_cap, min(qb_cap, qb_k * (new_epa - season_epa))))
            by_qb = qbs.groupby("player_display_name")["attempts"].sum().sort_values(ascending=False)
            ctx["qb_from"] = " / ".join(by_qb.index[:3])
            named = w[w["player_id"] == starter]["player_display_name"]
            ctx["qb_to"] = named.iat[0] if not named.empty else None
    return ctx


def _nfl_matchup_adj(chart_stat: str, opponent: str) -> float:
    """Scale on yards per play from how much the opponent's defense allows (±15% max)."""
    def_col = _NFL_PROJ_DEF_COL.get(chart_stat)
    stats = _load_nfl_stats()
    if not def_col or opponent not in stats.index or def_col not in stats.columns:
        return 0.0
    col = stats[def_col].astype(float)
    z = (float(stats.at[opponent, def_col]) - col.mean()) / (col.std() or 1.0)
    return float(max(-0.15, min(0.15, 0.06 * z)))


def _player_projection(league: str, chart_stat: str, chart: list[dict], career_cats: list[dict],
                       current_season: str, next_game: dict | None, games: list[dict], names: list[str],
                       athlete_id: str, team_name: str, player_name: str = "") -> dict | None:
    """Projection of the chart stat for the player's next game.

    Volume × efficiency where we have both (NFL yards: targets / carries / attempts; NBA points:
    minutes). Volume trusts this season quickly; efficiency is noisy, so it is shrunk hard toward
    last season and the league average. Adjustments: opponent defense (efficiency), NFL game
    script from our win probability and NBA game pace / back-to-backs (volume). Other stats:
    recency-weighted average shrunk toward last season's per-game average."""
    from datetime import datetime
    if not next_game or next_game.get("preseason") or len(chart) < 2:
        return None
    status = _nfl_injury_status_by_id.get(athlete_id) if league == "nfl" else None
    if status in _PROJ_OUT_STATUSES:
        return None
    vals = [p["value"] for p in chart]
    n = len(vals)
    out: dict = {"opp": next_game["opponent"], "at_vs": "vs" if next_game["home"] else "@",
                 "date": next_game["date"], "live": bool(next_game.get("live")), "status": status, "opp_adj_pct": 0, "script_adj_pct": 0,
                 "pace_adj_pct": 0, "rest_adj_pct": 0, "def_position": None, "qb_adj_pct": 0,
                 "qb_from": None, "qb_to": None, "vacated_adj_pct": 0, "vacated_names": [],
                 "method": "average", "recent": round(_recency_avg(vals), 1), "prior": None, "prior_label": None}

    vol_spec = _PROJ_VOLUME.get((league, chart_stat))
    vi, yi = (names.index(vol_spec[0]) if vol_spec and vol_spec[0] in names else None,
              names.index(chart_stat) if chart_stat in names else None)
    pairs = []
    if vi is not None and yi is not None:
        for g in games:
            st = g["stats"]
            v = _stat_num(st[vi]) if vi < len(st) else None
            y = _stat_num(st[yi]) if yi < len(st) else None
            if v is not None and y is not None:
                pairs.append((v, y))

    if vol_spec and len(pairs) >= 2:
        vol_stat, vol_label, eff_label, league_eff, k_eff, vol_prior_games, script_k = vol_spec
        last = _last_season_totals(career_cats, [vol_stat, chart_stat], current_season)
        vols = [v for v, _ in pairs]

        volume = _recency_avg(vols)
        prior_eff = league_eff
        if last:
            tot, out["prior_label"] = last
            m = len(vols)
            volume = (m * volume + vol_prior_games * tot[vol_stat] / tot["gamesPlayed"]) / (m + vol_prior_games)
            prior_eff = (tot[chart_stat] + k_eff * league_eff) / (tot[vol_stat] + k_eff)
        season_vol, season_yds = sum(vols), sum(y for _, y in pairs)
        eff = (season_yds + k_eff * prior_eff) / (season_vol + k_eff)

        script = pace = rest = opp = qb = vacated = 0.0
        if script_k and next_game.get("win_prob") is not None:
            script = max(-0.1, min(0.1, script_k * (next_game["win_prob"] / 100 - 0.5)))
        if league == "nfl":
            ctx = _nfl_player_context(chart_stat, player_name, team_name, next_game["opponent"],
                                      next_game.get("game_id", ""))
            # Defense vs his position when nflverse has it, else overall defensive EPA
            opp = ctx["def_adj"] if ctx["def_adj"] is not None else _nfl_matchup_adj(chart_stat, next_game["opponent"])
            qb, vacated = ctx["qb_adj"], ctx["vacated"]
            out.update({"def_position": ctx["position"] if ctx["def_adj"] is not None else None,
                        "qb_adj_pct": round(qb * 100), "qb_from": ctx["qb_from"], "qb_to": ctx["qb_to"],
                        "vacated_adj_pct": round(vacated * 100), "vacated_names": ctx["vacated_names"]})
        elif league == "nba":
            pace, opp = _nba_matchup_adj(team_name, next_game["opponent"])
            if chart_stat != "points":
                opp = 0.0   # points allowed say little about rebounds or assists
            try:
                gap = (datetime.fromisoformat(next_game["date"].replace("Z", "+00:00"))
                       - datetime.fromisoformat(games[-1]["date"].replace("Z", "+00:00"))).total_seconds() / 3600
                if 0 < gap < _NBA_B2B_HOURS:
                    rest = _NBA_B2B_ADJ
            except (ValueError, KeyError, IndexError):
                pass
        vol_scale = (1 + script) * (1 + rest) * (1 + vacated)
        eff_scale = (1 + opp) * (1 + qb)
        value = volume * vol_scale * eff * eff_scale * (1 + pace)
        eff_digits = 2 if league_eff < 2 else 1
        out.update({"method": "volume", "volume": round(volume * vol_scale, 1), "volume_label": vol_label,
                    "efficiency": round(eff * eff_scale, eff_digits), "efficiency_label": eff_label,
                    "season_efficiency": round(season_yds / season_vol, eff_digits) if season_vol else None,
                    "prior_efficiency": round(prior_eff, eff_digits),
                    "opp_adj_pct": round(opp * 100), "script_adj_pct": round(script * 100),
                    "pace_adj_pct": round(pace * 100), "rest_adj_pct": round(rest * 100)})
    else:
        last = _last_season_totals(career_cats, [chart_stat], current_season)
        base = _recency_avg(vals)
        if last:
            tot, out["prior_label"] = last
            prior = tot[chart_stat] / tot["gamesPlayed"]
            out["prior"] = round(prior, 1)
            base = (n * base + _PROJ_PRIOR_GAMES * prior) / (n + _PROJ_PRIOR_GAMES)
        opp = _nfl_matchup_adj(chart_stat, next_game["opponent"]) if league == "nfl" else 0.0
        value = base * (1 + opp)
        out["opp_adj_pct"] = round(opp * 100)
    value = max(0.0, value)

    # Middle-50% band: game-to-game spread, never narrower than a share of the projection
    # (NFL yardage swings far more, relative to its size, than NBA scoring)
    mean = sum(vals) / n
    sd = (sum((v - mean) ** 2 for v in vals) / (n - 1)) ** 0.5
    half = 0.67 * max(sd, (0.35 if league == "nfl" else 0.2) * value)
    if status in ("Questionable", "Doubtful"):
        half *= 1.25
    digits = 1 if value < 10 else 0
    out.update({"value": round(value, digits), "low": round(max(0.0, value - half), digits),
                "high": round(value + half, digits)})
    return out


def _live_player_stat(sport: str, league: str, event_id: str, athlete_id: str, stat: str) -> dict | None:
    """{'value', 'clock'} for one player's stat in a game in progress, from ESPN's live boxscore.
    0 when he has not recorded it yet; None when the boxscore cannot be read."""
    live = _live_player_stats(sport, league, event_id, athlete_id, [stat])
    return {"value": live["values"][stat], "clock": live["clock"]} if live else None


def _live_player_stats(sport: str, league: str, event_id: str, athlete_id: str, stats: list[str]) -> dict | None:
    """{'values': {stat: value}, 'clock'} from one read of ESPN's live boxscore (0 for a stat he
    has not recorded yet); None when the boxscore cannot be read."""
    url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/summary?event={event_id}"
    data = None
    for attempt in range(2):   # ESPN's TLS handshake sometimes stalls once — retry
        try:
            data = _espn_json(url, timeout=12)
            break
        except Exception:
            if attempt == 1:
                return None
    clock = (((data.get("header") or {}).get("competitions") or [{}])[0].get("status") or {}) \
        .get("type", {}).get("shortDetail", "")
    values = {stat: 0.0 for stat in stats}
    for team in (data.get("boxscore") or {}).get("players", []):
        for cat in team.get("statistics", []):
            keys = cat.get("keys") or []
            for a in cat.get("athletes", []):
                if str((a.get("athlete") or {}).get("id")) != athlete_id:
                    continue
                st = a.get("stats") or []
                for stat in stats:
                    key = _LIVE_STAT_KEYS.get(stat, stat)
                    if key in keys and keys.index(key) < len(st):
                        values[stat] = _stat_num(st[keys.index(key)]) or 0.0
    return {"values": values, "clock": clock}


@app.get("/api/player/{league}/{athlete_id}")
def get_player_page(league: str, athlete_id: str):
    """Bio, season / career stats, game log with trend, splits, awards and news for one player."""
    league = league.lower()
    if league not in _TEAM_LEAGUES:
        raise HTTPException(status_code=404, detail=f"Unknown league: {league}")
    if not athlete_id.isdigit():
        raise HTTPException(status_code=404, detail="Unknown player")
    key = (league, athlete_id)
    hit = _player_cache.get(key)
    if hit and _time_mod.time() - hit[0] < hit[2]:
        return hit[1]

    sport = _TEAM_LEAGUES[league]["sport"]
    base = f"https://site.web.api.espn.com/apis/common/v3/sports/{sport}/{league}/athletes/{athlete_id}"
    def safe(path: str) -> dict | None:
        try:
            return _espn_json(base + path)
        except Exception:
            return None

    results = _parallel(*(lambda path=path: safe(path)
                          for path in ("", "/overview", "/gamelog", "/splits", "/stats")))
    if results[0] is None:
        raise HTTPException(status_code=404, detail="Player not found")
    ath = results[0].get("athlete", {})
    overview, gamelog, splits_raw, career_raw = (r or {} for r in results[1:])

    names = gamelog.get("names") or []
    labels = gamelog.get("labels") or []
    kind = _player_kind(league, names)
    focus, chart_stat, chart_kind = _PLAYER_FOCUS[kind]
    focus = [f for f in focus if f in names]

    # ── Game log: the latest regular season (fall back to the first season type listed)
    season_types = gamelog.get("seasonTypes") or []
    st = next((s for s in season_types if "Regular" in s.get("displayName", "")), season_types[0] if season_types else {})
    events_meta = gamelog.get("events") or {}
    games = []
    for cat in st.get("categories", []):
        for row in cat.get("events", []):
            meta = events_meta.get(row.get("eventId"), {})
            opp = meta.get("opponent") or {}
            home = str(meta.get("homeTeamId", "")) == str((meta.get("team") or {}).get("id", ""))
            hs, as_ = _stat_num(meta.get("homeTeamScore")), _stat_num(meta.get("awayTeamScore"))
            games.append({
                "game_id":  row.get("eventId"),
                "date":     meta.get("gameDate", ""),
                "at_vs":    meta.get("atVs", ""),
                "opponent": opp.get("displayName", ""),
                "opponent_abbr": opp.get("abbreviation", ""),
                "opponent_logo": opp.get("logo"),
                "result":   meta.get("gameResult"),
                "score":    meta.get("score", ""),
                "home":       home,
                "team_abbr":  (meta.get("team") or {}).get("abbreviation", ""),
                "team_name":  None,
                "team_score": None if hs is None or as_ is None else int(hs if home else as_),
                "opp_score":  None if hs is None or as_ is None else int(as_ if home else hs),
                "win_prob":   None,
                "stats":    row.get("stats", []),
            })
    games.sort(key=lambda g: g["date"])
    if league == "nba":
        # Our pick for each game, from the side of the team he played for (he may have been traded)
        by_team: dict[str, list[dict]] = {}
        for g in games:
            name = _nba_team_from_espn_abbr(g["team_abbr"]) if g["team_abbr"] else None
            if name:
                by_team.setdefault(name, []).append(g)
        for name, lst in by_team.items():
            try:
                probs = _nba_game_probs(name, [{"game_id": g["game_id"], "opponent": g["opponent"],
                                                "home": g["home"], "date": g["date"], "completed": True}
                                               for g in lst])
                for g, p in zip(lst, probs):
                    g["team_name"], g["win_prob"] = name, p
            except Exception:
                pass

    def col(name: str) -> int | None:
        return names.index(name) if name in names else None

    def values(name: str, rows: list[dict]) -> list[float]:
        i = col(name)
        if i is None:
            return []
        out = []
        for g in rows:
            v = _stat_num(g["stats"][i]) if i < len(g["stats"]) else None
            if v is not None:
                out.append(_innings_to_float(v) if name == "innings" else v)
        return out

    # Season average vs last 5 games for the featured stats
    form = []
    for name in focus:
        all_v, last_v = values(name, games), values(name, games[-5:])
        if all_v:
            form.append({
                "label":  _PLAYER_STAT_LABELS.get(name) or (labels[col(name)] if col(name) < len(labels) else name),
                "season": round(sum(all_v) / len(all_v), 1),
                "last5":  round(sum(last_v) / len(last_v), 1) if last_v else None,
            })

    # Trend charts + best game, one per stat the chart can show (the first is the default)
    def stat_chart(stat: str) -> tuple[list[dict], dict | None]:
        ci = col(stat)
        points, best = [], None
        if ci is None:
            return points, best
        for g in games:
            v = _stat_num(g["stats"][ci]) if ci < len(g["stats"]) else None
            if v is None:
                continue
            points.append({"date": g["date"], "opp": g["opponent_abbr"], "at_vs": g["at_vs"], "value": v,
                           "result": g["result"], "score": g["score"]})
        if points and chart_kind == "bar":
            b = max(points, key=lambda x: x["value"])
            best = {**b, "label": stat_label(stat)}
        return points, best

    def stat_label(stat: str) -> str:
        ci = col(stat)
        return _PLAYER_STAT_LABELS.get(stat) or (labels[ci] if ci is not None and ci < len(labels) else stat)

    chart_stats = [x for x in _PLAYER_CHART_OPTIONS.get(league, [chart_stat]) if col(x) is not None] or [chart_stat]
    chart_stat = chart_stats[0]
    ci = col(chart_stat)
    charts = {stat: stat_chart(stat) for stat in chart_stats}
    chart, best = charts[chart_stat]

    # ── Splits (home/away, wins/losses, month…): small categories only
    split_names = splits_raw.get("names") or []
    split_labels = splits_raw.get("labels") or []
    wanted = [n for n in _PLAYER_SPLIT_COLS[kind] if n in split_names] or split_names[:6]
    idx = [split_names.index(n) for n in wanted]
    split_tables = []
    for cat in splits_raw.get("splitCategories") or splits_raw.get("categories") or []:
        rows = cat.get("splits", [])
        if not rows or len(rows) > 8:
            continue
        split_tables.append({
            "title": cat.get("displayName", "").replace("split", "Overall").title() if cat.get("displayName") == "split" else cat.get("displayName", ""),
            "rows": [{"label": r.get("displayName", ""), "stats": [r.get("stats", [])[i] if i < len(r.get("stats", [])) else "" for i in idx]}
                     for r in rows],
        })
        if len(split_tables) == 3:
            break

    # ── Career by season: the category that holds the featured stat
    cats = career_raw.get("categories") or []
    career_cat = next((c for c in cats if league == "nba" and c.get("name") == "averages"), None) \
        or next((c for c in cats if chart_stat in (c.get("names") or [])), None) \
        or next((c for c in cats if set(focus) & set(c.get("names") or [])), None) \
        or (cats[0] if cats else None)
    career = None
    if career_cat:
        career = {
            "title":  career_cat.get("displayName", ""),
            "labels": career_cat.get("labels", []),
            "rows":   [{"season": (s.get("season") or {}).get("displayName", ""),
                        "team":   s.get("teamSlug", "").replace("-", " ").title(),
                        "stats":  s.get("stats", [])}
                       for s in career_cat.get("statistics", [])],
            "totals": career_cat.get("totals"),
        }

    # Last game: the player's featured stats in his most recent game
    last_game = None
    if games:
        g = games[-1]
        last_game = {k: g[k] for k in ("game_id", "date", "at_vs", "opponent", "opponent_abbr",
                                        "opponent_logo", "result", "score", "home", "team_name",
                                        "team_score", "opp_score", "win_prob")}
        last_game["line"] = [
            {"label": _PLAYER_STAT_LABELS.get(n) or (labels[col(n)] if col(n) < len(labels) else n),
             "value": g["stats"][col(n)] if col(n) < len(g["stats"]) else "—"}
            for n in focus
        ]

    # Next game of his team (ESPN overview), with our win probability for NFL / NBA games
    next_game = None
    team_name = (ath.get("team") or {}).get("displayName", "")
    nxt = (((overview.get("nextGame") or {}).get("league") or {}).get("events") or [None])[0]
    # A game in progress still counts, so its projection stays up while it is played
    if nxt and nxt.get("status") in ("pre", "in") and " at " in nxt.get("name", "") and team_name:
        away_t, home_t = nxt["name"].split(" at ", 1)
        is_home = home_t == team_name
        next_game = {
            "game_id": str(nxt.get("id")), "date": nxt.get("date", ""), "home": is_home,
            "opponent": away_t if is_home else home_t, "label": nxt.get("weekText", ""),
            "location": nxt.get("location", ""), "broadcast": nxt.get("broadcast", ""),
            "win_prob": None, "preseason": nxt.get("seasonType") == 1, "live": nxt.get("status") == "in",
        }
        if league in ("nfl", "nba"):
            next_game["win_prob"] = _team_next_game_prob(
                league, {"game_id": next_game["game_id"], "home": is_home, "opponent": next_game["opponent"],
                         "date": next_game["date"]},
                team_name)

    projections: dict[str, dict | None] = {stat: None for stat in chart_stats}
    if chart_kind == "bar":
        current_season = st.get("displayName", "").replace(" Regular Season", "").strip()
        if league == "nfl":
            _fetch_nfl_injury_report()   # cached; fills the per-player status lookup
        for stat in chart_stats:
            projections[stat] = _player_projection(league, stat, charts[stat][0], cats, current_season, next_game,
                                                    games, names, athlete_id, team_name, ath.get("displayName", ""))
        live_stats = [stat for stat, pr in projections.items() if pr and pr["live"]]
        if live_stats:
            live = _live_player_stats(sport, league, next_game["game_id"], athlete_id, live_stats)
            for stat in live_stats:
                projections[stat]["live_value"] = live["values"][stat] if live else None
                projections[stat]["live_clock"] = live["clock"] if live else None
    projection = projections[chart_stat]

    ov_stats = overview.get("statistics") or {}
    team = ath.get("team") or {}
    rot = overview.get("rotowire") or {}
    result = {
        "league": league,
        "player": {
            "id": athlete_id, "name": ath.get("displayName", ""), "jersey": ath.get("displayJersey") or ath.get("jersey"),
            "position": (ath.get("position") or {}).get("displayName", ""),
            "position_abbr": (ath.get("position") or {}).get("abbreviation", ""),
            "headshot": (ath.get("headshot") or {}).get("href"),
            "age": ath.get("age"), "height": ath.get("displayHeight"), "weight": ath.get("displayWeight"),
            "birthplace": ath.get("displayBirthPlace"), "draft": ath.get("displayDraft"),
            "college": (ath.get("college") or {}).get("name"), "experience": ath.get("displayExperience"),
            "bats_throws": ath.get("displayBatsThrows"),
            "status": (ath.get("status") or {}).get("name"),
        },
        "team": {
            "name": team.get("displayName", ""), "abbr": team.get("abbreviation", ""),
            "color": "#" + (team.get("color") or "555555"),
            "logo": ((team.get("logos") or [{}])[0]).get("href") or team.get("logo"),
        } if team else None,
        "summary": [{"label": s.get("shortDisplayName") or s.get("displayName"), "value": s.get("displayValue"),
                     "rank": s.get("rankDisplayValue")}
                    for s in (ath.get("statsSummary") or {}).get("statistics", [])],
        "summary_title": (ath.get("statsSummary") or {}).get("displayName", ""),
        "season_lines": {"labels": ov_stats.get("labels", []),
                         "rows": [{"label": s.get("displayName"), "stats": s.get("stats", [])}
                                  for s in ov_stats.get("splits", [])]},
        "form": form,
        "chart": {"label": _PLAYER_STAT_LABELS.get(chart_stat) or (labels[ci] if ci is not None and ci < len(labels) else chart_stat),
                  "kind": chart_kind, "points": chart},
        "best_game": best,
        "projection": projection,
        # Every stat the chart can switch to (NBA: points, rebounds, assists)
        "charts": [{"key": stat, "label": stat_label(stat),
                    "chart": {"label": stat_label(stat), "kind": chart_kind, "points": charts[stat][0]},
                    "best_game": charts[stat][1], "projection": projections[stat]}
                   for stat in chart_stats],
        "last_game": last_game,
        "next_game": next_game,
        "game_log": {"title": st.get("displayName", ""), "labels": labels, "games": list(reversed(games))},
        "splits": {"labels": [_PLAYER_STAT_LABELS.get(n) or (split_labels[i] if i < len(split_labels) else n)
                              for n, i in zip(wanted, idx)], "tables": split_tables},
        "career": career,
        "note": {"headline": rot.get("headline"), "story": rot.get("story"), "published": rot.get("published")}
                if rot.get("headline") else None,
        "awards": [{"name": a.get("name"), "count": a.get("displayCount"), "seasons": a.get("seasons", [])}
                   for a in overview.get("awards") or []],
        "news": [{"headline": n.get("headline"), "published": n.get("published"),
                  "url": ((n.get("links") or {}).get("web") or {}).get("href")}
                 for n in (overview.get("news") or [])[:4]],
    }
    # Around game time (live, or the next game not yet listed) the page changes fast
    ttl = _PLAYER_LIVE_TTL if next_game is None or next_game.get("live") else _PLAYER_TTL
    _player_cache[key] = (_time_mod.time(), result, ttl)
    return result


@app.get("/api/team/{league}/{team}/roster")
def get_team_roster(league: str, team: str):
    """Full roster grouped by unit / position group, for the team roster page."""
    league = league.lower()
    if league not in _TEAM_LEAGUES:
        raise HTTPException(status_code=404, detail=f"Unknown league: {league}")
    t = _resolve_espn_team(league, team)
    if t is None:
        raise HTTPException(status_code=404, detail=f"Team not found: {team}")
    groups, _ = _team_roster(_TEAM_LEAGUES[league]["sport"], league, t["id"])
    logos = t.get("logos") or []
    return {
        "league": league,
        "team": {"name": t["displayName"], "abbr": t["abbreviation"],
                 "color": "#" + (t.get("color") or "555555"),
                 "logo": logos[0]["href"] if logos else None},
        "groups": groups,
    }
