"""Declarative base shared by every table model."""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Explicit names for every constraint and index. Without this the database
# invents names, and a later migration that needs to drop or alter a
# constraint has no reliable name to refer to.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def one_of(column: str, values: tuple[str, ...]) -> str:
    """SQL for a CHECK constraint: `column IN ('a', 'b')`.

    Enum-like columns are TEXT with a CHECK rather than a Postgres ENUM type,
    so adding a value later is a one-line migration.
    """
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


# Extracted[T].confidence (API_DECISIONS D-14).
CONFIDENCE_VALUES = ("high", "medium", "low")
