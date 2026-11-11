#!/usr/bin/env python3
"""
NFL projected-total model
Fits the game total (both teams' points) on the NFL training dataset and saves:
  models/nfl_totals.json   (intercept, coefficients, indoor stadiums, validation MAE vs Vegas)

Inputs, all known before kickoff:
  pts   — both attacks' plus both defenses' points per game above average (EPA, recency-weighted)
  dome  — the home stadium is indoors (dome, or a roof usually closed)
  qb    — both starting quarterbacks' EPA per dropback

Validation is leave-one-season-out, like the win model. The closing Vegas total is the
reference (evaluation only, never an input).

Run:
    python nfl/train_totals.py
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

ROOT      = Path(__file__).parent.parent
DATA_PATH = ROOT / "data" / "processed" / "nfl_training_data.csv"
OUT_PATH  = ROOT / "models" / "nfl_totals.json"
FEATURES  = ["pts", "dome", "qb"]
INDOOR    = ("dome", "closed")


def load_games() -> pd.DataFrame:
    """One row per regular-season game (the home team's), with the total and the inputs."""
    rows = pd.read_csv(DATA_PATH)
    rows = rows[rows["game_type"] == "REG"]
    g = rows[rows["home"] == 1].dropna(subset=["points_for"]).copy()
    g["total"] = g["points_for"] + g["points_against"]
    # Each stadium's usual roof from the season before: what is known ahead of a game
    indoor = g.assign(indoor=g["roof"].isin(INDOOR)).groupby(["season", "team"])["indoor"].mean()
    prev = indoor.rename("dome").reset_index().assign(season=lambda d: d["season"] + 1)
    g = g.merge(prev, on=["season", "team"], how="left")
    g["dome"] = (g["dome"].fillna(0) > 0.5).astype(float)
    g["pts"] = g["off_pts"] + g["opp_def_pts"] + g["opp_off_pts"] + g["def_pts"]
    g["qb"] = g["qb_epa"] + g["opp_qb_epa"]
    return g


def main():
    g = load_games()
    errors = []
    for season in sorted(g["season"].unique()):
        train, test = g[g["season"] != season], g[g["season"] == season]
        model = Ridge(alpha=1.0).fit(train[FEATURES], train["total"])
        errors.append(np.abs(model.predict(test[FEATURES]) - test["total"]))
    mae = float(np.concatenate(errors).mean())
    vegas = g.dropna(subset=["total_line"])
    vegas_mae = float(np.abs(vegas["total_line"] - vegas["total"]).mean())
    naive_mae = float(np.abs(g["total"] - g["total"].mean()).mean())

    model = Ridge(alpha=1.0).fit(g[FEATURES], g["total"])
    last = g[g["season"] == g["season"].max()]
    indoor_teams = sorted(last[last["roof"].isin(INDOOR)].groupby("team_name").size().loc[lambda s: s >= 4].index)
    out = {
        "intercept": round(float(model.intercept_), 3),
        "coefficients": {f: round(float(c), 4) for f, c in zip(FEATURES, model.coef_)},
        "indoor_teams": indoor_teams,
        "validation": {"games": len(g), "seasons": f"{g['season'].min()}-{g['season'].max()}",
                       "mae": round(mae, 3), "vegas_mae": round(vegas_mae, 3), "league_average_mae": round(naive_mae, 3)},
    }
    OUT_PATH.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"Leave-one-season-out MAE {mae:.2f} points (Vegas {vegas_mae:.2f}, league average {naive_mae:.2f})")
    print(f"Saved {OUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
