"""
Step 5 — Visualize feature importance and prediction probabilities.

Charts produced (saved to plots/):
  1. feature_importance.png  — model coefficients bar chart
  2. feature_distributions.png — win vs loss distributions for each feature
  3. correlation_heatmap.png  — feature correlation matrix
  4. win_probability.png      — predicted win prob for every team in 2024-25

Usage:
    python nba/visualize.py
"""

import pickle
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

DATA_PATH  = Path(__file__).parent.parent / "data" / "processed" / "training_data.csv"
MODEL_PATH = Path(__file__).parent.parent / "models" / "logistic_regression.pkl"
RAW_DIR    = Path(__file__).parent.parent / "data" / "raw"
PLOTS_DIR  = Path(__file__).parent.parent / "plots"

FEATURES = [
    "off_rtg", "def_rtg", "net_rtg", "pace", "rest_days",
    "ts_pct", "tov_pct", "oreb_pct", "home",
    "win_streak", "srs", "point_diff", "fg3_rate", "ftr",
    "back_to_back", "travel_km", "prev_margin",
    "playoff_net_rtg",
]

sns.set_theme(style="darkgrid", palette="muted")


def load_model():
    with open(MODEL_PATH, "rb") as f:
        return pickle.load(f)


# ── Chart 1: Feature importance ──────────────────────────────────────────────
def plot_feature_importance(model):
    coefs = model.named_steps["clf"].coef_[0]
    df = pd.DataFrame({"feature": FEATURES, "coefficient": coefs})
    df = df.reindex(df["coefficient"].abs().sort_values(ascending=True).index)

    fig, ax = plt.subplots(figsize=(7, 4))
    colors = ["#e74c3c" if c > 0 else "#3498db" for c in df["coefficient"]]
    ax.barh(df["feature"], df["coefficient"], color=colors)
    ax.axvline(0, color="white", linewidth=0.8)
    ax.set_title("Feature Importance (Logistic Regression Coefficients)", fontsize=13)
    ax.set_xlabel("Coefficient (scaled)")
    plt.tight_layout()
    fig.savefig(PLOTS_DIR / "feature_importance.png", dpi=150)
    plt.close(fig)
    print("  ✓ feature_importance.png")


# ── Chart 2: Win vs loss distributions ───────────────────────────────────────
def plot_distributions():
    df = pd.read_csv(DATA_PATH)
    df["outcome"] = df["label"].map({1: "Win", 0: "Loss"})

    fig, axes = plt.subplots(5, 4, figsize=(18, 18))
    axes = axes.flatten()

    titles = {
        "off_rtg":    "Offensive Rating",
        "def_rtg":    "Defensive Rating",
        "net_rtg":    "Net Rating",
        "pace":       "Pace",
        "rest_days":  "Rest Days",
        "ts_pct":     "True Shooting %",
        "tov_pct":    "Turnover %",
        "oreb_pct":   "Off. Rebound %",
        "home":       "Home Court",
        "win_streak": "Win Streak",
        "srs":        "SRS",
        "point_diff": "Point Differential",
        "fg3_rate":    "3PT Rate",
        "ftr":         "Free Throw Rate",
        "back_to_back":    "Back-to-Back",
        "travel_km":       "Travel Distance (km)",
        "prev_margin":     "Previous Game Margin",
        "playoff_net_rtg": "Prev Season Playoff Net Rtg",
    }

    for ax, feat in zip(axes, FEATURES):
        sns.kdeplot(
            data=df, x=feat, hue="outcome",
            fill=True, alpha=0.4, ax=ax,
            palette={"Win": "#2ecc71", "Loss": "#e74c3c"},
        )
        ax.set_title(titles[feat])
        ax.set_xlabel("")

    for ax in axes[len(FEATURES):]:
        ax.set_visible(False)

    fig.suptitle("Feature Distributions — Playoff Winners vs Losers", fontsize=14, y=1.01)
    plt.tight_layout()
    fig.savefig(PLOTS_DIR / "feature_distributions.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  ✓ feature_distributions.png")


# ── Chart 3: Correlation heatmap ─────────────────────────────────────────────
def plot_heatmap():
    df = pd.read_csv(DATA_PATH)
    corr = df[FEATURES + ["label"]].corr()

    fig, ax = plt.subplots(figsize=(6, 5))
    sns.heatmap(
        corr, annot=True, fmt=".2f", cmap="coolwarm",
        center=0, linewidths=0.5, ax=ax,
    )
    ax.set_title("Feature Correlation Matrix", fontsize=13)
    plt.tight_layout()
    fig.savefig(PLOTS_DIR / "correlation_heatmap.png", dpi=150)
    plt.close(fig)
    print("  ✓ correlation_heatmap.png")


# ── Chart 4: 2024-25 win probabilities ───────────────────────────────────────
def plot_win_probabilities(model):
    df = pd.read_csv(RAW_DIR / "reg_season_2024_25.csv")

    # Use round-1 defaults (shows raw team quality)
    df["rest_days"]  = 5
    df["home"]       = 1
    df["win_streak"]   = df.get("win_streak", 0)
    df["srs"]          = df.get("srs", 0.0)
    df["point_diff"]   = df.get("point_diff", 0.0)
    df["fg3_rate"]     = df.get("fg3_rate", 0.35)
    df["ftr"]          = df.get("ftr", 0.25)
    df["back_to_back"]    = 0
    df["travel_km"]       = 0
    df["prev_margin"]     = 0
    df["playoff_net_rtg"] = df.get("playoff_net_rtg", 0.0)
    probs = model.predict_proba(df[FEATURES])[:, 1]
    df["win_prob"] = probs
    df = df.sort_values("win_prob", ascending=True)

    fig, ax = plt.subplots(figsize=(9, 10))
    bars = ax.barh(
        df["team_name"], df["win_prob"],
        color=sns.color_palette("RdYlGn", len(df)),
    )
    ax.axvline(0.5, color="white", linewidth=1, linestyle="--")
    ax.set_xlim(0, 1)
    ax.set_xlabel("Predicted Win Probability")
    ax.set_title("2024–25 Playoff Series Win Probability\n(round 1, 5 rest days)", fontsize=13)

    for bar, prob in zip(bars, df["win_prob"]):
        ax.text(
            bar.get_width() + 0.01, bar.get_y() + bar.get_height() / 2,
            f"{prob:.0%}", va="center", fontsize=8,
        )

    plt.tight_layout()
    fig.savefig(PLOTS_DIR / "win_probability.png", dpi=150)
    plt.close(fig)
    print("  ✓ win_probability.png")


def main():
    PLOTS_DIR.mkdir(exist_ok=True)
    model = load_model()

    print("Generating plots …")
    plot_feature_importance(model)
    plot_distributions()
    plot_heatmap()
    plot_win_probabilities(model)
    print(f"\nAll plots saved → {PLOTS_DIR}")


if __name__ == "__main__":
    main()
