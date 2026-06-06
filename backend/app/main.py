from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import predict, game_data, schedule, mlb

app = FastAPI(title="NBA Playoff Predictor API")

app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
)

app.include_router(predict.router, prefix="/api")
app.include_router(game_data.router, prefix="/api")
app.include_router(schedule.router, prefix="/api")
app.include_router(mlb.router, prefix="/api/mlb")


@app.get("/health")
def health():
        return {"status": "ok"}
    
