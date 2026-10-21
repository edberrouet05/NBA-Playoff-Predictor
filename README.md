# NBA Playoff Predictor

## Project Structure

```
NBA-Playoff-Predictor/
├── backend/
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py          # FastAPI app entry point
│   │   ├── routers/         # API route handlers (step 4)
│   │   └── ml/              # Model training & inference (step 3)
│   └── data/
│       └── fetch_stats.py   # nba_api data fetching script
└── frontend/                # Next.js app (step 5)
```

## Setup

### Backend

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
pip install -r requirements.txt
```

### Fetch team stats

```bash
# Regular season stats (default)
python data/fetch_stats.py --season 2025-26

# Playoff stats, skip rest-day calculation
python data/fetch_stats.py --season 2025-26 --season-type Playoffs --no-rest
```

Output CSV is saved to `backend/data/`.

### Run API server

```bash
uvicorn app.main:app --reload
```

## NBA / NFL / MLB models

Each sport has a data pipeline and a training script (run from the repo root):

```bash
python nba/pipeline.py && python nba/train.py   # ESPN: Elo, recent point margin, roster strength, rest / back-to-backs
python nfl/pipeline.py && python nfl/train.py   # nflverse data: Elo, EPA, starting QBs, rest/travel
python mlb/pipeline.py && python mlb/train.py   # MLB Stats API: Elo, starter FIP to date, bullpen, recent offense
```

- Features are computed game by game from information available **before** each game.
- Validation is leave-one-season-out; `models/{sport}_metrics.json` holds accuracy,
  log loss, Brier score, the calibration curve and (NFL) a comparison with the Vegas closing line.
- Raw downloads are cached in `data/{nba,nfl,mlb}/raw/` (git-ignored); only the current season is re-fetched.
- NBA and NFL predictions are frozen before tip-off / kickoff (`data/{nba,nfl}/*_frozen_predictions.json`),
  so a played game is never re-predicted with later data.

`.github/workflows/refresh-data.yml` runs these automatically (NBA and MLB daily with a Monday
retrain, NFL every Tuesday) and commits the refreshed CSVs / models, which redeploys the API.
It can also be started by hand from the repo's Actions tab. `freeze-nba-predictions.yml` and
`freeze-nfl-predictions.yml` write down the pre-game predictions before each slate.

The NBA model (`nba/`) replaced the original playoff-only model (`nba/fetch_data.py`,
`nba/build_dataset.py`, `models/logistic_regression.pkl`), which used stats.nba.com and
full-season stats.
