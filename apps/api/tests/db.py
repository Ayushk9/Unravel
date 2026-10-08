"""Support for tests that need a real PostgreSQL database.

SQLite cannot stand in here: the code under test uses JSONB columns and
`FOR UPDATE SKIP LOCKED`. These tests therefore run against Postgres, but
never against real data:

  - they read TEST_DATABASE_URL (never DATABASE_URL);
  - they create a schema with a random name, `unravel_test_<random>`, build
    the tables inside it, and point every connection's search_path at it;
  - the schema is dropped when the test run ends.

The `public` schema, where the application's real tables live, is never
read or written. If TEST_DATABASE_URL is not set these tests are skipped.

All database work in a test run happens on ONE event loop (`run` below).
A database connection belongs to the loop that opened it, so pytest's sync
test functions hand their coroutines to this loop instead of starting a new
one each time.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Coroutine, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, TypeVar
from uuid import UUID, uuid4

import httpx
from dotenv import dotenv_values
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.auth import CurrentHousehold, get_current_household
from app.core.config import API_DIR, Settings
from app.core.ids import new_id
from app.db.base import Base
from app.db.models import Household
from app.jobs.runner import JobRunner
from app.jobs.worker_process import ChildTarget
from app.main import create_app
from app.storage.memory import InMemoryStorage
from tests import fake_workers

T = TypeVar("T")

_loop = asyncio.new_event_loop()


def run(coroutine: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine to completion on the shared test event loop."""
    return _loop.run_until_complete(coroutine)


def test_database_url() -> str | None:
    return os.environ.get("TEST_DATABASE_URL") or dotenv_values(API_DIR / ".env").get("TEST_DATABASE_URL") or None


@dataclass
class Database:
    # repr=False on everything that carries the connection string: pytest
    # prints fixture values when a test fails, and the URL holds a password.
    url: str = field(repr=False)
    schema: str
    engine: AsyncEngine = field(repr=False)
    session_factory: async_sessionmaker[AsyncSession] = field(repr=False)

    def create_household(self) -> UUID:
        household_id = new_id()

        async def insert() -> None:
            async with self.session_factory() as session, session.begin():
                session.add(Household(id=household_id, name="Test household", auth_user_id=uuid4()))

        run(insert())
        return household_id

    def execute(self, sql: str, **parameters: Any) -> list[Any]:
        async def go() -> list[Any]:
            async with self.session_factory() as session, session.begin():
                result = await session.execute(text(sql), parameters)
                return list(result.all()) if result.returns_rows else []

        return run(go())

    def scalar(self, sql: str, **parameters: Any) -> Any:
        rows = self.execute(sql, **parameters)
        return rows[0][0] if rows else None


def create_database(url: str) -> Database:
    schema = f"unravel_test_{uuid4().hex[:12]}"

    async def setup() -> AsyncEngine:
        admin = create_async_engine(url)
        async with admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        await admin.dispose()

        # Every connection from this engine looks in the test schema first,
        # so unqualified table names resolve there and never in `public`.
        engine = create_async_engine(
            url, connect_args={"server_settings": {"search_path": schema}}, pool_size=5, max_overflow=0
        )
        async with engine.begin() as connection:
            current = (await connection.execute(text("select current_schema()"))).scalar()
            if current != schema:
                raise RuntimeError(f"refusing to run: connections use schema {current!r}, not the test schema")
            await connection.run_sync(Base.metadata.create_all)
        return engine

    engine = run(setup())
    return Database(url=url, schema=schema, engine=engine, session_factory=async_sessionmaker(engine, expire_on_commit=False))


def drop_database(database: Database) -> None:
    async def teardown() -> None:
        await database.engine.dispose()
        admin = create_async_engine(database.url)
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{database.schema}" CASCADE'))
        await admin.dispose()

    run(teardown())


class _HeldRunner:
    """A runner that never runs anything, for tests about the upload request alone."""

    async def wake(self) -> None:
        return None

    async def wait_until_idle(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None


class ApiTester:
    """The real application, wired to the test database, fake storage and a fake child process.

    Requests go through the full ASGI app (middleware, validation, error
    handlers). Only three things are replaced: the database points at the
    test schema, storage is in memory, and Engine A's child process is one of
    the stand-ins in tests/fake_workers.py.
    """

    def __init__(self, database: Database, household_id: UUID, extraction_target: ChildTarget = fake_workers.succeed) -> None:
        self.database = database
        self.household_id = household_id
        self.storage = InMemoryStorage()
        self.settings = Settings(
            _env_file=None,
            database_url=database.url,
            supabase_url="https://test-project.supabase.co",
            gemini_api_key="test",
            environment="test",
            parse_timeout_seconds=20,
        )
        self.app: FastAPI = create_app(self.settings)
        run(self.app.state.engine.dispose())
        self.app.state.engine = database.engine
        self.app.state.session_factory = database.session_factory
        self.app.state.storage = self.storage
        self.use_worker(extraction_target)

        async def current_household() -> CurrentHousehold:
            return CurrentHousehold(household_id=self.household_id, auth_user_id=UUID(int=0))

        self.app.dependency_overrides[get_current_household] = current_household
        self._transport = httpx.ASGITransport(app=self.app, raise_app_exceptions=False)

    def use_worker(self, extraction_target: ChildTarget, **settings_overrides: Any) -> None:
        settings = self.settings.model_copy(update=settings_overrides)
        self.app.state.runner = JobRunner(
            session_factory=self.database.session_factory,
            storage=self.storage,
            settings=settings,
            extraction_target=extraction_target,
        )

    def hold_jobs(self) -> None:
        """Leave uploaded jobs queued instead of running them."""
        self.app.state.runner = _HeldRunner()

    @contextmanager
    def acting_as(self, household_id: UUID) -> Iterator[None]:
        """Send the requests inside the block as a different household."""
        original, self.household_id = self.household_id, household_id
        try:
            yield
        finally:
            self.household_id = original

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        async def go() -> httpx.Response:
            async with httpx.AsyncClient(transport=self._transport, base_url="http://test") as client:
                return await client.request(method, f"/api/v1{path}", **kwargs)

        return run(go())

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("PATCH", path, **kwargs)

    def upload(
        self,
        content: bytes = b"%PDF-1.7\nfake pdf body",
        *,
        key: str | None = "key-1",
        file_name: str = "policy.pdf",
        content_type: str = "application/pdf",
        claim_id: str | None = "",
    ) -> httpx.Response:
        headers = {"Idempotency-Key": key} if key is not None else {}
        data = {"claim_id": claim_id} if claim_id is not None else {}
        return self.request("POST", "/documents", files={"file": (file_name, content, content_type)}, data=data, headers=headers)

    def finish_jobs(self) -> None:
        """Let the runner work until the queue is empty."""
        run(self.app.state.runner.wait_until_idle())

    def upload_and_parse(self, **kwargs: Any) -> dict[str, Any]:
        """Upload a file, run its job, and return the finished job as JSON."""
        accepted = self.upload(**kwargs)
        assert accepted.status_code == 202, accepted.text
        self.finish_jobs()
        return self.get(f"/jobs/{accepted.json()['job_id']}").json()
