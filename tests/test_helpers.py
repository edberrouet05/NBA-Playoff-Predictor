"""Search, team-name matching and the frozen-prediction store."""
import json


def test_team_names_match_across_sources(api):
    n = api._normalize_team
    assert n("Montréal Canadiens") == n("Montreal Canadiens")
    assert n("St. Louis Blues") == n("St Louis Blues")
    assert n("Utah Hockey Club") == n("Utah Mammoth")
    assert api._pregame_odds_key("St. Louis Blues", "Utah Mammoth", "2026-11-09T00:30:00Z") == \
        "st louis blues|utah mammoth|2026-11-08"     # Eastern date


def test_player_names_lose_punctuation(api):
    assert api._norm_name("Ja'Marr Chase") == "jamarr chase"
    assert api._norm_name("Luka Dončić") == "luka doncic"
    assert api._norm_name("C.J. Stroud") == "cj stroud"
    assert api._norm_name("Josh Hines-Allen") == "josh hines allen"


def _player(name, star=0.0):
    norm = name.lower().replace("'", "")
    return {"league": "nfl", "id": name, "name": name, "norm": norm, "tokens": norm.split(),
            "team": "X", "team_name": "X", "position": "WR", "headshot": None, "star": star}


def test_search_typos_and_stars(api):
    index = [_player("Jamarr Chase", star=3.0), _player("Jamaree Bouyea"), _player("Patrick Mahomes", star=2.0),
             _player("Chase Burns", star=0.5)]
    names = lambda q: [p["name"] for p in api._search_index(q, index)]
    assert names("jamar")[0] == "Jamarr Chase"          # start of a word + star
    assert names("mahomse") == ["Patrick Mahomes"]      # close spelling
    assert names("chase")[0] == "Jamarr Chase"          # whole word + star beats first-name match
    assert names("zzz") == []


def test_frozen_store_merges_and_keeps_the_latest(api, tmp_path):
    path = tmp_path / "frozen.json"
    store = api.FrozenPredictions(path)
    store.record("1", {"home_team": "H", "away_team": "A", "home_win_prob": 60.0})
    assert json.loads(path.read_text())["1"]["home_win_prob"] == 60.0

    # Another copy (e.g. the deployed server's) with a later freeze of the same game wins
    other = {"1": {"home_team": "H", "away_team": "A", "home_win_prob": 55.0, "frozen_at": "2999-01-01T00:00:00Z"},
             "2": {"home_team": "C", "away_team": "D", "home_win_prob": 40.0, "frozen_at": "2026-01-01T00:00:00Z"}}
    store.merge(store.preds, other)
    store.save()
    saved = json.loads(path.read_text())
    assert saved["1"]["home_win_prob"] == 55.0 and "2" in saved
    assert api.FrozenPredictions(path).get("2")["home_team"] == "C"


def test_nhl_rest_days(api):
    assert api._nhl_rest("2026-11-07", "2026-11-08") == 1          # back-to-back
    assert api._nhl_rest("2026-11-01", "2026-11-08") == api.NHL_MAX_REST
    assert api._nhl_rest("", "2026-11-08") == api.NHL_MAX_REST


def test_game_day_turns_over_at_5am_eastern(api, monkeypatch):
    import datetime, zoneinfo
    et = zoneinfo.ZoneInfo("America/New_York")

    class Clock(datetime.datetime):
        now_value = None

        @classmethod
        def now(cls, tz=None):
            return cls.now_value.astimezone(tz)

    monkeypatch.setattr(datetime, "datetime", Clock)
    Clock.now_value = datetime.datetime(2026, 11, 11, 0, 40, tzinfo=et)     # overtime past midnight
    assert api._game_day() == datetime.date(2026, 11, 10)
    Clock.now_value = datetime.datetime(2026, 11, 11, 9, 0, tzinfo=et)
    assert api._game_day() == datetime.date(2026, 11, 11)
