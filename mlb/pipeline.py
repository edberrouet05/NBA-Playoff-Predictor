#!/usr/bin/env python3
"""
MLB Data Pipeline — Step 2
Fetches 3 seasons of regular-season game data, engineers features,
and outputs:
  data/mlb/mlb_stats_current.csv   — live team stats for inference
  data/processed/mlb_training_data.csv — labelled rows for model training

Run:
    python mlb/pipeline.py

Estimated runtime: ~8-12 minutes (API rate limiting).
"""

import statsapi
import pandas as pd
from pathlib import Path
from datetime import date
import time
import sys

ROOT       = Path(__file__).parent.parent
MLB_DIR    = ROOT / "data" / "mlb"
PROCESSED  = ROOT / "data" / "processed"
MLB_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED.mkdir(parents=True, exist_ok=True)

TRAIN_SEASONS  = [2023, 2024, 2025]
CURRENT_SEASON = 2026

# ── Park factors (2023-2025 multi-year average, neutral = 1.0) ─────────────────
# Source: FanGraphs / Baseball Savant park factor consensus
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
    "Athletics":              0.97,      # relocated to Sacramento 2025
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
    """Parse any MLB stat value to float; handles MLB's '.250' string format."""
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
    """Return {team_id: team_name} for every active MLB team."""
    raw = statsapi.get("teams", {"sportId": 1, "activeStatus": "Y"})
    return {t["id"]: t["name"] for t in raw.get("teams", [])}


# ── Season team stats ──────────────────────────────────────────────────────────

def get_team_stats(team_id: int, season: int) -> dict:
    """Fetch hitting + pitching season stats for one team. Returns {} on failure."""
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

        return {
            # Hitting
            "batting_avg": _safe_float(h.get("avg"), 0.250),
            "ops":         _safe_float(h.get("ops"), 0.700),
            "obp":         _safe_float(h.get("obp"), 0.320),
            "slg":         _safe_float(h.get("slg"), 0.420),
            "runs_scored": rs,
            # Pitching
            "era":         _safe_float(p.get("era"), 4.50),
            "whip":        _safe_float(p.get("whip"), 1.30),
            "k_per9":      _safe_float(p.get("strikeoutsPer9Inn"), 8.0),
            "bb_per9":     _safe_float(p.get("walksPer9Inn"), 3.2),
            # Derived
            "runs_allowed": ra,
            "run_diff":     rs - ra,
        }
    except Exception as exc:
        _progress(f"    WARNING: stats fetch failed team_id={team_id} season={season}: {exc}")
        return {}


# ── Season schedule ────────────────────────────────────────────────────────────

def get_season_schedule(season: int) -> list[dict]:
    """Fetch all regular-season games for a given year (split into two halves).

    The statsapi wrapper doesn't expose game_type, so we fetch April–September
    (spring training is done by late March; playoffs start in October) and
    post-filter to game_type == 'R' using the field each game dict carries.
    """
    halves = [
        (f"04/01/{season}", f"06/30/{season}"),
        (f"07/01/{season}", f"09/30/{season}"),
    ]
    games: list[dict] = []
    for start, end in halves:
        time.sleep(0.5)
        chunk = statsapi.schedule(
            start_date=start, end_date=end,
            sportId=1,
        )
        # Keep only regular-season games (type "R"); field may be absent on older entries
        chunk = [g for g in chunk if g.get("game_type", "R") in ("R", "")]
        games.extend(chunk)
    return games


# ── Training data builder ──────────────────────────────────────────────────────

