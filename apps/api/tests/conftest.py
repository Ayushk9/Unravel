"""Shared test fixtures.

The environment variables are set before anything from `app` is imported,
because importing app.main builds the application and reads the settings.
A real environment variable takes priority over apps/api/.env, so these
values guarantee the tests never see real credentials or a real database.
"""

from __future__ import annotations

import os

os.environ["DATABASE_URL"] = "postgresql+asyncpg://test:test@localhost:5432/unravel_test"
os.environ["SUPABASE_URL"] = "https://test-project.supabase.co"
os.environ["GEMINI_API_KEY"] = "test-gemini-key"
os.environ["STORAGE_BACKEND"] = "local"
# A folder that is never created: tests that store files use their own storage.
os.environ["LOCAL_STORAGE_DIR"] = "/nonexistent/unravel-test-storage"
os.environ["CORS_ALLOWED_ORIGINS"] = "http://localhost:5173"
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


# --- fixtures for tests that need a real database (see tests/db.py) ---

from collections.abc import Iterator  # noqa: E402
from uuid import UUID  # noqa: E402

from tests import db as test_db  # noqa: E402


@pytest.fixture(scope="session")
def database() -> Iterator[test_db.Database]:
    url = test_db.test_database_url()
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set; tests that need a real database are skipped")
    created = test_db.create_database(url)
    try:
        yield created
    finally:
        test_db.drop_database(created)


@pytest.fixture
def db(database: test_db.Database) -> test_db.Database:
    return database


@pytest.fixture
def household_id(db: test_db.Database) -> UUID:
    return db.create_household()


@pytest.fixture
def api(db: test_db.Database, household_id: UUID) -> Iterator[test_db.ApiTester]:
    tester = test_db.ApiTester(db, household_id)
    yield tester
    # The queue is shared by every household. Draining it here means no job
    # from this test is still waiting when the next test starts.
    tester.finish_jobs()
    db.execute("DELETE FROM job WHERE household_id = :h AND status = 'queued'", h=household_id)
