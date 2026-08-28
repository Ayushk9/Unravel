"""FastAPI application entry point."""

from fastapi import Depends, FastAPI

from app.core.auth import get_current_household, seed_development_household
from app.core.config import get_settings
from app.core.errors import RequestIDMiddleware, install_exception_handlers
from app.api.jobs import router as jobs_router
from app.api.documents import router as documents_router
from app.api.policies import router as policies_router


def create_app() -> FastAPI:
    """Create the API application and register its shared infrastructure."""
    get_settings()
    application = FastAPI(
        title="Unravel API",
        version="0.1.0",
        debug=False,
    )
    application.add_middleware(RequestIDMiddleware)
    install_exception_handlers(application)
    application.include_router(jobs_router)
    application.include_router(documents_router)
    application.include_router(policies_router)

    @application.on_event("startup")
    async def seed_dev_identity() -> None:
        """Ensure the dev-only frontend identity has a household after migration."""
        await seed_development_household()

    @application.get("/api/v1/health", dependencies=[Depends(get_current_household)])
    async def health() -> dict[str, str]:
        """Report that the API process is available."""
        return {"status": "ok"}

    return application


app = create_app()
