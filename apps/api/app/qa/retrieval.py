"""Finding a policy's clauses for a question: two searches, merged, then reranked.

    (Both searches run inside one SQL statement, _SEARCH below.)

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
import time
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

# ONE statement does both searches and returns the clauses, so a search costs
# one network round trip to Postgres (plus BEGIN and ROLLBACK) instead of three.
#
#   scoped   the policy's own clauses: this document, this household, not deleted
#   dense    the 20 closest by vector (cosine distance, <=>), ranked 1..20
#   keyword  the 20 best by full-text match (ts_rank), ranked 1..20
#   result   every clause in either list, with both ranks (null if not in that list)
#
# The ranks come from row_number() over the same ORDER BY as the LIMIT, so they
# are exactly the positions the two separate queries used to return.
# CAST(:terms AS text) keeps the parameter typed when there are no search words
# (null): to_tsquery(null) is null, matches nothing, and the keyword list is empty.
_SEARCH = text(
    """
    WITH scoped AS (
        SELECT c.id, c.page, c.position, c.text, c.bbox, c.embedding, c.search_text
        FROM document_chunk c
        JOIN document d ON d.id = c.document_id
        WHERE c.document_id = :document_id
          AND d.household_id = :household_id
          AND d.deleted_at IS NULL
    ),
    dense AS (
        SELECT id, row_number() OVER (ORDER BY embedding <=> CAST(:query_vector AS vector), position) AS dense_rank
        FROM scoped
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> CAST(:query_vector AS vector), position
        LIMIT :limit
    ),
    keyword AS (
        SELECT id, row_number() OVER (ORDER BY ts_rank(search_text, query) DESC, position) AS keyword_rank
        FROM scoped, to_tsquery('english', CAST(:terms AS text)) AS query
        WHERE search_text @@ query
        ORDER BY ts_rank(search_text, query) DESC, position
        LIMIT :limit
    )
    SELECT s.id, s.page, s.position, s.text, s.bbox, dense.dense_rank, keyword.keyword_rank
    FROM scoped s
    LEFT JOIN dense ON dense.id = s.id
    LEFT JOIN keyword ON keyword.id = s.id
    WHERE dense.id IS NOT NULL OR keyword.id IS NOT NULL
    """
)


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
    timings: dict[str, float] = field(default_factory=dict)  # seconds per step, for profiling


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
    timings: dict[str, float] = {}
    clock = time.perf_counter()

    def lap(name: str) -> None:
        nonlocal clock
        now = time.perf_counter()
        timings[name] = round(now - clock, 4)
        clock = now

    [query_vector] = await models.embed([query])
    lap("embed_question")
    found = list(
        await session.execute(
            _SEARCH, {**scope, "query_vector": to_vector_literal(query_vector), "terms": keyword_terms(query)}
        )
    )
    lap("db_search")

    dense = [row.id for row in sorted((r for r in found if r.dense_rank), key=lambda r: r.dense_rank)]
    keyword = [row.id for row in sorted((r for r in found if r.keyword_rank), key=lambda r: r.keyword_rank)]
    fused = [chunk_id for chunk_id, _ in reciprocal_rank_fusion([dense, keyword])]
    lap("fusion")
    if not fused:
        return Retrieved(clauses=[], timings=timings)

    rows = {row.id: row for row in found}
    candidates = [Clause(id=r.id, page=r.page, position=r.position, text=r.text, bbox=r.bbox) for cid in fused if (r := rows.get(cid))]

    scores = await models.rerank(query, [c.text for c in candidates])
    lap("rerank")
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
    timings["rerank_candidates"] = float(len(candidates))
    return Retrieved(clauses=[candidates[i] for i in order[:KEEP]], trace=trace, timings=timings)
