from __future__ import annotations

import time
from uuid import UUID

from app.core.ids import new_id


def test_new_id_is_a_version_7_uuid() -> None:
    generated = new_id()

    assert isinstance(generated, UUID)
    assert generated.version == 7


def test_new_ids_are_unique() -> None:
    assert len({new_id() for _ in range(1000)}) == 1000


def test_ids_created_later_sort_later() -> None:
    earlier = new_id()
    time.sleep(0.002)  # UUIDv7 orders by millisecond timestamp
    later = new_id()

    assert str(earlier) < str(later)
