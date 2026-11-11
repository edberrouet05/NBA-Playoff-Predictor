"""The trained models match what the API feeds them, and give sane probabilities."""
import json

import pandas as pd
import pytest

from conftest import ROOT

SPORTS = {
    # sport: (API feature list name, current-season pre-game rows)
    "nba": ("FEATURES", "data/nba/nba_game_features_current.csv"),
    "nfl": ("NFL_FEATURES", None),
    "mlb": ("MLB_FEATURES", "data/mlb/mlb_game_features_current.csv"),
    "nhl": ("NHL_FEATURES", "data/nhl/nhl_game_features_current.csv"),
}


@pytest.mark.parametrize("sport", SPORTS)
def test_api_features_match_the_trained_model(api, sport):
    metrics = json.loads((ROOT / "models" / f"{sport}_metrics.json").read_text(encoding="utf-8"))
    assert getattr(api, SPORTS[sport][0]) == metrics["features"]


@pytest.mark.parametrize("sport", SPORTS)
def test_validated_accuracy_is_plausible(sport):
    """Leave-one-season-out accuracy: better than a coin flip, not suspiciously high (a leak)."""
    metrics = json.loads((ROOT / "models" / f"{sport}_metrics.json").read_text(encoding="utf-8"))
    acc = metrics["logistic_regression"]["accuracy"]
    assert 0.53 < acc < 0.75


@pytest.mark.parametrize("sport", [s for s, (_, path) in SPORTS.items() if path])
def test_model_scores_this_seasons_rows(api, sport):
    import pickle
    feats = getattr(api, SPORTS[sport][0])
    rows = pd.read_csv(ROOT / SPORTS[sport][1])
    with open(ROOT / "models" / f"{sport}_logistic_regression.pkl", "rb") as f:
        model = pickle.load(f)
    p = model.predict_proba(rows[feats].fillna(rows[feats].median()).head(200))[:, 1]
    assert ((p > 0.02) & (p < 0.98)).all()


def test_nhl_pair_probability_is_symmetric(api):
    """Swapping the two teams' rows flips the probability (the two rows are normalized)."""
    rows = api._nhl_state_rows("Boston Bruins", "Florida Panthers", "2026-11-08")
    assert rows is not None
    p = api._nhl_pair_prob(*rows)
    assert 0 < p < 1
    assert api._nhl_pair_prob(rows[1], rows[0]) == pytest.approx(1 - p)


@pytest.mark.parametrize("sport, away, home, low, high", [
    ("nba", "Miami Heat", "Utah Jazz", 190, 260),
    ("nfl", "Buffalo Bills", "Kansas City Chiefs", 30, 65),
])
def test_projected_score_is_plausible_and_agrees_with_the_pick(api, sport, away, home, low, high):
    project = {"nba": lambda p: api._nba_projected_score(away, home, p),
               "nfl": lambda p: api._nfl_projected_score(away, home, p * 100)}[sport]
    for p_home in (0.3, 0.7):
        pr = project(p_home)
        assert low < pr["total"] < high
        assert pr["away"] + pr["home"] == pytest.approx(pr["total"], abs=1)
        assert (pr["home"] > pr["away"]) == (p_home > 0.5)
