"""
Step 3 — Build the labeled training dataset.

Game-level: one row per team per playoff game (not per series).
Features: season stats + per-game context (home, rest_days,
          back_to_back, travel_km, prev_margin)
Label: 1 = won this game, 0 = lost

Output: data/processed/training_data.csv

Usage:
    python nba/build_dataset.py
"""

import math
from pathlib import Path

import pandas as pd

RAW_DIR       = Path(__file__).parent.parent / "data" / "raw"
PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"

SEASONS = [
    "2015-16", "2016-17", "2017-18", "2018-19", "2019-20",
    "2020-21", "2021-22", "2022-23", "2023-24", "2024-25",
]

# All seasons including one year before the training window (for playoff history lookback)
_ALL_PLAYOFF_SEASONS = [
    "2010-11", "2011-12", "2012-13", "2013-14", "2014-15",
] + SEASONS

# Arena coordinates (lat, lon) keyed by 3-letter nba_api abbreviation
ARENA_COORDS = {
    "ATL": (33.757, -84.396), "BOS": (42.366, -71.062), "BKN": (40.683, -73.975),
    "CHA": (35.225, -80.839), "CHI": (41.881, -87.674), "CLE": (41.497, -81.688),
    "DAL": (32.790, -96.810), "DEN": (39.749, -105.008), "DET": (42.341, -83.055),
    "GSW": (37.768, -122.387), "HOU": (29.751, -95.362), "IND": (39.764, -86.156),
    "LAC": (33.942, -118.339), "LAL": (34.043, -118.267), "MEM": (35.138, -90.051),
    "MIA": (25.781, -80.187), "MIL": (43.045, -87.917), "MIN": (44.979, -93.276),
    "NOP": (29.949, -90.082), "NYK": (40.751, -73.993), "OKC": (35.463, -97.515),
    "ORL": (28.539, -81.384), "PHI": (39.901, -75.172), "PHX": (33.446, -112.071),
    "POR": (45.532, -122.667), "SAC": (38.580, -121.500), "SAS": (29.427, -98.437),
    "TOR": (43.643, -79.379), "UTA": (40.768, -111.901), "WAS": (38.898, -77.021),
}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


def _game_location_abbr(matchup: str) -> str:
    """Return the 3-letter abbreviation of the arena where the game was played."""
    m = str(matchup).strip()
    if " vs. " in m:
        return m.split(" vs. ")[0].strip()   # this team is home
    if " @ " in m:
        return m.split(" @ ")[1].strip()      # this team is away; game at opponent
    return ""


def _travel_km(prev_matchup: str, curr_matchup: str) -> float:
    prev_loc = _game_location_abbr(prev_matchup)
    curr_loc = _game_location_abbr(curr_matchup)
    if not prev_loc or not curr_loc:
        return 0.0
    if prev_loc not in ARENA_COORDS or curr_loc not in ARENA_COORDS:
        return 0.0
    if prev_loc == curr_loc:
        return 0.0
    return round(_haversine_km(*ARENA_COORDS[prev_loc], *ARENA_COORDS[curr_loc]), 1)


def _sf(row, col: str, default: float) -> float:
    """Safe float read — returns default if column missing or NaN."""
    val = row.get(col, default)
    try:
        f = float(val)
        return default if pd.isna(f) else f
    except (TypeError, ValueError):
        return default


def _season_end_year(season: str) -> int:
    """'2018-19' → 2019"""
    return int(season.split("-")[0]) + 1


def _build_playoff_history() -> dict:
    """Returns {team_id: sorted list of end-years where team appeared in playoffs}."""
    history: dict[int, list[int]] = {}
    for s in _ALL_PLAYOFF_SEASONS:
        slug = s.replace("-", "_")
        path = RAW_DIR / f"playoff_games_{slug}.csv"
        if not path.exists():
            continue
        year = _season_end_year(s)
        try:
            df = pd.read_csv(path, usecols=["TEAM_ID", "GAME_ID"])
            for tid in df["TEAM_ID"].dropna().astype(int).unique():
                history.setdefault(tid, [])
                if year not in history[tid]:
                    history[tid].append(year)
        except Exception:
            pass
    for tid in history:
        history[tid].sort()
    return history


def load_reg_stats(season: str) -> pd.DataFrame:
    slug = season.replace("-", "_")
    df = pd.read_csv(RAW_DIR / f"reg_season_{slug}.csv")
    return df.set_index("team_id")


