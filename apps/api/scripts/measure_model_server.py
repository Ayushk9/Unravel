"""Start the warm model server, and time loading, a first request and later requests.

Run from apps/api:
    ../../.venv/bin/python scripts/measure_model_server.py

The first run downloads BGE-M3 and bge-reranker-v2-m3 from Hugging Face
(about 4.5 GB in all, into ~/.cache/huggingface). Later runs load from disk.
"""

from __future__ import annotations

import asyncio
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.models_server.client import ModelServer  # noqa: E402

CLAUSES = [
    "Room rent: up to Rs 5,000 per day",
    "Pre-existing diseases: covered after 48 months of continuous coverage",
    "Cosmetic or aesthetic treatment is excluded",
    "Claim intimation: within 24 hours of admission",
]
QUESTIONS = ["What if I choose a 12,000 a day room?", "Is cosmetic surgery covered?", "When are pre-existing diseases covered?"]


async def main() -> None:
    settings = get_settings()
    server = ModelServer(
        embed_model=settings.embedding_model,
        rerank_model=settings.rerank_model,
        device=settings.model_device,
        load_timeout_seconds=settings.model_load_timeout_seconds,
        request_timeout_seconds=settings.model_request_timeout_seconds,
    )
    started = time.perf_counter()
    server.start()
    vectors = await server.embed(CLAUSES)
    first = time.perf_counter() - started
    print(f"device={settings.model_device}")
    print(f"model load (inside the server): {server.load_seconds}s")
    print(f"start -> first embedding (cold):  {first:.2f}s")
    print(f"vector length: {len(vectors[0])}, norm: {sum(v * v for v in vectors[0]) ** 0.5:.4f}")

    timings = []
    for question in QUESTIONS * 2:
        t = time.perf_counter()
        [query] = await server.embed([question])
        scores = await server.rerank(question, CLAUSES)
        timings.append(time.perf_counter() - t)
        best = max(range(len(CLAUSES)), key=lambda i: scores[i])
        similarity = max(sum(a * b for a, b in zip(query, v)) for v in vectors)
        print(f"  {question!r}: best clause {CLAUSES[best]!r} (rerank {scores[best]:.3f}, top cosine {similarity:.3f})")
    print(f"warm embed+rerank per question: median {statistics.median(timings) * 1000:.0f} ms, max {max(timings) * 1000:.0f} ms")
    await server.stop()


if __name__ == "__main__":
    asyncio.run(main())
