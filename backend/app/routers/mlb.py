from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/today")
def get_mlb_today():
    """Return today's MLB games. Stub — returns empty game list."""
    return {"games": []}


@router.get("/teams")
def get_mlb_teams():
    """Return MLB team names. Stub — returns empty list."""
    return []


@router.get("/predictions_log")
def get_mlb_predictions_log(n: int = 10):
    """Return recent MLB prediction results. Stub — returns empty log."""
    return {"log": []}
