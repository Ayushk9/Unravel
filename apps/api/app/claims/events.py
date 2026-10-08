"""Writing to the claim event log: creating a claim and appending a transition.

These are the only two places the application writes claim state, and both
only ever INSERT. There is no function that updates or deletes an event, and
the database would refuse one anyway (app/db/claim_event_ddl.py).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.claims.state_machine import INITIAL_STATE, allowed_targets, is_allowed
from app.core.errors import ApiError
from app.core.ids import new_id
from app.db.models import Claim, ClaimEvent, Member, Policy
from app.schemas.claims import ClaimCreateRequest, ClaimEventRequest
from app.schemas.errors import FieldError

SEQ_CONSTRAINT = "uq_claim_event_claim_id_seq"

# A phone's clock may run slightly ahead of the server's.
_CLOCK_SKEW_ALLOWANCE = timedelta(minutes=5)


def _unknown(field: str, what: str) -> ApiError:
    return ApiError(
        422,
        "validation_error",
        f"That {what} doesn't belong to your household.",
        field_errors=[FieldError(field=field, message=f"Unknown {what}.")],
    )


async def create_claim(
    session: AsyncSession, household_id: UUID, created_by: UUID, body: ClaimCreateRequest, now: datetime
) -> Claim:
    """Insert a claim and its first event together, in one transaction.

    A claim with no events would have no state at all, so the two rows are
    committed as one unit: both exist or neither does.
    """
    # The ids come from the request body, so they must be checked against the
    # caller's household. Without this, a caller could attach a claim to
    # someone else's policy just by knowing its id.
    policy_id = await session.scalar(
        select(Policy.id).where(Policy.id == body.policy_id, Policy.household_id == household_id)
    )
    if policy_id is None:
        raise _unknown("policy_id", "policy")
    member_id = await session.scalar(
        select(Member.id).where(Member.id == body.member_id, Member.household_id == household_id)
    )
    if member_id is None:
        raise _unknown("member_id", "member")

    claim = Claim(
        id=new_id(),
        household_id=household_id,
        policy_id=body.policy_id,
        member_id=body.member_id,
        claim_type=body.claim_type,
        admission_type=body.admission_type,
        hospital_name=body.hospital_name,
        admitted_on=body.admitted_on,
        discharged_on=body.discharged_on,
        claimed_amount=body.claimed_amount,
        settled_amount=None,
    )
    session.add(claim)
    # The claim row must exist before the event that references it.
    await session.flush()
    session.add(
        ClaimEvent(
            id=new_id(),
            claim_id=claim.id,
            seq=1,
            from_state=None,
            to_state=INITIAL_STATE,
            occurred_at=now,
            note="Claim intimated via app",
            source="user",
            created_by=created_by,
        )
    )
    await session.commit()
    return claim


async def append_event(
    session: AsyncSession, claim: Claim, created_by: UUID, body: ClaimEventRequest, now: datetime
) -> None:
    """Add one transition to a claim's log, if the state machine allows it.

    OPTIMISTIC CONCURRENCY, AND WHY NO LOCK IS NEEDED

    Suppose two requests arrive at the same moment for a claim that is
    `under_review`: one says "approved", the other "denied". Both are legal
    from `under_review`, but only one may happen. The second must be judged
    against the state the first one leaves behind.

    The pessimistic answer is to lock: take a lock on the claim (or the
    whole table), so the second request waits until the first finishes. That
    works, but every reader and writer of that claim queues behind the lock,
    a held lock can deadlock with another, and a crashed holder leaves
    others waiting.

    This function takes no lock. Each request:

      1. reads the latest event: its seq (say 3) and its to_state;
      2. checks its own transition against that state;
      3. inserts a new event with seq = 4.

    Both racing requests read seq 3 and both try to insert seq 4. The table
    has UNIQUE(claim_id, seq), so the database accepts exactly one of those
    inserts and rejects the other with a uniqueness error. The loser has not
    written anything; it reports 409 and the client reloads the claim.

    This is called optimistic because it assumes conflicts are rare and only
    checks for one at the moment of writing, instead of preventing it up
    front. The uniqueness check is atomic inside the database (it is how the
    index works), so there is no window in which both inserts could succeed.
    Readers are never blocked, and a request that dies midway holds nothing.

    The seq also gives the log a total order that does not depend on clocks.
    """
    latest = await session.scalar(
        select(ClaimEvent).where(ClaimEvent.claim_id == claim.id).order_by(ClaimEvent.seq.desc()).limit(1)
    )
    if latest is None:
        raise ApiError(409, "claim_has_no_history", "This claim has no events, so its state is unknown.")

    if not is_allowed(latest.to_state, body.to_state):
        # One field_errors entry per allowed state: the client rebuilds its
        # list of choices from these without a second request (D-04).
        raise ApiError(
            409,
            "illegal_transition",
            "That transition isn't allowed from the claim's current state.",
            field_errors=[FieldError(field="to_state", message=state) for state in allowed_targets(latest.to_state)],
        )

    if body.occurred_at > now + _CLOCK_SKEW_ALLOWANCE:
        raise ApiError(
            422,
            "validation_error",
            "An event can't be dated in the future.",
            field_errors=[FieldError(field="occurred_at", message="Must not be in the future.")],
        )

    session.add(
        ClaimEvent(
            id=new_id(),
            claim_id=claim.id,
            seq=latest.seq + 1,
            from_state=latest.to_state,
            to_state=body.to_state,
            occurred_at=body.occurred_at,
            note=(body.note or "").strip() or None,
            source="user",
            created_by=created_by,
        )
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if SEQ_CONSTRAINT not in str(exc.orig):
            raise
        # Another request added an event to this claim between our read and
        # our insert. Ours was judged against a state that no longer holds.
        raise ApiError(
            409,
            "claim_changed",
            "This claim was updated at the same moment by another request. Reload it and try again.",
            retryable=True,
        ) from exc
