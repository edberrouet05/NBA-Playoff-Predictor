"""
Step 4 — Train a gradient-boosting model to predict playoff game wins.

Uses XGBoost if installed, otherwise falls back to
sklearn's HistGradientBoostingClassifier.

Usage:
    pip install xgboost   # optional but recommended
    python src/train.py
"""

import pickle
from pathlib import Path

import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import Pipeline

DATA_PATH  = Path(__file__).parent.parent / "data" / "processed" / "training_data.csv"
MODELS_DIR = Path(__file__).parent.parent / "models"

FEATURES = [
    "off_rtg", "def_rtg", "net_rtg", "pace", "rest_days",
    "ts_pct", "tov_pct", "oreb_pct", "home",
    "win_streak", "srs", "point_diff", "fg3_rate", "ftr",
    "back_to_back", "travel_km", "prev_margin",
    "playoff_net_rtg",
    "win_pct_last10", "net_rtg_last15", "opp_3pt_pct_allowed", "bench_net_rtg",
    "net_rtg_diff", "off_vs_def_diff", "pace_diff", "srs_diff",
    "series_wins", "elimination_game",
]


def _make_clf():
    try:
        from xgboost import XGBClassifier
        print("Using XGBoost.")
        return XGBClassifier(
            n_estimators=400,
            max_depth=4,
            learning_rate=0.04,
            subsample=0.8,
            colsample_bytree=0.75,
            min_child_weight=3,
            gamma=0.1,
            reg_alpha=0.1,
            reg_lambda=1.0,
            eval_metric="logloss",
            random_state=42,
            n_jobs=-1,
        )
    except ImportError:
        from sklearn.ensemble import HistGradientBoostingClassifier
        print("XGBoost not found — using HistGradientBoostingClassifier.")
        return HistGradientBoostingClassifier(
            max_iter=400,
            max_depth=4,
            learning_rate=0.04,
            min_samples_leaf=20,
            random_state=42,
        )


def train():
    MODELS_DIR.mkdir(exist_ok=True)

    df = pd.read_csv(DATA_PATH)
    available = [f for f in FEATURES if f in df.columns]
    missing   = [f for f in FEATURES if f not in df.columns]
    if missing:
        print(f"Features not in training data (skipped): {missing}")
        print("Run python src/build_dataset.py to regenerate with all features.\n")

    X = df[available].fillna(0)
    y = df["label"]

    pipeline = Pipeline([
        ("imputer", SimpleImputer(strategy="constant", fill_value=0)),
        ("clf",     _make_clf()),
    ])

    cv     = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    scores = cross_val_score(pipeline, X, y, cv=cv, scoring="accuracy")
    print(f"Cross-validation accuracy: {scores.mean():.3f} ± {scores.std():.3f}")
    print(f"Per-fold scores: {[round(s, 3) for s in scores]}")

    pipeline.fit(X, y)

    model_path = MODELS_DIR / "logistic_regression.pkl"
    with open(model_path, "wb") as f:
        pickle.dump(pipeline, f)

    y_pred = pipeline.predict(X)
    report = classification_report(y, y_pred, target_names=["loss", "win"])
    acc    = accuracy_score(y, y_pred)

    estimator  = pipeline.named_steps["clf"]
    model_type = type(estimator).__name__

    metrics_text = (
        f"Model              : {model_type}\n"
        f"Features           : {len(available)}\n"
        f"Cross-val accuracy : {scores.mean():.3f} ± {scores.std():.3f}\n"
        f"Train accuracy     : {acc:.3f}\n\n"
        f"Classification report (train set):\n{report}"
    )
    (MODELS_DIR / "metrics.txt").write_text(metrics_text)
    print(f"\n{metrics_text}")
    print(f"Model saved → {model_path}")

    estimator = pipeline.named_steps["clf"]
    if hasattr(estimator, "feature_importances_"):
        print("\nFeature importances:")
        for feat, imp in sorted(zip(available, estimator.feature_importances_), key=lambda x: x[1], reverse=True):
            bar = "█" * int(imp * 200)
            print(f"  {feat:<25} {imp:.4f}  {bar}")
    elif hasattr(estimator, "coef_"):
        print("\nFeature coefficients (scaled):")
        for feat, coef in sorted(zip(available, estimator.coef_[0]), key=lambda x: abs(x[1]), reverse=True):
            print(f"  {feat:<25} {coef:+.4f}")


if __name__ == "__main__":
    train()
