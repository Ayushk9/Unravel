"""Print a human-readable summary of a spike_parse.py output folder.

Usage:
    python spike_report.py <output_dir>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python spike_report.py <output_dir>")
        sys.exit(1)

    out_dir = Path(sys.argv[1])
    stats_path = out_dir / "stats.json"
    if not stats_path.exists():
        print(f"No stats.json in {out_dir} — did spike_parse.py fail for this PDF? "
              f"(check for PARSE_FAILED.txt)")
        sys.exit(1)

    stats = json.loads(stats_path.read_text(encoding="utf-8"))

    print("=" * 70)
    print(f"{stats['source_pdf']}")
    print("=" * 70)
    print(f"pages:            {stats['total_pages']}")
    print(f"parse time:       {stats['parse_time_seconds']}s "
          f"({stats['avg_seconds_per_page']}s/page)")
    print(f"tables detected:  {stats['tables_detected']}")
    print(f"text items:       {stats['text_items_detected']}")
    print(f"ocr appeared needed: {stats['ocr_appeared_needed']}  ({stats['ocr_detection_note']})")
    print(f"conversion status: {stats['conversion_status']}")
    if stats["docling_errors"]:
        print(f"docling errors:   {stats['docling_errors']}")

    tables_dir = out_dir / "tables"
    if tables_dir.exists():
        csvs = sorted(tables_dir.glob("*.csv"))
        print(f"\ntables ({len(csvs)}):")
        for csv_path in csvs:
            print(f"  {csv_path.name}")
    else:
        print("\ntables: none")

    text_items_path = out_dir / "text_items.json"
    if text_items_path.exists():
        items = json.loads(text_items_path.read_text(encoding="utf-8"))
        print(f"\nfirst {min(5, len(items))} text items:")
        for item in items[:5]:
            text_preview = item["text"][:70].replace("\n", " ")
            bbox = item["bbox"]
            print(
                f"  p.{item['page_no']} [{item['label']}] "
                f"bbox=(l={bbox['l']:.1f}, t={bbox['t']:.1f}, r={bbox['r']:.1f}, b={bbox['b']:.1f}, "
                f"origin={bbox['coord_origin']}) "
                f"text=\"{text_preview}\""
            )

    print()


if __name__ == "__main__":
    main()
