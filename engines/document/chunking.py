"""Build DocumentChunk entries for later retrieval.

Chunk boundaries are Docling's own item boundaries, never a mid-item
character cut. Docling has already segmented the document into semantic
units (paragraphs, headings, list items) via its layout model — re-slicing
that by a fixed character count would throw that segmentation away and risk
cutting a sentence in half. Consecutive text items on the same page are
merged up to a soft size cap purely to avoid a chunk pool with hundreds of
one-line fragments (the spike corpus had 550-850 text items per document);
the cap only ever chooses *where between items* to end a chunk, never
splits inside one. A chunk never spans a page break, since a chunk carries
exactly one page + one bbox, and merging across pages would make that bbox
meaningless.

Tables get their own chunk each (one row per line), since a sub-limit table
is exactly the kind of content a policy Q&A retrieval system needs to find.
"""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID, uuid4

import _bootstrap  # noqa: F401 — puts the repo root on sys.path for `contracts`
from contracts.models import DocumentChunk
from docling_wrapper import PageInfo, ParsedDocument, TableRecord, TextItemRecord
from geometry import normalise_bbox

_MAX_CHUNK_CHARS = 1500


def build_chunks(parsed: ParsedDocument, document_id: UUID, warnings: list[str]) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    chunks.extend(_text_chunks(parsed, document_id, warnings))
    chunks.extend(_table_chunks(parsed, document_id, warnings))
    return chunks


def _text_chunks(parsed: ParsedDocument, document_id: UUID, warnings: list[str]) -> list[DocumentChunk]:
    items_by_page: dict[int, list[TextItemRecord]] = defaultdict(list)
    for item in parsed.text_items:
        items_by_page[item.page_no].append(item)

    chunks: list[DocumentChunk] = []
    for page_no in sorted(items_by_page):
        page_info = parsed.pages.get(page_no)
        group: list[TextItemRecord] = []
        group_chars = 0

        for item in items_by_page[page_no]:
            if group and group_chars + len(item.text) > _MAX_CHUNK_CHARS:
                chunks.append(_make_text_chunk(group, page_no, page_info, document_id, warnings))
                group, group_chars = [], 0
            group.append(item)
            group_chars += len(item.text)

        if group:
            chunks.append(_make_text_chunk(group, page_no, page_info, document_id, warnings))

    return chunks


def _make_text_chunk(
    items: list[TextItemRecord],
    page_no: int,
    page_info: PageInfo | None,
    document_id: UUID,
    warnings: list[str],
) -> DocumentChunk:
    text = "\n".join(item.text for item in items)
    bbox = _union_normalised_bbox(items, page_info, warnings) if page_info is not None else None
    return DocumentChunk(id=uuid4(), document_id=document_id, page=page_no, text=text, bbox=bbox)


def _union_normalised_bbox(
    items: list[TextItemRecord], page_info: PageInfo, warnings: list[str]
) -> tuple[float, float, float, float] | None:
    """Union of each item's own normalised bbox.

    Normalising each item individually first — rather than trying to union
    the raw l/t/r/b values directly — means this never has to re-derive the
    BOTTOMLEFT/TOPLEFT flip logic; it reuses normalise_bbox as the single
    place that knows about coordinate origins.
    """
    boxes: list[tuple[float, float, float, float]] = []
    for item in items:
        try:
            boxes.append(normalise_bbox(item.bbox, page_info.width, page_info.height))
        except ValueError as exc:
            warnings.append(f"chunk on page {item.page_no}: could not normalise a text item bbox: {exc}")

    if not boxes:
        return None

    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[2] for b in boxes)
    y1 = max(b[3] for b in boxes)
    return (x0, y0, x1, y1)


def _table_chunks(parsed: ParsedDocument, document_id: UUID, warnings: list[str]) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    for index, table in enumerate(parsed.tables, start=1):
        if table.page_no is None:
            warnings.append(f"table {index} has no page number — skipping its chunk")
            continue

        text = _render_table_text(table)
        bbox = None
        page_info = parsed.pages.get(table.page_no)
        if table.bbox is not None and page_info is not None:
            try:
                bbox = normalise_bbox(table.bbox, page_info.width, page_info.height)
            except ValueError as exc:
                warnings.append(f"table {index} on page {table.page_no}: could not normalise bbox: {exc}")

        chunks.append(DocumentChunk(id=uuid4(), document_id=document_id, page=table.page_no, text=text, bbox=bbox))
    return chunks


def _render_table_text(table: TableRecord) -> str:
    rows: dict[int, list] = defaultdict(list)
    for cell in table.cells:
        rows[cell.start_row_offset_idx].append(cell)

    lines = []
    for row_idx in sorted(rows):
        cells_in_row = sorted(rows[row_idx], key=lambda c: c.start_col_offset_idx)
        lines.append(" | ".join(" ".join(c.text.split()) for c in cells_in_row))
    return "\n".join(lines)
