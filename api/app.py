"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes.players import router as players_router
from api.routes.teams import router as teams_router
from common.settings import get_settings


def create_app() -> FastAPI:
    get_settings()
    app = FastAPI(title="NFL Analytics", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ],
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    app.include_router(teams_router, prefix="/api")
    app.include_router(players_router, prefix="/api")
    return app


app = create_app()
