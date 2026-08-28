"""Provenance matching, the validity gate (Fix 1), cross-field dedup, and
confidence tests.

Fix 1 incident, reproduced directly in several tests below: co_pay_percent,
a sub-limit, and an exclusion all resolved to a single-character cell
("1"); three different waiting periods all resolved to one cell ("All");
and a Rs.2,50,000 sub-limit resolved to a cell reading "5,00,000/-" — all
scored "high". See provenance.py's module comment above MIN_MATCH_LENGTH
for the full incident writeup.
"""

from __future__ import annotations

from uuid import uuid4

from docling_core.types.doc.base import BoundingBox, CoordOrigin

from docling_wrapper import PageInfo, ParsedDocument, TableCellRecord, TableRecord, TextItemRecord
from provenance import (
    MIN_BBOX_WIDTH_POINTS,
    MIN_MATCH_LENGTH,
    NO_MATCH,
    build_provenance,
    compute_confidence,
    deduplicate_by_location,
    find_best_match,
    is_spanned_header_column,
)

PAGE = PageInfo(page_no=1, width=595.2756, height=841.8898)

# A realistic normal-sized table cell, e.g. "5,00,000/-" rendered at a
# typical font size — comfortably clears MIN_BBOX_WIDTH_POINTS.
_NORMAL_BBOX = BoundingBox(l=47, t=284, r=97, b=295, coord_origin=CoordOrigin.TOPLEFT)
# The exact bbox from the Fix 1 incident: a single character, 4pt wide.
_TINY_BBOX = BoundingBox(l=71, t=489, r=75, b=500, coord_origin=CoordOrigin.TOPLEFT)


def _cell(text: str, bbox: BoundingBox = _NORMAL_BBOX, row: int = 0, col: int = 0, *, header: bool = False) -> TableCellRecord:
    return TableCellRecord(
        text=text,
        bbox=bbox,
        row_span=1,
        col_span=1,
        start_row_offset_idx=row,
        end_row_offset_idx=row + 1,
        start_col_offset_idx=col,
        end_col_offset_idx=col + 1,
        column_header=header,
        row_header=False,
    )


def _text_item(text: str, page_no: int = 1, bbox: BoundingBox | None = None) -> TextItemRecord:
    return TextItemRecord(
        text=text, page_no=page_no, bbox=bbox or BoundingBox(l=0, t=20, r=300, b=0, coord_origin=CoordOrigin.BOTTOMLEFT)
    )


def _parsed(tables: list[TableRecord] | None = None, text_items: list[TextItemRecord] | None = None) -> ParsedDocument:
    return ParsedDocument(
        page_count=1, pages={1: PAGE}, text_items=text_items or [], tables=tables or [], markdown="", ocr_used=False, warnings=[]
    )


# --- Gate: minimum length ----------------------------------------------------


def test_single_char_source_text_against_single_char_cell_is_rejected() -> None:
    # The exact Fix 1 scenario: source_text "1" against a cell containing "1".
    table = TableRecord(page_no=1, bbox=None, cells=[_cell("1", bbox=_TINY_BBOX)])
    match = find_best_match("1", _parsed(tables=[table]))
    assert match.matched_via == "none"


def test_short_source_text_is_rejected_regardless_of_candidate() -> None:
    # Target itself under MIN_MATCH_LENGTH — rejected before any candidate is even scanned.
    table = TableRecord(page_no=1, bbox=None, cells=[_cell("A perfectly long and legitimate cell of real content")])
    assert len("10%") < MIN_MATCH_LENGTH
    match = find_best_match("10%", _parsed(tables=[table]))
    assert match.matched_via == "none"


def test_long_source_text_against_short_candidate_is_rejected() -> None:
    table = TableRecord(page_no=1, bbox=None, cells=[_cell("or", bbox=_NORMAL_BBOX)])
    match = find_best_match("A co-payment of 10% is applicable on every admissible claim", _parsed(tables=[table]))
    assert match.matched_via == "none"


# --- Gate: value containment --------------------------------------------------


def test_copay_value_against_single_char_cell_rejected_by_containment() -> None:
    # co_pay_percent=10.0 with candidate cell "1" -> REJECTED (containment).
    # (Length gate alone already rejects "1" here, but this exercises the
    # value_text plumbing specifically — see the next test for a case where
    # length passes and only containment can catch it.)
    table = TableRecord(page_no=1, bbox=None, cells=[_cell("1", bbox=_TINY_BBOX)])
    match = find_best_match(
        "A co-payment of ten percent applies to every claim", _parsed(tables=[table]), value_text="10.0"
    )
    assert match.matched_via == "none"


