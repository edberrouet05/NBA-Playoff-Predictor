"""
Fetches current NBA team stats using nba_api and saves them to CSV.

Stats collected per team:
  - Offensive Rating  (OffRtg)  : points scored per 100 possessions
  - Defensive Rating  (DefRtg)  : opponent points allowed per 100 possessions
  - Net Rating        (NetRtg)  : OffRtg - DefRtg
  - Pace              (Pace)    : possessions per 48 minutes
  - Win %             (WPct)    : used later as a training label proxy

Usage:
    python fetch_stats.py [--season 2024-25] [--season-type Playoffs|Regular Season]
"""

import argparse
import time
from pathlib import Path

import pandas as pd
from nba_api.stats.endpoints import leaguedashteamstats, teamgamelogs
from nba_api.stats.static import teams as nba_teams_static


# nba_api rate-limits aggressively; a short sleep between calls avoids 429s.
_SLEEP = 0.6


def fetch_advanced_stats(season: str, season_type: str) -> pd.DataFrame:
    """Return a DataFrame of per-team advanced stats for the given season."""
    time.sleep(_SLEEP)
    response = leaguedashteamstats.LeagueDashTeamStats(
        season=season,
        season_type_all_star=season_type,
        measure_type_detailed_defense="Advanced",
        per_mode_detailed="PerGame",
    )
    df = response.get_data_frames()[0]

    keep = {
        "TEAM_ID": "team_id",
        "TEAM_NAME": "team_name",
        "GP": "games_played",
        "W": "wins",
        "L": "losses",
        "W_PCT": "win_pct",
        "OFF_RATING": "off_rtg",
        "DEF_RATING": "def_rtg",
        "NET_RATING": "net_rtg",
        "PACE": "pace",
        "PIE": "pie",          # Player Impact Estimate – useful auxiliary feature
    }
    df = df[list(keep.keys())].rename(columns=keep)
    return df


def fetch_last_game_date(team_id: int, season: str, season_type: str) -> str | None:
    """Return the most recent game date string (YYYY-MM-DD) for a team, or None."""
    time.sleep(_SLEEP)
    try:
        logs = teamgamelogs.TeamGameLogs(
            team_id_nullable=str(team_id),
            season_nullable=season,
            season_type_nullable=season_type,
        )
        df = logs.get_data_frames()[0]
        if df.empty:
            return None
        # Dates come back as "YYYY-MM-DD" strings; they are already sorted newest first.
        return df["GAME_DATE"].iloc[0]
    except Exception:
        return None


def compute_rest_days(df: pd.DataFrame, season: str, season_type: str, as_of: str) -> pd.DataFrame:
    """
    Add a `rest_days` column – days between each team's last game and `as_of`.

    Parameters
    ----------
    df       : DataFrame from fetch_advanced_stats
    as_of    : ISO date string (YYYY-MM-DD) representing 'today' for the prediction
    """
    as_of_ts = pd.Timestamp(as_of)
    rest = []
    for _, row in df.iterrows():
        last_date = fetch_last_game_date(int(row["team_id"]), season, season_type)
        if last_date:
            delta = (as_of_ts - pd.Timestamp(last_date)).days
        else:
            delta = None
        rest.append(delta)
    df = df.copy()
    df["rest_days"] = rest
    return df


def main():
    parser = argparse.ArgumentParser(description="Fetch NBA team stats via nba_api")
    parser.add_argument("--season", default="2024-25", help="e.g. 2024-25")
    parser.add_argument(
        "--season-type",
        default="Regular Season",
        choices=["Regular Season", "Playoffs", "Pre Season"],
        dest="season_type",
    )
    parser.add_argument(
        "--as-of",
        default=None,
        help="Date for rest-day calculation (YYYY-MM-DD). Defaults to today.",
        dest="as_of",
    )
    parser.add_argument(
        "--no-rest",
        action="store_true",
        help="Skip per-team game-log requests (faster, no rest_days column)",
        dest="no_rest",
    )
    args = parser.parse_args()

    as_of = args.as_of or pd.Timestamp.today().strftime("%Y-%m-%d")

    print(f"Fetching {args.season_type} advanced stats for {args.season} …")
    df = fetch_advanced_stats(args.season, args.season_type)
    print(f"  Retrieved {len(df)} teams.")

    if not args.no_rest:
        print("Fetching last-game dates to compute rest days …")
        df = compute_rest_days(df, args.season, args.season_type, as_of)

    out_dir = Path(__file__).parent
    out_path = out_dir / f"team_stats_{args.season.replace('-', '_')}_{args.season_type.replace(' ', '_')}.csv"
    df.to_csv(out_path, index=False)
    print(f"Saved → {out_path}")
    print(df[["team_name", "win_pct", "off_rtg", "def_rtg", "net_rtg", "pace"]].to_string(index=False))


if __name__ == "__main__":
    main()
