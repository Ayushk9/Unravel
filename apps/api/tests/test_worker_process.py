"""The child-process wrapper. Each test starts a real process."""

from __future__ import annotations

import asyncio
import os
import time

from app.jobs.worker_process import ChildCrashed, ChildResult, ChildTimedOut, run_in_child_process
from contracts.models import ExtractionResult
from tests import fake_workers

ARGS = (__file__, "policy", "test-key", 30.0)  # any existing file path will do


def _is_alive(pid: int) -> bool:
    """Ask the kernel whether a process exists. Signal 0 checks without sending anything."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_child_result_comes_back_over_the_pipe() -> None:
    outcome = asyncio.run(run_in_child_process(fake_workers.succeed, ARGS, timeout_seconds=30))

    assert isinstance(outcome, ChildResult)
    assert outcome.pid != os.getpid(), "the work must happen in a different process"
    assert outcome.message["ok"] is True
    ExtractionResult.model_validate_json(outcome.message["result_json"])
    assert not _is_alive(outcome.pid)


def test_a_reported_failure_is_a_result_not_a_crash() -> None:
    outcome = asyncio.run(run_in_child_process(fake_workers.report_failure, ARGS, timeout_seconds=30))

    assert isinstance(outcome, ChildResult)
    assert outcome.message["ok"] is False
    assert outcome.message["error_type"] == "ExtractionError"


def test_a_child_that_dies_silently_is_reported_as_crashed() -> None:
    outcome = asyncio.run(run_in_child_process(fake_workers.crash, ARGS, timeout_seconds=30))

    assert isinstance(outcome, ChildCrashed)
    assert outcome.exit_code == 3


def test_timeout_terminates_the_child_process() -> None:
    started = time.monotonic()

    outcome = asyncio.run(run_in_child_process(fake_workers.hang, ARGS, timeout_seconds=1.5))

    elapsed = time.monotonic() - started
    assert isinstance(outcome, ChildTimedOut)
    assert 1.5 <= elapsed < 15, f"should stop soon after the timeout, took {elapsed:.1f}s"
    # The point of using a process: after the timeout it is really gone,
    # not merely marked as failed while it carries on consuming CPU.
    assert not _is_alive(outcome.pid)
