"""Wire-format rules: nulls are emitted (D-05) and money is integer paise."""

from __future__ import annotations

import json
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import ValidationError

from contracts.models import CoverageProfile, Extracted, Provenance, SubLimit

DOCUMENT_ID = UUID("01920000-0000-7000-8000-000000000001")
POLICY_ID = UUID("01920000-0000-7000-8000-000000000002")


def _not_found() -> Extracted:
    return Extracted(value=None, confidence="low", provenance=None)


def test_route_emits_null_for_a_none_field(client: TestClient) -> None:
    response = client.get("/api/v1/_test/nullable")

    assert response.status_code == 200
    assert response.json() == {"name": "claim", "settled_amount": None}
    assert '"settled_amount":null' in response.text


def _api_routes(routes: list) -> list[APIRoute]:
    """Flatten the route tree.

    This FastAPI version keeps an included router as one entry holding the
    original router, rather than copying its routes onto the app.
    """
    found: list[APIRoute] = []
    for route in routes:
        if isinstance(route, APIRoute):
            found.append(route)
        elif hasattr(route, "original_router"):
            found.extend(_api_routes(route.original_router.routes))
    return found


def test_no_route_is_configured_to_drop_fields(app: FastAPI) -> None:
    """FastAPI can strip nulls per route. No route may switch that on."""
    routes = _api_routes(app.routes)

    assert any(route.path.endswith("/health") for route in routes), "route walk found nothing"
    for route in routes:
        assert route.response_model_exclude_none is False, route.path
        assert route.response_model_exclude_unset is False, route.path
        assert route.response_model_exclude_defaults is False, route.path


def test_extracted_with_no_value_serialises_every_key() -> None:
    dumped = json.loads(Extracted[int](value=None, confidence="low", provenance=None).model_dump_json())

    assert dumped == {"value": None, "confidence": "low", "provenance": None, "user_confirmed": False}


def test_empty_coverage_profile_serialises_every_key_with_nulls() -> None:
    profile = CoverageProfile(
        policy_id=POLICY_ID,
        sum_insured=_not_found(),
        co_pay_percent=_not_found(),
        sub_limits=[],
        waiting_periods=[],
        exclusions=[],
        intimation_deadline_hours=_not_found(),
        extraction_completeness=0.0,
    )

    dumped = json.loads(profile.model_dump_json())

    assert set(dumped) == set(CoverageProfile.model_fields)
    assert dumped["sum_insured"]["value"] is None
    assert dumped["sum_insured"]["provenance"] is None


def test_provenance_with_no_bbox_serialises_null_bbox() -> None:
    provenance = Provenance(document_id=DOCUMENT_ID, page=3, bbox=None, snippet=None)

    assert json.loads(provenance.model_dump_json()) == {
        "document_id": str(DOCUMENT_ID),
        "page": 3,
        "bbox": None,
        "snippet": None,
    }


def test_money_is_an_integer_on_the_wire() -> None:
    sub_limit = SubLimit(
        category="room_rent",
        label="Room rent",
        cap_amount=Extracted[int](value=500_000, confidence="high", provenance=None),  # Rs 5,000 in paise
        cap_basis="per_day",
        percent_value=None,
    )

    text = sub_limit.model_dump_json()
    value = json.loads(text)["cap_amount"]["value"]

    assert type(value) is int
    assert value == 500_000
    assert '"value":500000,' in text  # not 500000.0


def test_fractional_paise_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Extracted[int](value=500_000.5, confidence="high", provenance=None)


def test_cap_basis_and_waiting_period_kind_accept_other() -> None:
    sub_limit = SubLimit(
        category="other",
        label="Unclassified cap",
        cap_amount=_not_found(),
        cap_basis="other",
        percent_value=None,
    )

    assert sub_limit.cap_basis == "other"
