"""Shared test fixtures.

The environment variables are set before anything from `app` is imported,
because importing app.main builds the application and reads the settings.
A real environment variable takes priority over apps/api/.env, so these
values guarantee the tests never see real credentials or a real database.
"""

from __future__ import annotations

import os

os.environ["DATABASE_URL"] = "postgresql+asyncpg://test:test@localhost:5432/unravel_test"
os.environ["SUPABASE_JWT_SECRET"] = "test-jwt-secret-that-is-long-enough-for-hs256"
os.environ["GEMINI_API_KEY"] = "test-gemini-key"
os.environ["ENVIRONMENT"] = "test"

from typing import Literal  # noqa: E402

import pytest  # noqa: E402
from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.errors import ApiError  # noqa: E402
from app.main import API_PREFIX, create_app  # noqa: E402
from app.schemas.base import ApiModel  # noqa: E402
from app.schemas.errors import FieldError  # noqa: E402


class _ClaimInput(ApiModel):
    claim_type: Literal["cashless", "reimbursement"]
    claimed_amount: int


class _NullableOutput(ApiModel):
    name: str
    settled_amount: int | None


def _test_only_router() -> APIRouter:
    """Routes that exist only inside the test app, to trigger each error path."""
    router = APIRouter(prefix="/_test")

    @router.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail that must not leak")

    @router.post("/validate")
    async def validate(body: _ClaimInput) -> _ClaimInput:
        return body

    @router.get("/nullable")
    async def nullable() -> _NullableOutput:
        return _NullableOutput(name="claim", settled_amount=None)

    @router.get("/conflict")
    async def conflict() -> None:
        raise ApiError(
            409,
            "illegal_transition",
            "That transition isn't allowed.",
            field_errors=[FieldError(field="to_state", message="resolved")],
        )

    return router


@pytest.fixture
def app() -> FastAPI:
    application = create_app()
    application.include_router(_test_only_router(), prefix=API_PREFIX)
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    # raise_server_exceptions=False makes the test client behave like a real
    # client: an unhandled exception becomes a 500 response instead of being
    # re-raised inside the test.
    return TestClient(app, raise_server_exceptions=False)
