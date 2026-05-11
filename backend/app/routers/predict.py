from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.ml.model import predict_series

router = APIRouter()

_STATS_PATH = Path(__file__).parent.parent.parent / "data" / "team_stats_2024_25_Regular_Season.csv"
_STAT_COLS = ["off_rtg", "def_rtg", "net_rtg", "pace", "win_pct", "pie"]

def _load_stats() -> pd.DataFrame:
    if not _STATS_PATH.exists():
        raise HTTPException(
            status_code=503,
            detail="Team stats not found. Run: python data/fetch_stats.py --no-rest",
        )
    return pd.read_csv(_STATS_PATH).set_index("team_name")


class MatchupRequest(BaseModel):
    team_a: str
    team_b: str


class MatchupResponse(BaseModel):
    team_a: str
    team_b: str
    team_a_win_prob: float
    team_b_win_prob: float


@router.get("/teams")
def get_teams() -> list[str]:
    return sorted(_load_stats().index.tolist())


@router.post("/predict", response_model=MatchupResponse)
def predict_matchup(body: MatchupRequest) -> MatchupResponse:
    stats = _load_stats()

    missing = [t for t in (body.team_a, body.team_b) if t not in stats.index]
    if missing:
        raise HTTPException(status_code=404, detail=f"Team(s) not found: {missing}")

    team_a = stats.loc[body.team_a, _STAT_COLS].to_dict()
    team_b = stats.loc[body.team_b, _STAT_COLS].to_dict()

    prob_a = predict_series(team_a, team_b)
    return MatchupResponse(
        team_a=body.team_a,
        team_b=body.team_b,
        team_a_win_prob=round(prob_a, 4),
        team_b_win_prob=round(1 - prob_a, 4),
    )
