"""Running Engine A in a separate operating-system process.

WHY A PROCESS AND NOT A THREAD

Parsing a policy means running Docling: layout models, table-structure
models, sometimes OCR. It is CPU- and memory-heavy and, on a bad input, can
run for a very long time. We must be able to say "you have 300 seconds" and
actually enforce it.

A thread cannot be stopped from outside. Python has no way to kill a thread,
and neither does the operating system without taking the whole process with
it. If the parse ran in a thread and hung, we could mark the job failed, but
the thread would keep running, holding its CPU core and its gigabytes of
model memory, until the server was restarted. A few of those and the server
is dead while its job table says everything is fine.

A process can be stopped. The kernel owns it: on `terminate()` the kernel
delivers SIGTERM, the process ends, and ALL its memory is returned, however
badly its code was behaving. That is the property this file exists for.

Two more benefits follow from the same choice:

  Memory isolation.  Docling and PyTorch are imported only in the child. The
                     API process never loads them, so it stays small, and a
                     crash or memory leak inside the parser cannot corrupt or
                     bloat the API.
  Fault isolation.   If the child is killed by the kernel for using too much
                     memory, or segfaults in native code, the parent sees a
                     dead child and fails one job. The API keeps serving.

The cost is start-up time: every job pays for starting a fresh interpreter
and importing the libraries. scripts/measure_spawn_overhead.py measures it.

WHY "spawn"

A child can be created by `fork` (copy the parent's memory) or `spawn`
(start a brand-new interpreter). The parent here is an asyncio server with
threads and open network connections. Forking such a process copies locks
that may be held by threads which do not exist in the child, a classic
source of deadlocks. `spawn` starts clean and behaves the same on Linux,
macOS and Windows.

HOW PARENT AND CHILD TALK

Through one pipe. The child sends exactly one message, a small dict, and
exits. The parent waits for that message with a timeout. Three things can
happen, and the parent tells them apart:

  a message arrives     -> ChildResult (the work finished, well or badly)
  the pipe closes empty -> ChildCrashed (the process died without answering)
  the timeout passes    -> ChildTimedOut (the parent terminates the process)
"""

from __future__ import annotations

import asyncio
import logging
import multiprocessing
import os
import signal
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from pathlib import Path
from typing import Any

logger = logging.getLogger("unravel.jobs")

# How often the waiting thread checks whether it should give up.
_POLL_SLICE_SECONDS = 0.5

# How long to wait for a terminated child to exit before using SIGKILL.
_TERMINATE_GRACE_SECONDS = 5.0

# The child ends itself this long after the parent's timeout, in case the
# parent is no longer there to do it (see run_extraction).
_SELF_DESTRUCT_MARGIN_SECONDS = 30


@dataclass(frozen=True)
class ChildResult:
    """The child ran to completion and reported back."""

    pid: int
    message: dict[str, Any]


@dataclass(frozen=True)
class ChildCrashed:
    """The child process died without sending anything."""

    pid: int
    exit_code: int | None


@dataclass(frozen=True)
class ChildTimedOut:
    """The child was still working at the deadline and was terminated."""

    pid: int


ChildOutcome = ChildResult | ChildCrashed | ChildTimedOut

# A function that can be the child's entry point. Its first argument is the
# pipe end to answer on.
ChildTarget = Callable[..., None]


