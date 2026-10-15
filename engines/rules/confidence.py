"""A check's confidence, derived only from the confidence of its inputs.

Rules:
  - An extracted field counts at its own confidence ("high", "medium", "low"),
    unless the user has confirmed or corrected it, in which case it counts as "high".
  - Facts the user entered about the claim, and policy dates, count as "high".
  - A check's confidence is the LOWEST of its inputs. One low-confidence,
    unconfirmed input is therefore enough to stop a check being "high".

Nothing here is a probability. It is a three-level label of how much the
inputs can be trusted, carried through so a doubtful number cannot produce
a confident verdict.
"""

from __future__ import annotations

from contracts.models import Extracted

from engines.rules.models import Confidence

_ORDER: dict[Confidence, int] = {"low": 0, "medium": 1, "high": 2}
USER_FACT: Confidence = "high"


def of_extracted(field: Extracted) -> Confidence:
    return "high" if field.user_confirmed else field.confidence


def lowest(*levels: Confidence) -> Confidence:
    """The lowest level given; "high" when there are no extracted inputs at all."""
    return min(levels, key=_ORDER.__getitem__, default=USER_FACT)
