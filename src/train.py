"""
Step 4 — Train a logistic regression to predict playoff series wins.

Features: off_rtg, def_rtg, net_rtg, pace, rest_days,
          ts_pct, tov_pct, oreb_pct, home,
          win_streak, srs, point_diff, fg3_rate, ftr,
          back_to_back, travel_km, prev_margin
Label:    1 = won the series, 0 = lost

Output:
  models/logistic_regression.pkl   — trained pipeline (scaler + model)
  models/metrics.txt               — accuracy, classification report

Usage:
    python src/train.py
"""

import pickle
from pathlib import Path

import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

DATA_PATH  = Path(__file__).parent.parent / "data" / "processed" / "training_data.csv"
MODELS_DIR = Path(__file__).parent.parent / "models"

FEATURES = [
    "off_rtg", "def_rtg", "net_rtg", "pace", "rest_days",
    "ts_pct", "tov_pct", "oreb_pct", "home",
    "win_streak", "srs", "point_diff", "fg3_rate", "ftr",
    "back_to_back", "travel_km", "prev_margin",
]


def train():
    MODELS_DIR.mkdir(exist_ok=True)

    df = pd.read_csv(DATA_PATH)
    X  = df[FEATURES]
    y  = df["label"]

    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("clf",    LogisticRegression(max_iter=1000, random_state=42)),
    ])

    # Cross-validation (stratified 5-fold keeps 50/50 balance in each fold)
    cv     = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    scores = cross_val_score(pipeline, X, y, cv=cv, scoring="accuracy")

    print(f"Cross-validation accuracy: {scores.mean():.3f} ± {scores.std():.3f}")
    print(f"Per-fold scores: {[round(s, 3) for s in scores]}")

    # Fit on full dataset and save
    pipeline.fit(X, y)

    model_path = MODELS_DIR / "logistic_regression.pkl"
    with open(model_path, "wb") as f:
        pickle.dump(pipeline, f)

    # Full-dataset metrics (for inspection, not as a true test score)
    y_pred  = pipeline.predict(X)
    report  = classification_report(y, y_pred, target_names=["loss", "win"])
    acc     = accuracy_score(y, y_pred)

    metrics_text = (
        f"Cross-val accuracy : {scores.mean():.3f} ± {scores.std():.3f}\n"
        f"Train accuracy     : {acc:.3f}\n\n"
        f"Classification report (train set):\n{report}"
    )
    (MODELS_DIR / "metrics.txt").write_text(metrics_text)

    print(f"\nClassification report (train set):\n{report}")
    print(f"Model saved → {model_path}")

    # Feature importance (log-reg coefficients after scaling)
    coefs = pipeline.named_steps["clf"].coef_[0]
    print("Feature coefficients (scaled):")
    for feat, coef in sorted(zip(FEATURES, coefs), key=lambda x: abs(x[1]), reverse=True):
        print(f"  {feat:<12} {coef:+.4f}")


if __name__ == "__main__":
    train()
