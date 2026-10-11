"""Write down this week's NFL pre-game predictions before kickoff.

Run by the freeze workflow ahead of each slate (Thursday, Sunday, Monday). It
  1. pulls in what the deployed API already stored (predictions for games this run is too late
     for, pre-game odds) — the commit that follows redeploys the API and wipes the server's disk,
  2. predicts every game that has not started and records it,
then data/nfl/nfl_frozen_predictions.json is committed so every deploy starts from it.

    python nfl/freeze_predictions.py            # API_URL env var = deployed API (optional)
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
    before = dict(main._nfl_frozen_preds)
    for attempt in range(3):        # ESPN times out now and then — a missed run means unfrozen games
        try:
            main._fetch_nfl_week()  # predicts upcoming games and records them
            break
        except Exception as e:
            print(f"Week fetch failed ({e}), attempt {attempt + 1}/3")
            if attempt == 2:
                raise
            time.sleep(10 * (attempt + 1))
    main._save_nfl_frozen_preds()
    changed = sum(1 for k, v in main._nfl_frozen_preds.items() if before.get(k) != v)
    print(f"{len(main._nfl_frozen_preds)} frozen prediction(s), {changed} new or updated this run")


if __name__ == "__main__":
    main_()
