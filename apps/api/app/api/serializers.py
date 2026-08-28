"""Database-to-contract serializers for the currently implemented API slices."""

from __future__ import annotations

from typing import Any

from app.db.models import CoverageProfile, Document, Exclusion, Member, Policy, SubLimit, WaitingPeriod


def extracted(value: Any, confidence: str | None, provenance: dict[str, Any] | None, user_confirmed: bool) -> dict[str, Any]:
    return {
        "value": value,
        "confidence": confidence or "unknown",
        "provenance": provenance,
        "user_confirmed": user_confirmed,
    }


def document_read(document: Document) -> dict[str, Any]:
    status = {"queued": "queued", "running": "parsing", "succeeded": "parsed", "failed": "failed"}.get(document.parse_status, "unknown")
    provenance = document.detected_type_provenance
    return {
        "id": document.id,
        "file_name": document.file_name,
        "mime_type": document.mime_type,
        "page_count": document.page_count or 0,
        "uploaded_at": document.uploaded_at,
        "detected_type": extracted(document.detected_type, document.detected_type_confidence, provenance, document.detected_type_user_confirmed),
        "parse_status": status,
        "parse_error": document.parse_error,
        "deleted_at": document.deleted_at,
        "claim_id": None,
    }


def _sub_limit_read(item: SubLimit) -> dict[str, Any]:
    return {
        "category": item.category,
        "label": item.label,
        "cap_amount": extracted(item.cap_amount_value, item.cap_amount_confidence, item.cap_amount_provenance, item.cap_amount_user_confirmed),
        "cap_basis": item.cap_basis,
        "percent_value": item.percent_value,
    }


def _waiting_period_read(item: WaitingPeriod) -> dict[str, Any]:
    return {
        "kind": item.kind,
        "months": extracted(item.months_value, item.months_confidence, item.months_provenance, item.months_user_confirmed),
        "applies_to": item.applies_to,
        "starts_on": item.starts_on,
        "expires_on": item.expires_on,
    }


def _exclusion_read(item: Exclusion) -> dict[str, Any]:
    return extracted(item.value, item.confidence, item.provenance, item.user_confirmed)


def coverage_profile_read(profile: CoverageProfile) -> dict[str, Any]:
    return {
        "policy_id": profile.policy_id,
        "sum_insured": extracted(profile.sum_insured_value, profile.sum_insured_confidence, profile.sum_insured_provenance, profile.sum_insured_user_confirmed),
        "co_pay_percent": extracted(profile.co_pay_percent_value, profile.co_pay_percent_confidence, profile.co_pay_percent_provenance, profile.co_pay_percent_user_confirmed),
        "sub_limits": [_sub_limit_read(item) for item in profile.sub_limits],
        "waiting_periods": [_waiting_period_read(item) for item in profile.waiting_periods],
        "exclusions": [_exclusion_read(item) for item in profile.exclusions],
        "intimation_deadline_hours": extracted(profile.intimation_deadline_hours_value, profile.intimation_deadline_hours_confidence, profile.intimation_deadline_hours_provenance, profile.intimation_deadline_hours_user_confirmed),
        "extraction_completeness": profile.extraction_completeness,
    }


def policy_read(policy: Policy, members: list[Member]) -> dict[str, Any]:
    profile = policy.coverage_profile
    return {
        "id": policy.id,
        "insurer": {"id": policy.insurer.id, "name": policy.insurer.name, "irdai_code": policy.insurer.irdai_code},
        "policy_number": policy.policy_number,
        "product_name": policy.product_name or "Unknown product",
        "policy_type": policy.policy_type or "other",
        "start_date": policy.start_date,
        "end_date": policy.end_date,
        "members": [{"id": member.id, "full_name": member.full_name, "relationship": member.relationship, "date_of_birth": member.date_of_birth} for member in members],
        "coverage_profile": coverage_profile_read(profile) if profile else None,
        "source_document_id": policy.source_document_id,
    }
