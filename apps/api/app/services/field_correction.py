"""Apply a user's confirmation or correction to one coverage-profile field (D-15).

`field_path` is a dotted path from the URL. Only the forms listed below are
accepted. There is no general "set any attribute by name" mechanism: a path
from a client must never be turned into a column name directly.

    sum_insured
    co_pay_percent
    intimation_deadline_hours
    sub_limits.<position>.cap_amount       e.g. sub_limits.2.cap_amount        (D-41)
    waiting_periods.<position>.months      e.g. waiting_periods.0.months       (D-41)
    sub_limits.<category>.cap_amount       e.g. sub_limits.room_rent.cap_amount
    waiting_periods.<kind>.months          e.g. waiting_periods.pre_existing.months

<position> is the 0-based index of the row in the policy's `sub_limits` or
`waiting_periods` list, exactly as GET /policies/{id} returns it. It always
names one row. The category / kind form still works, but is refused with a
409 when several rows share that category or kind.

A correction sets `_value` and `_user_confirmed` only (apply_correction).
The parser's `_original_value` and `_provenance` are never changed.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.db.models import CoverageProfile, SubLimit, WaitingPeriod
from app.db.models.coverage import SUB_LIMIT_CATEGORIES, WAITING_PERIOD_KINDS
from app.schemas.errors import FieldError
from app.services.extracted_columns import apply_correction

Validator = Callable[[Any], "int | float"]


def _invalid_value(message: str) -> ApiError:
    return ApiError(
        422, "validation_error", "That value isn't valid for this field.", field_errors=[FieldError(field="value", message=message)]
    )


def _unknown_path(field_path: str) -> ApiError:
    return ApiError(
        422,
        "validation_error",
        "That field path isn't correctable.",
        field_errors=[FieldError(field="field_path", message=f"Unknown or non-correctable field: {field_path}")],
    )


def _is_number(value: Any) -> bool:
    # bool is a subclass of int in Python; True must not pass as the number 1.
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def paise(value: Any) -> int:
    """Money is a whole number of paise. 5000.5 or "5000" is rejected, not rounded."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise _invalid_value("Must be a whole number of paise.")
    if value < 0:
        raise _invalid_value("Must not be negative.")
    return value


def percent(value: Any) -> float:
    if not _is_number(value) or not 0 <= value <= 100:
        raise _invalid_value("Must be a number between 0 and 100.")
    return float(value)


def non_negative_number(value: Any) -> float:
    if not _is_number(value) or value < 0:
        raise _invalid_value("Must be a number that is not negative.")
    return float(value)


# The allow-list for fields that sit directly on the coverage profile:
# path -> (column prefix, value check).
_PROFILE_FIELDS: dict[str, tuple[str, Validator]] = {
    "sum_insured": ("sum_insured", paise),
    "co_pay_percent": ("co_pay_percent", percent),
    "intimation_deadline_hours": ("intimation_deadline_hours", non_negative_number),
}


async def correct_field(session: AsyncSession, profile: CoverageProfile, field_path: str, value: Any) -> None:
    """Validate the path and the value, then record the correction on the right row."""
    if field_path in _PROFILE_FIELDS:
        prefix, validate = _PROFILE_FIELDS[field_path]
        apply_correction(profile, prefix, validate(value))
        return

    parts = field_path.split(".")
    if len(parts) == 3 and parts[0] == "sub_limits" and parts[2] == "cap_amount" and _is_position(parts[1]):
        rows = await session.scalars(
            select(SubLimit).where(SubLimit.coverage_profile_id == profile.id).order_by(SubLimit.position)
        )
        apply_correction(_at_position(list(rows), int(parts[1]), field_path), "cap_amount", paise(value))
        return

    if len(parts) == 3 and parts[0] == "waiting_periods" and parts[2] == "months" and _is_position(parts[1]):
        rows = await session.scalars(
            select(WaitingPeriod).where(WaitingPeriod.coverage_profile_id == profile.id).order_by(WaitingPeriod.position)
        )
        apply_correction(_at_position(list(rows), int(parts[1]), field_path), "months", non_negative_number(value))
        return

    if len(parts) == 3 and parts[0] == "sub_limits" and parts[2] == "cap_amount" and parts[1] in SUB_LIMIT_CATEGORIES:
        rows = await session.scalars(
            select(SubLimit).where(SubLimit.coverage_profile_id == profile.id, SubLimit.category == parts[1])
        )
        apply_correction(_exactly_one(list(rows), field_path), "cap_amount", paise(value))
        return

    if len(parts) == 3 and parts[0] == "waiting_periods" and parts[2] == "months" and parts[1] in WAITING_PERIOD_KINDS:
        rows = await session.scalars(
            select(WaitingPeriod).where(WaitingPeriod.coverage_profile_id == profile.id, WaitingPeriod.kind == parts[1])
        )
        apply_correction(_exactly_one(list(rows), field_path), "months", non_negative_number(value))
        return

    raise _unknown_path(field_path)


def _is_position(segment: str) -> bool:
    """'0', '1', '12': plain digits only. '-1', '+1' or '1.0' are not positions."""
    return segment.isascii() and segment.isdigit()


def _at_position(rows: list[Any], position: int, field_path: str) -> Any:
    """The row at this index of the list the client was shown (ordered as GET /policies/{id} orders it)."""
    if position >= len(rows):
        raise _unknown_path(field_path)
    return rows[position]


def _exactly_one(rows: list[Any], field_path: str) -> Any:
    """The single row a path refers to.

    The contract addresses a sub-limit by its category and a waiting period
    by its kind. A real policy can have several rows sharing one (two
    "procedure" caps, several disease-specific waiting periods). The path
    then does not say which row is meant, and changing the wrong number in
    someone's policy is worse than refusing, so this refuses.
    """
    if not rows:
        raise _unknown_path(field_path)
    if len(rows) > 1:
        raise ApiError(
            409,
            "ambiguous_field_path",
            f"This policy has {len(rows)} entries matching that field, so it isn't clear which one to change. "
            "Address the entry by its position in the list instead, e.g. sub_limits.1.cap_amount.",
            field_errors=[FieldError(field="field_path", message=field_path)],
        )
    return rows[0]


async def find_profile(session: AsyncSession, policy_id: UUID) -> CoverageProfile | None:
    return await session.scalar(select(CoverageProfile).where(CoverageProfile.policy_id == policy_id))
