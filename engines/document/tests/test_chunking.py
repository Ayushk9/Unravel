from __future__ import annotations

from uuid import uuid4

from docling_core.types.doc.base import BoundingBox, CoordOrigin

from chunking import build_chunks
from docling_wrapper import PageInfo, ParsedDocument, TableCellRecord, TableRecord, TextItemRecord

PAGE = PageInfo(page_no=1, width=595.2756, height=841.8898)


def _text_item(text: str, page_no: int = 1, t: float = 800, b: float = 780) -> TextItemRecord:
    return TextItemRecord(
        text=text, page_no=page_no, bbox=BoundingBox(l=50, t=t, r=200, b=b, coord_origin=CoordOrigin.BOTTOMLEFT)
    )


def _cell(text: str, row: int, col: int) -> TableCellRecord:
    return TableCellRecord(
        text=text,
        bbox=BoundingBox(l=0, t=10, r=10, b=0, coord_origin=CoordOrigin.TOPLEFT),
        row_span=1,
        col_span=1,
        start_row_offset_idx=row,
        end_row_offset_idx=row + 1,
        start_col_offset_idx=col,
        end_col_offset_idx=col + 1,
        column_header=False,
        row_header=False,
    )


def test_short_items_on_same_page_merge_into_one_chunk() -> None:
    parsed = ParsedDocument(
        page_count=1,
        pages={1: PAGE},
        text_items=[_text_item("First paragraph."), _text_item("Second paragraph.", t=770, b=750)],
        tables=[],
        markdown="",
        ocr_used=False,
        warnings=[],
    )

    chunks = build_chunks(parsed, uuid4(), [])

    assert len(chunks) == 1
    assert chunks[0].text == "First paragraph.\nSecond paragraph."
    assert chunks[0].page == 1


def test_chunk_never_splits_mid_item_even_over_soft_cap() -> None:
    huge_item = _text_item("x" * 2000)
    parsed = ParsedDocument(
        page_count=1, pages={1: PAGE}, text_items=[huge_item], tables=[], markdown="", ocr_used=False, warnings=[]
    )

    chunks = build_chunks(parsed, uuid4(), [])

    assert len(chunks) == 1
    assert chunks[0].text == "x" * 2000


def test_items_over_soft_cap_split_into_multiple_chunks_at_item_boundaries() -> None:
    # Two 700-char items merge (1400 <= 1500 cap); the third would push the
    # group to 2100, so it starts a fresh chunk instead — the split always
    # falls between items, never inside one.
    items = [_text_item("y" * 700, t=800 - i * 10, b=790 - i * 10) for i in range(3)]
    parsed = ParsedDocument(
        page_count=1, pages={1: PAGE}, text_items=items, tables=[], markdown="", ocr_used=False, warnings=[]
    )

    chunks = build_chunks(parsed, uuid4(), [])

    assert len(chunks) == 2
    assert len(chunks[0].text) == 700 * 2 + 1  # two items joined by "\n"
    assert len(chunks[1].text) == 700


def test_chunks_never_span_a_page_break() -> None:
    pages = {1: PAGE, 2: PAGE}
    parsed = ParsedDocument(
        page_count=2,
        pages=pages,
        text_items=[_text_item("page one text", page_no=1), _text_item("page two text", page_no=2)],
        tables=[],
        markdown="",
        ocr_used=False,
        warnings=[],
    )

    chunks = build_chunks(parsed, uuid4(), [])

    assert len(chunks) == 2
    assert {c.page for c in chunks} == {1, 2}


def test_chunk_bbox_is_union_of_its_items_and_normalised() -> None:
    parsed = ParsedDocument(
        page_count=1,
        pages={1: PAGE},
        text_items=[_text_item("top", t=800, b=790), _text_item("bottom", t=700, b=690)],
        tables=[],
        markdown="",
        ocr_used=False,
        warnings=[],
    )

    chunks = build_chunks(parsed, uuid4(), [])

    assert len(chunks) == 1
    bbox = chunks[0].bbox
    assert bbox is not None
    assert all(0.0 <= c <= 1.0 for c in bbox)
    # top item's bottom-left-origin t=800 normalises to a smaller y than the
    # bottom item's t=700 — union y0 must be the smaller (topmost) value.
    x0, y0, x1, y1 = bbox
    assert y0 < y1


def test_table_gets_its_own_chunk_rendered_as_rows() -> None:
    table = TableRecord(
        page_no=1,
        bbox=BoundingBox(l=50, t=600, r=300, b=500, coord_origin=CoordOrigin.BOTTOMLEFT),
        cells=[_cell("Sum Insured", 0, 0), _cell("Room Rent", 0, 1), _cell("5,00,000/-", 1, 0), _cell("1,250/-", 1, 1)],
    )
    parsed = ParsedDocument(
        page_count=1, pages={1: PAGE}, text_items=[], tables=[table], markdown="", ocr_used=False, warnings=[]
    )

    chunks = build_chunks(parsed, uuid4(), [])

    assert len(chunks) == 1
    assert chunks[0].text == "Sum Insured | Room Rent\n5,00,000/- | 1,250/-"
    assert chunks[0].page == 1
    assert chunks[0].bbox is not None


def test_table_with_no_page_is_skipped_with_warning() -> None:
    table = TableRecord(page_no=None, bbox=None, cells=[_cell("x", 0, 0)])
    parsed = ParsedDocument(
        page_count=1, pages={1: PAGE}, text_items=[], tables=[table], markdown="", ocr_used=False, warnings=[]
    )

    warnings: list[str] = []
    chunks = build_chunks(parsed, uuid4(), warnings)

    assert chunks == []
    assert len(warnings) == 1


def test_empty_document_produces_no_chunks() -> None:
    parsed = ParsedDocument(
        page_count=0, pages={}, text_items=[], tables=[], markdown="", ocr_used=False, warnings=[]
    )
    assert build_chunks(parsed, uuid4(), []) == []
