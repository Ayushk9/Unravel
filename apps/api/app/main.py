"""Application factory.

Run from apps/api:
    ../../.venv/bin/python -m uvicorn app.main:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import register_error_handlers
from app.core.request_id import RequestIdMiddleware

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. Tests pass their own settings; production reads the environment."""
    app = FastAPI(title="Unravel API", version="0.1.0")
    app.state.settings = settings or get_settings()

    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)
    app.include_router(api_router, prefix=API_PREFIX)
    return app


app = create_app()
