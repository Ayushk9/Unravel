"""Claim endpoints.

GET  /claims                      CONTRACTS.md row 13
POST /claims                      CONTRACTS.md row 14
GET  /claims/{id}                 CONTRACTS.md row 15
POST /claims/{id}/events          CONTRACTS.md row 16, D-16
POST /claims/{id}/completeness    CONTRACTS.md row 18

The clock is read here, at the edge, and passed inwards. The rule code in
app/claims never calls now() itself.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.claims.completeness import compute_completeness
from app.claims.deadlines import india_date
from app.claims.events import append_event, create_claim
from app.claims.reader import build_claims, find_claim_row, list_claim_rows, load_attached_documents
from app.core.auth import CurrentHousehold, get_current_household
from app.core.errors import ApiError
from app.db.models import Claim as ClaimRow
from app.db.session import get_session
from app.rules.loader import load_required_documents
from app.claims.facts import save_facts
from app.schemas.claims import Claim, ClaimCreateRequest, ClaimEventRequest, ClaimFacts, CompletenessReport

router = APIRouter()


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _owned_claim(session: AsyncSession, household: CurrentHousehold, claim_id: UUID) -> ClaimRow:
    row = await find_claim_row(session, household.household_id, claim_id)
    if row is None:
        raise ApiError(404, "not_found", "No claim with that id belongs to your household.")
    return row


async def _wire_claim(session: AsyncSession, row: ClaimRow, now: datetime) -> Claim:
    return (await build_claims(session, [row], india_date(now)))[0]


@router.get("/claims")
async def list_claims(
    household: Annotated[CurrentHousehold, Depends(get_current_household)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[Claim]:
    """A full array, oldest first. The client groups by state itself."""
    rows = await list_claim_rows(session, household.household_id)
    return await build_claims(session, rows, india_date(_now()))


@router.post("/claims", status_code=201)
async def create_claim_route(
    body: ClaimCreateRequest,
    household: Annotated[CurrentHousehold, Depends(get_current_household)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Claim:
    now = _now()
    row = await create_claim(session, household.household_id, household.auth_user_id, body, now)
    return await _wire_claim(session, row, now)


@router.get("/claims/{claim_id}")
async def get_claim(
    claim_id: UUID,
    household: Annotated[CurrentHousehold, Depends(get_current_household)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Claim:
    return await _wire_claim(session, await _owned_claim(session, household, claim_id), _now())


@router.post("/claims/{claim_id}/events")
async def append_claim_event(
    claim_id: UUID,
    body: ClaimEventRequest,
    household: Annotated[CurrentHousehold, Depends(get_current_household)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Claim:
    """Log that something happened to the claim. Returns the claim with its new state and deadlines."""
    now = _now()
    row = await _owned_claim(session, household, claim_id)
    await append_event(session, row, household.auth_user_id, body, now)
    return await _wire_claim(session, row, now)


@router.put("/claims/{claim_id}/facts")
async def put_claim_facts(
    claim_id: UUID,
    body: ClaimFacts,
    household: Annotated[CurrentHousehold, Depends(get_current_household)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Claim:
    """Replace what the user has told us about the illness and the stay (D-37).

    A full replacement: send every field, null for "not answered".
    Returns the claim, so the client sees the stored facts.
    """
    now = _now()
    row = await _owned_claim(session, household, claim_id)
    await save_facts(session, row, body, india_date(now))
    return await _wire_claim(session, row, now)


@router.post("/claims/{claim_id}/completeness")
async def claim_completeness(
    claim_id: UUID,
    household: Annotated[CurrentHousehold, Depends(get_current_household)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CompletenessReport:
    """Which of the documents this kind of claim usually needs are present, and which are missing."""
    row = await _owned_claim(session, household, claim_id)
    attached = await load_attached_documents(session, household.household_id, row.id)
    return compute_completeness(row.id, row.claim_type, row.admission_type, attached, load_required_documents())
