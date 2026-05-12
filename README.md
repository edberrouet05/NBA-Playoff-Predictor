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
