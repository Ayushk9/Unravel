"""Wire shapes for household data (docs/claude-code-frontend-prompt.md section 5)."""

from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict

from app.schemas.base import ApiModel


# What kind of city the household lives in, as the household itself chose (D-40).
CityTier = Literal["metro", "tier_2", "other"]


class Household(ApiModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    name: str
    # Null until the household says. Only the room-rent alert reads it.
    city_tier: CityTier | None


class HouseholdUpdate(ApiModel):
    """Body of PATCH /household. The key is required; null clears the choice."""

    city_tier: CityTier | None


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
