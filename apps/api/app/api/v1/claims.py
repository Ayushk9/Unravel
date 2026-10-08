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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.claims.completeness import AttachedDocument, compute_completeness
from app.claims.deadlines import india_date
from app.claims.events import append_event, create_claim
from app.claims.reader import build_claims, find_claim_row, list_claim_rows
from app.core.auth import CurrentHousehold, get_current_household
from app.core.errors import ApiError
from app.db.models import Claim as ClaimRow
from app.db.models import Document
from app.db.session import get_session
from app.rules.loader import load_required_documents
from app.schemas.claims import Claim, ClaimCreateRequest, ClaimEventRequest, CompletenessReport

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


@router.post("/claims/{claim_id}/completeness")
async def claim_completeness(
    claim_id: UUID,
    household: Annotated[CurrentHousehold, Depends(get_current_household)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CompletenessReport:
    """Which of the documents this kind of claim usually needs are present, and which are missing."""
    row = await _owned_claim(session, household, claim_id)
    documents = await session.scalars(
        select(Document)
        .where(
            Document.claim_id == row.id,
            Document.household_id == household.household_id,
            Document.deleted_at.is_(None),
            # A document still being read has no type yet.
            Document.parse_status == "parsed",
        )
        .order_by(Document.id)
    )
    attached = [
        AttachedDocument(
            document_type=document.detected_type_value,
            confidence=document.detected_type_confidence,
            user_confirmed=document.detected_type_user_confirmed,
        )
        for document in documents
    ]
    return compute_completeness(row.id, row.claim_type, row.admission_type, attached, load_required_documents())
