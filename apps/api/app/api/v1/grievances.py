"""Grievance drafting (Feature 7) and Ombudsman awards.

GET   /claims/{id}/grievance-rungs     CONTRACTS.md row 30 (D-43)
POST  /claims/{id}/grievance-drafts    CONTRACTS.md row 20 (D-07 job, D-13 / D-27 idempotency, D-44 errors)
GET   /ombudsman-awards                CONTRACTS.md row 22 (D-45)

The clock is read here, at the edge, and passed inwards.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.claims.deadlines import EventFact, india_date
from app.claims.reader import build_claims, find_claim_row
from app.claims.rungs import RungContext, rung_options
from app.core.auth import CurrentHousehold, get_current_household
from app.core.errors import ApiError
from app.core.ids import new_id
from app.db.models import Claim as ClaimRow
from app.db.models import Job as JobRow
from app.db.models import Policy
from app.db.session import get_session
from app.jobs.idempotency import accepted, find_job_by_key, replay_or_conflict, require_key
from app.qa.indexing import index_counts
from app.rules.loader import load_grievance_rungs, load_ombudsman_rules
from app.schemas.common import Collection
from app.schemas.errors import FieldError
from app.schemas.grievances import GrievanceDraftRequest, GrievanceRungOption, OmbudsmanAward
from app.schemas.jobs import JobAccepted
from engines.rules import Award, load_awards

router = APIRouter()

REUSED_KEY_MESSAGE = "This Idempotency-Key was already used to draft a letter for a different rung. Use a new key for a new draft."


async def _owned_claim(session: AsyncSession, household: CurrentHousehold, claim_id: UUID) -> ClaimRow:
    row = await find_claim_row(session, household.household_id, claim_id)
    if row is None:
        raise ApiError(404, "not_found", "No claim with that id belongs to your household.")
    return row


async def claim_rung_options(session: AsyncSession, row: ClaimRow) -> list[GrievanceRungOption]:
    # The wire claim already carries its state, events and deadlines, all computed for today.
    [claim] = await build_claims(session, [row], india_date(datetime.now(timezone.utc)))
    context = RungContext(
        current_state=claim.current_state,
        events=tuple(EventFact(seq=i, to_state=e.to_state, occurred_at=e.occurred_at) for i, e in enumerate(claim.events, start=1)),
        deadlines=tuple(claim.deadlines),
    )
    ombudsman = load_ombudsman_rules()
    return rung_options(context, load_grievance_rungs(), ombudsman.award_ceiling.shown_sentence(), ombudsman.award_time.shown())


@router.get("/claims/{claim_id}/grievance-rungs")
async def grievance_rungs(
    claim_id: UUID,
    household: Annotated[CurrentHousehold, Depends(get_current_household)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[GrievanceRungOption]:
    """Every rung, in ladder order, with whether a letter for it makes sense now and why (D-43)."""
    return await claim_rung_options(session, await _owned_claim(session, household, claim_id))


def _request_hash(claim_id: UUID, rung: str) -> str:
    return hashlib.sha256(f"grievance-draft|{claim_id}|{rung}".encode()).hexdigest()


@router.post("/claims/{claim_id}/grievance-drafts", status_code=202)
async def request_grievance_draft(
    claim_id: UUID,
    body: GrievanceDraftRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    household: Annotated[CurrentHousehold, Depends(get_current_household)],
    session: Annotated[AsyncSession, Depends(get_session)],
    idempotency_key: Annotated[str | None, Header()] = None,
) -> JobAccepted:
    """Queue a letter draft for one rung. The draft arrives through GET /jobs/{id}; it is never cached (D-42)."""
    key = require_key(idempotency_key)
    row = await _owned_claim(session, household, claim_id)
    request_hash = _request_hash(row.id, body.rung)

    existing = await find_job_by_key(session, household.household_id, key)
    if existing is not None:
        return replay_or_conflict(existing, request_hash, REUSED_KEY_MESSAGE)

    options = {option.rung: option for option in await claim_rung_options(session, row)}
    if not options[body.rung].available:
        raise ApiError(
            409,
            "rung_not_available",
            f"A letter to the {options[body.rung].label} doesn't fit this claim yet. {options[body.rung].reason}",
            # One entry per rung that IS available now, like illegal_transition (D-31).
            field_errors=[FieldError(field="rung", message=rung) for rung, option in options.items() if option.available],
        )

    policy = await session.get(Policy, row.policy_id)
    assert policy is not None  # foreign key, same household
    total, indexed = await index_counts(session, policy.source_document_id)
    if total == 0 or indexed < total:
        raise ApiError(
            409,
            "policy_not_indexed",
            "This claim's policy hasn't been prepared for searching yet. Try again once it has finished processing.",
            retryable=True,
        )

    job = JobRow(
        id=new_id(),
        household_id=household.household_id,
        kind="generate_grievance_draft",
        status="queued",
        progress={"step": "queued", "percent": 0},
        payload={"claim_id": str(row.id), "rung": body.rung},
        idempotency_key=key,
        request_hash=request_hash,
    )
    session.add(job)
    try:
        await session.commit()
    except IntegrityError:
        # The same key arrived twice at once and the other request won. Answer from its row.
        await session.rollback()
        winner = await find_job_by_key(session, household.household_id, key)
        if winner is None:
            raise
        return replay_or_conflict(winner, request_hash, REUSED_KEY_MESSAGE)
    # Only a nudge: the job is already committed, whether or not this runs.
    background_tasks.add_task(request.app.state.runner.wake)
    return accepted(job)


def award_to_wire(award: Award) -> OmbudsmanAward:
    return OmbudsmanAward(
        id=award.id,
        case_reference=award.case_reference,
        insurer_name=award.insurer_name,
        decided_on=award.decided_on,
        denial_ground=award.denial_ground_label,
        outcome=award.outcome,
        summary=award.summary,
        external_url=award.external_url,
    )


@router.get("/ombudsman-awards")
async def list_ombudsman_awards(
    household: Annotated[CurrentHousehold, Depends(get_current_household)],
    cursor: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Collection[OmbudsmanAward]:
    """The awards Ayush has checked, newest first, one page at a time (D-45).

    Reference data, the same for every household; the token is still
    required (D-24). The cursor is the id of the last award already seen.
    The file is read on every request, so a newly checked award appears
    without a restart.
    """
    awards = load_awards()
    start = 0
    if cursor is not None:
        ids = [award.id for award in awards]
        if cursor not in ids:
            raise ApiError(
                422, "validation_error", "That cursor is not valid any more. Start from the first page.",
                field_errors=[FieldError(field="cursor", message="Unknown cursor.")],
            )
        start = ids.index(cursor) + 1
    page = awards[start : start + limit]
    next_cursor = str(page[-1].id) if start + limit < len(awards) else None
    return Collection[OmbudsmanAward](items=[award_to_wire(a) for a in page], next_cursor=next_cursor, total=len(awards))
