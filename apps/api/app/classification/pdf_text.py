"""Cheap reads of a PDF's first pages, without the layout pipeline.

Classifying a claim document ("is this a discharge summary or a bill?")
needs only a glance at the first page. Engine A's full pipeline (layout
models, table structure, OCR) takes tens of seconds and is not needed for
that. pypdfium2 reads the text already embedded in a digital PDF in
milliseconds, and can render a page to an image when there is no text.
"""

from __future__ import annotations

import io
from pathlib import Path

import pypdfium2 as pdfium

MAX_PAGES = 2
# Rendering at 2x gives roughly 144 dpi: enough to read a heading.
_RENDER_SCALE = 2.0


def read_first_pages(file_path: Path) -> tuple[str, int]:
    """Text of the first two pages, and the document's page count.

    The text is empty for a scanned PDF, which has pictures of pages and no
    text layer.
    """
    pdf = pdfium.PdfDocument(str(file_path))
    try:
        page_count = len(pdf)
        texts = [pdf[index].get_textpage().get_text_range() for index in range(min(page_count, MAX_PAGES))]
        return "\n".join(texts).strip(), page_count
    finally:
        pdf.close()


def render_first_page_png(file_path: Path) -> bytes:
    """The first page as a PNG image, for a PDF with no text layer."""
    pdf = pdfium.PdfDocument(str(file_path))
    try:
        image = pdf[0].render(scale=_RENDER_SCALE).to_pil()
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()
    finally:
        pdf.close()
