"""Embed every chunk that has no search vector yet (backfill, and retry after a failed indexing step).

Run from apps/api, with the API stopped or running (it uses its own model server):
    ../../.venv/bin/python scripts/index_chunks.py              every document
    ../../.venv/bin/python scripts/index_chunks.py <document_id>

Idempotent: chunks that already have a vector are skipped.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import distinct, select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.models import DocumentChunk  # noqa: E402
from app.db.session import create_engine, create_session_factory  # noqa: E402
from app.models_server.client import ModelServer  # noqa: E402
from app.qa.indexing import index_document  # noqa: E402


async def main(only: UUID | None) -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    async with session_factory() as session:
        query = select(distinct(DocumentChunk.document_id)).where(DocumentChunk.embedding.is_(None))
        if only is not None:
            query = query.where(DocumentChunk.document_id == only)
        document_ids = list(await session.scalars(query))
    if not document_ids:
        print("Every chunk already has a vector. Nothing to do.")
        await engine.dispose()
        return

    server = ModelServer(
        embed_model=settings.embedding_model,
        rerank_model=settings.rerank_model,
        device=settings.model_device,
        load_timeout_seconds=settings.model_load_timeout_seconds,
        request_timeout_seconds=settings.model_request_timeout_seconds,
    )
    server.start()
    try:
        for document_id in document_ids:
            started = time.perf_counter()
            count = await index_document(session_factory, server, document_id)
            print(f"document {document_id}: embedded {count} chunk(s) in {time.perf_counter() - started:.1f}s")
    finally:
        await server.stop()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(UUID(sys.argv[1]) if len(sys.argv) > 1 else None))
