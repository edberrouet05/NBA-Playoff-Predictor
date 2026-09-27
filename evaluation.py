"""
Shared model evaluation for the NFL / MLB training scripts.

Every training row is one team's view of a game, and each game has a mirrored
row for the opponent. The API serves the head-to-head normalised probability
p_team / (p_team + p_opp), so metrics are computed on that same quantity using
out-of-fold predictions from leave-one-season-out cross-validation.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import LeaveOneGroupOut, cross_val_predict

N_BINS = 10


def oof_game_probs(estimator, X: pd.DataFrame, y: pd.Series, groups: pd.Series,
                   game_ids: pd.Series) -> pd.Series:
    """Out-of-fold P(win) per row, normalised against the mirrored row of the same game."""
    raw = cross_val_predict(estimator, X, y, groups=groups, cv=LeaveOneGroupOut(),
                            method="predict_proba")[:, 1]
    raw = pd.Series(raw, index=X.index)
    total = raw.groupby(game_ids).transform("sum")
    return raw / total


def _scores(p: np.ndarray, y: np.ndarray) -> dict:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return {
        "accuracy": round(float(((p >= 0.5) == (y == 1)).mean()), 4),
        "log_loss": round(float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean()), 4),
        "brier":    round(float(((p - y) ** 2).mean()), 4),
    }


def calibration(p: np.ndarray, y: np.ndarray, n_bins: int = N_BINS) -> list[dict]:
    """Predicted vs observed win rate in equal-width probability bins."""
    edges = np.linspace(0, 1, n_bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, n_bins - 1)
    out = []
    for b in range(n_bins):
        m = idx == b
        if m.sum() == 0:
            continue
        out.append({
            "lo": round(float(edges[b]), 2), "hi": round(float(edges[b + 1]), 2),
            "predicted": round(float(p[m].mean()), 4),
            "actual":    round(float(y[m].mean()), 4),
            "n":         int(m.sum()),
        })
    return out


def evaluate(probs: pd.Series, y: pd.Series, groups: pd.Series,
             vegas: pd.Series | None = None) -> dict:
    """Headline metrics, per-season accuracy, calibration curve, optional Vegas comparison."""
    p, yv = probs.to_numpy(), y.to_numpy()
    out = {
        **_scores(p, yv),
        "per_season": {int(s): _scores(p[m], yv[m])["accuracy"]
                       for s in sorted(groups.unique()) for m in [(groups == s).to_numpy()]},
        "calibration": calibration(p, yv),
    }
    if vegas is not None:
        m = vegas.notna().to_numpy()
        if m.sum() > 0:
            out["vegas"] = {
                "n_games": int(m.sum() // 2),
                "model":   _scores(p[m], yv[m]),
                "vegas":   _scores(vegas.to_numpy()[m].astype(float), yv[m]),
            }
    return out


def write_metrics(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
