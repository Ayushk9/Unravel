"""Recording the dates on a user's policy schedule (PATCH /policies/{id}, D-39).

Engine A does not read these dates, so the user enters them. They are plain
dates, not Extracted[T]: they were typed by the user, not read from a page,
so there is no bbox to point at and none is invented.

Only the keys present in the request change. The result is checked as a
whole, so a request that changes one date cannot leave the three
contradicting each other.
"""

from __future__ import annotations

from datetime import date

from app.core.errors import ApiError
from app.db.models import Policy
from app.schemas.errors import FieldError
from app.schemas.policies import PolicyDatesUpdate

FIELDS = ("start_date", "end_date", "first_inception_date")


def apply_dates(policy: Policy, body: PolicyDatesUpdate, today: date) -> None:
    sent = body.model_fields_set
    if not sent:
        raise ApiError(
            422, "validation_error", "Send at least one date to change.",
            field_errors=[FieldError(field=name, message="Not sent.") for name in FIELDS],
        )

    # What the policy would hold after this request.
    start, end, inception = (getattr(body, name) if name in sent else getattr(policy, name) for name in FIELDS)

    errors = []
    if start is not None and end is not None and end <= start:
        errors.append(FieldError(field="end_date", message="Must be after start_date."))
    if inception is not None and inception > today:
        errors.append(FieldError(field="first_inception_date", message="Can't be in the future."))
    if inception is not None and start is not None and inception > start:
        errors.append(FieldError(
            field="first_inception_date",
            message="Can't be after start_date: continuous cover begins on or before the current policy's start.",
        ))
    if errors:
        raise ApiError(422, "validation_error", "Those policy dates don't fit together.", field_errors=errors)

    policy.start_date, policy.end_date, policy.first_inception_date = start, end, inception
