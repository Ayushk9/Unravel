"""POST /claims/{id}/eligibility (CONTRACTS.md row 17): run Engine B on one claim.

Synchronous (D-07): rules over data already stored, no model call.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.claims.deadlines import india_date
from app.claims.reader import find_claim_row
from app.core.auth import CurrentHousehold, get_current_household
from app.core.errors import ApiError
from app.db.session import get_session
from app.rules_bridge import eligibility_input
from app.schemas.eligibility import EligibilityAssessment, EligibilityCheck, MissingFact
from app.api.v1.grievances import award_to_wire
from engines.rules import assess_eligibility, load_awards, match_precedent

router = APIRouter()


@router.post("/claims/{claim_id}/eligibility")
async def claim_eligibility(
    claim_id: UUID,
    household: Annotated[CurrentHousehold, Depends(get_current_household)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EligibilityAssessment:
    claim = await find_claim_row(session, household.household_id, claim_id)
    if claim is None:
        raise ApiError(404, "not_found", "No claim with that id belongs to your household.")

    # The clock is read here, at the edge, and handed to the engine.
    now = datetime.now(timezone.utc)
    assessment = assess_eligibility(await eligibility_input(session, claim), india_date(now))
    # Checked Ombudsman awards on the same ground as a failed or at-risk check: exact tag match, no model (D-45).
    precedent = match_precedent(assessment.checks, load_awards())

    return EligibilityAssessment(
        claim_id=claim.id,
        band=assessment.band,
        checks=[
            EligibilityCheck(
                id=check.id,
                title=check.title,
                status=check.status,
                explanation=check.explanation,
                governing_clause=check.governing_clause,
                missing_fact=check.missing_facts[0].fact if check.missing_facts else None,
                resolving_document=check.missing_facts[0].resolving_document if check.missing_facts else None,
                confidence=check.confidence,
                # mode="json" turns dates into YYYY-MM-DD strings.
                values={key: value for key, value in check.model_dump(mode="json")["values"].items()},
                missing_facts=[MissingFact(**fact.model_dump()) for fact in check.missing_facts],
            )
            for check in assessment.checks
        ],
        ombudsman_precedent=[award_to_wire(award) for award in precedent.awards],
        ombudsman_precedent_note=precedent.note,
        generated_at=now,
    )
