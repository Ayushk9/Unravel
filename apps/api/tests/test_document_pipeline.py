"""Upload -> job -> stored policy, against a real Postgres (temporary schema).

Engine A is replaced by the stand-ins in tests/fake_workers.py, each of which
runs in a real child process.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.core.ids import new_id
from app.db.models import Document, Job
from app.jobs.queue import claim_next_job, delete_expired_jobs, recover_interrupted_jobs
from tests import fake_workers
from tests.db import ApiTester, Database, run

PDF = b"%PDF-1.7\nfake pdf body"
OTHER_PDF = b"%PDF-1.7\na different file"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def _counts(db: Database, household_id: UUID) -> tuple[int, int]:
    jobs = db.scalar("SELECT count(*) FROM job WHERE household_id = :h", h=household_id)
    documents = db.scalar("SELECT count(*) FROM document WHERE household_id = :h", h=household_id)
    return jobs, documents


# --- upload and idempotency ---


def test_upload_returns_202_and_creates_one_document_and_one_queued_job(api: ApiTester, db: Database) -> None:
    api.hold_jobs()
    response = api.upload(PDF, file_name="My Policy (final).pdf")

    assert response.status_code == 202
    body = response.json()
    assert set(body) == {"job_id", "kind", "status"}
    assert body["kind"] == "parse_document" and body["status"] == "queued"
    assert UUID(body["job_id"]).version == 7

    assert _counts(db, api.household_id) == (1, 1)
    row = db.execute(
        "SELECT id, file_name, mime_type, storage_path, sha256, size_bytes FROM document WHERE household_id = :h",
        h=api.household_id,
    )[0]
    # Stored under {household_id}/{document_id}/{sanitised name}; the original name is kept on the row.
    assert row.file_name == "My Policy (final).pdf"
    assert row.storage_path == f"{api.household_id}/{row.id}/My_Policy_final_.pdf"
    assert api.storage.objects == {row.storage_path: PDF}
    assert row.mime_type == "application/pdf" and row.size_bytes == len(PDF) and len(row.sha256) == 64


def test_same_key_and_same_file_replays_the_original_response_and_creates_nothing(api: ApiTester, db: Database) -> None:
    first = api.upload(PDF, key="retry-me")
    second = api.upload(PDF, key="retry-me")
    api.finish_jobs()
    third = api.upload(PDF, key="retry-me")  # even after the job has finished

    assert first.status_code == second.status_code == third.status_code == 202
    assert first.json() == second.json() == third.json()
    assert third.json()["status"] == "queued", "a replay returns the ORIGINAL body"
    assert _counts(db, api.household_id) == (1, 1)
    assert len(api.storage.objects) == 1


def test_same_key_with_a_different_file_is_409(api: ApiTester, db: Database) -> None:
    api.hold_jobs()
    api.upload(PDF, key="reused")

    response = api.upload(OTHER_PDF, key="reused")

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "idempotency_key_reused"
    assert error["field_errors"][0]["field"] == "Idempotency-Key"
    assert _counts(db, api.household_id) == (1, 1)
    assert len(api.storage.objects) == 1, "the second file must not be stored"


def test_idempotency_keys_are_scoped_to_a_household(api: ApiTester, db: Database) -> None:
    api.hold_jobs()
    other_household = db.create_household()
    mine = api.upload(PDF, key="shared-key")

    with api.acting_as(other_household):
        theirs = api.upload(OTHER_PDF, key="shared-key")

    assert theirs.status_code == 202, "another household's key must not collide with mine"
    assert theirs.json()["job_id"] != mine.json()["job_id"]
    assert _counts(db, other_household) == (1, 1)


def test_different_keys_create_separate_jobs(api: ApiTester, db: Database) -> None:
    api.hold_jobs()
    api.upload(PDF, key="a")
    api.upload(PDF, key="b")

    assert _counts(db, api.household_id) == (2, 2)


# --- a successful parse ---


@pytest.fixture(scope="module")
def parsed(database: Database) -> SimpleNamespace:
    """One document uploaded and parsed, shared by the read-only tests below."""
    api = ApiTester(database, database.create_household())
    queued = api.get(f"/jobs/{api.upload(PDF, key='shared').json()['job_id']}").json()
    api.finish_jobs()
    job = api.get(f"/jobs/{queued['job_id']}").json()
    return SimpleNamespace(
        api=api,
        db=database,
        queued=queued,
        job=job,
        document_id=job["result"]["document_id"] if job["result"] else None,
        policy_id=job["result"]["policy_id"] if job["result"] else None,
    )


def test_job_is_queued_with_uploading_progress_before_it_runs(parsed: SimpleNamespace) -> None:
    assert parsed.queued["status"] == "queued"
    assert parsed.queued["progress"] == {"step": "uploading", "percent": 5}
    assert parsed.queued["result"] is None and parsed.queued["error"] is None


def test_finished_job_has_the_contract_shape_and_points_at_real_rows(parsed: SimpleNamespace) -> None:
    job = parsed.job

    assert set(job) == {"job_id", "kind", "status", "progress", "result", "error"}
    assert job["status"] == "succeeded" and job["error"] is None
    assert set(job["result"]) == {"document_id", "policy_id"}
    assert UUID(job["result"]["policy_id"]).version == 7


def test_document_is_marked_parsed_with_page_count_and_warnings(parsed: SimpleNamespace) -> None:
    row = parsed.db.execute(
        "SELECT parse_status, parse_error, page_count, warnings FROM document WHERE id = :d", d=parsed.document_id
    )[0]

    assert (row.parse_status, row.parse_error, row.page_count) == ("parsed", None, 48)
    # Engine A's real warning is kept; its placeholder-id note is not.
    assert row.warnings == ["sub-limit 'ICU' omitted: basis could not be determined"]


def test_every_extracted_field_is_stored_with_original_value_and_unconfirmed(parsed: SimpleNamespace) -> None:
    db = parsed.db
    profile = db.execute("SELECT * FROM coverage_profile WHERE policy_id = :p", p=parsed.policy_id)[0]

    assert profile.sum_insured_value == profile.sum_insured_original_value == 50_000_000
    assert profile.co_pay_percent_value == profile.co_pay_percent_original_value == 10.0
    assert profile.sum_insured_confidence == "high" and profile.co_pay_percent_confidence == "medium"
    assert profile.sum_insured_user_confirmed is False
    # A field the parser could not find: all nulls, never a made-up value.
    assert profile.intimation_deadline_hours_value is None
    assert profile.intimation_deadline_hours_original_value is None
    assert profile.intimation_deadline_hours_provenance is None
    assert profile.intimation_deadline_hours_confidence == "low"

    sub_limits = db.execute(
        "SELECT category, cap_amount_value, cap_amount_original_value, cap_amount_confidence, cap_amount_user_confirmed "
        "FROM sub_limit WHERE coverage_profile_id = :c ORDER BY position",
        c=profile.id,
    )
    assert [(s.category, s.cap_amount_value, s.cap_amount_original_value) for s in sub_limits] == [
        ("room_rent", 500_000, 500_000),
        ("procedure", 4_000_000, 4_000_000),
        ("procedure", 6_000_000, 6_000_000),
    ]
    assert all(s.cap_amount_user_confirmed is False for s in sub_limits)
    assert db.scalar("SELECT count(*) FROM waiting_period WHERE coverage_profile_id = :c", c=profile.id) == 1
    assert db.scalar("SELECT count(*) FROM exclusion WHERE coverage_profile_id = :c", c=profile.id) == 1


def test_no_placeholder_id_reached_the_database(parsed: SimpleNamespace) -> None:
    db = parsed.db
    profile = db.execute("SELECT id, sum_insured_provenance FROM coverage_profile WHERE policy_id = :p", p=parsed.policy_id)[0]
    provenance_document_ids = {profile.sum_insured_provenance["document_id"]}
    for table, column in (("sub_limit", "cap_amount_provenance"), ("waiting_period", "months_provenance"), ("exclusion", "text_provenance")):
        for row in db.execute(f"SELECT {column} AS provenance FROM {table} WHERE coverage_profile_id = :c", c=profile.id):
            provenance_document_ids.add(row.provenance["document_id"])

    assert provenance_document_ids == {parsed.document_id}

    chunks = db.execute("SELECT id, document_id, position FROM document_chunk WHERE document_id = :d ORDER BY position", d=parsed.document_id)
    assert [chunk.position for chunk in chunks] == [0, 1]
    assert all(chunk.id.version == 7 for chunk in chunks)


def test_policy_identity_columns_are_null_not_invented(parsed: SimpleNamespace) -> None:
    row = parsed.db.execute(
        "SELECT insurer_id, policy_number, product_name, policy_type, start_date, end_date, source_document_id "
        "FROM policy WHERE id = :p",
        p=parsed.policy_id,
    )[0]

    assert tuple(row)[:6] == (None, None, None, None, None, None)
    assert str(row.source_document_id) == parsed.document_id


def test_temporary_file_is_gone_after_the_parse(parsed: SimpleNamespace) -> None:
    temp_paths = parsed.api.storage.temp_paths

    assert len(temp_paths) == 1
    assert not temp_paths[0].exists() and not temp_paths[0].parent.exists()


# --- failures: the job always ends, with a sentence a person can read ---


def _assert_failed_cleanly(api: ApiTester, db: Database, job: dict, expected_code: str, retryable: bool) -> None:
    assert job["status"] == "failed"
    assert job["result"] is None
    assert isinstance(job["error"], str) and job["error"].endswith(".")
    for leaked in ("Traceback", "secret internal path", "Docling", "ExtractionError", "exit code", "pid"):
        assert leaked not in job["error"]

    row = db.execute("SELECT error_code, retryable, finished_at, payload FROM job WHERE id = :j", j=job["job_id"])[0]
    assert (row.error_code, row.retryable) == (expected_code, retryable)
    assert row.finished_at is not None

    document = db.execute("SELECT parse_status, parse_error FROM document WHERE id = :d", d=row.payload["document_id"])[0]
    assert document.parse_status == "failed"
    assert document.parse_error == job["error"]

    # Nothing half-written, and the temporary file is gone even on failure.
    assert db.scalar("SELECT count(*) FROM policy WHERE household_id = :h", h=api.household_id) == 0
    assert all(not path.exists() for path in api.storage.temp_paths)


@pytest.mark.parametrize(
    ("worker", "expected_code", "retryable"),
    [
        (fake_workers.report_failure, "parse_failed", False),  # e.g. a corrupt PDF
        (fake_workers.return_garbage, "parse_failed", True),
        (fake_workers.crash, "parse_crashed", True),  # e.g. killed for using too much memory
    ],
)
def test_a_failing_parse_ends_the_job_as_failed(api: ApiTester, db: Database, worker, expected_code: str, retryable: bool) -> None:
    api.use_worker(worker)

    job = api.upload_and_parse(content=PDF)

    _assert_failed_cleanly(api, db, job, expected_code, retryable)


def test_a_parse_that_exceeds_the_timeout_is_stopped_and_failed(api: ApiTester, db: Database) -> None:
    api.use_worker(fake_workers.hang, parse_timeout_seconds=1.5)

    job = api.upload_and_parse(content=PDF)

    _assert_failed_cleanly(api, db, job, "parse_timeout", True)
    assert "took longer than" in job["error"]


def test_an_image_upload_is_accepted_then_failed_without_starting_a_parse(api: ApiTester, db: Database) -> None:
    job = api.upload_and_parse(content=PNG, file_name="scan.png", content_type="image/png")

    _assert_failed_cleanly(api, db, job, "unsupported_document", False)
    assert "PDF" in job["error"]
    assert api.storage.temp_paths == [], "no temporary file, so no parse was attempted"


def test_no_job_is_left_running_or_queued_after_the_runner_is_idle(api: ApiTester, db: Database) -> None:
    api.use_worker(fake_workers.crash)
    api.upload(PDF, key="1")
    api.use_worker(fake_workers.succeed)
    api.upload(PDF, key="2")

    api.finish_jobs()

    statuses = {row.status for row in db.execute("SELECT status FROM job WHERE household_id = :h", h=api.household_id)}
    assert statuses <= {"succeeded", "failed"} and statuses


# --- one parse at a time ---


def _job_times(db: Database, household_id: UUID) -> list:
    """(started_at, finished_at) for each job, in the order they were created."""
    return db.execute("SELECT started_at, finished_at FROM job WHERE household_id = :h ORDER BY id", h=household_id)


def _queue_two_jobs_then_run(api: ApiTester, max_concurrent_parses: int) -> None:
    """Put both jobs in the queue BEFORE any runner starts, then start one.

    Starting from a queue that already holds two jobs makes the outcome
    depend only on the concurrency limit, not on how quickly the second
    upload request happened to arrive.
    """
    api.hold_jobs()
    api.upload(PDF, key="first")
    api.upload(PDF, key="second")
    api.use_worker(fake_workers.succeed, max_concurrent_parses=max_concurrent_parses)
    run(api.app.state.runner.wake())
    api.finish_jobs()


def test_only_one_parse_runs_at_a_time_by_default(api: ApiTester, db: Database) -> None:
    assert api.settings.max_concurrent_parses == 1

    _queue_two_jobs_then_run(api, max_concurrent_parses=1)

    first, second = _job_times(db, api.household_id)
    assert second.started_at >= first.finished_at, "the second job must wait until the first has finished"


def test_raising_the_limit_lets_parses_overlap(api: ApiTester, db: Database) -> None:
    _queue_two_jobs_then_run(api, max_concurrent_parses=2)

    first, second = _job_times(db, api.household_id)
    assert second.started_at < first.finished_at, "with a limit of 2 the second job starts while the first is running"


# --- the table as a queue ---


def _insert_job(db: Database, household_id: UUID, *, status: str, finished_hours_ago: float | None = None) -> tuple[UUID, UUID]:
    document_id, job_id = new_id(), new_id()

    async def insert() -> None:
        async with db.session_factory() as session, session.begin():
            session.add(
                Document(
                    id=document_id,
                    household_id=household_id,
                    file_name="policy.pdf",
                    mime_type="application/pdf",
                    storage_path=f"{household_id}/{document_id}/policy.pdf",
                    parse_status={"queued": "queued", "running": "parsing", "succeeded": "parsed", "failed": "failed"}[status],
                )
            )
            session.add(
                Job(
                    id=job_id,
                    household_id=household_id,
                    kind="parse_document",
                    status=status,
                    payload={"document_id": str(document_id), "document_kind": "policy"},
                )
            )

    run(insert())
    if finished_hours_ago is not None:
        db.execute(
            "UPDATE job SET finished_at = now() - make_interval(secs => :s) WHERE id = :j",
            s=finished_hours_ago * 3600,
            j=job_id,
        )
    return job_id, document_id


def test_two_workers_claiming_at_once_never_get_the_same_job(db: Database, household_id: UUID) -> None:
    db.execute("DELETE FROM job WHERE status IN ('queued', 'running')")
    older, _ = _insert_job(db, household_id, status="queued")
    newer, _ = _insert_job(db, household_id, status="queued")

    async def claim_twice():
        return await asyncio.gather(claim_next_job(db.session_factory), claim_next_job(db.session_factory))

    first, second = run(claim_twice())
    third = run(claim_next_job(db.session_factory))

    assert {first.id, second.id} == {older, newer}, "each worker gets a different job"
    assert third is None, "nothing is left to claim"
    assert db.scalar("SELECT count(*) FROM job WHERE status = 'running' AND household_id = :h", h=household_id) == 2
    db.execute("UPDATE job SET status = 'failed', finished_at = now() WHERE household_id = :h", h=household_id)


def test_jobs_are_claimed_oldest_first_and_their_document_marked_parsing(db: Database, household_id: UUID) -> None:
    db.execute("DELETE FROM job WHERE status IN ('queued', 'running')")
    older, older_document = _insert_job(db, household_id, status="queued")
    _insert_job(db, household_id, status="queued")

    claimed = run(claim_next_job(db.session_factory))

    assert claimed.id == older
    assert claimed.payload == {"document_id": str(older_document), "document_kind": "policy"}
    assert db.scalar("SELECT parse_status FROM document WHERE id = :d", d=older_document) == "parsing"
    assert db.scalar("SELECT started_at IS NOT NULL FROM job WHERE id = :j", j=older) is True
    db.execute("UPDATE job SET status = 'failed', finished_at = now() WHERE household_id = :h", h=household_id)


# --- restart recovery and retention ---


def test_startup_recovery_fails_jobs_left_running_and_leaves_queued_ones(db: Database, household_id: UUID) -> None:
    db.execute("DELETE FROM job WHERE status IN ('queued', 'running')")
    stale, stale_document = _insert_job(db, household_id, status="running")
    waiting, waiting_document = _insert_job(db, household_id, status="queued")

    recovered = run(recover_interrupted_jobs(db.session_factory))

    assert recovered == 1
    job = db.execute("SELECT status, error, error_code, retryable, finished_at FROM job WHERE id = :j", j=stale)[0]
    assert (job.status, job.error_code, job.retryable) == ("failed", "interrupted", True)
    assert "restarted" in job.error and job.finished_at is not None
    document = db.execute("SELECT parse_status, parse_error FROM document WHERE id = :d", d=stale_document)[0]
    assert document.parse_status == "failed" and document.parse_error == job.error

    assert db.scalar("SELECT status FROM job WHERE id = :j", j=waiting) == "queued"
    assert db.scalar("SELECT parse_status FROM document WHERE id = :d", d=waiting_document) == "queued"
    db.execute("DELETE FROM job WHERE id = :j", j=waiting)


def test_application_startup_recovers_stale_jobs_and_then_runs_queued_ones(api: ApiTester, db: Database) -> None:
    db.execute("DELETE FROM job WHERE status IN ('queued', 'running')")
    stale, _ = _insert_job(db, api.household_id, status="running")
    queued_job_id = api.upload(PDF, key="waiting-through-a-restart").json()["job_id"]
    # Simulate "the server died before running it": throw away the runner that was woken.
    run(api.app.state.runner.shutdown())
    db.execute("UPDATE job SET status = 'queued', error = NULL, finished_at = NULL WHERE id = :j", j=queued_job_id)
    db.execute("UPDATE document SET parse_status = 'queued', parse_error = NULL WHERE household_id = :h AND sha256 IS NOT NULL", h=api.household_id)
    api.use_worker(fake_workers.succeed)

    async def start_the_app() -> None:
        async with api.app.router.lifespan_context(api.app):
            await api.app.state.runner.wait_until_idle()

    run(start_the_app())

    assert db.scalar("SELECT status FROM job WHERE id = :j", j=stale) == "failed"
    assert db.scalar("SELECT status FROM job WHERE id = :j", j=queued_job_id) == "succeeded"


def test_finished_jobs_are_deleted_after_24_hours_and_not_before(db: Database, household_id: UUID) -> None:
    expired, _ = _insert_job(db, household_id, status="succeeded", finished_hours_ago=25)
    expired_failure, _ = _insert_job(db, household_id, status="failed", finished_hours_ago=30)
    recent, _ = _insert_job(db, household_id, status="succeeded", finished_hours_ago=23)

    deleted = run(delete_expired_jobs(db.session_factory))

    remaining = {row.id for row in db.execute("SELECT id FROM job WHERE household_id = :h", h=household_id)}
    assert deleted >= 2
    assert remaining == {recent}
    # Deleting a job does not delete the document it parsed.
    assert db.scalar("SELECT count(*) FROM document WHERE household_id = :h", h=household_id) == 3
