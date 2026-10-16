"""The API's handle on the warm model server.

WHY ONE LONG-LIVED PROCESS

Answering a question needs two models: BGE-M3 to turn the question into a
vector, and a reranker to re-order the candidate clauses. Loading them takes
several seconds (reading ~2 GB of weights each). Document parsing pays a
fresh process per job (app/jobs/worker_process.py) because a parse can hang
and must be killable; if questions did the same, every question would wait
for both models to load. So these models live in one process that loads
them once and then serves requests for as long as the API runs.

It is still a separate process, not a thread in the API, for the same
reasons as parsing: torch is never imported into the API, its memory is
returned when the process ends, and a hang can be ended by killing it.

WHAT HAPPENS WHEN IT MISBEHAVES

Every request has a timeout. If it passes, or the process dies, it is
killed, ModelServerError is raised (the job fails with a readable sentence),
and the next request starts a fresh process.

Requests are served one at a time (an asyncio lock): the models are not
safe to call from two requests at once, and a request takes well under a
second, so a queue of one is fine for this project.
"""

from __future__ import annotations

import asyncio
import logging
import multiprocessing
import time
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from collections.abc import Callable
from typing import Any, Protocol

from app.models_server.process import serve

logger = logging.getLogger("unravel.models")

_POLL_SLICE_SECONDS = 0.25


class ModelServerError(Exception):
    """The models could not answer. `str(error)` is for the log, not the user."""


class Models(Protocol):
    """What the Q&A pipeline and indexing need. Tests use an in-process fake."""

    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    async def rerank(self, query: str, passages: list[str]) -> list[float]: ...


class ModelServer:
    def __init__(
        self,
        *,
        embed_model: str,
        rerank_model: str,
        device: str,
        load_timeout_seconds: float,
        request_timeout_seconds: float,
        # Tests replace the child's entry point with small stand-ins (tests/fake_model_process.py).
        target: Callable[..., None] = serve,
    ) -> None:
        self._args = (embed_model, rerank_model, device)
        self._target = target
        self._load_timeout = load_timeout_seconds
        self._request_timeout = request_timeout_seconds
        self._process: BaseProcess | None = None
        self._connection: Connection | None = None
        self._ready = False
        self._lock = asyncio.Lock()
        self.load_seconds: float | None = None

    def start(self) -> None:
        """Start loading in the background. Returns at once; the first request waits for loading to finish."""
        if self._process is not None and self._process.is_alive():
            return
        context = multiprocessing.get_context("spawn")
        parent_end, child_end = context.Pipe(duplex=True)
        self._process = context.Process(target=self._target, args=(child_end, *self._args), daemon=True, name="unravel-models")
        self._process.start()
        child_end.close()
        self._connection = parent_end
        self._ready = False
        logger.info("Model server starting. pid=%s models=%s,%s device=%s", self._process.pid, *self._args)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return (await self._call({"op": "embed", "texts": texts}))["vectors"]

    async def rerank(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        return (await self._call({"op": "rerank", "query": query, "passages": passages}))["scores"]

    async def stop(self) -> None:
        async with self._lock:
            self._kill("shutting down")

    async def _call(self, request: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            if self._process is None or not self._process.is_alive():
                self.start()
            if not self._ready:
                await self._wait_until_ready()
            assert self._connection is not None
            self._connection.send(request)
            reply = await self._receive(self._request_timeout, "request")
            if not reply.get("ok"):
                raise ModelServerError(f"model server error: {reply.get('error')}")
            return reply

    async def _wait_until_ready(self) -> None:
        started = time.perf_counter()
        message = await self._receive(self._load_timeout, "loading")
        if not message.get("ready"):
            self._kill("failed to load")
            raise ModelServerError(f"models failed to load: {message.get('error')}")
        self._ready = True
        self.load_seconds = message.get("load_seconds")
        logger.info("Model server ready. load_seconds=%s waited_seconds=%.2f", self.load_seconds, time.perf_counter() - started)

    async def _receive(self, timeout: float, what: str) -> dict[str, Any]:
        connection = self._connection
        assert connection is not None
        try:
            message = await asyncio.to_thread(_poll, connection, timeout)
        except EOFError:
            self._kill(f"died during {what}")
            raise ModelServerError(f"model server died during {what}") from None
        if message is None:
            self._kill(f"timed out during {what}")
            raise ModelServerError(f"model server timed out after {timeout}s during {what}")
        return message

    def _kill(self, reason: str) -> None:
        process, self._process = self._process, None
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        self._ready = False
        if process is not None and process.is_alive():
            logger.warning("Stopping model server. pid=%s reason=%s", process.pid, reason)
            process.terminate()
            process.join(5)
            if process.is_alive():
                process.kill()
                process.join(5)


def _poll(connection: Connection, timeout: float) -> dict[str, Any] | None:
    """Wait for one message, or None at the deadline. Raises EOFError if the other end closed."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if connection.poll(_POLL_SLICE_SECONDS):
            return connection.recv()
    return None
