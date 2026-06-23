from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/schedule")
def get_schedule(days: int = 7):
    """Return upcoming NBA games. Stub — returns empty schedule."""
    return {"schedule": []}
