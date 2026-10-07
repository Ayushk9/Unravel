"""Application factory.

Run from apps/api:
    ../../.venv/bin/python -m uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.auth import TokenVerifier
from app.core.config import Settings, get_settings
from app.core.errors import UnhandledErrorMiddleware, register_error_handlers
from app.core.request_id import REQUEST_ID_HEADER, RequestIdMiddleware
from app.db.session import create_engine, create_session_factory
from app.jobs.queue import delete_expired_jobs, recover_interrupted_jobs
from app.jobs.runner import JobRunner
from app.storage.supabase import SupabaseStorage

API_PREFIX = "/api/v1"

logger = logging.getLogger("unravel.api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Code before `yield` runs once at startup; code after it at shutdown."""
    session_factory = app.state.session_factory
    runner: JobRunner = app.state.runner

    # 1. Any job still marked `running` belonged to a server that is gone
    #    (crash or restart). Fail it, so it does not stay "running" forever.
    interrupted = await recover_interrupted_jobs(session_factory)
    # 2. Finished jobs are kept for 24 hours, then removed.
    expired = await delete_expired_jobs(session_factory)
    if interrupted or expired:
        logger.warning("Startup: failed %s interrupted job(s), deleted %s expired job(s).", interrupted, expired)
    # 3. Jobs that were still `queued` lost nothing. Start working on them.
    await runner.wake()

    yield

    await runner.shutdown()
    # Close pooled database connections cleanly.
    await app.state.engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. Tests pass their own settings; production reads the environment."""
    settings = settings or get_settings()

    app = FastAPI(title="Unravel API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    # None of these opens a network connection until first used.
    app.state.engine = create_engine(settings.database_url)
    app.state.session_factory = create_session_factory(app.state.engine)
    app.state.token_verifier = TokenVerifier(settings.supabase_url)
    app.state.storage = SupabaseStorage(
        settings.supabase_url, settings.supabase_service_role_key, settings.storage_bucket
    )
    app.state.runner = JobRunner(
        session_factory=app.state.session_factory, storage=app.state.storage, settings=settings
    )

    # Middleware wraps the app in layers, and the LAST one added is the
    # OUTERMOST. Reading from the outside in, a request passes through:
    #   RequestIdMiddleware      -> every response, including errors, has an id
    #   CORSMiddleware           -> answers browser preflight requests
    #   UnhandledErrorMiddleware -> its 500 response travels back out through CORS
    #   the routes
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
        # Headers the browser lets the web app's JavaScript read.
        expose_headers=[REQUEST_ID_HEADER, "Retry-After"],
    )
    app.add_middleware(RequestIdMiddleware)

    register_error_handlers(app)
    app.include_router(api_router, prefix=API_PREFIX)
    return app


app = create_app()