def test_wrong_amount_of_similar_shape_rejected_by_containment() -> None:
    # The real ambulance bug: a Rs.2,50,000 sub-limit resolving to a cell
    # reading "5,00,000/-" — same shape, different number. Both sides are
    # long enough to clear the length gate; only containment catches this.
    table = TableRecord(
        page_no=10,
        bbox=None,
        cells=[_cell("5,00,000/- per hospitalisation and policy period combined")],
    )
    match = find_best_match(
        "5,00,000/- per hospitalisation and policy period combined",
        _parsed(tables=[table]),
        value_text="2,50,000/-",
    )
    assert match.matched_via == "none"


def test_correct_amount_accepted_by_containment() -> None:
    table = TableRecord(
        page_no=10,
        bbox=None,
        cells=[_cell("5,00,000/- per hospitalisation and policy period combined")],
    )
    match = find_best_match(
        "5,00,000/- per hospitalisation and policy period combined",
        _parsed(tables=[table]),
        value_text="5,00,000/-",
    )
    assert match.matched_via == "cell"


def test_value_embedded_in_longer_candidate_passes_containment() -> None:
    # The real OPD case: value "300" embedded inside a full descriptive sentence.
    table = TableRecord(page_no=15, bbox=None, cells=[_cell("Limit of per consultation is Rs. 300/-")])
    match = find_best_match(
        "Limit of per consultation is Rs. 300/-", _parsed(tables=[table]), value_text="300/-"
    )
    assert match.matched_via == "cell"
    assert match.snippet == "Limit of per consultation is Rs. 300/-"


# --- Gate: bbox size -----------------------------------------------------------


def test_tiny_bbox_rejected_even_with_long_matching_text() -> None:
    # Text itself is long enough and matches perfectly — only the bbox is
    # degenerate (narrower than MIN_BBOX_WIDTH_POINTS). Still rejected.
    long_text = "This cell nominally contains a long string of real words"
    assert MIN_BBOX_WIDTH_POINTS > abs(_TINY_BBOX.r - _TINY_BBOX.l)
    table = TableRecord(page_no=1, bbox=None, cells=[_cell(long_text, bbox=_TINY_BBOX)])
    match = find_best_match(long_text, _parsed(tables=[table]))
    assert match.matched_via == "none"


def test_normal_sized_bbox_with_long_text_accepted() -> None:
    long_text = "This cell nominally contains a long string of real words"
    table = TableRecord(page_no=1, bbox=None, cells=[_cell(long_text, bbox=_NORMAL_BBOX)])
    match = find_best_match(long_text, _parsed(tables=[table]))
    assert match.matched_via == "cell"


# --- Gate: token overlap --------------------------------------------------------


def test_shared_stopwords_only_does_not_satisfy_token_overlap() -> None:
    # Long enough on both sides, decent partial_ratio potential from shared
    # connector words, but no shared *content* — must still be rejected.
    target = "The claim shall be settled in accordance with and subject to the policy terms"
    candidate = "This document is provided for and in accordance with all applicable regulations"
    table = TableRecord(page_no=1, bbox=None, cells=[_cell(candidate)])
    match = find_best_match(target, _parsed(tables=[table]))
    assert match.matched_via == "none"


def test_shared_content_words_pass_token_overlap() -> None:
    # Near-identical wording (clears both the fuzzy-score threshold and the
    # content-token-overlap gate) as a contrast to the stopword-only test above.
    target = "The waiting period for pre-existing diseases is thirty six months"
    candidate = "The waiting period for pre-existing diseases is thirty six months from inception"
    table = TableRecord(page_no=1, bbox=None, cells=[_cell(candidate)])
    match = find_best_match(target, _parsed(tables=[table]))
    assert match.matched_via == "cell"


# --- End-to-end: the exclusion garbage matches from the incident ---------------


def test_exclusion_does_not_match_bare_stopword_cells() -> None:
    for garbage in ["or", "x.", "All", "1", "and"]:
        table = TableRecord(page_no=6, bbox=None, cells=[_cell(garbage, bbox=_TINY_BBOX)])
        match = find_best_match(
            "Cosmetic surgery and treatment for obesity are permanently excluded", _parsed(tables=[table])
        )
        assert match.matched_via == "none", f"garbage candidate {garbage!r} should not have matched"