def build_training_data(
    seasons: list[int],
    all_teams: dict[int, str],
) -> pd.DataFrame:
    """
    For each season:
      1. Fetch season-level team stats (hitting + pitching).
      2. Fetch the full regular-season schedule.
      3. For each completed game, emit two rows — one per team perspective —
         with the team's season stats, contextual features (rest, rolling form),
         opponent stats, differentials, and win target.
    """
    name_to_id = {v: k for k, v in all_teams.items()}
    all_rows: list[dict] = []

    for season in seasons:
        # ── 1. Team stats ──────────────────────────────────────────────────────
        _progress(f"\n[{season}] Fetching team stats ({len(all_teams)} teams)...")
        team_stats: dict[int, dict] = {}
        for i, (tid, tname) in enumerate(all_teams.items()):
            s = get_team_stats(tid, season)
            if s:
                s["team_name"] = tname
                team_stats[tid] = s
            if (i + 1) % 10 == 0:
                _progress(f"    {i+1}/{len(all_teams)} done")
        _progress(f"  Got stats for {len(team_stats)} teams")

        # ── 2. Schedule ────────────────────────────────────────────────────────
        _progress(f"[{season}] Fetching schedule...")
        games = get_season_schedule(season)
        final_games = [g for g in games if g.get("status") == "Final"]
        _progress(f"  {len(final_games)} final games out of {len(games)} scheduled")

        # ── 3. Build per-team chronological result history ─────────────────────
        # Used later for rest_days and rolling win%.
        team_history: dict[int, list[dict]] = {tid: [] for tid in all_teams}
        for g in final_games:
            hid = g.get("home_id") or name_to_id.get(g.get("home_name"))
            aid = g.get("away_id") or name_to_id.get(g.get("away_name"))
            if not hid or not aid:
                continue
            try:
                hs  = int(g.get("home_score", 0) or 0)
                as_ = int(g.get("away_score", 0) or 0)
            except (ValueError, TypeError):
                continue
            gd = g.get("game_date", "")
            if hid in team_history:
                team_history[hid].append({"date": gd, "won": hs > as_})
            if aid in team_history:
                team_history[aid].append({"date": gd, "won": as_ > hs})

        # ── 4. Emit training rows ──────────────────────────────────────────────
        _progress(f"[{season}] Building training rows...")
        season_rows = 0

        def _ctx(tid: int, gd_obj: date | None) -> tuple[int, float]:
            """Return (rest_days, win_pct_last10) for a team before a given date."""
            hist = team_history.get(tid, [])
            if gd_obj:
                past = [h for h in hist if h["date"] < str(gd_obj)]
            else:
                past = hist
            if past:
                last_date = date.fromisoformat(past[-1]["date"])
                rest = min((gd_obj - last_date).days, 7) if gd_obj else 4
            else:
                rest = 4
            last10 = past[-10:]
            pct = sum(1 for h in last10 if h["won"]) / len(last10) if last10 else 0.5
            return rest, round(pct, 3)

        for g in final_games:
            hid = g.get("home_id") or name_to_id.get(g.get("home_name"))
            aid = g.get("away_id") or name_to_id.get(g.get("away_name"))
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

            h_rest, h_l10 = _ctx(hid, gd_obj)
            a_rest, a_l10 = _ctx(aid, gd_obj)

            for team_s, opp_s, is_home, won, rest, l10, tname, oname in [
                (hs_,  as_, 1, int(home_won),     h_rest, h_l10, hname, aname),
                (as_,  hs_, 0, int(not home_won), a_rest, a_l10, aname, hname),
            ]:
                all_rows.append({
                    "season":          season,
                    "game_date":       gd_str,
                    "team_name":       tname,
                    "opp_name":        oname,
                    # Team pitching
                    "era":             team_s.get("era",     4.50),
                    "whip":            team_s.get("whip",    1.30),
                    "k_per9":          team_s.get("k_per9",  8.00),
                    "bb_per9":         team_s.get("bb_per9", 3.20),
                    # Team hitting
                    "batting_avg":     team_s.get("batting_avg", 0.250),
                    "ops":             team_s.get("ops",     0.700),
                    "obp":             team_s.get("obp",     0.320),
                    "slg":             team_s.get("slg",     0.420),
                    "run_diff":        team_s.get("run_diff", 0),
                    # Opponent stats (mirror)
                    "opp_era":         opp_s.get("era",     4.50),
                    "opp_whip":        opp_s.get("whip",    1.30),
                    "opp_ops":         opp_s.get("ops",     0.700),
                    "opp_run_diff":    opp_s.get("run_diff", 0),
                    # Differentials (team minus opp; negative = disadvantage)
                    "era_diff":        team_s.get("era",     4.50) - opp_s.get("era",     4.50),
                    "whip_diff":       team_s.get("whip",    1.30) - opp_s.get("whip",    1.30),
                    "ops_diff":        team_s.get("ops",     0.700) - opp_s.get("ops",    0.700),
                    "run_diff_diff":   team_s.get("run_diff", 0)   - opp_s.get("run_diff", 0),
                    # Context
                    "home":            is_home,
                    "rest_days":       rest,
                    "win_pct_last10":  l10,
                    "park_factor":     PARK_FACTORS.get(tname, 1.0),
                    # Target
                    "win":             won,
                })
                season_rows += 1

        _progress(f"  {season_rows} rows built for {season}")

    return pd.DataFrame(all_rows)


# ── Current-season stats (inference) ──────────────────────────────────────────

def build_current_stats(
    all_teams: dict[int, str],
    season: int = CURRENT_SEASON,
) -> pd.DataFrame:
    """Fetch current-season hitting+pitching stats + W-L for all teams."""
    _progress(f"\nBuilding current-season stats ({season})...")

    # Standings — one call covers all divisions
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
    _progress("  MLB Data Pipeline")
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
    _progress(f"  Done in {elapsed}s")
    _progress(f"  Training rows  : {len(train_df):,}")
    _progress(f"  Win rate       : {train_df['win'].mean():.3f}  (should be ~0.500)")
    _progress(f"  Seasons        : {sorted(train_df['season'].unique())}")
    _progress(f"  Saved          : {out}")
    _progress(f"{'='*60}")
    _progress(f"\nFeatures: {[c for c in train_df.columns if c != 'win']}")
