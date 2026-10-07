"""Measure what running each parse in its own process costs.

Every job starts a fresh interpreter, imports Docling and PyTorch, and loads
the layout and table models, none of which a long-lived worker would repeat.
This script times those steps so the cost of the process-per-job design is a
measured number rather than a guess.

Run from apps/api (it needs no database and no API keys):
    ../../.venv/bin/python scripts/measure_spawn_overhead.py [path/to/small.pdf]

Steps timed, each in a freshly spawned process:

    spawn           start a new interpreter and run an empty function
    import          import Engine A (pulls in Docling and PyTorch)
    first convert   Docling on a small PDF: loads the models, then parses
    second convert  the same PDF again in the same process: models already loaded

    model load  =  first convert - second convert
    overhead    =  spawn + import + model load
"""

from __future__ import annotations

import multiprocessing
import statistics
import sys
import time
from multiprocessing.connection import Connection
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PDF = REPO_ROOT / "engines" / "document" / "samples" / "warmup.pdf"
REPEATS = 3


def _empty_child(connection: Connection) -> None:
    connection.send(time.time())
    connection.close()


def _engine_child(connection: Connection, pdf_path: str) -> None:
    started = time.time()
    sys.path.insert(0, str(REPO_ROOT))
    from engines.document.pipeline import parse_and_extract  # noqa: F401 - timing the import itself

    imported = time.time()
    from docling_wrapper import convert_document  # importable once the pipeline has set up sys.path

    convert_document(Path(pdf_path))
    first_done = time.time()
    convert_document(Path(pdf_path))
    second_done = time.time()
    connection.send(
        {
            "child_started": started,
            "import": imported - started,
            "first_convert": first_done - imported,
            "second_convert": second_done - first_done,
        }
    )
    connection.close()


def _spawn(target, *args):
    """Start `target` in a spawned process; return (time the parent started it, what it sent)."""
    context = multiprocessing.get_context("spawn")
    parent_end, child_end = context.Pipe(duplex=False)
    launched = time.time()
    process = context.Process(target=target, args=(child_end, *args))
    process.start()
    child_end.close()
    message = parent_end.recv()
    process.join()
    return launched, message


def main() -> None:
    pdf_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PDF
    if not pdf_path.exists():
        raise SystemExit(f"No PDF at {pdf_path}. Pass a small PDF as the first argument.")

    spawn_times = []
    for _ in range(REPEATS):
        launched, child_time = _spawn(_empty_child)
        spawn_times.append(child_time - launched)

    runs = []
    for _ in range(REPEATS):
        launched, timings = _spawn(_engine_child, str(pdf_path))
        timings["spawn"] = timings.pop("child_started") - launched
        runs.append(timings)

    def median(key: str) -> float:
        return statistics.median(run[key] for run in runs)

    spawn = statistics.median(spawn_times)
    model_load = median("first_convert") - median("second_convert")
    print(f"PDF used: {pdf_path.name}   repeats: {REPEATS}   (medians, seconds)")
    print(f"  spawn a new interpreter           {spawn:6.2f}")
    print(f"  import Engine A (Docling, torch)  {median('import'):6.2f}")
    print(f"  first convert  (loads models)     {median('first_convert'):6.2f}")
    print(f"  second convert (models loaded)    {median('second_convert'):6.2f}")
    print(f"  => model load                     {model_load:6.2f}")
    print(f"  => overhead per job               {spawn + median('import') + model_load:6.2f}")
    print("  individual runs:", [{key: round(value, 2) for key, value in run.items()} for run in runs])


if __name__ == "__main__":
    main()
