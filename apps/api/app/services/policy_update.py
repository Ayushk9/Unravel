"""Recording what the user copies from their policy schedule (PATCH /policies/{id}, D-39, D-46).

Engine A does not read a policy's identity (insurer, product, number) or its
dates, so the user enters them. They are plain values, not Extracted[T]: they
were typed by the user, not read from a page, so there is no bbox to point at
and none is invented. Instead, every field the user sets is listed in
`policy.user_entered_fields`, which the client shows as "Entered by you".

Only the keys present in the request change. The dates are checked as a
whole, so a request that changes one date cannot leave the three
contradicting each other.

The user's insurer name is stored on the policy itself, never in the shared
`insurer` table: that table is reference data every household sees.
"""

from __future__ import annotations

from datetime import date

from app.core.errors import ApiError
from app.db.models import Policy
from app.schemas.errors import FieldError
from app.schemas.policies import PolicyUpdate

DATE_FIELDS = ("start_date", "end_date", "first_inception_date")
TEXT_FIELDS = ("insurer_name", "product_name", "policy_number")
FIELDS = TEXT_FIELDS + DATE_FIELDS


def apply_policy_update(policy: Policy, body: PolicyUpdate, today: date) -> None:
    sent = body.model_fields_set
    if not sent:
        raise ApiError(
            422, "validation_error", "Send at least one field to change.",
            field_errors=[FieldError(field=name, message="Not sent.") for name in FIELDS],
        )

    # The dates the policy would hold after this request.
    start, end, inception = (getattr(body, name) if name in sent else getattr(policy, name) for name in DATE_FIELDS)

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

    for name in FIELDS:
        if name in sent:
            setattr(policy, name, getattr(body, name))

    # A field the user set is marked as entered by them; one they cleared is no longer marked.
    entered = set(policy.user_entered_fields or ())
    for name in sent:
        if getattr(body, name) is None:
            entered.discard(name)
        else:
            entered.add(name)
    # A new list (in a fixed order) so SQLAlchemy sees the change.
    policy.user_entered_fields = [name for name in FIELDS if name in entered]
