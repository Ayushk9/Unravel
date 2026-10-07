"""Wire shapes for policies (docs/claude-code-frontend-prompt.md section 5)."""

from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from app.schemas.base import ApiModel
from app.schemas.household import Insurer, Member
from contracts.models import CoverageProfile

PolicyType = Literal["individual", "family_floater", "group_employer", "top_up", "other"]


class Policy(ApiModel):
    id: UUID
    # These five are nullable (D-25). A policy created from an uploaded
    # document only knows what Engine A extracted, and Engine A does not yet
    # extract them. Null means "not known", which the client must show as such.
    insurer: Insurer | None
    policy_number: str | None
    product_name: str | None
    start_date: date | None
    end_date: date | None
    # Never null: an unknown type is sent as the enum's escape hatch, "other".
    policy_type: PolicyType
    members: list[Member]
    # Every field inside is Extracted[T]; it is never flattened (D-14).
    coverage_profile: CoverageProfile | None
    source_document_id: UUID


class FieldCorrectionRequest(ApiModel):
    """Body of PATCH /policies/{id}/coverage-profile/fields/{field_path} (D-15)."""

    # Checked against the specific field's type in services/field_correction.py.
    value: int | float | str | bool | None
    user_confirmed: bool
