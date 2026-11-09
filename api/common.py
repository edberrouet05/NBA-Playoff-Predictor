"""Shared by every module: the FastAPI app, paths, background cache refresh, parallel calls."""

from pathlib import Path
import os
import threading as _threading

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware


# The Odds API key — environment only (Render: service env vars). Without it, odds are skipped.
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")

ROOT                = Path(__file__).parent.parent

app = FastAPI(title="NBA Playoff Predictor")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # same as the previous Render backend: Vercel previews + prod + localhost
    allow_methods=["*"],
    allow_headers=["*"],
)

_swr_local = _threading.local()
_swr_busy: set[str] = set()
_swr_lock = _threading.Lock()


def _serve_stale(key: str, endpoint) -> bool:
    """Stale-while-revalidate for a cached endpoint whose TTL has run out.

    Returns True when the caller should answer with its expired cache right away, while
    `endpoint()` recomputes it on a background thread (one at a time per key). Returns False
    inside that background call, so the endpoint does the real work there."""
    if getattr(_swr_local, "key", None) == key:
        return False
    with _swr_lock:
        if key in _swr_busy:
            return True
        _swr_busy.add(key)

    def run():
        _swr_local.key = key
        try:
            endpoint()
        except Exception:
            pass
        finally:
            _swr_local.key = None
            with _swr_lock:
                _swr_busy.discard(key)

    _threading.Thread(target=run, daemon=True).start()
    return True


def _parallel(*calls):
    """Run independent zero-argument calls on threads and return their results in order
    (most pages wait on several ESPN requests that do not depend on each other).
    An exception is re-raised from the result that failed."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = [pool.submit(c) for c in calls]
        return [f.result() for f in futures]


def _nba_season_year(day=None) -> int:
    """ESPN's NBA season year, i.e. the year it ends (2026-27 → 2027). A new season from August."""
    import datetime
    d = day or datetime.date.today()
    return d.year + 1 if d.month >= 8 else d.year
NFL_CURRENT_SEASON = 2026
