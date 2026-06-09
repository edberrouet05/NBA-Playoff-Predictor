import os

import uvicorn
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


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))

