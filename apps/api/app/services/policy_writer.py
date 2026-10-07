"""Store one Engine A result: policy, coverage profile, and document chunks.

Called inside a transaction opened by the caller. Either every row from one
document is stored or none is, so a half-written policy can never be read.

Engine A's placeholder ids are replaced first (remap_ids). Each Extracted[T]
field is written through extracted_to_columns, which stores the parsed value
as both `_value` and `_original_value`: the second is never updated again,
so it stays as a record of what the parser read.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.db.models import CoverageProfile, Document, DocumentChunk, Exclusion, Policy, SubLimit, WaitingPeriod
from app.services.extracted_columns import extracted_to_columns
from app.services.extraction_mapper import remap_ids
from contracts.models import CoverageProfile as ExtractedCoverageProfile
from contracts.models import ExtractionResult

logger = logging.getLogger("unravel.jobs")


async def store_extraction(session: AsyncSession, document: Document, result: ExtractionResult) -> UUID | None:
    """Write `result` for `document`. Returns the new policy id, or None.

    A policy is created only when the result contains a coverage profile.
    """
    policy_id = new_id() if result.coverage_profile is not None else None
    # After this line the result contains only real, server-issued ids.
    result = remap_ids(result, document_id=document.id, policy_id=policy_id)

    if result.coverage_profile is not None and policy_id is not None:
        # insurer, policy number, product name, type and dates stay null:
        # Engine A does not extract them, and a guess would be a fact without
        # provenance (D-25).
        session.add(Policy(id=policy_id, household_id=document.household_id, source_document_id=document.id))
        # Parents are flushed before children: the tables are linked by
        # foreign keys, so the policy row must exist before its profile.
        await session.flush()
        await _store_coverage_profile(session, policy_id, result.coverage_profile)

    session.add_all(
        DocumentChunk(
            id=chunk.id,
            document_id=document.id,
            position=position,
            page=chunk.page,
            text=chunk.text,
            bbox=list(chunk.bbox) if chunk.bbox is not None else None,
        )
        for position, chunk in enumerate(result.chunks)
    )

    document.page_count = result.page_count
    document.warnings = result.warnings
    for warning in result.warnings:
        logger.warning("Extraction warning. document_id=%s %s", document.id, warning)

    await session.flush()
    return policy_id


async def _store_coverage_profile(session: AsyncSession, policy_id: UUID, profile: ExtractedCoverageProfile) -> None:
    profile_id = new_id()
    session.add(
        CoverageProfile(
            id=profile_id,
            policy_id=policy_id,
            extraction_completeness=profile.extraction_completeness,
            **extracted_to_columns("sum_insured", profile.sum_insured),
            **extracted_to_columns("co_pay_percent", profile.co_pay_percent),
            **extracted_to_columns("intimation_deadline_hours", profile.intimation_deadline_hours),
        )
    )
    await session.flush()

    # `position` keeps each list in the order Engine A produced it.
    session.add_all(
        SubLimit(
            id=new_id(),
            coverage_profile_id=profile_id,
            position=position,
            category=sub_limit.category,
            label=sub_limit.label,
            cap_basis=sub_limit.cap_basis,
            percent_value=sub_limit.percent_value,
            **extracted_to_columns("cap_amount", sub_limit.cap_amount),
        )
        for position, sub_limit in enumerate(profile.sub_limits)
    )
    session.add_all(
        WaitingPeriod(
            id=new_id(),
            coverage_profile_id=profile_id,
            position=position,
            kind=waiting_period.kind,
            applies_to=waiting_period.applies_to,
            starts_on=waiting_period.starts_on,
            expires_on=waiting_period.expires_on,
            **extracted_to_columns("months", waiting_period.months),
        )
        for position, waiting_period in enumerate(profile.waiting_periods)
    )
    session.add_all(
        Exclusion(
            id=new_id(),
            coverage_profile_id=profile_id,
            position=position,
            **extracted_to_columns("text", exclusion),
        )
        for position, exclusion in enumerate(profile.exclusions)
    )
