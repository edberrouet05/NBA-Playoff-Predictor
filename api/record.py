"""How the picks did (season record) and the model cards, for every sport."""

from fastapi import FastAPI, HTTPException
import numpy as np

from api.common import (
    NFL_CURRENT_SEASON,
    ROOT,
    _nba_season_year,
)
from api.odds import (
    _pregame_odds,
    _pregame_odds_key,
    _value_bet,
)


def _sport_season_label(sport: str) -> str:
    if sport in ("nba", "nhl"):     # both run from fall to June: "2026-27"
        year = _nba_season_year()
        return f"{year - 1}-{str(year)[-2:]}"
    return str(NFL_CURRENT_SEASON if sport == "nfl" else 2026)


def _performance_payload(sport: str, log: list[dict]) -> dict:
    """How a sport's pre-game picks did this season: accuracy, log loss / Brier, by confidence, a
    calibration curve, accuracy day by day, and — on games with a stored pre-game line — the
    bookmakers' no-vig probabilities scored the same way, plus our value bets' record.

    Only fair picks count: frozen before the game, or the model on the pipeline's pre-game rows.
    A pick recomputed with today's team ratings (source "current") would know the result."""
    import datetime, json as _json, math
    fair = [g for g in log if g.get("source", "pregame") != "current"]
    games = sorted(fair, key=lambda g: (g["date"], str(g["game_id"])))
    n = len(games)

    def scores(rows: list[tuple[float, int]]) -> dict:
        """rows: (P(away wins), away won) → accuracy, log loss, Brier."""
        if not rows:
            return {"accuracy": None, "log_loss": None, "brier": None}
        clip = lambda p: min(max(p, 1e-6), 1 - 1e-6)
        return {
            "accuracy": round(sum((p >= 0.5) == bool(y) for p, y in rows) / len(rows), 4),
            "log_loss": round(-sum(y * math.log(clip(p)) + (1 - y) * math.log(1 - clip(p)) for p, y in rows) / len(rows), 4),
            "brier":    round(sum((p - y) ** 2 for p, y in rows) / len(rows), 4),
        }

    rows = [(g["away_win_prob"] / 100, int(g["actual_winner"] == g["away_team"])) for g in games]

    # By confidence of the pick
    by_conf = []
    for lo, hi in [(50, 55), (55, 60), (60, 65), (65, 70), (70, 80), (80, 101)]:
        sub = [g for g in games if lo <= g["predicted_prob"] < hi]
        if sub:
            by_conf.append({"lo": lo, "hi": min(hi, 100), "n": len(sub),
                            "correct": sum(g["correct"] for g in sub),
                            "accuracy": round(sum(g["correct"] for g in sub) / len(sub), 4),
                            "avg_prob": round(sum(g["predicted_prob"] for g in sub) / len(sub) / 100, 4)})

    # Calibration: both sides of every game, 10 equal-width bins (as models/*_metrics.json)
    sides = rows + [(1 - p, 1 - y) for p, y in rows]
    calibration = []
    for b in range(10):
        lo, hi = b / 10, (b + 1) / 10
        sub = [(p, y) for p, y in sides if lo <= p < hi or (b == 9 and p == 1.0)]
        if sub:
            calibration.append({"lo": lo, "hi": hi, "n": len(sub),
                                "predicted": round(sum(p for p, _ in sub) / len(sub), 4),
                                "actual": round(sum(y for _, y in sub) / len(sub), 4)})

    # Day by day
    by_day, total, correct = [], 0, 0
    for date in sorted({g["date"] for g in games}):
        day = [g for g in games if g["date"] == date]
        total += len(day)
        correct += sum(g["correct"] for g in day)
        by_day.append({"date": date, "games": len(day), "correct": sum(g["correct"] for g in day),
                       "cum_accuracy": round(correct / total, 4)})

    # Bookmakers, on games with a stored pre-game line (keyed by the Eastern date; a night game
    # can carry the next UTC date, so the day before is tried too)
    def line_for(g: dict) -> dict | None:
        for back in (0, 1):
            try:
                day = (datetime.date.fromisoformat(g["date"]) - datetime.timedelta(days=back)).isoformat()
            except ValueError:
                return None
            line = _pregame_odds.get(_pregame_odds_key(g["away_team"], g["home_team"], day))
            if line and line.get("away_odds") and line.get("home_odds"):
                return line
        return None

    market_rows, model_rows, bets = [], [], []
    for g, (p, y) in zip(games, rows):
        line = line_for(g)
        if not line:
            continue
        ia, ih = 1 / line["away_odds"], 1 / line["home_odds"]
        market_rows.append((ia / (ia + ih), y))
        model_rows.append((p, y))
        vb = _value_bet(g["away_win_prob"], g["home_win_prob"], line["away_odds"], line["home_odds"])
        if vb["value_side"]:
            won = (vb["value_side"] == "away") == bool(y)
            odds = line["away_odds"] if vb["value_side"] == "away" else line["home_odds"]
            bets.append(odds - 1 if won else -1.0)
    market = None
    if market_rows:
        market = {"n_games": len(market_rows), "model": scores(model_rows), "vegas": scores(market_rows),
                  "value_bets": {"n": len(bets), "won": sum(b > 0 for b in bets),
                                 "units": round(sum(bets), 2),
                                 "roi": round(sum(bets) / len(bets), 4) if bets else None}}

    # What testing promised: leave-one-season-out accuracy of the served model
    try:
        metrics = _json.loads((ROOT / "models" / f"{sport}_metrics.json").read_text(encoding="utf-8"))
        expected = round(metrics["logistic_regression"]["accuracy"] * 100, 2)
    except Exception:
        expected = None

    return {"sport": sport, "season": _sport_season_label(sport), "n_games": n,
            "frozen": sum(1 for g in games if g.get("source") == "frozen") if sport in ("nba", "nfl", "nhl") else None,
            "excluded": len(log) - n, "expected_accuracy": expected,
            "correct": sum(g["correct"] for g in games), **scores(rows),
            "by_confidence": by_conf, "calibration": calibration, "by_day": by_day, "market": market}


def _model_stats_payload(sport: str, features: list[str]) -> dict:
    """Model card for /api/{sport}/stats, read from models/{sport}_metrics.json
    (written by {sport}/train.py). Metrics are for the served logistic regression."""
    import json
    path = ROOT / "models" / f"{sport}_metrics.json"
    if not path.exists():
        raise HTTPException(status_code=503, detail=f"{sport} metrics not found — run {sport}/train.py")
    m = json.loads(path.read_text(encoding="utf-8"))
    lr = m.get("logistic_regression", {})
    per_season = lr.get("per_season", {})
    accs = list(per_season.values())
    return {
        "accuracy":     round(lr.get("accuracy", 0.0) * 100, 2),
        "cv_std":       round(float(np.std(accs)) * 100, 2) if accs else 0.0,
        "cv_folds":     [round(a * 100, 1) for a in accs],
        "n_rows":       m.get("n_rows", 0),
        "seasons":      m.get("seasons", []),
        "features":     features,
        "coefficients": m.get("coefficients", []),
        "log_loss":     lr.get("log_loss"),
        "brier":        lr.get("brier"),
        "calibration":  lr.get("calibration", []),
        "vegas":        lr.get("vegas"),
        "xgboost":      {k: m.get("xgboost", {}).get(k) for k in ("accuracy", "log_loss", "brier")},
    }
