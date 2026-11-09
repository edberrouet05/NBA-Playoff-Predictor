"""In-game win probabilities, value bets and the season record: the math behind the numbers."""
import pytest


# ── NBA live win probability ───────────────────────────────────────────────────

def test_nba_live_starts_at_the_pregame_pick(api):
    for p in (0.3, 0.5, 0.72):
        assert api._nba_live_prob(p, 0, 48) == pytest.approx(p, abs=1e-3)


def test_nba_live_follows_the_score(api):
    behind, tied, ahead = (api._nba_live_prob(0.5, m, 24) for m in (-10, 0, 10))
    assert behind < tied < ahead
    assert tied == pytest.approx(0.5, abs=1e-3)


def test_nba_live_lead_matters_more_late(api):
    assert api._nba_live_prob(0.5, 6, 2) > api._nba_live_prob(0.5, 6, 30)


def test_nba_live_final(api):
    assert api._nba_live_prob(0.2, 1, 0) == 1.0
    assert api._nba_live_prob(0.8, -1, 0) == 0.0


# ── NHL live win probability ───────────────────────────────────────────────────

def test_nhl_live_starts_at_the_pregame_pick(api):
    for p in (0.35, 0.5, 0.65):
        assert api._nhl_live_prob(p, 0, 60) == pytest.approx(p, abs=2e-3)


def test_nhl_live_follows_the_score_and_clock(api):
    assert api._nhl_live_prob(0.5, 1, 30) > 0.5 > api._nhl_live_prob(0.5, -1, 30)
    assert api._nhl_live_prob(0.5, 1, 2) > api._nhl_live_prob(0.5, 1, 40)


def test_nhl_tied_at_the_end_goes_to_overtime(api):
    # Halfway between a coin flip and the pre-game pick
    assert api._nhl_live_prob(0.7, 0, 0) == pytest.approx(0.6)
    assert api._nhl_live_prob(0.7, 0, 0, overtime=True) == pytest.approx(0.6)
    assert api._nhl_live_prob(0.3, 2, 0) == 1.0


def test_nhl_strength_reuse_gives_the_same_number(api):
    s = api._nhl_strength(0.62)
    for margin, left in ((0, 45), (1, 12), (-2, 8)):
        assert api._nhl_live_prob(0.62, margin, left, strength=s) == pytest.approx(api._nhl_live_prob(0.62, margin, left))


def test_nhl_clock(api):
    assert api._nhl_minutes_left(1, "20:00") == 60
    assert api._nhl_minutes_left(2, "10:30") == pytest.approx(30.5)
    assert api._nhl_minutes_left(4, "3:00") == 0


# ── Value bets ─────────────────────────────────────────────────────────────────

def test_value_bet_removes_the_bookmaker_margin(api):
    out = api._value_bet(50.0, 50.0, 1.9, 1.9)
    assert out["away_market_prob"] == pytest.approx(50.0)
    assert out["value_side"] is None


def test_value_bet_flags_a_big_edge(api):
    out = api._value_bet(60.0, 40.0, 2.6, 1.55)   # market ≈ 37 % for the away team
    assert out["value_side"] == "away"
    assert out["value_edge"] >= api.VALUE_EDGE_MIN
    assert out["value_ev"] == pytest.approx(0.6 * 2.6 - 1, abs=1e-3)


def test_value_bet_without_odds(api):
    assert api._value_bet(55.0, 45.0, None, 1.8)["value_side"] is None


# ── Season record ──────────────────────────────────────────────────────────────

def _game(i, away_prob, away_won, source="pregame"):
    winner = "A" if away_won else "H"
    pick = "A" if away_prob >= 50 else "H"
    return {"game_id": str(i), "date": f"2026-10-{10 + i % 20:02d}", "away_team": "A", "home_team": "H",
            "away_win_prob": away_prob, "home_win_prob": 100 - away_prob, "predicted_winner": pick,
            "predicted_prob": max(away_prob, 100 - away_prob), "actual_winner": winner,
            "correct": pick == winner, "source": source}


def test_performance_scores_only_fair_picks(api):
    log = [_game(1, 70, True), _game(2, 70, False), _game(3, 40, False), _game(4, 90, False, source="current")]
    out = api._performance_payload("nhl", log)
    assert out["n_games"] == 3 and out["excluded"] == 1
    assert out["correct"] == 2
    assert out["accuracy"] == pytest.approx(2 / 3, abs=1e-4)
    assert 0 < out["log_loss"] < 1 and 0 < out["brier"] < 0.5


def test_performance_calibration_bins(api):
    log = [_game(i, 65, i % 3 != 0) for i in range(30)]
    out = api._performance_payload("nhl", log)
    # Both sides of every game are binned
    assert sum(b["n"] for b in out["calibration"]) == 60
    assert out["by_confidence"][0]["n"] == 30
