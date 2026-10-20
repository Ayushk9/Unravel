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

LANES

Jobs run in two lanes, each with its own drain loops:

    documents   parse_document (policies and claim documents)
                at most `max_concurrent_parses` at once
    questions   answer_question and generate_grievance_draft, one at a time

A question takes seconds and a parse can take minutes; with one lane, a
question asked while a policy is being read would wait for the whole parse.

CONCURRENCY

In the documents lane, at most `max_concurrent_parses` drain loops exist at
once, and each runs one job at a time, so that is also the maximum number of
parses in progress. The default is 1: Docling loads large models, and two parses side
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
from app.classification.classifier import run_classification
from app.jobs.classify_document import run_classify_document
from app.jobs.parse_document import JobFailure, run_parse_document
from app.jobs.queue import ClaimedJob, SessionFactory, claim_next_job, interrupted_message, mark_failed
from app.jobs.worker_process import ChildTarget, run_extraction
from app.models_server.client import Models
from app.grievance.llm import GrievanceLlm
from app.grievance.run_draft import run_generate_grievance_draft
from app.qa.cache import QaCache
from app.qa.llm import QaLlm
from app.qa.run_question import run_answer_question
from app.storage.base import DocumentStorage

DOCUMENT_KINDS = ("parse_document",)
# Grievance drafts share the questions' lane: both make Gemini calls, and one at a time keeps the quota predictable.
QUESTION_KINDS = ("answer_question", "generate_grievance_draft")

logger = logging.getLogger("unravel.jobs")

CRASH_MESSAGES = {
    "parse_document": "Something went wrong on our side while reading this document. Please try again.",
    "answer_question": "Something went wrong on our side while answering this question. Please try again.",
    "generate_grievance_draft": "Something went wrong on our side while drafting this letter. Please try again.",
}


class JobRunner:
    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        storage: DocumentStorage,
        settings: Settings,
        # Tests replace this with a small stand-in so they never start Docling.
        extraction_target: ChildTarget = run_extraction,
        classification_target: ChildTarget = run_classification,
        # The warm model server and Gemini for questions and indexing. None
        # means unavailable: question jobs fail readably and indexing is skipped.
        models: Models | None = None,
        qa_llm: QaLlm | None = None,
        qa_cache: QaCache | None = None,
        grievance_llm: GrievanceLlm | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage
        self._settings = settings
        self._extraction_target = extraction_target
        self._classification_target = classification_target
        self.models = models
        self.qa_llm = qa_llm
        self.qa_cache = qa_cache or QaCache()
        self.grievance_llm = grievance_llm
        self._lanes: dict[tuple[str, ...], int] = {DOCUMENT_KINDS: settings.max_concurrent_parses, QUESTION_KINDS: 1}
        self._drain_tasks: dict[tuple[str, ...], set[asyncio.Task[None]]] = {kinds: set() for kinds in self._lanes}
        self._wake_requested: dict[tuple[str, ...], bool] = {kinds: False for kinds in self._lanes}

    async def wake(self) -> None:
        """Make sure something is looking at the queue.

        Async so that FastAPI's BackgroundTasks runs it on the event loop,
        where creating a task is allowed.
        """
        for kinds, limit in self._lanes.items():
            self._wake_requested[kinds] = True
            tasks = {task for task in self._drain_tasks[kinds] if not task.done()}
            while len(tasks) < limit:
                tasks.add(asyncio.create_task(self._drain(kinds)))
            self._drain_tasks[kinds] = tasks

    def _all_tasks(self) -> set[asyncio.Task[None]]:
        return set().union(*self._drain_tasks.values())

    async def wait_until_idle(self) -> None:
        """Wait for every job currently being drained to finish. Used by tests and scripts."""
        while tasks := {task for task in self._all_tasks() if not task.done()}:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def shutdown(self) -> None:
        """Stop draining. A job in progress is cancelled; its child process is terminated."""
        tasks = self._all_tasks()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for kinds in self._drain_tasks:
            self._drain_tasks[kinds] = set()

    async def _drain(self, kinds: tuple[str, ...]) -> None:
        """Run this lane's queued jobs one after another until there are none."""
        while True:
            # A wake() that arrives while the query below is in flight may be
            # for a job that query did not see. The flag makes the loop look
            # once more instead of exiting and stranding that job.
            self._wake_requested[kinds] = False
            job = await claim_next_job(self._session_factory, kinds)
            if job is None:
                if self._wake_requested[kinds]:
                    continue
                return
            await self._run(job)

    async def _run(self, job: ClaimedJob) -> None:
        """Run one job. Every way out of this function leaves the job finished.

        This is the guarantee that a job never stays `running`: a known
        failure, an unknown exception and success all end in a final status.
        """
        try:
            if job.kind == "answer_question":
                if self.models is None or self.qa_llm is None:
                    raise JobFailure("qa_unavailable", "Questions can't be answered on this server right now.", retryable=True)
                await run_answer_question(
                    job,
                    session_factory=self._session_factory,
                    models=self.models,
                    llm=self.qa_llm,
                    cache=self.qa_cache,
                    gemini_model=self._settings.gemini_model,
                )
            elif job.kind == "generate_grievance_draft":
                if self.models is None or self.grievance_llm is None:
                    raise JobFailure("drafting_unavailable", "Letters can't be drafted on this server right now.", retryable=True)
                await run_generate_grievance_draft(
                    job, session_factory=self._session_factory, models=self.models, llm=self.grievance_llm
                )
            elif job.kind != "parse_document":
                raise JobFailure("unsupported_job", "This kind of task isn't available yet.", retryable=False)
            elif job.payload.get("document_kind") == "claim_document":
                # A document uploaded to a claim only needs a label.
                await run_classify_document(
                    job,
                    session_factory=self._session_factory,
                    storage=self._storage,
                    settings=self._settings,
                    classification_target=self._classification_target,
                )
            else:
                # A policy: the full Engine A parse.
                await run_parse_document(
                    job,
                    session_factory=self._session_factory,
                    storage=self._storage,
                    settings=self._settings,
                    extraction_target=self._extraction_target,
                    models=self.models,
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
                    message=interrupted_message(job.kind),
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
                message=CRASH_MESSAGES.get(job.kind, CRASH_MESSAGES["parse_document"]),
                retryable=True,
            )
