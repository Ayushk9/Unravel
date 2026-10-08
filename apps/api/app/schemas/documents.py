"""Wire shapes for uploaded documents."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from app.schemas.base import ApiModel
from contracts.models import Extracted

DocumentType = Literal[
    "policy_schedule",
    "policy_wording",
    "discharge_summary",
    "itemised_bill",
    "payment_receipt",
    "investigation_report",
    "denial_letter",
    "id_proof",
    "unknown",
]
ParseStatus = Literal["queued", "parsing", "parsed", "failed"]


class StoredDocument(ApiModel):
    id: UUID
    file_name: str
    mime_type: str
    page_count: int
    uploaded_at: datetime
    detected_type: Extracted[DocumentType]
    parse_status: ParseStatus
    parse_error: str | None
    deleted_at: datetime | None
    claim_id: UUID | None


class DocumentTypeCorrectionRequest(ApiModel):
    """Body of PATCH /documents/{id}: the user's own label for a document."""

    detected_type: DocumentType


class DocumentFile(ApiModel):
    """A short-lived link to the document's file (D-26)."""

    # Downloadable by anyone holding it, with no token, until `expires_at`.
    url: str
    expires_at: datetime
