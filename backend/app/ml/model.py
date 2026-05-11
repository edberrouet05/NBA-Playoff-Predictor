"""
Trains a logistic regression classifier to predict playoff series winners.

Features are the stat *differences* between the two competing teams
(team_a minus team_b), so a positive prediction means team_a wins.

Usage:
    python -m app.ml.model          # train and save
"""

import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

_MODEL_PATH = Path(__file__).parent / "trained_model.pkl"
_DATA_PATH = Path(__file__).parent.parent.parent / "data" / "historical_training_data.csv"

FEATURES = [
    "off_rtg_diff",
    "def_rtg_diff",
    "net_rtg_diff",
    "pace_diff",
    "win_pct_diff",
    "pie_diff",
]


def _make_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute per-series diff features.
    Columns w_* belong to the winner, l_* to the loser.
    def_rtg is inverted so that positive always means team_a is better.
    """
    return pd.DataFrame({
        "off_rtg_diff": df["w_off_rtg"] - df["l_off_rtg"],
        "def_rtg_diff": df["l_def_rtg"] - df["w_def_rtg"],
        "net_rtg_diff": df["w_net_rtg"] - df["l_net_rtg"],
        "pace_diff":    df["w_pace"]    - df["l_pace"],
        "win_pct_diff": df["w_win_pct"] - df["l_win_pct"],
        "pie_diff":     df["w_pie"]     - df["l_pie"],
    })


def train() -> Pipeline:
    if not _DATA_PATH.exists():
        raise FileNotFoundError(
            f"Training data not found at {_DATA_PATH}.\n"
            "Run:  python data/build_training_data.py"
        )
    df = pd.read_csv(_DATA_PATH)

    # Winner rows → label 1; flip all diffs for loser rows → label 0
    X_win = _make_features(df)
    X_lose = X_win * -1
    X = pd.concat([X_win, X_lose], ignore_index=True)
    y = np.array([1] * len(df) + [0] * len(df))

    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(max_iter=1000, random_state=42)),
    ])
    pipeline.fit(X, y)

    with open(_MODEL_PATH, "wb") as f:
        pickle.dump(pipeline, f)

    print(f"Trained on {len(df)} series ({len(df) * 2} samples). Saved → {_MODEL_PATH}")
    return pipeline


def load_model() -> Pipeline:
    if not _MODEL_PATH.exists():
        raise FileNotFoundError(
            "Model not found. Train it first:\n"
            "  python -m app.ml.model"
        )
    with open(_MODEL_PATH, "rb") as f:
        return pickle.load(f)


def predict_series(team_a: dict, team_b: dict) -> float:
    """
    Return the probability (0–1) that team_a wins a series vs team_b.

    Each dict must contain: off_rtg, def_rtg, net_rtg, pace, win_pct, pie
    """
    model = load_model()
    X = pd.DataFrame([{
        "off_rtg_diff": team_a["off_rtg"] - team_b["off_rtg"],
        "def_rtg_diff": team_b["def_rtg"] - team_a["def_rtg"],
        "net_rtg_diff": team_a["net_rtg"] - team_b["net_rtg"],
        "pace_diff":    team_a["pace"]    - team_b["pace"],
        "win_pct_diff": team_a["win_pct"] - team_b["win_pct"],
        "pie_diff":     team_a["pie"]     - team_b["pie"],
    }])
    return float(model.predict_proba(X)[0][1])


if __name__ == "__main__":
    train()