def load_playoff_stats(season: str) -> pd.DataFrame:
    """Load previous season's playoff team ratings. Returns DataFrame indexed by team_id."""
    slug = season.replace("-", "_")
    path = RAW_DIR / f"playoff_stats_{slug}.csv"
    if not path.exists():
        return pd.DataFrame(columns=["playoff_net_rtg"])
    df = pd.read_csv(path)
    if "team_id" not in df.columns or "playoff_net_rtg" not in df.columns:
        return pd.DataFrame(columns=["playoff_net_rtg"])
    return df[["team_id", "playoff_net_rtg"]].set_index("team_id")


def _build_series_context(games: pd.DataFrame) -> dict:
    """
    For each (team_id, game_id), compute series_wins and elimination_game
    based on the running series record *before* that game is played.
    Returns {(team_id, game_id): {'series_wins': int, 'elimination_game': int}}
    """
    game_info: dict = {}
    for game_id, grp in games.groupby("GAME_ID"):
        if len(grp) < 2:
            continue
        teams = sorted(grp["TEAM_ID"].astype(int).tolist())
        pair  = tuple(teams)
        date  = grp["GAME_DATE"].iloc[0]
        results = {int(r["TEAM_ID"]): r["WL"] for _, r in grp.iterrows()}
        game_info[game_id] = {"pair": pair, "date": date, "results": results}

    # Group by team pair (each unique pair = one series)
    by_pair: dict[tuple, list] = {}
    for gid, info in game_info.items():
        by_pair.setdefault(info["pair"], []).append((info["date"], gid, info["results"]))

    result: dict[tuple, dict] = {}
    for pair, sgames in by_pair.items():
        sgames.sort(key=lambda x: x[0])
        wins = {pair[0]: 0, pair[1]: 0}
        for _date, gid, gresults in sgames:
            for tid in pair:
                opp = pair[1] if tid == pair[0] else pair[0]
                result[(tid, gid)] = {
                    "series_wins":      wins[tid],
                    "elimination_game": 1 if wins[opp] == 3 else 0,
                }
            for tid in pair:
                if gresults.get(tid) == "W":
                    wins[tid] += 1
    return result


def load_playoff_games(season: str) -> pd.DataFrame:
    slug = season.replace("-", "_")
    df = pd.read_csv(RAW_DIR / f"playoff_games_{slug}.csv")
    df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"])
    return df.sort_values("GAME_DATE").reset_index(drop=True)


