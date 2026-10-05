"""Wire shapes for household data (docs/claude-code-frontend-prompt.md section 5)."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import ConfigDict

from app.schemas.base import ApiModel


class Member(ApiModel):
    # from_attributes lets this be built straight from a database row.
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    full_name: str
    relationship: str
    date_of_birth: date | None


class Insurer(ApiModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    name: str
    irdai_code: str | None
