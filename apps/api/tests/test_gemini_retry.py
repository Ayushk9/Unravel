"""Retries, backoff and the fallback model in GeminiQaLlm, with a fake client (no network)."""

from __future__ import annotations

import random
from types import SimpleNamespace

import pytest

from app.qa.llm import MAX_ATTEMPTS, GeminiQaLlm, LlmError, SearchTerms, backoff_seconds
from tests.db import run


class ApiFailure(Exception):
    def __init__(self, code: int, text: str = "") -> None:
        super().__init__(f"HTTP {code} {text}")
        self.code = code  # google.genai errors carry the HTTP status as `.code`


class FakeClient:
    """Replays a script of outcomes: an int is an HTTP error, anything else is a successful parsed reply."""

    def __init__(self, script: list) -> None:
        self.script = list(script)
        self.calls: list[str] = []
        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content=self._generate))

    async def _generate(self, *, model: str, contents, config):
        self.calls.append(model)
        outcome = self.script.pop(0)
        if isinstance(outcome, int):
            raise ApiFailure(outcome)
        if isinstance(outcome, ApiFailure):
            raise outcome
        return SimpleNamespace(parsed=outcome)


def _llm(script: list, fallback: str | None = "backup-model") -> tuple[GeminiQaLlm, FakeClient, list[float]]:
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    client = FakeClient(script)
    llm = GeminiQaLlm(api_key="x", model="main-model", fallback_model=fallback, timeout_seconds=5, sleep=sleep, client=client)
    return llm, client, waits


OK = SearchTerms(search_terms="room rent")


def test_a_busy_model_is_retried_and_then_answers() -> None:
    llm, client, waits = _llm([503, 503, OK])

    answered = run(llm.rewrite("q"))

    assert answered.value == "room rent" and answered.model == "main-model"
    assert client.calls == ["main-model"] * 3
    assert len(waits) == 2, "a wait between attempts, none after the last"


def test_after_four_failed_attempts_the_fallback_gets_one_try() -> None:
    llm, client, waits = _llm([429] * MAX_ATTEMPTS + [OK])

    answered = run(llm.rewrite("q"))

    assert answered.model == "backup-model", "which model answered is reported"
    assert client.calls == ["main-model"] * 4 + ["backup-model"]
    assert len(waits) == MAX_ATTEMPTS - 1


def test_without_a_fallback_the_error_is_retryable_and_says_why() -> None:
    llm, client, _ = _llm([503] * MAX_ATTEMPTS, fallback=None)

    with pytest.raises(LlmError) as error:
        run(llm.rewrite("q"))

    assert error.value.code == "overloaded" and error.value.retryable is True
    assert len(client.calls) == MAX_ATTEMPTS


def test_a_failing_fallback_is_not_retried() -> None:
    llm, client, _ = _llm([429] * MAX_ATTEMPTS + [429])

    with pytest.raises(LlmError) as error:
        run(llm.rewrite("q"))

    assert error.value.code == "rate_limited"
    assert client.calls[-1] == "backup-model" and len(client.calls) == MAX_ATTEMPTS + 1


@pytest.mark.parametrize("status", [400, 401, 404])
def test_other_errors_are_not_retried_and_not_retryable(status: int) -> None:
    llm, client, waits = _llm([status])

    with pytest.raises(LlmError) as error:
        run(llm.rewrite("q"))

    assert client.calls == ["main-model"] and waits == []
    assert error.value.code == "failed" and error.value.retryable is False


def test_backoff_grows_exponentially_with_full_jitter_and_a_cap() -> None:
    rng = random.Random(7)
    for attempt, ceiling in [(1, 2.0), (2, 4.0), (3, 8.0), (6, 8.0)]:
        samples = [backoff_seconds(attempt, rng) for _ in range(200)]
        assert all(0 <= s <= ceiling for s in samples)
        assert max(samples) > ceiling * 0.8, "jitter spreads over the whole range"


def test_the_fallback_is_ignored_when_it_is_the_same_model() -> None:
    llm, client, _ = _llm([503] * MAX_ATTEMPTS, fallback="main-model")

    with pytest.raises(LlmError):
        run(llm.rewrite("q"))

    assert client.calls == ["main-model"] * MAX_ATTEMPTS


def test_a_daily_quota_429_goes_straight_to_the_fallback() -> None:
    # The text Gemini sends when the free daily quota is used up.
    daily = ApiFailure(429, "{'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '68278s'}")
    llm, client, waits = _llm([daily, OK])

    answered = run(llm.rewrite("q"))

    assert answered.model == "backup-model"
    assert client.calls == ["main-model", "backup-model"] and waits == [], "no pointless waiting"


def test_a_short_retry_delay_is_still_retried() -> None:
    brief = ApiFailure(429, "{'retryDelay': '3s'}")
    llm, client, waits = _llm([brief, OK])

    assert run(llm.rewrite("q")).model == "main-model"
    assert len(waits) == 1


class ConfigRecorder(FakeClient):
    """Records the config each call was sent with."""

    def __init__(self, script: list) -> None:
        super().__init__(script)
        self.configs: list = []
        generate = self._generate

        async def recording(*, model: str, contents, config):
            self.configs.append(config)
            return await generate(model=model, contents=contents, config=config)

        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content=recording))


def test_grievance_calls_cap_thinking_and_output_while_qa_keeps_the_defaults() -> None:
    from app.grievance.llm import GeminiGrievanceLlm, GeneratedDraft
    from app.qa.llm import ClausePrompt, Verdict, Verdicts

    clause = ClausePrompt(id="c1", page=9, text="Room rent is limited to Rs 5,000 per day.")
    client = ConfigRecorder([GeneratedDraft(abstain=True), Verdicts(verdicts=[Verdict(pair=0, verdict="supported")]), OK])
    llm = GeminiGrievanceLlm(api_key="x", model="main-model", timeout_seconds=5, client=client)

    run(llm.draft("a letter", "facts", [clause]))
    run(llm.judge_paragraphs("facts", [("A paragraph.", clause)]))
    run(llm.rewrite("q"))  # a Q&A call on the same client

    draft, judge, qa = client.configs
    assert (draft.thinking_config.thinking_level, draft.max_output_tokens) == ("LOW", 2048)
    assert (judge.thinking_config.thinking_level, judge.max_output_tokens) == ("MINIMAL", 1024)
    assert (qa.thinking_config, qa.max_output_tokens) == (None, None), "Q&A is unchanged"
    assert all(config.temperature == 0.0 for config in client.configs)
