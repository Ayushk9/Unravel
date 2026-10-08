"""Shapes shared by several resources."""

from __future__ import annotations

from typing import Generic, TypeVar

from app.schemas.base import ApiModel

T = TypeVar("T")


class Collection(ApiModel, Generic[T]):
    """A page of a paginated list (API_DECISIONS D-03)."""

    items: list[T]
    # Pass this back as `cursor` to get the next page. Null on the last page.
    next_cursor: str | None
    total: int | None
