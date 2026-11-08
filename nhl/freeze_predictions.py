"""Write down today's NHL pre-game predictions before puck drop.

Run by the freeze workflow ahead of the day's games. It
  1. pulls in what the deployed API already stored (predictions for games this run is too late
     for, pre-game odds) — the commit that follows redeploys the API and wipes the server's disk,
  2. predicts every game of the day that has not started (with ESPN's probable goalies) and
     records it,
then data/nhl/nhl_frozen_predictions.json is committed so every deploy starts from it.

    python nhl/freeze_predictions.py            # API_URL env var = deployed API (optional)
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api import main  # noqa: E402
from scripts.sync_deployed_state import sync  # noqa: E402


def main_() -> None:
    api_url = os.environ.get("API_URL", "")
    if api_url:
        sync(api_url)
    store = main._nhl_frozen
    before = dict(store.preds)
    for attempt in range(3):        # ESPN times out now and then — a missed run means unfrozen games
        try:
            main._nhl_day(main._nhl_today())    # records every game of the day that has not started
            break
        except Exception as e:
            print(f"Day fetch failed ({e}), attempt {attempt + 1}/3")
            if attempt == 2:
                raise
            time.sleep(10 * (attempt + 1))
    store.save()
    changed = sum(1 for k, v in store.preds.items() if before.get(k) != v)
    print(f"{len(store.preds)} frozen prediction(s), {changed} new or updated this run")


if __name__ == "__main__":
    main_()
