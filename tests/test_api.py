"""API endpoints that answer from the repo's own data files (no outside requests)."""
import pytest


def test_health(client):
    assert client.get("/api/health").json() == {"ok": True}


@pytest.mark.parametrize("path", ["/api/stats", "/api/nfl/stats", "/api/mlb/stats", "/api/nhl/stats"])
def test_model_cards(client, path):
    r = client.get(path)
    assert r.status_code == 200
    d = r.json()
    assert 50 < d["accuracy"] < 75
    assert len(d["features"]) == len(d["coefficients"])


def test_nhl_standings(client):
    d = client.get("/api/nhl/standings").json()
    divisions = {x["division"] for x in d["divisions"]}
    assert divisions == {"Atlantic", "Metropolitan", "Central", "Pacific"}
    teams = [t for x in d["divisions"] for t in x["teams"]]
    assert len(teams) == 32
    for div in d["divisions"]:
        pts = [t["pts"] for t in div["teams"]]
        assert pts == sorted(pts, reverse=True)
    # Two points a win, one an overtime loss
    for t in teams:
        assert t["pts"] == 2 * t["w"] + t["otl"]


def test_unknown_routes(client):
    assert client.get("/api/team/xyz/abc").status_code == 404
    assert client.get("/api/player/nba/not-a-number").status_code == 404
    assert client.get("/api/nhl/game/abc").status_code == 404


def test_search_needs_two_letters(client):
    assert client.get("/api/search?q=a").json()["players"] == []
