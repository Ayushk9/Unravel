"""Server-side id generation (API_DECISIONS D-11).

Ids are UUIDv7: the first 48 bits are a millisecond timestamp, so ids
created later sort later. That keeps Postgres B-tree indexes compact for
append-heavy tables, which random UUIDv4 values do not.

Python 3.12's standard library has no uuid7 (it arrives in 3.14), so the
small `uuid6` package provides it. Everything else calls `new_id()`, which
makes this file the only place to change when the standard library catches up.
"""

from __future__ import annotations

from uuid import UUID

from uuid6 import uuid7


def new_id() -> UUID:
    """Return a new time-ordered UUIDv7."""
    return uuid7()
