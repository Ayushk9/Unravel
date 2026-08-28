"""Docling conversion, configured per SPIKE_NOTES.md finding 1.

OCR is the dominant cost on digital PDFs (200.75s vs 19.6s for the same
47-page file, identical 24 tables extracted — see SPIKE_NOTES.md) because
RapidOCR still runs and finds nothing when a text layer already exists.
`do_ocr=False` is therefore the default, and this module decides whether a
given PDF needs OCR *before* running Docling at all, by sampling the PDF's
own embedded text via pypdfium2 — this is a single cheap pass (well under a
second even on a 50-page file), versus running the expensive Docling
pipeline once to find out and then re-running it. Docling's own post-hoc
`ocr_appeared_needed` signal (confidence.pages[n].ocr_score) was tried in
the spike and found noisy — see SPIKE_NOTES.md finding 6 — so it is not
used here as the trigger.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pypdfium2 as pdfium
from docling.datamodel.base_models import ConversionStatus, InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc.base import BoundingBox
from docling_core.types.doc.document import TableItem, TextItem

from errors import ExtractionError

# Below this average of non-whitespace characters per sampled page, a PDF is
# treated as having no usable text layer. The scanned sample in the spike
# corpus measured 0 chars/page; the digital samples measured 1,000+
# chars/page — the gap is wide enough that this threshold is not sensitive
# to its exact value.
_TEXT_LAYER_CHARS_PER_PAGE_THRESHOLD = 20
_TEXT_LAYER_SAMPLE_PAGES = 10


@dataclass(frozen=True)
class PageInfo:
    page_no: int
    width: float
    height: float


@dataclass(frozen=True)
class TextItemRecord:
    text: str
    page_no: int
    bbox: BoundingBox


@dataclass(frozen=True)
class TableCellRecord:
    text: str
    bbox: BoundingBox
    row_span: int
    col_span: int
    start_row_offset_idx: int
    end_row_offset_idx: int
    start_col_offset_idx: int
    end_col_offset_idx: int
    column_header: bool
    row_header: bool


@dataclass(frozen=True)
class TableRecord:
    page_no: int | None
    bbox: BoundingBox | None
    cells: list[TableCellRecord]


@dataclass
class ParsedDocument:
    page_count: int
    pages: dict[int, PageInfo]
    text_items: list[TextItemRecord]
    tables: list[TableRecord]
    markdown: str
    ocr_used: bool
    warnings: list[str] = field(default_factory=list)


def convert_document(file_path: Path) -> ParsedDocument:
    """Run Docling over `file_path` and return a flat, framework-free record
    of everything downstream code needs: text items, table cells (with their
    own bboxes — see SPIKE_NOTES.md finding 3), page dimensions, and markdown.
    """
    warnings: list[str] = []

    has_text_layer = _has_text_layer(file_path)
    do_ocr = not has_text_layer
    if do_ocr:
        warnings.append(
            f"{file_path.name}: no extractable text layer detected "
            f"(< {_TEXT_LAYER_CHARS_PER_PAGE_THRESHOLD} chars/page sampled) — OCR enabled for this parse"
        )

    pipeline_options = PdfPipelineOptions(do_ocr=do_ocr, do_table_structure=True)
    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
    )

    try:
        result = converter.convert(str(file_path))
    except Exception as exc:  # noqa: BLE001 — any Docling failure becomes a domain error
        raise ExtractionError(f"Docling failed to convert {file_path.name}: {exc}") from exc

    if result.status == ConversionStatus.FAILURE:
        raise ExtractionError(f"Docling reported FAILURE converting {file_path.name}: {result.errors}")
    if result.status == ConversionStatus.PARTIAL_SUCCESS:
        warnings.append(f"{file_path.name}: Docling reported PARTIAL_SUCCESS: {result.errors}")

    doc = result.document

    pages: dict[int, PageInfo] = {}
    for page_no, page in doc.pages.items():
        width, height = page.size.width, page.size.height
        if width <= 0 or height <= 0:
            warnings.append(
                f"{file_path.name}: page {page_no} has invalid dimensions "
                f"({width}x{height}) — bboxes on this page cannot be normalised"
            )
        pages[page_no] = PageInfo(page_no=page_no, width=width, height=height)

    text_items: list[TextItemRecord] = []
    tables: list[TableRecord] = []

    for item, _level in doc.iterate_items():
        if isinstance(item, TextItem):
            for prov in item.prov:
                text_items.append(TextItemRecord(text=item.text, page_no=prov.page_no, bbox=prov.bbox))
        elif isinstance(item, TableItem):
            table_page_no = item.prov[0].page_no if item.prov else None
            table_bbox = item.prov[0].bbox if item.prov else None
            if table_page_no is None:
                warnings.append(f"{file_path.name}: a table has no provenance (no page/bbox) — skipping its bbox")
            cells = [
                TableCellRecord(
                    text=cell.text,
                    bbox=cell.bbox,
                    row_span=cell.row_span,
                    col_span=cell.col_span,
                    start_row_offset_idx=cell.start_row_offset_idx,
                    end_row_offset_idx=cell.end_row_offset_idx,
                    start_col_offset_idx=cell.start_col_offset_idx,
                    end_col_offset_idx=cell.end_col_offset_idx,
                    column_header=cell.column_header,
                    row_header=cell.row_header,
                )
                for cell in item.data.table_cells
            ]
            tables.append(TableRecord(page_no=table_page_no, bbox=table_bbox, cells=cells))

    return ParsedDocument(
        page_count=len(pages),
        pages=pages,
        text_items=text_items,
        tables=tables,
        markdown=doc.export_to_markdown(),
        ocr_used=do_ocr,
        warnings=warnings,
    )


def _has_text_layer(file_path: Path) -> bool:
    try:
        pdf = pdfium.PdfDocument(str(file_path))
    except Exception as exc:  # noqa: BLE001 — surfaced as ExtractionError by the caller's own convert() attempt
        raise ExtractionError(f"could not open {file_path.name} to check for a text layer: {exc}") from exc

    sample_page_count = min(len(pdf), _TEXT_LAYER_SAMPLE_PAGES)
    if sample_page_count == 0:
        raise ExtractionError(f"{file_path.name} has no pages")

    total_chars = 0
    for i in range(sample_page_count):
        page = pdf[i]
        text = page.get_textpage().get_text_range()
        total_chars += len(text.strip())

    return (total_chars / sample_page_count) >= _TEXT_LAYER_CHARS_PER_PAGE_THRESHOLD
