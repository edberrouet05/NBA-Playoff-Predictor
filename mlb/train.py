#!/usr/bin/env python3
"""
MLB Model Training — Step 3
Trains Logistic Regression + XGBoost on the MLB training dataset and saves:
  models/mlb_logistic_regression.pkl
  models/mlb_xgboost.pkl
  models/mlb_metrics.txt

Run:
    python mlb/train.py
"""

import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

ROOT       = Path(__file__).parent.parent
DATA_PATH  = ROOT / "data" / "processed" / "mlb_training_data.csv"
MODELS_DIR = ROOT / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

MODEL_PATH     = MODELS_DIR / "mlb_logistic_regression.pkl"
XGB_MODEL_PATH = MODELS_DIR / "mlb_xgboost.pkl"
METRICS_PATH   = MODELS_DIR / "mlb_metrics.txt"

# ── Feature list — must match api/main.py ─────────────────────────────────────
# Removed raw + opp pairs (era/opp_era, whip/opp_whip, ops/opp_ops,
# run_diff/opp_run_diff) — the differential already captures that info.
# Keeping them causes multicollinearity that scrambles win_pct_last10 sign.
FEATURES = [
    # Game-specific starter ERA
    "sp_era", "opp_sp_era",
    # Pitching differentials
    "era_diff", "whip_diff",
    # K/9 and BB/9 add info not captured by ERA alone
    "k_per9", "bb_per9",
    # Bullpen separate from starter
    "bullpen_era",
    # Offense and run differential
    "ops_diff", "run_diff_diff",
    # Context
    "home", "rest_days", "win_pct_last10", "park_factor",
    # Rolling form (last 15 games)
    "run_diff_last15", "opp_run_diff_last15",
]
TARGET = "win"


def load_data() -> tuple[pd.DataFrame, pd.Series]:
    df = pd.read_csv(DATA_PATH)
    print(f"Loaded {len(df):,} rows from {DATA_PATH.name}")
    print(f"  Seasons: {sorted(df['season'].unique())}")
    print(f"  Win rate: {df[TARGET].mean():.3f}")
    missing = [f for f in FEATURES if f not in df.columns]
    if missing:
        raise ValueError(f"Missing features in training data: {missing}")
    X = df[FEATURES].copy()
    y = df[TARGET].copy()
    nan_cols = X.columns[X.isna().any()].tolist()
    if nan_cols:
        print(f"  WARNING: NaN values in {nan_cols} — filling with column median")
        X = X.fillna(X.median())
    return X, y


def train(X: pd.DataFrame, y: pd.Series) -> Pipeline:
    """Fit Logistic Regression with L2 regularisation inside a scaling pipeline."""
    pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(
            C=1.0,
            max_iter=1000,
            solver="lbfgs",
            class_weight="balanced",
            random_state=42,
        )),
    ])

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    scores = cross_val_score(pipe, X, y, cv=cv, scoring="accuracy")
    print(f"\n  5-fold CV accuracy: {scores.mean():.4f} +/- {scores.std():.4f}")
    print(f"  Per-fold: {[round(s, 4) for s in scores]}")

    pipe.fit(X, y)
    return pipe, scores


def train_xgb(X: pd.DataFrame, y: pd.Series) -> tuple:
    """Fit XGBoost classifier — no scaling needed, handles multicollinearity better."""
    clf = XGBClassifier(
        n_estimators=500,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=10,
        eval_metric="logloss",
        random_state=42,
        n_jobs=-1,
        verbosity=0,
    )
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    scores = cross_val_score(clf, X, y, cv=cv, scoring="accuracy")
    print(f"\n  XGBoost 5-fold CV accuracy: {scores.mean():.4f} +/- {scores.std():.4f}")
    print(f"  Per-fold: {[round(s, 4) for s in scores]}")
    clf.fit(X, y)
    return clf, scores


def feature_report(pipe: Pipeline) -> list[tuple[str, float]]:
    clf = pipe.named_steps["clf"]
    coefs = clf.coef_[0]
    pairs = sorted(zip(FEATURES, coefs), key=lambda x: abs(x[1]), reverse=True)
    print("\n  Top features by |coefficient|:")
    for feat, coef in pairs[:10]:
        bar = "#" * int(abs(coef) * 20)
        sign = "+" if coef > 0 else "-"
        print(f"    {feat:22s}  {sign}{abs(coef):.4f}  {bar}")
    return pairs


def save(pipe: Pipeline, scores: np.ndarray, coef_pairs: list,
         xgb_clf: XGBClassifier, xgb_scores: np.ndarray) -> None:
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(pipe, f)
    print(f"\n  LR model saved: {MODEL_PATH}")

    with open(XGB_MODEL_PATH, "wb") as f:
        pickle.dump(xgb_clf, f)
    print(f"  XGBoost model saved: {XGB_MODEL_PATH}")

    lines = [
        "MLB Models",
        f"Features        : {FEATURES}",
        f"Training rows   : {len(pd.read_csv(DATA_PATH)):,}",
        "",
        "=== Logistic Regression ===",
        f"Cross-val accuracy: {scores.mean():.4f} +/- {scores.std():.4f}",
        f"Per-fold scores : {list(scores.round(4))}",
        "",
        "Feature coefficients (sorted by |coef|):",
    ] + [f"  {f:22s} {c:+.6f}" for f, c in coef_pairs] + [
        "",
        "=== XGBoost ===",
        f"Cross-val accuracy: {xgb_scores.mean():.4f} +/- {xgb_scores.std():.4f}",
        f"Per-fold scores : {list(xgb_scores.round(4))}",
    ]

    METRICS_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Metrics saved: {METRICS_PATH}")


if __name__ == "__main__":
    print("=" * 55)
    print("  MLB Model Training")
    print("=" * 55)

    X, y = load_data()

    print(f"\nFeature matrix: {X.shape[0]:,} rows x {X.shape[1]} features")

    print("\nTraining Logistic Regression...")
    pipe, scores = train(X, y)
    coef_pairs   = feature_report(pipe)

    print("\nTraining XGBoost...")
    xgb_clf, xgb_scores = train_xgb(X, y)

    save(pipe, scores, coef_pairs, xgb_clf, xgb_scores)

    print("\nDone!")
