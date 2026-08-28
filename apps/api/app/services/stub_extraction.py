"""Temporary deterministic extraction output used until the parser service lands."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.db.models import CoverageProfile, Document, DocumentChunk, Exclusion, Insurer, Policy, SubLimit, WaitingPeriod
from app.db.session import build_async_session_factory
from app.services.jobs import ProgressReporter


def _provenance(document_id: UUID, page: int, snippet: str) -> dict[str, Any]:
    return {"document_id": str(document_id), "page": page, "bbox": None, "snippet": snippet}


async def parse_uploaded_document(reporter: ProgressReporter, document_id: UUID) -> dict[str, Any]:
    """Create stable policy-shaped fixture data while the real parser is unavailable."""
    await reporter.update({"step": "classifying_document", "percent": 20})
    session_factory = build_async_session_factory()
    async with session_factory() as session:
        document = await session.get(Document, document_id)
        if document is None:
            raise ValueError("Uploaded document disappeared before parsing.")

        document.parse_status = "running"
        document.detected_type = "policy_schedule"
        document.detected_type_original_value = "policy_schedule"
        document.detected_type_confidence = "high"
        document.detected_type_provenance = _provenance(document.id, 1, "Policy Schedule")
        document.page_count = 3
        insurer = await session.scalar(select(Insurer).order_by(Insurer.name).limit(1))
        if insurer is None:
            insurer = Insurer(name="Stub Health Insurance Co.", irdai_code="STUB001")
            session.add(insurer)
            await session.flush()
        policy = Policy(
            household_id=document.household_id,
            insurer_id=insurer.id,
            policy_number=f"STUB/{str(document.id)[:8].upper()}",
            product_name="Stub Complete Health Plan",
            policy_type="family_floater",
            start_date=date(2026, 4, 1),
            end_date=date(2027, 3, 31),
            source_document_id=document.id,
        )
        session.add(policy)
        await session.flush()
        source = _provenance(document.id, 1, "Sum insured: Rs. 5,00,000")
        profile = CoverageProfile(
            policy_id=policy.id,
            sum_insured_value=50_000_000,
            sum_insured_original_value=50_000_000,
            sum_insured_confidence="high",
            sum_insured_provenance=source,
            co_pay_percent_value=10,
            co_pay_percent_original_value=10,
            co_pay_percent_confidence="medium",
            co_pay_percent_provenance=_provenance(document.id, 1, "Co-payment: 10%"),
            intimation_deadline_hours_value=48,
            intimation_deadline_hours_original_value=48,
            intimation_deadline_hours_confidence="high",
            intimation_deadline_hours_provenance=_provenance(document.id, 2, "Intimate within 48 hours"),
            extraction_completeness=0.9,
        )
        session.add(profile)
        await session.flush()
        session.add_all([
            SubLimit(coverage_profile_id=profile.id, category="room_rent", label="Room rent", cap_amount_value=500_000, cap_amount_original_value=500_000, cap_amount_confidence="medium", cap_amount_provenance=_provenance(document.id, 2, "Room rent: Rs. 5,000 per day"), cap_basis="per_day"),
            WaitingPeriod(coverage_profile_id=profile.id, kind="pre_existing", months_value=48, months_original_value=48, months_confidence="high", months_provenance=_provenance(document.id, 2, "Pre-existing disease: 48 months"), starts_on=date(2023, 4, 1), expires_on=date(2027, 4, 1)),
            Exclusion(coverage_profile_id=profile.id, value="Cosmetic surgery unless medically necessary after an accident.", original_value="Cosmetic surgery unless medically necessary after an accident.", confidence="high", provenance=_provenance(document.id, 3, "Exclusion: cosmetic surgery")),
            DocumentChunk(document_id=document.id, page=1, text="Stub policy schedule: sum insured Rs. 5,00,000.", bbox=None),
        ])
        await session.commit()

    await reporter.update({"step": "extracting_coverage", "percent": 75})
    async with session_factory() as session:
        document = await session.get(Document, document_id)
        if document is None:
            raise ValueError("Uploaded document disappeared before finishing.")
        document.parse_status = "succeeded"
        document.parse_error = None
        await session.commit()
    return {"document_id": str(document_id), "policy_id": str(policy.id)}
