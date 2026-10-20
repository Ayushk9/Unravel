"""Wire shapes for policies (docs/claude-code-frontend-prompt.md section 5)."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import StringConstraints

from app.schemas.base import ApiModel
from app.schemas.household import Insurer, Member
from contracts.models import CoverageProfile

PolicyType = Literal["individual", "family_floater", "group_employer", "top_up", "other"]
# The fields of a policy the user can type in themselves (D-39, D-46).
UserEnteredField = Literal["insurer_name", "product_name", "policy_number", "start_date", "end_date", "first_inception_date"]
# A name or number as typed: trimmed, then 1 to 200 characters.
EnteredText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


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
    # The start of cover renewed without a break, given by the user (D-39).
    # Waiting periods are counted from it when it is set.
    first_inception_date: date | None
    # The insurer's name as the user typed it (D-46). `insurer` above is the
    # shared reference row, linked only by us; a client shows insurer.name if
    # set, else this.
    insurer_name: str | None
    # Which of the fields above the user typed in themselves (D-46). They are
    # plain values with no page to point at; clients mark them "Entered by you".
    user_entered_fields: list[UserEnteredField]
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


class PolicyUpdate(ApiModel):
    """Body of PATCH /policies/{id} (D-39, D-46): what the user copies from their policy schedule.

    Only the keys present in the body are changed; a key sent as null clears
    that value. A key left out keeps its current value. That is why each field
    has a default: the service reads `model_fields_set` to tell "left out" from "null".
    """

    insurer_name: EnteredText | None = None
    product_name: EnteredText | None = None
    policy_number: EnteredText | None = None
    start_date: date | None = None
    end_date: date | None = None
    first_inception_date: date | None = None
