"""Pull what the deployed API wrote to its own disk into the repo before a workflow commits.

Every commit redeploys the API, and a redeploy wipes the server's disk — so the stored pre-game
betting lines (data/pregame_odds.json) and frozen NFL predictions
(data/nfl/nfl_frozen_predictions.json) the server saved since the last commit would be lost.
Run this right before `git add` in every workflow that commits.

    API_URL=https://… python scripts/sync_deployed_state.py
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api import main  # noqa: E402


def fetch(api_url: str, path: str) -> dict | None:
    try:
        req = urllib.request.Request(f"{api_url.rstrip('/')}{path}", headers={"User-Agent": "sync-deployed-state"})
        with urllib.request.urlopen(req, timeout=90) as resp:   # Render may be waking up
            return json.loads(resp.read())
    except Exception as e:
        print(f"Could not read {path} from the deployed API ({e}) — keeping the repo copy")
        return None


def sync(api_url: str) -> None:
    preds = fetch(api_url, "/api/nfl/frozen_predictions")
    if preds:
        before = dict(main._nfl_frozen_preds)
        main._merge_nfl_frozen_preds(main._nfl_frozen_preds, preds)
        main._save_nfl_frozen_preds()
        print(f"NFL frozen predictions: {sum(1 for k, v in main._nfl_frozen_preds.items() if before.get(k) != v)} new from the server")

    odds = fetch(api_url, "/api/pregame_odds")
    if odds:
        before = dict(main._pregame_odds)
        main._merge_pregame_odds(main._pregame_odds, odds)
        main._save_pregame_odds(main._pregame_odds)
        print(f"Pre-game odds: {sum(1 for k, v in main._pregame_odds.items() if before.get(k) != v)} new from the server")


if __name__ == "__main__":
    url = os.environ.get("API_URL", "")
    if not url:
        sys.exit("API_URL is not set")
    sync(url)
