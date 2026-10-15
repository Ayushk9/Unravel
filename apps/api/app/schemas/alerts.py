"""Wire shape for a gap alert (contract section 5, plus the D-38 additions)."""

from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from app.schemas.base import ApiModel
from contracts.models import Provenance


class Alert(ApiModel):
    id: str
    policy_id: UUID
    kind: Literal["room_rent_below_market", "waiting_period_expiring", "renewal_due", "no_maternity_cover", "low_sum_insured", "other"]
    severity: Literal["info", "warning", "critical"]
    title: str
    explanation: str
    suggested_action: str | None
    reference_source: str | None
    triggers_on: date | None
    # False when the alert relies on a reference figure nobody has checked yet (D-38).
    verified: bool
    # The policy field the alert is based on; null when it is based on something not being found.
    provenance: Provenance | None
