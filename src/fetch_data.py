"""
Step 2 — Fetch the last 10 seasons of NBA team stats.

Saves two CSV files per season into data/raw/:
  reg_season_{season}.csv   — regular-season advanced stats (OffRtg, DefRtg, Pace, …)
  playoff_games_{season}.csv — every playoff game (used in step 3 for series labels
                               and rest-day calculation)

Usage:
    python src/fetch_data.py
"""

import time
from pathlib import Path

import pandas as pd
from nba_api.stats.endpoints import leaguedashteamstats, leaguegamefinder

SEASONS = [
    "2015-16", "2016-17", "2017-18", "2018-19", "2019-20",
    "2020-21", "2021-22", "2022-23", "2023-24", "2024-25",
]

RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
_SLEEP = 0.8   # stay under nba_api rate limit


def fetch_reg_season(season: str) -> pd.DataFrame:
    time.sleep(_SLEEP)
    r = leaguedashteamstats.LeagueDashTeamStats(
        season=season,
        season_type_all_star="Regular Season",
        measure_type_detailed_defense="Advanced",
        per_mode_detailed="PerGame",
    )
    df = r.get_data_frames()[0]
    keep = {
        "TEAM_ID":     "team_id",
        "TEAM_NAME":   "team_name",
        "GP":          "games_played",
        "W":           "wins",
        "L":           "losses",
        "W_PCT":       "win_pct",
        "OFF_RATING":  "off_rtg",
        "DEF_RATING":  "def_rtg",
        "NET_RATING":  "net_rtg",
        "PACE":        "pace",
        "PIE":         "pie",
    }
    return df[list(keep.keys())].rename(columns=keep)


def fetch_playoff_games(season: str) -> pd.DataFrame:
    time.sleep(_SLEEP)
    r = leaguegamefinder.LeagueGameFinder(
        season_nullable=season,
        season_type_nullable="Playoffs",
        league_id_nullable="00",
        player_or_team_abbreviation="T",
    )
    df = r.get_data_frames()[0]
    if df.empty:
        return df
    cols = ["GAME_ID", "GAME_DATE", "TEAM_ID", "TEAM_NAME", "MATCHUP", "WL", "PTS"]
    return df[[c for c in cols if c in df.columns]]


def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    for season in SEASONS:
        slug = season.replace("-", "_")

        reg_path = RAW_DIR / f"reg_season_{slug}.csv"
        playoff_path = RAW_DIR / f"playoff_games_{slug}.csv"

        print(f"{season}  regular season … ", end="", flush=True)
        try:
            reg = fetch_reg_season(season)
            reg.to_csv(reg_path, index=False)
            print(f"{len(reg)} teams saved.", end="  ")
        except Exception as e:
            print(f"FAILED ({e})")
            continue

        print(f"playoffs … ", end="", flush=True)
        try:
            games = fetch_playoff_games(season)
            games.to_csv(playoff_path, index=False)
            print(f"{len(games)} game rows saved.")
        except Exception as e:
            print(f"FAILED ({e})")

    print(f"\nDone. Files in: {RAW_DIR}")


if __name__ == "__main__":
    main()
