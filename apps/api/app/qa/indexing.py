"""Indexing: give every chunk of a document its BGE-M3 vector.

Runs as the last stage of a policy parse (app/jobs/parse_document.py), and
from scripts/index_chunks.py for documents parsed before this existed or
whose indexing failed. Only chunks without a vector are embedded, so running
it twice does no extra work.

The keyword index needs no step here: `search_text` is a generated column,
which Postgres fills in itself whenever a chunk is written.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DocumentChunk
from app.jobs.queue import SessionFactory
from app.models_server.client import Models

BATCH = 32


async def index_document(session_factory: SessionFactory, models: Models, document_id: UUID) -> int:
    """Embed this document's unindexed chunks. Returns how many were embedded."""
    async with session_factory() as session:
        pending = list(
            await session.execute(
                select(DocumentChunk.id, DocumentChunk.text)
                .where(DocumentChunk.document_id == document_id, DocumentChunk.embedding.is_(None))
                .order_by(DocumentChunk.position)
            )
        )
    done = 0
    for start in range(0, len(pending), BATCH):
        batch = pending[start : start + BATCH]
        vectors = await models.embed([row.text for row in batch])
        # One short transaction per batch: a long document never holds a transaction open while the model works.
        async with session_factory() as session, session.begin():
            for row, vector in zip(batch, vectors, strict=True):
                chunk = await session.get(DocumentChunk, row.id)
                if chunk is not None:
                    chunk.embedding = vector
        done += len(batch)
    return done


async def index_counts(session: AsyncSession, document_id: UUID) -> tuple[int, int]:
    """(chunks, chunks with a vector) for a document. count(column) counts only non-null values."""
    row = (
        await session.execute(select(func.count(), func.count(DocumentChunk.embedding)).where(DocumentChunk.document_id == document_id))
    ).one()
    return int(row[0]), int(row[1])
