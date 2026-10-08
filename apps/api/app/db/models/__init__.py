"""Every table model, imported in one place.

Alembic and the seed script import this package so that all tables are
registered on Base.metadata before it is used.
"""

from app.db.models.claim import Claim, ClaimEvent, claim_current_state
from app.db.models.coverage import CoverageProfile, Exclusion, SubLimit, WaitingPeriod
from app.db.models.document import Document, DocumentChunk
from app.db.models.household import Household, Member
from app.db.models.insurer import Insurer, InsurerTermMap
from app.db.models.job import Job
from app.db.models.policy import Policy, policy_member

__all__ = [
    "Claim",
    "ClaimEvent",
    "CoverageProfile",
    "Document",
    "DocumentChunk",
    "Exclusion",
    "Household",
    "Insurer",
    "InsurerTermMap",
    "Job",
    "Member",
    "Policy",
    "SubLimit",
    "WaitingPeriod",
    "claim_current_state",
    "policy_member",
]
