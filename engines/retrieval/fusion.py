"""Reciprocal rank fusion: merge ranked lists without comparing their scores.

Dense search scores are cosine similarities; keyword search scores are
ts_rank values. The two are on unrelated scales, so adding them would be
meaningless. RRF uses only each item's RANK in each list:

    score(item) = sum over lists of 1 / (k + rank)      rank starts at 1

An item near the top of both lists beats one at the top of only one. k=60 is
the value from the original paper (Cormack et al., 2009); it damps the
difference between rank 1 and rank 2 so one list cannot dominate.
"""

from __future__ import annotations

from collections.abc import Hashable, Sequence
from typing import TypeVar

K = 60

T = TypeVar("T", bound=Hashable)


def reciprocal_rank_fusion(ranked_lists: Sequence[Sequence[T]], k: int = K) -> list[tuple[T, float]]:
    """All items from all lists, best first, with their fused score.

    Ties are broken by where the item first appeared (the earlier list, then
    the higher rank), so the output is fully deterministic.
    """
    scores: dict[T, float] = {}
    first_seen: dict[T, tuple[int, int]] = {}
    for list_index, ranked in enumerate(ranked_lists):
        for rank, item in enumerate(ranked, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
            first_seen.setdefault(item, (list_index, rank))
    return sorted(scores.items(), key=lambda pair: (-pair[1], first_seen[pair[0]]))
