"""The warm model server's process handling, with stand-in children (no real models).

Real models are measured separately: scripts/measure_model_server.py.
"""

from __future__ import annotations

import pytest

from app.models_server.client import ModelServer, ModelServerError
from tests import fake_model_process
from tests.db import run


def _server(target, request_timeout: float = 5.0) -> ModelServer:
    return ModelServer(
        embed_model="x", rerank_model="y", device="cpu", load_timeout_seconds=10, request_timeout_seconds=request_timeout, target=target
    )


def test_one_process_serves_many_requests() -> None:
    server = _server(fake_model_process.echo)

    async def go() -> tuple[list[list[float]], list[float], int | None, int | None]:
        server.start()
        vectors = await server.embed(["ab", "abcd"])
        first_pid = server._process.pid if server._process else None
        scores = await server.rerank("q", ["a", "abc"])
        second_pid = server._process.pid if server._process else None
        await server.stop()
        return vectors, scores, first_pid, second_pid

    vectors, scores, first_pid, second_pid = run(go())

    assert [v[0] for v in vectors] == [2.0, 4.0]
    assert scores == [1.0, 3.0]
    assert first_pid == second_pid, "the same warm process answered both requests"


def test_empty_inputs_make_no_request() -> None:
    server = _server(fake_model_process.fail_to_load)

    assert run(server.embed([])) == [] and run(server.rerank("q", [])) == []
    assert server._process is None, "nothing was started"


@pytest.mark.parametrize(
    ("target", "words"),
    [(fake_model_process.hang_on_request, "timed out"), (fake_model_process.crash_on_request, "died"), (fake_model_process.fail_to_load, "failed to load")],
)
def test_a_misbehaving_server_raises_and_is_stopped(target, words: str) -> None:
    server = _server(target, request_timeout=1.0)

    with pytest.raises(ModelServerError, match=words):
        run(server.embed(["text"]))

    assert server._process is None, "the process was killed, so the next request starts a fresh one"


def test_the_next_request_after_a_failure_starts_a_fresh_process() -> None:
    server = _server(fake_model_process.crash_on_request, request_timeout=1.0)
    with pytest.raises(ModelServerError):
        run(server.embed(["text"]))

    server._target = fake_model_process.echo
    assert run(server.embed(["abc"]))[0][0] == 3.0
    run(server.stop())
