"""Finding a policy's clauses for a question: two searches, merged, then reranked.

    dense    the 20 chunks whose BGE-M3 vector is closest to the question's
             (cosine distance, pgvector's <=> operator). Finds clauses that
             mean the same thing in different words.
    keyword  the 20 chunks whose words best match the question's (Postgres
             full-text search, ts_rank). Finds exact terms the vectors can
             blur, such as "co-payment" or a section number.
    fusion   reciprocal rank fusion (engines/retrieval/fusion.py)
    rerank   the cross-encoder scores every fused candidate against the
             question; the top 5 go to the answer model.

SCOPE: both queries join document and filter on the policy's own document
id, the caller's household id and `deleted_at IS NULL`. A clause from any
other document, or any other household, cannot be returned. That filter is
in the SQL, not applied afterwards in Python.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.vector_type import to_vector_literal
from app.models_server.client import Models
from engines.retrieval.fusion import reciprocal_rank_fusion

PER_SEARCH = 20
KEEP = 5

_SCOPE = """
    FROM document_chunk c
    JOIN document d ON d.id = c.document_id
    WHERE c.document_id = :document_id
      AND d.household_id = :household_id
      AND d.deleted_at IS NULL
"""

_DENSE = text(
    "SELECT c.id" + _SCOPE + " AND c.embedding IS NOT NULL "
    "ORDER BY c.embedding <=> CAST(:query_vector AS vector), c.position LIMIT :limit"
)
_KEYWORD = text(
    "SELECT c.id" + _SCOPE + " AND c.search_text @@ to_tsquery('english', :terms) "
    "ORDER BY ts_rank(c.search_text, to_tsquery('english', :terms)) DESC, c.position LIMIT :limit"
)
_ROWS = text("SELECT c.id, c.page, c.position, c.text, c.bbox" + _SCOPE + " AND c.id = ANY(:ids)")


@dataclass(frozen=True)
class Clause:
    id: UUID
    page: int
    position: int
    text: str
    bbox: list[float] | None


@dataclass
class Retrieved:
    clauses: list[Clause]  # the top KEEP, best first
    trace: list[dict[str, Any]] = field(default_factory=list)  # for policy_question.retrieved


def keyword_terms(query: str) -> str | None:
    """The question's words joined with OR ("room | rent | cap").

    plainto_tsquery would join them with AND, and a long question would then
    match only a chunk containing every single word: usually none. Postgres
    stems the words and drops stop-words ("what", "if") itself. Only letters
    and digits are kept, so nothing the user typed can change the query's syntax.
    """
    words = [w for w in re.findall(r"[A-Za-z0-9]+", query.lower()) if len(w) > 1]
    return " | ".join(dict.fromkeys(words)) or None


async def retrieve(
    session: AsyncSession, models: Models, *, household_id: UUID, document_id: UUID, query: str
) -> Retrieved:
    scope = {"document_id": document_id, "household_id": household_id, "limit": PER_SEARCH}

    [query_vector] = await models.embed([query])
    dense = [row.id for row in await session.execute(_DENSE, {**scope, "query_vector": to_vector_literal(query_vector)})]
    terms = keyword_terms(query)
    keyword = [row.id for row in await session.execute(_KEYWORD, {**scope, "terms": terms})] if terms else []

    fused = [chunk_id for chunk_id, _ in reciprocal_rank_fusion([dense, keyword])]
    if not fused:
        return Retrieved(clauses=[])

    rows = {row.id: row for row in await session.execute(_ROWS, {**scope, "ids": fused})}
    candidates = [Clause(id=r.id, page=r.page, position=r.position, text=r.text, bbox=r.bbox) for cid in fused if (r := rows.get(cid))]

    scores = await models.rerank(query, [c.text for c in candidates])
    # Best rerank score first; equal scores keep their fused order.
    order = sorted(range(len(candidates)), key=lambda i: (-scores[i], i))

    trace = [
        {
            "chunk_id": str(candidates[i].id),
            "page": candidates[i].page,
            "dense_rank": dense.index(candidates[i].id) + 1 if candidates[i].id in dense else None,
            "keyword_rank": keyword.index(candidates[i].id) + 1 if candidates[i].id in keyword else None,
            "fused_rank": i + 1,
            "rerank_score": round(float(scores[i]), 4),
            "kept": position < KEEP,
        }
        for position, i in enumerate(order)
    ]
    return Retrieved(clauses=[candidates[i] for i in order[:KEEP]], trace=trace)
