"""Tests that don't require network access or a real GEMINI_API_KEY:
prompt/table rendering (pure string building) and the cache short-circuit
(a cache hit must never construct a genai.Client — this is the "second run
makes zero API calls" requirement from the task brief)."""

from __future__ import annotations

from pathlib import Path

import pytest
from docling_core.types.doc.base import BoundingBox, CoordOrigin

import llm_extraction
from cache import DiskCache
from docling_wrapper import ParsedDocument, PageInfo, TableCellRecord, TableRecord
from errors import ExtractionError
from llm_schema import LLMPolicyExtraction


def _cell(text: str, row: int, col: int, *, header: bool = False) -> TableCellRecord:
    return TableCellRecord(
        text=text,
        bbox=BoundingBox(l=0, t=10, r=10, b=0, coord_origin=CoordOrigin.TOPLEFT),
        row_span=1,
        col_span=1,
        start_row_offset_idx=row,
        end_row_offset_idx=row + 1,
        start_col_offset_idx=col,
        end_col_offset_idx=col + 1,
        column_header=header,
        row_header=False,
    )


def test_render_table_for_prompt_marks_header_cells() -> None:
    table = TableRecord(
        page_no=10,
        bbox=None,
        cells=[
            _cell("Sum Insured", 0, 0, header=True),
            _cell("Room Rent (per day)", 0, 1, header=True),
            _cell("5,00,000/-", 1, 0),
            _cell("1,250/-", 1, 1),
        ],
    )

    rendered = llm_extraction.render_table_for_prompt(table, index=1)

    assert "[Table 1, page 10]" in rendered
    assert "[H]Sum Insured | [H]Room Rent (per day)" in rendered
    assert "5,00,000/- | 1,250/-" in rendered


def test_render_table_for_prompt_orders_rows_and_columns() -> None:
    # Cells inserted out of order — output must still read top-to-bottom, left-to-right.
    table = TableRecord(
        page_no=1,
        bbox=None,
        cells=[
            _cell("B1", 1, 0),
            _cell("A2", 0, 1),
            _cell("A1", 0, 0),
            _cell("B2", 1, 1),
        ],
    )

    rendered = llm_extraction.render_table_for_prompt(table, index=1)
    lines = rendered.splitlines()

    assert lines[1] == "A1 | A2"
    assert lines[2] == "B1 | B2"


def _empty_parsed_document(markdown: str, tables: list[TableRecord]) -> ParsedDocument:
    return ParsedDocument(
        page_count=1,
        pages={1: PageInfo(page_no=1, width=595.2756, height=841.8898)},
        text_items=[],
        tables=tables,
        markdown=markdown,
        ocr_used=False,
        warnings=[],
    )


def test_build_prompt_includes_markdown_and_table_dump() -> None:
    table = TableRecord(page_no=1, bbox=None, cells=[_cell("Sum Insured", 0, 0, header=True)])
    parsed = _empty_parsed_document("## Policy Schedule\n\nSum insured is Rs.5,00,000/-.", [table])

    prompt = llm_extraction.build_prompt(parsed, "policy")

    assert "Sum insured is Rs.5,00,000/-." in prompt
    assert "[Table 1, page 1]" in prompt
    assert "[H]Sum Insured" in prompt
    assert "claim intimation deadline" in prompt  # policy-specific instructions present


def test_build_prompt_omits_table_section_when_no_tables() -> None:
    parsed = _empty_parsed_document("no tables here", [])
    prompt = llm_extraction.build_prompt(parsed, "bill")
    assert "=== TABLES" not in prompt


def test_cache_hit_short_circuits_without_client_or_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    def _fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("genai.Client should never be constructed on a cache hit")

    monkeypatch.setattr(llm_extraction.genai, "Client", _fail_if_called)

    cache = DiskCache(cache_dir=tmp_path)
    file_path = tmp_path / "policy.pdf"
    file_path.write_bytes(b"fake pdf bytes")

    cached_payload = LLMPolicyExtraction(
        sum_insured_raw="5,00,000/-",
        sum_insured_source_text="Sum insured is Rs.5,00,000/-.",
        co_pay_percent=None,
        co_pay_percent_source_text=None,
        sub_limits=[],
        waiting_periods=[],
        exclusions=[],
        intimation_deadline_hours=None,
        intimation_deadline_hours_source_text=None,
    )
    from cache import build_cache_key

    cache.set(
        build_cache_key(file_path, "policy", llm_extraction.PROMPT_VERSION),
        cached_payload.model_dump(mode="json"),
    )

    parsed = _empty_parsed_document("irrelevant", [])
    result = llm_extraction.extract_with_llm(file_path, "policy", parsed, cache=cache)

    assert result == cached_payload


def test_missing_api_key_raises_on_cache_miss(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    cache = DiskCache(cache_dir=tmp_path)
    file_path = tmp_path / "policy.pdf"
    file_path.write_bytes(b"fake pdf bytes")
    parsed = _empty_parsed_document("irrelevant", [])

    with pytest.raises(ExtractionError, match="GEMINI_API_KEY"):
        llm_extraction.extract_with_llm(file_path, "policy", parsed, cache=cache)


# --- Fix 5: retries must exclude non-retryable 4xx (a retired model id is a 404) ---


def test_sdk_default_retry_codes_exclude_non_retryable_4xx() -> None:
    """Guards the assumption Fix 5 relies on: google-genai's own default
    retry status-code allowlist already excludes 404 and every other
    non-retryable 4xx, and includes 429 plus the 5xx family. If a future
    SDK upgrade ever changes this default, this test catches it — our fix
    is "turn retries on", not "invent our own status-code list", so it's
    only correct as long as this assumption holds.
    """
    from google.genai._api_client import _RETRY_HTTP_STATUS_CODES

    for non_retryable in (400, 401, 403, 404, 422):
        assert non_retryable not in _RETRY_HTTP_STATUS_CODES

    assert 429 in _RETRY_HTTP_STATUS_CODES
    for server_error in (500, 502, 503, 504):
        assert server_error in _RETRY_HTTP_STATUS_CODES


def test_extract_with_llm_enables_retries_via_sdk_default_codes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """extract_with_llm must construct its Client with retries turned on
    (retry_options set), and must NOT override http_status_codes with a
    custom list — leaving it None means the SDK's own already-correct
    default (see the test above) governs which errors get retried.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-this-test-only")

    captured_kwargs: dict[str, object] = {}

    class _FakeModels:
        def generate_content(self, **kwargs: object) -> None:
            raise RuntimeError("network call should not happen in this test")

    class _FakeClient:
        def __init__(self, **kwargs: object) -> None:
            captured_kwargs.update(kwargs)
            self.models = _FakeModels()

    monkeypatch.setattr(llm_extraction.genai, "Client", _FakeClient)

    cache = DiskCache(cache_dir=tmp_path)
    file_path = tmp_path / "policy.pdf"
    file_path.write_bytes(b"fake pdf bytes")
    parsed = _empty_parsed_document("irrelevant", [])

    with pytest.raises(ExtractionError, match="Gemini extraction call failed"):
        llm_extraction.extract_with_llm(file_path, "policy", parsed, cache=cache)

    http_options = captured_kwargs["http_options"]
    assert http_options.retry_options is not None
    assert http_options.retry_options.attempts == 3
    assert http_options.retry_options.http_status_codes is None  # defer to the SDK's own default allowlist