# --- Uniqueness / cross-field dedup ---------------------------------------------


def test_two_fields_sharing_a_bbox_only_one_keeps_provenance() -> None:
    long_text = "All admissible claims under this policy are subject to a defined waiting period"
    shared_bbox = _NORMAL_BBOX
    matches = {
        "waiting_period[initial]": find_best_match(
            long_text, _parsed(tables=[TableRecord(page_no=20, bbox=None, cells=[_cell(long_text, bbox=shared_bbox)])])
        ),
        "waiting_period[pre_existing]": find_best_match(
            long_text, _parsed(tables=[TableRecord(page_no=20, bbox=None, cells=[_cell(long_text, bbox=shared_bbox)])])
        ),
    }
    # Force distinct scores so the winner is deterministic for the assertion.
    winner = matches["waiting_period[initial]"]
    loser_replacement = type(winner)(
        matched_via=winner.matched_via,
        score=winner.score - 1,
        page_no=winner.page_no,
        bbox=winner.bbox,
        snippet=winner.snippet,
        table=winner.table,
        cell=winner.cell,
    )
    matches["waiting_period[pre_existing]"] = loser_replacement

    deduped, warnings = deduplicate_by_location(matches)

    survivors = [name for name, m in deduped.items() if m.matched_via != "none"]
    assert survivors == ["waiting_period[initial]"]
    assert deduped["waiting_period[pre_existing]"] is NO_MATCH
    assert len(warnings) == 1
    assert "waiting_period[initial]" in warnings[0] and "waiting_period[pre_existing]" in warnings[0]


def test_three_waiting_periods_sharing_one_bbox_only_one_survives() -> None:
    # Direct reproduction of the reported incident shape (three fields, one bbox).
    m = find_best_match(
        "All admissible claims are subject to the applicable waiting period stated herein",
        _parsed(
            tables=[
                TableRecord(
                    page_no=20,
                    bbox=None,
                    cells=[
                        _cell(
                            "All admissible claims are subject to the applicable waiting period stated herein",
                            bbox=_NORMAL_BBOX,
                        )
                    ],
                )
            ]
        ),
    )
    matches = {"waiting_period[initial]": m, "waiting_period[disease_specific]": m, "waiting_period[pre_existing]": m}

    deduped, warnings = deduplicate_by_location(matches)

    survivors = [name for name, match in deduped.items() if match.matched_via != "none"]
    assert len(survivors) == 1
    assert len(warnings) == 1


def test_distinct_locations_are_left_untouched_by_dedup() -> None:
    table = TableRecord(
        page_no=1,
        bbox=None,
        cells=[
            _cell("This is the first genuinely distinct sentence content", bbox=BoundingBox(l=0, t=20, r=200, b=10, coord_origin=CoordOrigin.TOPLEFT)),
            _cell("This is a second, entirely different sentence content", bbox=BoundingBox(l=0, t=40, r=200, b=30, coord_origin=CoordOrigin.TOPLEFT)),
        ],
    )
    parsed = _parsed(tables=[table])
    matches = {
        "a": find_best_match("This is the first genuinely distinct sentence content", parsed),
        "b": find_best_match("This is a second, entirely different sentence content", parsed),
    }

    deduped, warnings = deduplicate_by_location(matches)

    assert deduped["a"].matched_via == "cell"
    assert deduped["b"].matched_via == "cell"
    assert warnings == []


def test_dedup_ignores_fields_with_no_match() -> None:
    deduped, warnings = deduplicate_by_location({"a": NO_MATCH, "b": NO_MATCH})
    assert deduped == {"a": NO_MATCH, "b": NO_MATCH}
    assert warnings == []


# --- build_provenance (unaffected by the gate, still exercised) ----------------


def test_build_provenance_normalises_bbox() -> None:
    long_text = "This is the first genuinely distinct sentence content"
    table = TableRecord(page_no=1, bbox=None, cells=[_cell(long_text)])
    match = find_best_match(long_text, _parsed(tables=[table]))

    warnings: list[str] = []
    doc_id = uuid4()
    prov = build_provenance(match, doc_id, {1: PAGE}, warnings)

    assert prov is not None
    assert prov.document_id == doc_id
    assert prov.page == 1
    assert prov.bbox is not None
    assert all(0.0 <= c <= 1.0 for c in prov.bbox)
    assert prov.snippet == long_text
    assert warnings == []


