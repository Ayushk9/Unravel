"""GET /alerts (CONTRACTS.md row 21): gaps in the household's cover, worked out now.

Nothing is stored and nothing is scheduled: every request runs Engine B's
alert rules over the household's policies for today's date. An alert that
needs an input we don't have is skipped, and the reason is logged (D-38).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.claims.deadlines import india_date
from app.core.auth import CurrentHousehold, get_current_household
from app.db.session import get_session
from app.rules_bridge import alert_inputs
from app.schemas.alerts import Alert
from engines.rules import compute_alerts, load_reference

router = APIRouter()
logger = logging.getLogger("unravel.rules")


@router.get("/alerts")
async def list_alerts(
    household: Annotated[CurrentHousehold, Depends(get_current_household)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[Alert]:
    """A full array (API_DECISIONS section 5)."""
    today = india_date(datetime.now(timezone.utc))
    reference = load_reference()
    alerts: list[Alert] = []
    for data in await alert_inputs(session, household.household_id):
        outcome = compute_alerts(data, reference, today)
        for skipped in outcome.skipped:
            logger.info("Alert skipped. kind=%s policy_id=%s reason=%s", skipped.kind, skipped.policy_id, skipped.reason)
        alerts.extend(Alert(**alert.model_dump()) for alert in outcome.alerts)
    return alerts
