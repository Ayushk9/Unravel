"""The job runner: takes queued jobs from the table and runs them.

WHAT IT IS

A loop inside the API process:

    while there is a queued job:
        claim it  (queued -> running, see queue.claim_next_job)
        run it    (in a child process, see worker_process.py)
        record the outcome (succeeded or failed)

WHAT IT IS NOT

It is not the queue. The queue is the `job` table. This object holds no
list of pending jobs and no job state. If the server dies:

  - a job that was still `queued` is untouched and is picked up on restart;
  - a job that was `running` is marked failed on restart (main.py calls
    queue.recover_interrupted_jobs), so nothing stays "running" forever.

`wake()` only means "there may be work, go and look". It is called after an
upload (through FastAPI's BackgroundTasks) and once at startup. Losing a
wake-up loses no work, because the job row is already committed.

CONCURRENCY

At most `max_concurrent_parses` drain loops exist at once, and each runs
one job at a time, so that is also the maximum number of parses in
progress. The default is 1: Docling loads large models, and two parses side
by side can use more memory than a small host has, at which point the
kernel starts killing processes. Extra jobs simply wait as `queued` rows.

RUNNING THE WORKER ELSEWHERE LATER

Everything a job needs is in its row (`payload`), and claiming uses
`FOR UPDATE SKIP LOCKED`, which is safe with any number of workers. A
standalone worker would be a small script that builds a JobRunner and calls
`wake()` on a timer, on any machine that can reach the database and storage.
The API would not change.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import Settings
from app.jobs.parse_document import JobFailure, run_parse_document
from app.jobs.queue import ClaimedJob, SessionFactory, claim_next_job, mark_failed
from app.jobs.worker_process import ChildTarget, run_extraction
from app.storage.base import DocumentStorage

logger = logging.getLogger("unravel.jobs")


class JobRunner:
    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        storage: DocumentStorage,
        settings: Settings,
        # Tests replace this with a small stand-in so they never start Docling.
        extraction_target: ChildTarget = run_extraction,
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage
        self._settings = settings
        self._extraction_target = extraction_target
        self._drain_tasks: set[asyncio.Task[None]] = set()
        self._wake_requested = False

    async def wake(self) -> None:
        """Make sure something is looking at the queue.

        Async so that FastAPI's BackgroundTasks runs it on the event loop,
        where creating a task is allowed.
        """
        self._wake_requested = True
        self._drain_tasks = {task for task in self._drain_tasks if not task.done()}
        while len(self._drain_tasks) < self._settings.max_concurrent_parses:
            self._drain_tasks.add(asyncio.create_task(self._drain()))

    async def wait_until_idle(self) -> None:
        """Wait for every job currently being drained to finish. Used by tests and scripts."""
        while self._drain_tasks:
            await asyncio.gather(*self._drain_tasks, return_exceptions=True)
            self._drain_tasks = {task for task in self._drain_tasks if not task.done()}

    async def shutdown(self) -> None:
        """Stop draining. A job in progress is cancelled; its child process is terminated."""
        for task in self._drain_tasks:
            task.cancel()
        await asyncio.gather(*self._drain_tasks, return_exceptions=True)
        self._drain_tasks.clear()

    async def _drain(self) -> None:
        """Run queued jobs one after another until the queue is empty."""
        while True:
            # A wake() that arrives while the query below is in flight may be
            # for a job that query did not see. The flag makes the loop look
            # once more instead of exiting and stranding that job.
            self._wake_requested = False
            job = await claim_next_job(self._session_factory)
            if job is None:
                if self._wake_requested:
                    continue
                return
            await self._run(job)

    async def _run(self, job: ClaimedJob) -> None:
        """Run one job. Every way out of this function leaves the job finished.

        This is the guarantee that a job never stays `running`: a known
        failure, an unknown exception and success all end in a final status.
        """
        try:
            if job.kind != "parse_document":
                raise JobFailure("unsupported_job", "This kind of task isn't available yet.", retryable=False)
            await run_parse_document(
                job,
                session_factory=self._session_factory,
                storage=self._storage,
                settings=self._settings,
                extraction_target=self._extraction_target,
            )
        except JobFailure as failure:
            logger.warning("Job failed. job_id=%s code=%s detail=%s", job.id, failure.code, failure.detail)
            await mark_failed(
                self._session_factory, job.id, code=failure.code, message=failure.message, retryable=failure.retryable
            )
        except asyncio.CancelledError:
            # The server is shutting down. Record that rather than leave the
            # row `running`; then let the cancellation continue.
            await asyncio.shield(
                mark_failed(
                    self._session_factory,
                    job.id,
                    code="interrupted",
                    message="This document was being read when the server stopped. Please upload it again.",
                    retryable=True,
                )
            )
            raise
        except Exception:  # noqa: BLE001 - an unexpected bug must still end the job
            # The trace is logged; the user sees a plain sentence.
            logger.exception("Job crashed unexpectedly. job_id=%s", job.id)
            await mark_failed(
                self._session_factory,
                job.id,
                code="internal_error",
                message="Something went wrong on our side while reading this document. Please try again.",
                retryable=True,
            )