def test_build_provenance_none_for_no_match() -> None:
    warnings: list[str] = []
    assert build_provenance(NO_MATCH, uuid4(), {1: PAGE}, warnings) is None
    assert warnings == []


def test_build_provenance_degrades_gracefully_on_bad_page_dims() -> None:
    bad_page = PageInfo(page_no=1, width=0.0, height=0.0)
    long_text = "This is the first genuinely distinct sentence content"
    table = TableRecord(page_no=1, bbox=None, cells=[_cell(long_text)])
    match = find_best_match(long_text, _parsed(tables=[table]))

    warnings: list[str] = []
    prov = build_provenance(match, uuid4(), {1: bad_page}, warnings)

    assert prov is not None
    assert prov.bbox is None
    assert prov.page == 1
    assert len(warnings) == 1
    assert "could not normalise" in warnings[0]


# --- compute_confidence, revised rules ------------------------------------------


def test_confidence_high_on_gated_cell_match() -> None:
    long_text = "This is the first genuinely distinct sentence content"
    table = TableRecord(page_no=1, bbox=None, cells=[_cell(long_text)])
    match = find_best_match(long_text, _parsed(tables=[table]))

    assert compute_confidence(match=match, value_is_present=True, value_parsed_cleanly=True) == "high"


def test_confidence_medium_on_text_item_match() -> None:
    long_text = "excluded until the expiry of thirty six months of continuous coverage"
    item = _text_item(long_text)
    match = find_best_match(long_text, _parsed(text_items=[item]))

    assert match.matched_via == "text_item"
    assert compute_confidence(match=match, value_is_present=True, value_parsed_cleanly=True) == "medium"


def test_confidence_medium_when_coercion_needed_despite_cell_match() -> None:
    long_text = "This is the first genuinely distinct sentence content"
    table = TableRecord(page_no=1, bbox=None, cells=[_cell(long_text)])
    match = find_best_match(long_text, _parsed(tables=[table]))

    assert compute_confidence(match=match, value_is_present=True, value_parsed_cleanly=False) == "medium"


def test_confidence_medium_when_basis_from_spanned_header() -> None:
    long_text = "This is the first genuinely distinct sentence content"
    table = TableRecord(page_no=1, bbox=None, cells=[_cell(long_text)])
    match = find_best_match(long_text, _parsed(tables=[table]))

    confidence = compute_confidence(
        match=match, value_is_present=True, value_parsed_cleanly=True, basis_from_spanned_header=True
    )
    assert confidence == "medium"


def test_confidence_low_when_no_match() -> None:
    assert compute_confidence(match=NO_MATCH, value_is_present=True, value_parsed_cleanly=True) == "low"


def test_confidence_low_when_value_absent() -> None:
    long_text = "This is the first genuinely distinct sentence content"
    table = TableRecord(page_no=1, bbox=None, cells=[_cell(long_text)])
    match = find_best_match(long_text, _parsed(tables=[table]))

    assert compute_confidence(match=match, value_is_present=False, value_parsed_cleanly=True) == "low"


# --- is_spanned_header_column (unaffected by the gate) --------------------------


def test_is_spanned_header_column_detects_duplicated_header_text() -> None:
    table = TableRecord(
        page_no=1,
        bbox=None,
        cells=[
            _cell("Sum Insured (Rs.)", row=0, col=0, header=True),
            _cell("Sum Insured (Rs.)", row=0, col=1, header=True),
            _cell("5,00,000/-", row=1, col=0),
            _cell("7,50,000/-", row=1, col=1),
        ],
    )
    matched_cell = table.cells[2]
    assert is_spanned_header_column(table, matched_cell)


def test_is_spanned_header_column_false_for_distinct_headers() -> None:
    table = TableRecord(
        page_no=1,
        bbox=None,
        cells=[
            _cell("Sum Insured", row=0, col=0, header=True),
            _cell("Room Rent", row=0, col=1, header=True),
            _cell("5,00,000/-", row=1, col=0),
        ],
    )
    matched_cell = table.cells[2]
    assert not is_spanned_header_column(table, matched_cell)
