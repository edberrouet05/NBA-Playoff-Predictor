"""
Step 2 — Fetch the last 10 seasons of NBA team stats.

Saves two CSV files per season into data/raw/:
  reg_season_{season}.csv   — regular-season stats (Advanced + Four Factors + Base)
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
    "2025-26",
]

RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
_SLEEP = 0.8   # stay under nba_api rate limit


def _fetch_advanced(season: str) -> pd.DataFrame:
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


def _fetch_four_factors(season: str) -> pd.DataFrame:
    time.sleep(_SLEEP)
    r = leaguedashteamstats.LeagueDashTeamStats(
        season=season,
        season_type_all_star="Regular Season",
        measure_type_detailed_defense="Four Factors",
        per_mode_detailed="PerGame",
    )
    df = r.get_data_frames()[0]
    return df[["TEAM_ID", "TM_TOV_PCT", "OREB_PCT"]].rename(columns={
        "TEAM_ID":    "team_id",
        "TM_TOV_PCT": "tov_pct",
        "OREB_PCT":   "oreb_pct",
    })


def _fetch_base(season: str) -> pd.DataFrame:
    time.sleep(_SLEEP)
    r = leaguedashteamstats.LeagueDashTeamStats(
        season=season,
        season_type_all_star="Regular Season",
        measure_type_detailed_defense="Base",
        per_mode_detailed="PerGame",
    )
    df = r.get_data_frames()[0]
    df["ts_pct"]    = df["PTS"] / (2 * (df["FGA"] + 0.44 * df["FTA"]))
    df["fg3_rate"]  = df["FG3A"] / df["FGA"]
    df["ftr"]       = df["FTA"] / df["FGA"]
    df["point_diff"] = df["PLUS_MINUS"]
    return df[["TEAM_ID", "ts_pct", "fg3_rate", "ftr", "point_diff"]].rename(
        columns={"TEAM_ID": "team_id"}
    )


def _fetch_reg_games(season: str) -> pd.DataFrame:
    """Fetch all regular-season game logs (needed for SRS and win streak)."""
    time.sleep(_SLEEP)
    r = leaguegamefinder.LeagueGameFinder(
        season_nullable=season,
        season_type_nullable="Regular Season",
        league_id_nullable="00",
        player_or_team_abbreviation="T",
    )
    df = r.get_data_frames()[0]
    if df.empty:
        return df
    cols = ["GAME_ID", "GAME_DATE", "TEAM_ID", "WL", "PLUS_MINUS"]
    return df[[c for c in cols if c in df.columns]]


def _compute_season_extras(reg_games: pd.DataFrame) -> pd.DataFrame:
    """Compute SRS and end-of-season win streak from regular-season game logs."""
    if reg_games.empty or "WL" not in reg_games.columns:
        return pd.DataFrame(columns=["team_id", "srs", "win_streak"])

    reg_games = reg_games.copy()
    reg_games["GAME_DATE"] = pd.to_datetime(reg_games["GAME_DATE"])
    teams = reg_games["TEAM_ID"].unique()

    # Win streak — consecutive W/L at the end of the regular season
    streaks = {}
    for tid in teams:
        wl = reg_games[reg_games["TEAM_ID"] == tid].sort_values("GAME_DATE")["WL"].tolist()
        if not wl:
            streaks[tid] = 0
            continue
        last, count = wl[-1], 0
        for result in reversed(wl):
            if result == last:
                count += 1
            else:
                break
        streaks[tid] = count if last == "W" else -count

    # SRS — iterative: SRS_i = MOV_i + mean(SRS_j for all opponents j)
    if "PLUS_MINUS" not in reg_games.columns:
        srs = {t: 0.0 for t in teams}
    else:
        gdf = reg_games[["GAME_ID", "TEAM_ID", "PLUS_MINUS"]].dropna()
        # Self-join to create (team, opponent, margin) rows
        paired = gdf.merge(
            gdf[["GAME_ID", "TEAM_ID"]].rename(columns={"TEAM_ID": "opp_id"}),
            on="GAME_ID",
        )
        paired = paired[paired["TEAM_ID"] != paired["opp_id"]]

        mov = paired.groupby("TEAM_ID")["PLUS_MINUS"].mean().to_dict()
        srs = dict(mov)
        for _ in range(10):
            srs_series = pd.Series(srs)
            paired["opp_srs"] = paired["opp_id"].map(srs_series).fillna(0)
            sos = paired.groupby("TEAM_ID")["opp_srs"].mean().to_dict()
            srs = {t: mov.get(t, 0.0) + sos.get(t, 0.0) for t in srs}

    return pd.DataFrame({
        "team_id":    list(teams),
        "win_streak": [streaks.get(t, 0) for t in teams],
        "srs":        [round(srs.get(t, 0.0), 3) for t in teams],
    })


def fetch_reg_season(season: str) -> pd.DataFrame:
    adv       = _fetch_advanced(season)
    ff        = _fetch_four_factors(season)
    base      = _fetch_base(season)
    reg_games = _fetch_reg_games(season)
    extras    = _compute_season_extras(reg_games)
    return (
        adv
        .merge(ff,     on="team_id")
        .merge(base,   on="team_id")
        .merge(extras, on="team_id", how="left")
    )


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
    cols = ["GAME_ID", "GAME_DATE", "TEAM_ID", "TEAM_NAME", "MATCHUP", "WL", "PTS", "PLUS_MINUS"]
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
