"""
Builds historical_training_data.csv by fetching regular-season advanced stats
and playoff series results for multiple past seasons.

Each row represents one playoff series:
  winner stats, loser stats, and the season it occurred in.

Usage:
    python build_training_data.py
"""

import time
from pathlib import Path

import pandas as pd
from nba_api.stats.endpoints import leaguedashteamstats, leaguegamefinder

SEASONS = [
    "2015-16", "2016-17", "2017-18", "2018-19", "2019-20",
    "2020-21", "2021-22", "2022-23", "2023-24",
]
_SLEEP = 0.8


def fetch_reg_season_stats(season: str) -> pd.DataFrame:
    time.sleep(_SLEEP)
    r = leaguedashteamstats.LeagueDashTeamStats(
        season=season,
        season_type_all_star="Regular Season",
        measure_type_detailed_defense="Advanced",
        per_mode_detailed="PerGame",
    )
    df = r.get_data_frames()[0]
    keep = {
        "TEAM_ID": "team_id",
        "W_PCT": "win_pct",
        "OFF_RATING": "off_rtg",
        "DEF_RATING": "def_rtg",
        "NET_RATING": "net_rtg",
        "PACE": "pace",
        "PIE": "pie",
    }
    return df[list(keep.keys())].rename(columns=keep).set_index("team_id")


def fetch_playoff_series(season: str) -> list[tuple[int, int]]:
    """Return (winner_id, loser_id) pairs for every completed series in season."""
    time.sleep(_SLEEP)
    r = leaguegamefinder.LeagueGameFinder(
        season_nullable=season,
        season_type_nullable="Playoffs",
        league_id_nullable="00",
        player_or_team_abbreviation="T",
    )
    games = r.get_data_frames()[0]
    if games.empty:
        return []

    game_data = games[["GAME_ID", "TEAM_ID", "WL"]].dropna(subset=["WL"])

    winners = (
        game_data[game_data["WL"] == "W"]
        .rename(columns={"TEAM_ID": "winner_id"})
    )
    losers = (
        game_data[game_data["WL"] == "L"]
        .rename(columns={"TEAM_ID": "loser_id"})
    )
    game_results = winners.merge(losers, on="GAME_ID")[["winner_id", "loser_id"]]
    game_results["series_key"] = game_results.apply(
        lambda row: tuple(sorted([row["winner_id"], row["loser_id"]])), axis=1
    )

    series_wins = (
        game_results.groupby(["series_key", "winner_id"])
        .size()
        .reset_index(name="wins")
    )

    results = []
    for key, group in series_wins.groupby("series_key"):
        best = group.loc[group["wins"].idxmax()]
        winner = int(best["winner_id"])
        loser = next(int(t) for t in key if t != winner)
        results.append((winner, loser))
    return results


def build():
    rows = []
    for season in SEASONS:
        print(f"  {season}: fetching regular-season stats …", end=" ", flush=True)
        try:
            stats = fetch_reg_season_stats(season)
        except Exception as e:
            print(f"SKIP (stats error: {e})")
            continue

        print("fetching playoff series …", end=" ", flush=True)
        try:
            series = fetch_playoff_series(season)
        except Exception as e:
            print(f"SKIP (series error: {e})")
            continue

        for winner_id, loser_id in series:
            if winner_id not in stats.index or loser_id not in stats.index:
                continue
            w = stats.loc[winner_id]
            l = stats.loc[loser_id]
            rows.append({
                "season": season,
                "winner_id": winner_id,
                "loser_id": loser_id,
                "w_win_pct": w["win_pct"],  "l_win_pct": l["win_pct"],
                "w_off_rtg": w["off_rtg"],  "l_off_rtg": l["off_rtg"],
                "w_def_rtg": w["def_rtg"],  "l_def_rtg": l["def_rtg"],
                "w_net_rtg": w["net_rtg"],  "l_net_rtg": l["net_rtg"],
                "w_pace":    w["pace"],     "l_pace":    l["pace"],
                "w_pie":     w["pie"],      "l_pie":     l["pie"],
            })
        print(f"done ({len(series)} series)")

    df = pd.DataFrame(rows)
    out = Path(__file__).parent / "historical_training_data.csv"
    df.to_csv(out, index=False)
    print(f"\nSaved {len(df)} series records → {out}")


if __name__ == "__main__":
    build()
