"""The server's startup routine and the basic HTTP checks, against the TEST database only.

The startup routine (app/main.py `lifespan`) writes to the database: it fails
every job left `running` and deletes expired ones. Run against the dev
database it changes real rows (on 2026-10-20 it failed two stale question
jobs there; DECISIONS.md). So these checks run here, in the temporary test
schema, through ApiTester, whose app uses the test schema's session factory.
Never build the app against apps/api/.env to check it.

The model server is switched off, so no model is loaded.
"""

from __future__ import annotations

import httpx

from app.core.ids import new_id
from app.db.models import Job
from tests.db import ApiTester, Database, run


def _running_job(database: Database, household_id) -> object:
    job_id = new_id()

    async def insert() -> None:
        async with database.session_factory() as session, session.begin():
            session.add(Job(id=job_id, household_id=household_id, kind="answer_question", status="running", payload={"question": "q"}))

    run(insert())
    return job_id


def test_startup_fails_a_job_left_running_in_the_test_schema_only(database: Database) -> None:
    household_id = database.create_household()
    api = ApiTester(database, household_id)
    api.app.state.model_server = None  # no models are loaded in tests
    job_id = _running_job(database, household_id)
    assert database.scalar("SELECT current_schema()").startswith("unravel_test_"), "never the dev schema"

    async def start_and_stop() -> None:
        async with api.app.router.lifespan_context(api.app):
            pass

    run(start_and_stop())

    row = database.execute("SELECT status, error_code, retryable, error FROM job WHERE id = :j", j=job_id)[0]
    assert (row.status, row.error_code, row.retryable) == ("failed", "interrupted", True)
    assert row.error == "This question was being answered when the server restarted. Please ask it again."


def test_health_404_and_401_are_the_contract_shapes(database: Database) -> None:
    api = ApiTester(database, database.create_household())

    health = api.get("/health")
    missing = api.get("/nonexistent")
    # Without ApiTester's stand-in for the token check: a request with no Authorization header.
    api.app.dependency_overrides.clear()

    async def no_token() -> httpx.Response:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://test") as client:
            return await client.get("/api/v1/claims")

    unauthorised = run(no_token())

    assert (health.status_code, health.json()) == (200, {"status": "ok"})
    assert missing.status_code == 404 and set(missing.json()) == {"error"} and missing.json()["error"]["code"] == "not_found"
    assert unauthorised.status_code == 401 and unauthorised.json()["error"]["code"] == "unauthorized"
    assert "detail" not in missing.json() and "detail" not in unauthorised.json()
