#!/usr/bin/env python3
"""
NFL Model Training
Trains Logistic Regression + XGBoost on the NFL training dataset and saves:
  models/nfl_logistic_regression.pkl
  models/nfl_xgboost.pkl
  models/nfl_metrics.json   (accuracy, log loss, Brier, calibration, vs Vegas)

Validation is leave-one-season-out: each fold holds out a whole season, so the
two mirrored rows of a game (one per team) never straddle train and test.

Run:
    python nfl/train.py
"""

import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

ROOT       = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from evaluation import evaluate, oof_game_probs, write_metrics  # noqa: E402

SPORT      = "nfl"
DATA_PATH  = ROOT / "data" / "processed" / "nfl_training_data.csv"
MODELS_DIR = ROOT / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

MODEL_PATH     = MODELS_DIR / "nfl_logistic_regression.pkl"
XGB_MODEL_PATH = MODELS_DIR / "nfl_xgboost.pkl"
METRICS_PATH   = MODELS_DIR / "nfl_metrics.json"

# ── Feature list — must match api/main.py ─────────────────────────────────────
FEATURES = [
    # Context
    "home", "rest_diff", "off_bye", "opp_off_bye",
    # Team strength (Elo carries across seasons → no week-1 cold start)
    "elo_diff",
    # Efficiency: (off EPA/play − def EPA/play allowed) gap, recency-weighted
    "net_epa_diff",
    # Starting quarterback
    "qb_epa_diff", "qb_changed", "opp_qb_changed",
    # Non-QB injuries: gap in status-weighted snap share of players on the injury report
    "inj_total_diff",
]
TARGET   = "win"
GAME_KEY = "game_id"


def load_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    df = pd.read_csv(DATA_PATH)
    print(f"Loaded {len(df):,} rows from {DATA_PATH.name}")
    print(f"  Seasons: {sorted(int(s) for s in df['season'].unique())}")
    print(f"  Win rate: {df[TARGET].mean():.3f}")
    missing = [f for f in FEATURES if f not in df.columns]
    if missing:
        raise ValueError(f"Missing features in training data: {missing}")
    X = df[FEATURES].copy()
    nan_cols = X.columns[X.isna().any()].tolist()
    if nan_cols:
        print(f"  WARNING: NaN values in {nan_cols} — filling with column median")
        X = X.fillna(X.median())
    return df, X, df[TARGET]


def make_lr() -> Pipeline:
    return Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(
            C=1.0, max_iter=1000, solver="lbfgs",
            class_weight="balanced", random_state=42,
        )),
    ])


def make_xgb() -> XGBClassifier:
    return XGBClassifier(
        n_estimators=300, max_depth=3, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, min_child_weight=10,
        eval_metric="logloss", random_state=42, n_jobs=-1, verbosity=0,
    )


def report(name: str, m: dict) -> None:
    accs = list(m["per_season"].values())
    print(f"\n  {name}: accuracy {m['accuracy']:.4f} (+/- {np.std(accs):.4f} across seasons)"
          f"  log loss {m['log_loss']:.4f}  Brier {m['brier']:.4f}")
    print(f"  Per season: {m['per_season']}")


if __name__ == "__main__":
    print("=" * 55)
    print("  NFL Model Training")
    print("=" * 55)

    df, X, y = load_data()
    groups, games = df["season"], df[GAME_KEY]
    print(f"\nFeature matrix: {X.shape[0]:,} rows x {X.shape[1]} features")

    print("\nLogistic Regression (leave-one-season-out)...")
    lr_metrics = evaluate(oof_game_probs(make_lr(), X, y, groups, games), y, groups, df.get("vegas_prob"))
    report("LR", lr_metrics)
    if "vegas" in lr_metrics:
        v = lr_metrics["vegas"]
        print(f"  vs Vegas on {v['n_games']:,} games: model acc {v['model']['accuracy']:.4f} / "
              f"log loss {v['model']['log_loss']:.4f}  |  Vegas acc {v['vegas']['accuracy']:.4f} / "
              f"log loss {v['vegas']['log_loss']:.4f}")

    print("\nXGBoost (leave-one-season-out)...")
    xgb_metrics = evaluate(oof_game_probs(make_xgb(), X, y, groups, games), y, groups)
    report("XGBoost", xgb_metrics)

    pipe = make_lr().fit(X, y)
    xgb_clf = make_xgb().fit(X, y)
    coefs = pipe.named_steps["clf"].coef_[0]
    print("\n  LR features by |coefficient|:")
    for feat, coef in sorted(zip(FEATURES, coefs), key=lambda x: abs(x[1]), reverse=True):
        print(f"    {feat:32s}  {coef:+.4f}  {'#' * int(abs(coef) * 20)}")

    with open(MODEL_PATH, "wb") as f:
        pickle.dump(pipe, f)
    with open(XGB_MODEL_PATH, "wb") as f:
        pickle.dump(xgb_clf, f)
    write_metrics(METRICS_PATH, {
        "sport": SPORT,
        "served_model": "logistic_regression",
        "features": FEATURES,
        "coefficients": [round(float(c), 6) for c in coefs],
        "n_rows": int(len(df)),
        "seasons": sorted(int(s) for s in groups.unique()),
        "validation": "leave-one-season-out, game-level normalised probabilities",
        "logistic_regression": lr_metrics,
        "xgboost": xgb_metrics,
    })
    print(f"\n  Saved: {MODEL_PATH.name}, {XGB_MODEL_PATH.name}, {METRICS_PATH.name}")
    print("\nDone!")
