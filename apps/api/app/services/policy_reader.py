"""Load policies from the database and build the wire `Policy`.

Every lookup starts from a household id that came from the caller's token.
A policy in another household is simply not found, which is how the API
returns 404 rather than 403 for other people's data (D-10).

LOADING IN A FIXED NUMBER OF QUERIES

The database is a network round trip away (about 200 ms from the demo Mac to
Supabase), so the number of queries matters more than their size. Loading
each policy's insurer, members, profile and three lists one by one cost
1 + 6 queries per policy. `load_policies` instead asks for everything at once:

    1 query    the policies, joined to their insurer and coverage profile
    1 query    the members of all those policies         (selectinload)
    3 queries  all their sub-limits, waiting periods and exclusions (selectinload)

Five queries whether the household has one policy or ten. The build_*
functions below then only read what was loaded; they never query.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.orm.interfaces import LoaderOption

from app.db.models import CoverageProfile as CoverageProfileRow
from app.db.models import Policy as PolicyRow
from app.schemas.household import Insurer, Member
from app.schemas.policies import Policy
from app.services.extracted_columns import columns_to_extracted
from contracts.models import CoverageProfile, SubLimit, WaitingPeriod
from engines.rules.dates import add_months, whole_months


def coverage_terms() -> list[LoaderOption]:
    """Load options for a policy's coverage profile and its three lists: what the rules need."""
    profile = joinedload(PolicyRow.coverage_profile)
    return [
        profile.selectinload(CoverageProfileRow.sub_limits),
        profile.selectinload(CoverageProfileRow.waiting_periods),
        profile.selectinload(CoverageProfileRow.exclusions),
    ]


def everything() -> list[LoaderOption]:
    """Load options for everything the wire `Policy` shows."""
    return [joinedload(PolicyRow.insurer), selectinload(PolicyRow.members), *coverage_terms()]


def waiting_clock_start(row: PolicyRow) -> date | None:
    """The date waiting periods count from: first inception if the user gave it, else the policy start (D-39)."""
    return row.first_inception_date or row.start_date


def _period_dates(start_date: date | None, months: float | None) -> dict[str, date | None]:
    whole = whole_months(months)
    if start_date is None or whole is None:
        return {"starts_on": None, "expires_on": None}
    return {"starts_on": start_date, "expires_on": add_months(start_date, whole)}


async def find_policy_row(session: AsyncSession, household_id: UUID, policy_id: UUID) -> PolicyRow | None:
    """The policy, only if it belongs to this household."""
    return await session.scalar(
        select(PolicyRow).where(PolicyRow.id == policy_id, PolicyRow.household_id == household_id)
    )


async def load_policies(
    session: AsyncSession, household_id: UUID, *, policy_id: UUID | None = None, options: list[LoaderOption] | None = None
) -> list[PolicyRow]:
    """This household's policies (or the one `policy_id`), oldest first, with `options` loaded up front.

    populate_existing: a policy already in this session (for example one
    just corrected and committed) is refreshed from the database, so the
    response always shows what was stored.
    """
    query = select(PolicyRow).where(PolicyRow.household_id == household_id)
    if policy_id is not None:
        query = query.where(PolicyRow.id == policy_id)
    query = query.options(*(everything() if options is None else options)).order_by(PolicyRow.id)
    rows = await session.scalars(query.execution_options(populate_existing=True))
    return list(rows.unique())


async def load_policy(session: AsyncSession, household_id: UUID, policy_id: UUID) -> PolicyRow | None:
    rows = await load_policies(session, household_id, policy_id=policy_id)
    return rows[0] if rows else None


def build_policy(row: PolicyRow) -> Policy:
    """The wire `Policy` from a row loaded by load_policies. No queries."""
    return Policy(
        id=row.id,
        insurer=Insurer.model_validate(row.insurer) if row.insurer else None,
        policy_number=row.policy_number,
        product_name=row.product_name,
        start_date=row.start_date,
        end_date=row.end_date,
        first_inception_date=row.first_inception_date,
        policy_type=row.policy_type or "other",
        members=[Member.model_validate(member) for member in row.members],
        coverage_profile=build_coverage_profile(row),
        source_document_id=row.source_document_id,
    )


def build_coverage_profile(row: PolicyRow) -> CoverageProfile | None:
    """The coverage profile of a row loaded with coverage_terms(). No queries.

    Each waiting period's starts_on / expires_on is filled in when the policy's
    waiting clock start is known (first inception if the user gave it, else the
    start date; D-39). The contract marks those two dates "derived
    server-side": they are computed here from the start date and the month
    count, with the same calendar rule the eligibility engine uses, and never stored.
    """
    profile = row.coverage_profile
    if profile is None:
        return None
    start_date = waiting_clock_start(row)
    return CoverageProfile(
        policy_id=row.id,
        sum_insured=columns_to_extracted(profile, "sum_insured"),
        co_pay_percent=columns_to_extracted(profile, "co_pay_percent"),
        sub_limits=[
            SubLimit(
                category=sub_limit.category,
                label=sub_limit.label,
                cap_amount=columns_to_extracted(sub_limit, "cap_amount"),
                cap_basis=sub_limit.cap_basis,
                percent_value=sub_limit.percent_value,
            )
            for sub_limit in profile.sub_limits
        ],
        waiting_periods=[
            WaitingPeriod(
                kind=period.kind,
                months=columns_to_extracted(period, "months"),
                applies_to=period.applies_to,
                **_period_dates(start_date, period.months_value),
            )
            for period in profile.waiting_periods
        ],
        exclusions=[columns_to_extracted(exclusion, "text") for exclusion in profile.exclusions],
        intimation_deadline_hours=columns_to_extracted(profile, "intimation_deadline_hours"),
        extraction_completeness=profile.extraction_completeness,
    )