async def run_in_child_process(target: ChildTarget, args: tuple[Any, ...], timeout_seconds: float) -> ChildOutcome:
    """Run `target(connection, *args)` in a new process and wait for its answer.

    Whatever happens, the child is not running when this function returns.
    """
    context = multiprocessing.get_context("spawn")
    parent_end, child_end = context.Pipe(duplex=False)

    # daemon=True: if this server shuts down normally, Python terminates the
    # child too, rather than leaving it behind.
    process = context.Process(target=target, args=(child_end, *args), daemon=True)
    process.start()
    pid = process.pid or -1

    # The parent must close its own copy of the child's end. A pipe reports
    # "closed" only when EVERY copy of the writing end is closed. If the
    # parent kept one, a crashed child would look like a silent one forever.
    child_end.close()

    # Lets this function tell the helper thread below to stop waiting, for
    # example when the server is shutting down mid-parse.
    stop_waiting = threading.Event()
    timed_out = False
    message: dict[str, Any] | None = None
    try:
        # Waiting on a pipe blocks, so it runs in a helper thread; the event
        # loop stays free to answer HTTP requests meanwhile.
        message = await asyncio.to_thread(_wait_for_message, parent_end, timeout_seconds, stop_waiting)
    except TimeoutError:
        timed_out = True
    finally:
        # Runs on every path: answer received, timeout, crash, or this task
        # being cancelled. The child never outlives this function.
        stop_waiting.set()
        _stop(process)
        parent_end.close()

    if timed_out:
        return ChildTimedOut(pid=pid)
    if message is None:
        return ChildCrashed(pid=pid, exit_code=process.exitcode)
    return ChildResult(pid=pid, message=message)


def _wait_for_message(
    connection: Connection, timeout_seconds: float, stop_waiting: threading.Event
) -> dict[str, Any] | None:
    """Block until the child answers. None means it died without answering.

    Waits in short slices rather than one long block, so the thread notices
    promptly when `stop_waiting` is set and does not hold up a shutdown.
    """
    deadline = time.monotonic() + timeout_seconds
    while not stop_waiting.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        # poll() returns True when there is data to read OR the other end closed.
        if connection.poll(min(_POLL_SLICE_SECONDS, remaining)):
            try:
                return connection.recv()
            except EOFError:
                return None
    return None


def _stop(process: BaseProcess) -> None:
    """Make sure the child is gone, and collect its exit status.

    SIGTERM first (a polite request the process could handle), then SIGKILL
    (which the kernel enforces and no process can ignore). `join` afterwards
    reaps the child so it does not linger as a zombie entry in the process
    table.
    """
    if process.is_alive():
        process.terminate()
        process.join(_TERMINATE_GRACE_SECONDS)
    if process.is_alive():
        logger.warning("Child process %s ignored SIGTERM; sending SIGKILL.", process.pid)
        process.kill()
    process.join()


def run_extraction(
    connection: Connection,
    file_path: str,
    document_kind: str,
    gemini_api_key: str,
    gemini_model: str,
    timeout_seconds: float,
) -> None:
    """Child entry point: run Engine A on one file and send back the result.

    Runs in the child process only. Nothing here touches the database or
    storage; the child's single job is the pure function
    `parse_and_extract(file_path, document_kind)`.
    """
    # Self-destruct timer. The parent normally enforces the timeout. But if
    # the parent itself was killed outright (kill -9, the host running out of
    # memory), nobody is left to stop this process. An alarm makes the kernel
    # send SIGALRM after the given time, and the default action for SIGALRM
    # is to end the process. Unix only.
    if hasattr(signal, "SIGALRM"):
        signal.alarm(int(timeout_seconds) + _SELF_DESTRUCT_MARGIN_SECONDS)

    try:
        # Engine A reads its API key and model name from the environment, and
        # reads the model name once, when it is imported. Both are therefore
        # set before the import below. This configures Engine A through its
        # own documented settings; its code is not changed.
        os.environ["GEMINI_API_KEY"] = gemini_api_key
        os.environ["GEMINI_MODEL"] = gemini_model

        # Imported here, not at the top of the file, so that only the child
        # process ever loads Docling and PyTorch.
        from engines.document.pipeline import parse_and_extract

        result = parse_and_extract(Path(file_path), document_kind)  # type: ignore[arg-type]
        connection.send({"ok": True, "result_json": result.model_dump_json()})
    except Exception as exc:  # noqa: BLE001 - every failure must be reported to the parent, not lost
        connection.send({"ok": False, "error_type": type(exc).__name__, "detail": str(exc)})
    finally:
        connection.close()
