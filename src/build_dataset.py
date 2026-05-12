"""
Step 3 — Build the labeled training dataset.

Game-level: one row per team per playoff game (not per series).
Features: season stats + per-game context (home, rest_days,
          back_to_back, travel_km, prev_margin)
Label: 1 = won this game, 0 = lost

Output: data/processed/training_data.csv

Usage:
    python src/build_dataset.py
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


def load_reg_stats(season: str) -> pd.DataFrame:
    slug = season.replace("-", "_")
    df = pd.read_csv(RAW_DIR / f"reg_season_{slug}.csv")
    return df.set_index("team_id")


def load_playoff_games(season: str) -> pd.DataFrame:
    slug = season.replace("-", "_")
    df = pd.read_csv(RAW_DIR / f"playoff_games_{slug}.csv")
    df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"])
    return df.sort_values("GAME_DATE").reset_index(drop=True)


def build():
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    rows = []

    for season in SEASONS:
        print(f"  {season} … ", end="", flush=True)
        stats = load_reg_stats(season)
        games = load_playoff_games(season)

        if games.empty:
            print("no games")
            continue

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

                s       = stats.loc[tid]
                matchup = str(team_row.get("MATCHUP", ""))
                is_home = 1 if " vs. " in matchup else 0

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
                    rest_days    = 5   # round 1: ~5 days after regular season
                    back_to_back = 0
                    prev_margin  = 0.0
                    travel       = 0.0

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
                    "back_to_back": back_to_back,
                    "travel_km":    travel,
                    "prev_margin":  prev_margin,
                    "label":        label,
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