def build():
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    rows = []

    playoff_history = _build_playoff_history()

    # Precompute playoff game counts per team per season end-year
    _playoff_games_by_year: dict[int, dict[int, int]] = {}
    for hs in _ALL_PLAYOFF_SEASONS:
        hy = _season_end_year(hs)
        slug2 = hs.replace("-", "_")
        ph = RAW_DIR / f"playoff_games_{slug2}.csv"
        if not ph.exists():
            continue
        try:
            hdf = pd.read_csv(ph, usecols=["TEAM_ID"])
            counts = hdf["TEAM_ID"].dropna().astype(int).value_counts().to_dict()
            _playoff_games_by_year[hy] = counts
        except Exception:
            _playoff_games_by_year[hy] = {}

    for season in SEASONS:
        print(f"  {season} … ", end="", flush=True)
        stats = load_reg_stats(season)
        games = load_playoff_games(season)

        # Previous season's playoff net rating (0.0 if team missed playoffs)
        year = int(season.split("-")[0])
        prev_season = f"{year - 1}-{str(year)[2:]}"
        playoff_stats = load_playoff_stats(prev_season)

        if games.empty:
            print("no games")
            continue

        series_ctx = _build_series_context(games)
        n_rows = 0
        skipped = 0

        for game_id, grp in games.groupby("GAME_ID"):
            w_rows = grp[grp["WL"] == "W"]
            l_rows = grp[grp["WL"] == "L"]
            if w_rows.empty or l_rows.empty:
                continue

            w = w_rows.iloc[0]
            l = l_rows.iloc[0]
            game_date = w["GAME_DATE"]

            for team_row, label in [(w, 1), (l, 0)]:
                tid = int(team_row["TEAM_ID"])
                if tid not in stats.index:
                    skipped += 1
                    continue

                opp_team_row = l if label == 1 else w
                opp_tid      = int(opp_team_row["TEAM_ID"])

                s       = stats.loc[tid]
                matchup = str(team_row.get("MATCHUP", ""))
                is_home = 1 if " vs. " in matchup else 0
                playoff_net_rtg = (
                    float(playoff_stats.loc[tid, "playoff_net_rtg"])
                    if tid in playoff_stats.index else 0.0
                )

                # Previous playoff games for this team (sorted newest first)
                prev = games[
                    (games["TEAM_ID"] == tid) & (games["GAME_DATE"] < game_date)
                ].sort_values("GAME_DATE")

                if not prev.empty:
                    last         = prev.iloc[-1]
                    rest_days    = (game_date - last["GAME_DATE"]).days
                    back_to_back = 1 if rest_days == 1 else 0
                    prev_margin  = float(last.get("PLUS_MINUS", 0) or 0)
                    travel       = _travel_km(str(last.get("MATCHUP", "")), matchup)
                else:
                    rest_days    = 5
                    back_to_back = 0
                    prev_margin  = 0.0
                    travel       = 0.0

                # days_since_last_playoff — approx from end-year of last playoff appearance
                current_year = _season_end_year(season)
                prev_years = [y for y in playoff_history.get(tid, []) if y < current_year]
                if prev_years:
                    days_since_last_playoff = (current_year - max(prev_years)) * 365
                else:
                    days_since_last_playoff = 2000

                # team_playoff_exp — total playoff games played in previous 5 playoff seasons
                past_years = sorted(y for y in _playoff_games_by_year if y < current_year)[-5:]
                team_playoff_exp = sum(
                    _playoff_games_by_year[y].get(tid, 0) for y in past_years
                )

                # Matchup differentials (team vs opponent)
                if opp_tid in stats.index:
                    os = stats.loc[opp_tid]
                    net_rtg_diff    = float(s["net_rtg"]) - float(os["net_rtg"])
                    off_vs_def_diff = float(s["off_rtg"]) - float(os["def_rtg"])
                    pace_diff       = float(s["pace"])    - float(os["pace"])
                    srs_diff        = float(s["srs"])     - float(os["srs"])
                else:
                    net_rtg_diff = off_vs_def_diff = pace_diff = srs_diff = 0.0

                ctx = series_ctx.get((tid, game_id), {})
                rows.append({
                    "season":       season,
                    "team_id":      tid,
                    "team_name":    s["team_name"],
                    "off_rtg":      s["off_rtg"],
                    "def_rtg":      s["def_rtg"],
                    "net_rtg":      s["net_rtg"],
                    "pace":         s["pace"],
                    "rest_days":    rest_days,
                    "ts_pct":       s["ts_pct"],
                    "tov_pct":      s["tov_pct"],
                    "oreb_pct":     s["oreb_pct"],
                    "home":         is_home,
                    "win_streak":   s["win_streak"],
                    "srs":          s["srs"],
                    "point_diff":   s["point_diff"],
                    "fg3_rate":     s["fg3_rate"],
                    "ftr":          s["ftr"],
                    "back_to_back":    back_to_back,
                    "travel_km":       travel,
                    "prev_margin":     prev_margin,
                    "playoff_net_rtg": playoff_net_rtg,
                    "win_pct_last10":  _sf(s, "win_pct_last10", 0.5),
                    "net_rtg_last15":  _sf(s, "net_rtg_last15", 0.0),
                    "opp_3pt_pct_allowed": _sf(s, "opp_3pt_pct_allowed", 0.35),
                    "bench_net_rtg":       _sf(s, "bench_net_rtg", 0.0),
                    "days_since_last_playoff": days_since_last_playoff,
                    "team_playoff_exp":        team_playoff_exp,
                    "net_rtg_diff":     net_rtg_diff,
                    "off_vs_def_diff":  off_vs_def_diff,
                    "pace_diff":        pace_diff,
                    "srs_diff":         srs_diff,
                    "series_wins":      ctx.get("series_wins", 0),
                    "elimination_game": ctx.get("elimination_game", 0),
                    "label":           label,
                })
                n_rows += 1

        print(f"{n_rows} game rows ({skipped} skipped)")

    df = pd.DataFrame(rows)
    out = PROCESSED_DIR / "training_data.csv"
    df.to_csv(out, index=False)

    print(f"\nDataset saved → {out}")
    print(f"Total rows: {len(df)}  ({df['label'].sum()} wins, {(df['label']==0).sum()} losses)")
    print(f"\nSample:\n{df.head(4).to_string(index=False)}")


if __name__ == "__main__":
    build()
