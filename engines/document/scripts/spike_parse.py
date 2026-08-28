"""Capability spike: run Docling over a single PDF and dump its raw output.

No extraction, no LLM, no normalisation — this exists to answer "what does
Docling actually give us" before any prompt or schema gets designed against it.

Usage:
    python spike_parse.py <pdf_path> <output_dir>
"""

from __future__ import annotations

import csv
import json
import math
import sys
import threading
import time
from pathlib import Path
from typing import Any

from docling.document_converter import DocumentConverter
from docling_core.types.doc.document import TableItem, TextItem

HEARTBEAT_SECONDS = 15


def log(msg: str) -> None:
    print(f"[spike_parse] {msg}", flush=True)


class Heartbeat:
    """Prints an elapsed-time line every HEARTBEAT_SECONDS so a slow (scanned)
    parse reads as 'still working' rather than a silent hang."""

    def __init__(self, label: str) -> None:
        self._label = label
        self._start = time.monotonic()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop_event.wait(HEARTBEAT_SECONDS):
            elapsed = time.monotonic() - self._start
            log(f"{self._label}: still running ({elapsed:.0f}s elapsed)...")

    def __enter__(self) -> "Heartbeat":
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._stop_event.set()


def bbox_to_dict(bbox: Any) -> dict[str, Any]:
    return {
        "l": bbox.l,
        "t": bbox.t,
        "r": bbox.r,
        "b": bbox.b,
        "coord_origin": bbox.coord_origin.value,
    }


def dump_text_items(doc: Any, out_path: Path) -> int:
    items: list[dict[str, Any]] = []
    for item, _level in doc.iterate_items():
        if not isinstance(item, TextItem):
            continue
        for prov in item.prov:
            items.append(
                {
                    "text": item.text,
                    "label": item.label.value if hasattr(item.label, "value") else str(item.label),
                    # RAW as Docling reports it — 1-indexed, confirmed against
                    # doc.pages keys during the spike. Do NOT convert to 0-index.
                    "page_no": prov.page_no,
                    "page_indexing": "1-indexed (confirmed: prov.page_no matches doc.pages dict keys)",
                    "bbox": bbox_to_dict(prov.bbox),
                    "bbox_note": "raw units (PDF points), NOT normalised 0..1 — see pages.json for page size to normalise yourself",
                }
            )
    out_path.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    return len(items)


def dump_pages(doc: Any, out_path: Path) -> int:
    pages = []
    for page_no, page in sorted(doc.pages.items()):
        pages.append(
            {
                "page_no": page_no,
                "width": page.size.width,
                "height": page.size.height,
                "units": "PDF points, same coordinate space as the raw bboxes in text_items.json",
            }
        )
    out_path.write_text(json.dumps(pages, indent=2, ensure_ascii=False), encoding="utf-8")
    return len(pages)


def dump_tables(doc: Any, tables_dir: Path) -> list[dict[str, Any]]:
    tables_dir.mkdir(parents=True, exist_ok=True)
    table_meta: list[dict[str, Any]] = []
    table_items = [item for item, _level in doc.iterate_items() if isinstance(item, TableItem)]
    for n, item in enumerate(table_items, start=1):
        page_no = item.prov[0].page_no if item.prov else "unknown"
        df = item.export_to_dataframe(doc=doc)
        csv_path = tables_dir / f"table_{n}_page_{page_no}.csv"
        df.to_csv(csv_path, index=False)
        table_meta.append(
            {
                "table_index": n,
                "page_no": page_no,
                "rows": df.shape[0],
                "cols": df.shape[1],
                "file": csv_path.name,
            }
        )
        log(f"  table {n}: page {page_no}, {df.shape[0]}x{df.shape[1]} -> {csv_path.name}")
    return table_meta


def detect_ocr_usage(confidence: Any) -> bool:
    """Heuristic: Docling's confidence report carries a per-page ocr_score
    that is NaN when OCR did not run on that page (native text was used
    instead) and a real number when it did. This is the only OCR-usage
    signal the library exposes post-hoc; treat it as an approximation, not
    a certainty, and say so in stats.json."""
    for page_score in confidence.pages.values():
        if not math.isnan(page_score.ocr_score):
            return True
    return False


def main() -> None:
    if len(sys.argv) != 3:
        log("usage: python spike_parse.py <pdf_path> <output_dir>")
        sys.exit(1)

    pdf_path = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)

    if not pdf_path.exists():
        log(f"ERROR: {pdf_path} does not exist — skipping")
        sys.exit(1)

    log(f"Converting {pdf_path.name} ({pdf_path.stat().st_size / 1_048_576:.1f} MB) -> {out_dir}")

    converter = DocumentConverter()
    start = time.monotonic()
    try:
        with Heartbeat(pdf_path.name):
            result = converter.convert(str(pdf_path))
    except Exception as exc:  # noqa: BLE001 — spike must survive a bad PDF and move on
        log(f"ERROR: Docling raised while converting {pdf_path.name}: {exc!r}")
        (out_dir / "PARSE_FAILED.txt").write_text(f"{exc!r}\n", encoding="utf-8")
        sys.exit(1)

    elapsed = time.monotonic() - start
    log(f"Conversion status: {result.status.value}, {elapsed:.1f}s")

    if result.errors:
        log(f"  {len(result.errors)} error(s) reported by Docling (non-fatal, continuing): {result.errors}")

    doc = result.document

    log("Writing full_document.md ...")
    (out_dir / "full_document.md").write_text(doc.export_to_markdown(), encoding="utf-8")

    log("Writing tables/*.csv ...")
    table_meta = dump_tables(doc, out_dir / "tables")

    log("Writing text_items.json ...")
    n_text_items = dump_text_items(doc, out_dir / "text_items.json")

    log("Writing pages.json ...")
    n_pages = dump_pages(doc, out_dir / "pages.json")

    needed_ocr = detect_ocr_usage(result.confidence)

    stats = {
        "source_pdf": pdf_path.name,
        "total_pages": n_pages,
        "parse_time_seconds": round(elapsed, 2),
        "avg_seconds_per_page": round(elapsed / n_pages, 2) if n_pages else None,
        "tables_detected": len(table_meta),
        "text_items_detected": n_text_items,
        "ocr_appeared_needed": needed_ocr,
        "ocr_detection_note": (
            "Heuristic from Docling's per-page confidence.ocr_score: non-NaN on "
            "at least one page means OCR ran on that page. Approximation, not "
            "a Docling-reported fact — verify by eye for anything this flags."
        ),
        "conversion_status": result.status.value,
        "docling_errors": [str(e) for e in result.errors],
    }
    (out_dir / "stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")

    log(f"Done: {n_pages} pages, {n_text_items} text items, {len(table_meta)} tables, {elapsed:.1f}s, ocr_needed={needed_ocr}")


if __name__ == "__main__":
    main()
