"""
CourtEdge API: game predictions for the NBA, NFL, MLB and NHL.

The app is assembled from one module per area (imported in dependency order):
  common    FastAPI app, paths, background cache refresh, parallel calls
  espn      ESPN's public API helpers
  odds      betting odds and value bets
  record    season record and model cards
  nba, mlb, nfl, nhl    one module per sport
  teams     team pages, live-game indicator, search
  players   player pages

Usage:
    uvicorn api.main:app --reload --reload-dir api
"""

import threading as _threading

from api.common import (
    app,
)
from api.nba import (
    get_bracket,
    get_nba_projections,
    get_nba_standings,
    get_predictions_log,
)
from api.mlb import (
    get_mlb_predictions_log,
    get_mlb_season_recap,
    get_mlb_standings,
)
from api.nfl import (
    get_nfl_power,
    get_nfl_predictions_log,
    get_nfl_projections,
    get_nfl_standings,
)
from api.nhl import (
    get_nhl_predictions_log,
    get_nhl_projections,
)
from api.teams import (
    _get_player_index,
)

# Every module's names are also reachable as `api.main.<name>` (scripts and tests use them)
from api import common, espn, odds, record, nba, mlb, nfl, nhl, teams, players  # noqa: E402

for _module in (common, espn, odds, record, nba, mlb, nfl, nhl, teams, players):
    globals().update({k: v for k, v in vars(_module).items() if not k.startswith("__")})


# ── Warm-up: compute the slow pages as soon as the server starts ──────────────

@app.on_event("startup")
def _warm_caches() -> None:
    """Fill the slowest caches on a background thread, so the first visitor after a deploy or a
    restart does not wait for them (the MLB log alone takes several seconds)."""
    def run():
        for fn in (get_predictions_log, get_nba_standings, get_nba_projections, get_bracket,
                   get_nfl_predictions_log, get_nfl_standings, get_nfl_projections, get_nfl_power,
                   get_mlb_standings, get_mlb_predictions_log, get_mlb_season_recap,
                   get_nhl_predictions_log, get_nhl_projections, _get_player_index):
            try:
                fn()
            except Exception:
                pass
    _threading.Thread(target=run, daemon=True).start()
