"""A pgvector `vector(n)` column, without the pgvector Python package.

asyncpg has no codec for pgvector's type, so values cross the wire as text,
the format pgvector itself reads and writes: "[0.12,-0.03,...]".

  writing: CAST(CAST($1 AS TEXT) AS vector(1024)). Postgres allows an
           explicit cast from text to any type through that type's own input
           function, so no special driver support is needed.
  reading: CAST(column AS TEXT), parsed back into a list of floats.

Search queries (app/qa/retrieval.py) use the same text form for the question
vector.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Text, cast
from sqlalchemy.types import UserDefinedType


def to_vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{float(v):.7g}" for v in values) + "]"


def from_vector_literal(text: str) -> list[float]:
    return [float(part) for part in text.strip("[]").split(",") if part]


class Vector(UserDefinedType[list[float]]):
    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **_: Any) -> str:
        return f"vector({self.dimensions})"

    def bind_expression(self, bindvalue: Any) -> Any:
        return cast(cast(bindvalue, Text), self)

    def column_expression(self, column: Any) -> Any:
        return cast(column, Text)

    def bind_processor(self, dialect: Any) -> Any:
        def process(value: list[float] | None) -> str | None:
            return None if value is None else to_vector_literal(value)

        return process

    def result_processor(self, dialect: Any, coltype: Any) -> Any:
        def process(value: str | None) -> list[float] | None:
            return None if value is None else from_vector_literal(value)

        return process
