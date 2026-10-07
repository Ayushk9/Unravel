"""Build the wire `Policy` from database rows.

Every lookup starts from a household id that came from the caller's token.
A policy in another household is simply not found, which is how the API
returns 404 rather than 403 for other people's data (D-10).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CoverageProfile as CoverageProfileRow
from app.db.models import Exclusion as ExclusionRow
from app.db.models import Insurer as InsurerRow
from app.db.models import Member as MemberRow
from app.db.models import Policy as PolicyRow
from app.db.models import SubLimit as SubLimitRow
from app.db.models import WaitingPeriod as WaitingPeriodRow
from app.db.models import policy_member
from app.schemas.household import Insurer, Member
from app.schemas.policies import Policy
from app.services.extracted_columns import columns_to_extracted
from contracts.models import CoverageProfile, SubLimit, WaitingPeriod


async def find_policy_row(session: AsyncSession, household_id: UUID, policy_id: UUID) -> PolicyRow | None:
    """The policy, only if it belongs to this household."""
    return await session.scalar(
        select(PolicyRow).where(PolicyRow.id == policy_id, PolicyRow.household_id == household_id)
    )


async def list_policy_rows(session: AsyncSession, household_id: UUID) -> list[PolicyRow]:
    """This household's policies, oldest first (ids are time-ordered)."""
    rows = await session.scalars(select(PolicyRow).where(PolicyRow.household_id == household_id).order_by(PolicyRow.id))
    return list(rows)


async def build_policy(session: AsyncSession, row: PolicyRow) -> Policy:
    insurer_row = await session.get(InsurerRow, row.insurer_id) if row.insurer_id else None
    member_rows = await session.scalars(
        select(MemberRow)
        .join(policy_member, policy_member.c.member_id == MemberRow.id)
        .where(policy_member.c.policy_id == row.id)
        .order_by(MemberRow.id)
    )
    return Policy(
        id=row.id,
        insurer=Insurer.model_validate(insurer_row) if insurer_row else None,
        policy_number=row.policy_number,
        product_name=row.product_name,
        start_date=row.start_date,
        end_date=row.end_date,
        policy_type=row.policy_type or "other",
        members=[Member.model_validate(member) for member in member_rows],
        coverage_profile=await _build_coverage_profile(session, row.id),
        source_document_id=row.source_document_id,
    )


async def _build_coverage_profile(session: AsyncSession, policy_id: UUID) -> CoverageProfile | None:
    profile = await session.scalar(select(CoverageProfileRow).where(CoverageProfileRow.policy_id == policy_id))
    if profile is None:
        return None

    sub_limits = await session.scalars(
        select(SubLimitRow).where(SubLimitRow.coverage_profile_id == profile.id).order_by(SubLimitRow.position)
    )
    waiting_periods = await session.scalars(
        select(WaitingPeriodRow)
        .where(WaitingPeriodRow.coverage_profile_id == profile.id)
        .order_by(WaitingPeriodRow.position)
    )
    exclusions = await session.scalars(
        select(ExclusionRow).where(ExclusionRow.coverage_profile_id == profile.id).order_by(ExclusionRow.position)
    )

    return CoverageProfile(
        policy_id=policy_id,
        sum_insured=columns_to_extracted(profile, "sum_insured"),
        co_pay_percent=columns_to_extracted(profile, "co_pay_percent"),
        sub_limits=[
            SubLimit(
                category=row.category,
                label=row.label,
                cap_amount=columns_to_extracted(row, "cap_amount"),
                cap_basis=row.cap_basis,
                percent_value=row.percent_value,
            )
            for row in sub_limits
        ],
        waiting_periods=[
            WaitingPeriod(
                kind=row.kind,
                months=columns_to_extracted(row, "months"),
                applies_to=row.applies_to,
                starts_on=row.starts_on,
                expires_on=row.expires_on,
            )
            for row in waiting_periods
        ],
        exclusions=[columns_to_extracted(row, "text") for row in exclusions],
        intimation_deadline_hours=columns_to_extracted(profile, "intimation_deadline_hours"),
        extraction_completeness=profile.extraction_completeness,
    )
