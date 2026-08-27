"""FastAPI application entry point."""

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.errors import RequestIDMiddleware, install_exception_handlers


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

    @application.get("/api/v1/health")
    async def health() -> dict[str, str]:
        """Report that the API process is available."""
        return {"status": "ok"}

    return application


app = create_app()
