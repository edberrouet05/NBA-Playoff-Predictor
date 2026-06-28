#!/usr/bin/env python3
"""
MLB Data Pipeline — Step 2
Fetches 5 seasons of regular-season game data, engineers features,
and outputs:
  data/mlb/mlb_stats_current.csv   — live team stats for inference
  data/processed/mlb_training_data.csv — labelled rows for model training

Key improvements vs v1:
  - Actual game-day starter ERA per training row (fixes train/inference mismatch)
  - Exponentially weighted recent win% (last 20 games, recency-weighted)
  - 5 seasons of data (2021–2025) instead of 3

Run:
    python mlb/pipeline.py

Estimated runtime: ~15-20 minutes (API rate limiting).
"""

import statsapi
import json
import urllib.request
import pandas as pd
from pathlib import Path
from datetime import date
import time

ROOT       = Path(__file__).parent.parent
MLB_DIR    = ROOT / "data" / "mlb"
PROCESSED  = ROOT / "data" / "processed"
MLB_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED.mkdir(parents=True, exist_ok=True)

TRAIN_SEASONS  = [2021, 2022, 2023, 2024, 2025, 2026]
CURRENT_SEASON = 2026

# ── Park factors (2023-2025 multi-year average, neutral = 1.0) ─────────────────
PARK_FACTORS: dict[str, float] = {
    "Colorado Rockies":       1.15,
    "Cincinnati Reds":        1.08,
    "Texas Rangers":          1.07,
    "Boston Red Sox":         1.05,
    "Chicago Cubs":           1.04,
    "Houston Astros":         1.02,
    "Philadelphia Phillies":  1.02,
    "Atlanta Braves":         1.02,
    "Milwaukee Brewers":      1.01,
    "New York Yankees":       1.01,
    "Pittsburgh Pirates":     1.00,
    "Minnesota Twins":        1.00,
    "Detroit Tigers":         1.00,
    "Toronto Blue Jays":      0.99,
    "New York Mets":          0.99,
    "Kansas City Royals":     0.99,
    "Los Angeles Angels":     0.99,
    "St. Louis Cardinals":    0.98,
    "Chicago White Sox":      0.98,
    "Cleveland Guardians":    0.98,
    "Baltimore Orioles":      0.97,
    "Seattle Mariners":       0.97,
    "Oakland Athletics":      0.97,
    "Athletics":              0.97,
    "Tampa Bay Rays":         0.97,
    "Miami Marlins":          0.96,
    "Washington Nationals":   0.96,
    "Arizona Diamondbacks":   0.96,
    "Los Angeles Dodgers":    0.95,
    "San Francisco Giants":   0.94,
    "San Diego Padres":       0.93,
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _safe_float(val: object, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _progress(msg: str) -> None:
    print(msg, flush=True)


# ── Team catalogue ─────────────────────────────────────────────────────────────

def get_all_teams() -> dict[int, str]:
    raw = statsapi.get("teams", {"sportId": 1, "activeStatus": "Y"})
    return {t["id"]: t["name"] for t in raw.get("teams", [])}


# ── Pitcher ERA lookup ─────────────────────────────────────────────────────────

def get_pitcher_era_lookup(season: int) -> dict[int, float]:
    """Return {player_id: era} for all pitchers with >= 5 IP in a season.

    Used to substitute actual game-day starter ERA into each training row
    instead of the team's rotation-average sp_era.
    """
    url = (
        f"https://statsapi.mlb.com/api/v1/stats"
        f"?stats=season&group=pitching&season={season}"
        f"&sportId=1&gameType=R&limit=1000"
    )
    lookup: dict[int, float] = {}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CourtEdge/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
        for group in data.get("stats", []):
            for split in group.get("splits", []):
                pid  = split.get("player", {}).get("id")
                stat = split.get("stat", {})
                era_str = str(stat.get("era", "") or "")
                ip_str  = str(stat.get("inningsPitched", "0") or "0")
                try:
                    parts = ip_str.split(".")
                    ip = float(parts[0]) + (float(parts[1]) / 3 if len(parts) > 1 and parts[1] else 0.0)
                except Exception:
                    ip = 0.0
                if pid and ip >= 5.0:
                    try:
                        era = float(era_str) if era_str not in ("", "-.--") else 4.50
                        # Cap absurd small-sample ERAs
                        lookup[pid] = min(era, 18.0)
                    except (ValueError, TypeError):
                        lookup[pid] = 4.50
    except Exception as e:
        _progress(f"    WARNING: pitcher ERA lookup failed for {season}: {e}")
    _progress(f"  Pitcher ERA lookup: {len(lookup)} pitchers for {season}")
    return lookup


# ── Starter / bullpen ERA split ────────────────────────────────────────────────

def get_pitcher_splits(team_id: int, season: int) -> tuple[float, float, float]:
    """Return (sp_era, bullpen_era, fip) for a team/season."""
    url = (
        f"https://statsapi.mlb.com/api/v1/stats"
        f"?stats=season&group=pitching&season={season}"
        f"&sportId=1&teamId={team_id}&gameType=R&limit=60"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CourtEdge/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception:
        return 4.50, 4.00, 4.20

    sp_er = sp_ip = 0.0
    bp_er = bp_ip = 0.0
    fip_hr = fip_bb = fip_hbp = fip_k = 0
    fip_ip = 0.0

    for group in data.get("stats", []):
        for split in group.get("splits", []):
            s      = split.get("stat", {})
            gs     = int(s.get("gamesStarted", 0) or 0)
            er     = int(s.get("earnedRuns",   0) or 0)
            hr     = int(s.get("homeRuns",     0) or 0)
            bb     = int(s.get("baseOnBalls",  0) or 0)
            hbp    = int(s.get("hitBatsmen",   0) or 0)
            k      = int(s.get("strikeOuts",   0) or 0)
            ip_str = str(s.get("inningsPitched", "0") or "0")
            try:
                parts = ip_str.split(".")
                ip = float(parts[0]) + (float(parts[1]) / 3 if len(parts) > 1 and parts[1] else 0.0)
            except Exception:
                ip = 0.0
            if ip < 1.0:
                continue
            if gs >= 3:
                sp_er += er;  sp_ip += ip
            else:
                bp_er += er;  bp_ip += ip
            fip_hr  += hr
            fip_bb  += bb
            fip_hbp += hbp
            fip_k   += k
            fip_ip  += ip

    sp_era      = round(sp_er / sp_ip * 9, 2) if sp_ip > 0 else 4.50
    bullpen_era = round(bp_er / bp_ip * 9, 2) if bp_ip > 0 else 4.00
    if fip_ip > 0:
        raw_fip = (13 * fip_hr + 3 * (fip_bb + fip_hbp) - 2 * fip_k) / fip_ip + 3.10
        fip = round(max(1.0, min(raw_fip, 9.0)), 2)
    else:
        fip = 4.20
    return sp_era, bullpen_era, fip


# ── Season team stats ──────────────────────────────────────────────────────────

def get_team_stats(team_id: int, season: int) -> dict:
    time.sleep(0.25)
    try:
        hit_raw = statsapi.get("team_stats", {
            "teamId": team_id, "stats": "season", "group": "hitting",
            "season": season, "sportIds": 1,
        })
        pit_raw = statsapi.get("team_stats", {
            "teamId": team_id, "stats": "season", "group": "pitching",
            "season": season, "sportIds": 1,
        })
        h = hit_raw["stats"][0]["splits"][0]["stat"] if hit_raw.get("stats") else {}
        p = pit_raw["stats"][0]["splits"][0]["stat"] if pit_raw.get("stats") else {}

        rs = _safe_float(h.get("runs"), 700.0)
        ra = _safe_float(p.get("runs"), 700.0)

        sp_era, bullpen_era, fip = get_pitcher_splits(team_id, season)

        return {
            "batting_avg":  _safe_float(h.get("avg"),                0.250),
            "ops":          _safe_float(h.get("ops"),                0.700),
            "obp":          _safe_float(h.get("obp"),                0.320),
            "slg":          _safe_float(h.get("slg"),                0.420),
            "runs_scored":  rs,
            "era":          _safe_float(p.get("era"),                4.50),
            "whip":         _safe_float(p.get("whip"),               1.30),
            "k_per9":       _safe_float(p.get("strikeoutsPer9Inn"),  8.0),
            "bb_per9":      _safe_float(p.get("walksPer9Inn"),       3.2),
            "sp_era":       sp_era,
            "bullpen_era":  bullpen_era,
            "fip":          fip,
            "runs_allowed": ra,
            "run_diff":     rs - ra,
        }
    except Exception as exc:
        _progress(f"    WARNING: stats fetch failed team_id={team_id} season={season}: {exc}")
        return {}


# ── Season schedule with pitcher hydration ─────────────────────────────────────

def get_season_schedule_with_pitchers(season: int) -> list[dict]:
    """Fetch all final regular-season games for a season via direct MLB Stats API.

    Uses hydrate=probablePitcher to get the starting pitcher for each game.
    For completed games the 'probable' pitcher field = actual starter ~95% of the time.
    """
    games: list[dict] = []
    halves = [
        (f"{season}-04-01", f"{season}-06-30"),
        (f"{season}-07-01", f"{season}-09-30"),
    ]
    for start, end in halves:
        url = (
            f"https://statsapi.mlb.com/api/v1/schedule"
            f"?sportId=1&gameType=R"
            f"&startDate={start}&endDate={end}"
            f"&hydrate=probablePitcher"
            f"&limit=1500"
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "CourtEdge/1.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read())
            for date_entry in data.get("dates", []):
                for g in date_entry.get("games", []):
                    state = g.get("status", {}).get("codedGameState", "")
                    if state not in ("F", "O"):   # F=Final, O=Game Over
                        continue
                    t    = g.get("teams", {})
                    home = t.get("home", {})
                    away = t.get("away", {})
                    games.append({
                        "game_id":         g.get("gamePk"),
                        "game_date":       g.get("gameDate", "")[:10],
                        "status":          "Final",
                        "home_id":         home.get("team", {}).get("id"),
                        "away_id":         away.get("team", {}).get("id"),
                        "home_name":       home.get("team", {}).get("name", ""),
                        "away_name":       away.get("team", {}).get("name", ""),
                        "home_score":      home.get("score", 0),
                        "away_score":      away.get("score", 0),
                        # Actual starting pitcher IDs (None if unknown)
                        "home_pitcher_id": home.get("probablePitcher", {}).get("id"),
                        "away_pitcher_id": away.get("probablePitcher", {}).get("id"),
                    })
        except Exception as e:
            _progress(f"    WARNING: schedule fetch failed {start}–{end}: {e}")
        time.sleep(0.5)
    return games


# ── Training data builder ──────────────────────────────────────────────────────

def build_training_data(
    seasons: list[int],
    all_teams: dict[int, str],
) -> pd.DataFrame:
    """
    For each season:
      1. Fetch season-level team stats (used for most features).
      2. Fetch per-pitcher ERA lookup (used to substitute actual starter ERA).
      3. Fetch the full schedule WITH starter IDs hydrated.
      4. For each completed game, emit two rows — one per team perspective —
         where sp_era / opp_sp_era reflect the ACTUAL pitchers who started.
    """
    name_to_id = {v: k for k, v in all_teams.items()}
    all_rows: list[dict] = []

    for season in seasons:
        # ── 1. PREVIOUS season team stats (avoids data leakage) ───────────────
        # Using season-1 stats prevents the model from seeing future game outcomes
        # embedded in season totals. Rolling features still use current-season history.
        prev_season = season - 1
        _progress(f"\n[{season}] Fetching {prev_season} team stats (prior for {season} games)...")
        team_stats: dict[int, dict] = {}
        for i, (tid, tname) in enumerate(all_teams.items()):
            s = get_team_stats(tid, prev_season)
            if s:
                s["team_name"] = tname
                team_stats[tid] = s
            if (i + 1) % 10 == 0:
                _progress(f"    {i+1}/{len(all_teams)} done")
        _progress(f"  Got prev-season ({prev_season}) stats for {len(team_stats)} teams")

        # ── 2. Per-pitcher ERA lookup ──────────────────────────────────────────
        _progress(f"[{season}] Fetching pitcher ERA lookup...")
        era_lookup = get_pitcher_era_lookup(season)
        time.sleep(0.5)

        # ── 3. Schedule with starter IDs ──────────────────────────────────────
        _progress(f"[{season}] Fetching schedule with pitchers...")
        games = get_season_schedule_with_pitchers(season)
        final_games = [g for g in games if g.get("status") == "Final"]
        _progress(f"  {len(final_games)} final games")

        # Count how many games have identified starters
        has_starters = sum(
            1 for g in final_games
            if g.get("home_pitcher_id") and g.get("away_pitcher_id")
        )
        _progress(f"  {has_starters}/{len(final_games)} games have starter IDs "
                  f"({100*has_starters//max(len(final_games),1)}%)")

        # ── 4. Build chronological win/loss history (for rest + form) ─────────
        team_history: dict[int, list[dict]] = {tid: [] for tid in all_teams}
        for g in final_games:
            hid = g.get("home_id") or name_to_id.get(g.get("home_name", ""))
            aid = g.get("away_id") or name_to_id.get(g.get("away_name", ""))
            if not hid or not aid:
                continue
            try:
                hs  = int(g.get("home_score", 0) or 0)
                as_ = int(g.get("away_score", 0) or 0)
            except (ValueError, TypeError):
                continue
            gd = g.get("game_date", "")
            if hid in team_history:
                team_history[hid].append({"date": gd, "won": hs > as_, "run_diff": hs - as_})
            if aid in team_history:
                team_history[aid].append({"date": gd, "won": as_ > hs, "run_diff": as_ - hs})

        # ── 5. Emit training rows ──────────────────────────────────────────────
        _progress(f"[{season}] Building training rows...")
        season_rows = 0

        def _ctx(tid: int, gd_obj: date | None) -> tuple[int, float, float]:
            """Return (rest_days, weighted_win_pct, run_diff_last15)."""
            hist = team_history.get(tid, [])
            past = [h for h in hist if h["date"] < str(gd_obj)] if gd_obj else hist

            # Rest days (capped at 7)
            if past:
                last_date = date.fromisoformat(past[-1]["date"])
                rest = min((gd_obj - last_date).days, 7) if gd_obj else 4
            else:
                rest = 4

            # Exponentially weighted win% over last 20 games
            recent = past[-20:]
            if recent:
                weights = [0.88 ** i for i in range(len(recent) - 1, -1, -1)]
                weighted_wins = sum(w * (1.0 if g["won"] else 0.0) for w, g in zip(weights, recent))
                total_w = sum(weights)
                pct = weighted_wins / total_w if total_w > 0 else 0.5
            else:
                pct = 0.5

            # Average run differential over last 15 games
            recent15 = past[-15:]
            rdl15 = sum(h["run_diff"] for h in recent15) / len(recent15) if recent15 else 0.0

            return rest, round(pct, 3), round(rdl15, 2)

        for g in final_games:
            hid = g.get("home_id") or name_to_id.get(g.get("home_name", ""))
            aid = g.get("away_id") or name_to_id.get(g.get("away_name", ""))
            if not hid or not aid:
                continue
            if hid not in team_stats or aid not in team_stats:
                continue
            try:
                hs  = int(g.get("home_score", 0) or 0)
                as_ = int(g.get("away_score", 0) or 0)
            except (ValueError, TypeError):
                continue

            gd_str = g.get("game_date", "")
            try:
                gd_obj = date.fromisoformat(gd_str) if gd_str else None
            except ValueError:
                gd_obj = None

            home_won = hs > as_
            hs_ = team_stats[hid]
            as_ = team_stats[aid]
            hname = hs_["team_name"]
            aname = as_["team_name"]

            h_rest, h_l10, h_rdl15 = _ctx(hid, gd_obj)
            a_rest, a_l10, a_rdl15 = _ctx(aid, gd_obj)

            h_fip = float(hs_.get("fip", 4.20))
            a_fip = float(as_.get("fip", 4.20))

            # ── Actual starter ERA (falls back to rotation avg if unknown) ──
            h_pitcher_id = g.get("home_pitcher_id")
            a_pitcher_id = g.get("away_pitcher_id")
            home_sp = era_lookup.get(h_pitcher_id, hs_.get("sp_era", 4.50)) if h_pitcher_id else hs_.get("sp_era", 4.50)
            away_sp = era_lookup.get(a_pitcher_id, as_.get("sp_era", 4.50)) if a_pitcher_id else as_.get("sp_era", 4.50)

            for team_s, opp_s, is_home, won, rest, l10, rdl15, opp_rdl15, tname, oname, t_sp, o_sp, t_fip, o_fip in [
                (hs_,  as_, 1, int(home_won),     h_rest, h_l10, h_rdl15, a_rdl15, hname, aname, home_sp, away_sp, h_fip, a_fip),
                (as_,  hs_, 0, int(not home_won), a_rest, a_l10, a_rdl15, h_rdl15, aname, hname, away_sp, home_sp, a_fip, h_fip),
            ]:
                all_rows.append({
                    "season":          season,
                    "game_date":       gd_str,
                    "team_name":       tname,
                    "opp_name":        oname,
                    # Team pitching
                    "era":             team_s.get("era",         4.50),
                    "whip":            team_s.get("whip",        1.30),
                    "k_per9":          team_s.get("k_per9",      8.00),
                    "bb_per9":         team_s.get("bb_per9",     3.20),
                    "sp_era":          t_sp,
                    "bullpen_era":     team_s.get("bullpen_era", 4.00),
                    # Team hitting
                    "batting_avg":     team_s.get("batting_avg", 0.250),
                    "ops":             team_s.get("ops",         0.700),
                    "obp":             team_s.get("obp",         0.320),
                    "slg":             team_s.get("slg",         0.420),
                    "run_diff":        team_s.get("run_diff",    0),
                    # Opponent stats
                    "opp_era":         opp_s.get("era",         4.50),
                    "opp_whip":        opp_s.get("whip",        1.30),
                    "opp_ops":         opp_s.get("ops",         0.700),
                    "opp_run_diff":    opp_s.get("run_diff",    0),
                    "opp_sp_era":      o_sp,
                    # Differentials
                    "era_diff":        team_s.get("era",     4.50) - opp_s.get("era",     4.50),
                    "whip_diff":       team_s.get("whip",    1.30) - opp_s.get("whip",    1.30),
                    "ops_diff":        team_s.get("ops",     0.700) - opp_s.get("ops",    0.700),
                    "run_diff_diff":   team_s.get("run_diff", 0)   - opp_s.get("run_diff", 0),
                    "fip_diff":        round(t_fip - o_fip, 3),
                    # Context + rolling form
                    "home":              is_home,
                    "rest_days":         rest,
                    "win_pct_last10":    l10,
                    "run_diff_last15":   rdl15,
                    "opp_run_diff_last15": opp_rdl15,
                    "park_factor":       PARK_FACTORS.get(tname, 1.0),
                    # Target
                    "win":             won,
                })
                season_rows += 1

        _progress(f"  {season_rows} rows built for {season}")

    return pd.DataFrame(all_rows)


# ── Current-season rolling form (inference) ───────────────────────────────────

def compute_current_rolling_stats(
    all_teams: dict[int, str],
    season: int = CURRENT_SEASON,
) -> dict[str, dict]:
    """Fetch last 30 days of completed games and compute per-team rolling stats.

    Returns {team_name: {win_pct_last10, run_diff_last15}}.
    """
    import datetime as dt
    end_date   = dt.date.today()
    start_date = end_date - dt.timedelta(days=30)

    url = (
        f"https://statsapi.mlb.com/api/v1/schedule"
        f"?sportId=1&gameType=R"
        f"&startDate={start_date}&endDate={end_date}"
        f"&limit=600"
    )

    team_history: dict[int, list[dict]] = {tid: [] for tid in all_teams}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CourtEdge/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
        for date_entry in data.get("dates", []):
            for g in date_entry.get("games", []):
                state = g.get("status", {}).get("codedGameState", "")
                if state not in ("F", "O"):
                    continue
                t    = g.get("teams", {})
                home = t.get("home", {})
                away = t.get("away", {})
                hid  = home.get("team", {}).get("id")
                aid  = away.get("team", {}).get("id")
                hs   = int(home.get("score", 0) or 0)
                as_  = int(away.get("score", 0) or 0)
                gd   = g.get("gameDate", "")[:10]
                if hid in team_history:
                    team_history[hid].append({"date": gd, "won": hs > as_, "run_diff": hs - as_})
                if aid in team_history:
                    team_history[aid].append({"date": gd, "won": as_ > hs, "run_diff": as_ - hs})
    except Exception as e:
        _progress(f"  WARNING: rolling stats fetch failed: {e}")
        return {}

    result: dict[str, dict] = {}
    for tid, tname in all_teams.items():
        hist    = sorted(team_history[tid], key=lambda h: h["date"])
        r20     = hist[-20:]
        r15     = hist[-15:]

        if r20:
            weights = [0.88 ** i for i in range(len(r20) - 1, -1, -1)]
            ww = sum(w * (1.0 if h["won"] else 0.0) for w, h in zip(weights, r20))
            win_pct = ww / sum(weights)
        else:
            win_pct = 0.5

        rdl15 = sum(h["run_diff"] for h in r15) / len(r15) if r15 else 0.0

        result[tname] = {
            "win_pct_last10":    round(win_pct, 3),
            "run_diff_last15":   round(rdl15, 2),
        }

    _progress(f"  Rolling stats computed for {len(result)} teams")
    return result


# ── Current-season stats (inference) ──────────────────────────────────────────

def build_current_stats(
    all_teams: dict[int, str],
    season: int = CURRENT_SEASON,
) -> pd.DataFrame:
    """Fetch current-season hitting+pitching stats + W-L for all teams."""
    _progress(f"\nBuilding current-season stats ({season})...")

    wl_map: dict[int, tuple[int, int]] = {}
    try:
        time.sleep(0.5)
        standings = statsapi.standings_data(
            leagueId="103,104", season=season, standingsTypes="regularSeason"
        )
        for div in standings.values():
            for t in div["teams"]:
                wl_map[t["team_id"]] = (int(t.get("w", 0)), int(t.get("l", 0)))
    except Exception as exc:
        _progress(f"  WARNING: standings fetch failed: {exc}")

    rows: list[dict] = []
    for tid, tname in all_teams.items():
        s = get_team_stats(tid, season)
        if not s:
            continue
        w, l = wl_map.get(tid, (0, 0))
        gp = w + l
        s.update({
            "team_id":     tid,
            "team_name":   tname,
            "wins":        w,
            "losses":      l,
            "win_pct":     round(w / gp, 3) if gp else 0.500,
            "park_factor": PARK_FACTORS.get(tname, 1.0),
        })
        rows.append(s)

    df = pd.DataFrame(rows)

    # Merge rolling form stats
    _progress("  Computing rolling form (last 30 days)...")
    rolling = compute_current_rolling_stats(all_teams, season)
    if rolling:
        df["win_pct_last10"]    = df["team_name"].map(lambda n: rolling.get(n, {}).get("win_pct_last10",  0.5))
        df["run_diff_last15"]   = df["team_name"].map(lambda n: rolling.get(n, {}).get("run_diff_last15", 0.0))
    else:
        df["win_pct_last10"]  = 0.5
        df["run_diff_last15"] = 0.0

    out = MLB_DIR / "mlb_stats_current.csv"
    df.to_csv(out, index=False)
    _progress(f"  Saved: {out}  ({len(df)} teams)\n")

    top = df.sort_values("run_diff", ascending=False)[
        ["team_name", "wins", "losses", "win_pct", "era", "ops", "run_diff"]
    ]
    _progress("  Top-5 by run differential:")
    for _, r in top.head(5).iterrows():
        _progress(
            f"    {r['team_name']:28s} "
            f"W={int(r['wins']):2d} L={int(r['losses']):2d}  "
            f"ERA={r['era']:.2f}  OPS={r['ops']:.3f}  RunDiff={int(r['run_diff']):+d}"
        )
    return df


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _progress("=" * 60)
    _progress("  MLB Data Pipeline  (v2 — actual starters + 5 seasons)")
    _progress(f"  Training seasons : {TRAIN_SEASONS}")
    _progress(f"  Inference season : {CURRENT_SEASON}")
    _progress("=" * 60)

    t0 = time.time()

    all_teams = get_all_teams()
    _progress(f"\nActive MLB teams : {len(all_teams)}")

    # Step A — current season stats (used by the API at inference time)
    current_df = build_current_stats(all_teams)

    # Step B — historical training data
    train_df = build_training_data(TRAIN_SEASONS, all_teams)

    out = PROCESSED / "mlb_training_data.csv"
    train_df.to_csv(out, index=False)

    elapsed = round(time.time() - t0)
    _progress(f"\n{'='*60}")
    _progress(f"  Done in {elapsed}s  ({elapsed//60}m {elapsed%60}s)")
    _progress(f"  Training rows  : {len(train_df):,}")
    _progress(f"  Win rate       : {train_df['win'].mean():.3f}  (should be ~0.500)")
    _progress(f"  Seasons        : {sorted(train_df['season'].unique())}")
    _progress(f"  Starter ERA coverage:")
    for s in TRAIN_SEASONS:
        sub = train_df[train_df["season"] == s]
        # sp_era same as team avg = probable fallback; rough coverage check
        _progress(f"    {s}: {len(sub):,} rows")
    _progress(f"  Saved          : {out}")
    _progress(f"{'='*60}")
