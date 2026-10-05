"""Every non-2xx response uses the D-03 envelope. {"detail": ...} never appears."""

from __future__ import annotations

import logging
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

ENVELOPE_KEYS = {"code", "message", "field_errors", "request_id", "retryable"}


def assert_envelope(body: dict) -> dict:
    """Check the exact shape and return the inner error object."""
    assert set(body) == {"error"}, body
    error = body["error"]
    assert set(error) == ENVELOPE_KEYS, error
    assert isinstance(error["code"], str)
    assert isinstance(error["message"], str)
    assert isinstance(error["field_errors"], list)
    assert isinstance(error["retryable"], bool)
    assert UUID(error["request_id"]).version == 7
    return error


def test_unknown_route_returns_404_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/nonexistent")

    assert response.status_code == 404
    error = assert_envelope(response.json())
    assert error["code"] == "not_found"
    assert error["field_errors"] == []
    assert error["retryable"] is False


def test_unknown_route_outside_api_prefix_returns_404_envelope(client: TestClient) -> None:
    response = client.get("/nowhere")

    assert response.status_code == 404
    assert_envelope(response.json())


def test_wrong_method_returns_405_envelope(client: TestClient) -> None:
    response = client.post("/api/v1/health")

    assert response.status_code == 405
    error = assert_envelope(response.json())
    assert error["code"] == "method_not_allowed"
    assert response.headers["allow"] == "GET"


def test_validation_failure_returns_422_envelope_with_field_errors(client: TestClient) -> None:
    response = client.post("/api/v1/_test/validate", json={"claim_type": "barter", "claimed_amount": "lots"})

    assert response.status_code == 422
    error = assert_envelope(response.json())
    assert error["code"] == "validation_error"
    # Field names match the contract's example ("claim_type"), with no "body." prefix.
    assert {field_error["field"] for field_error in error["field_errors"]} == {"claim_type", "claimed_amount"}
    assert all(set(field_error) == {"field", "message"} for field_error in error["field_errors"])


def test_missing_body_returns_422_envelope(client: TestClient) -> None:
    response = client.post("/api/v1/_test/validate")

    assert response.status_code == 422
    error = assert_envelope(response.json())
    assert error["field_errors"] == [{"field": "body", "message": "Field required"}]


def test_unhandled_exception_returns_500_envelope_without_leaking(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger="unravel.api"):
        response = client.get("/api/v1/_test/boom")

    assert response.status_code == 500
    error = assert_envelope(response.json())
    assert error["code"] == "internal_error"
    assert "secret internal detail" not in response.text
    assert "Traceback" not in response.text
    assert "RuntimeError" not in response.text

    # The same id is in the body, the header and the server log.
    assert response.headers["x-request-id"] == error["request_id"]
    assert error["request_id"] in caplog.text
    assert "secret internal detail" in caplog.text


def test_api_error_carries_code_and_field_errors(client: TestClient) -> None:
    response = client.get("/api/v1/_test/conflict")

    assert response.status_code == 409
    error = assert_envelope(response.json())
    assert error["code"] == "illegal_transition"
    assert error["field_errors"] == [{"field": "to_state", "message": "resolved"}]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/nonexistent"),
        ("POST", "/api/v1/health"),
        ("POST", "/api/v1/_test/validate"),
        ("GET", "/api/v1/_test/boom"),
        ("GET", "/api/v1/_test/conflict"),
    ],
)
def test_no_error_response_uses_fastapi_detail_shape(client: TestClient, method: str, path: str) -> None:
    response = client.request(method, path)

    assert response.status_code >= 400
    assert "detail" not in response.json()


def test_request_id_header_matches_body_and_differs_per_request(client: TestClient) -> None:
    first = client.get("/api/v1/nonexistent")
    second = client.get("/api/v1/nonexistent")

    assert first.headers["x-request-id"] == first.json()["error"]["request_id"]
    assert first.headers["x-request-id"] != second.headers["x-request-id"]


def test_client_supplied_request_id_is_ignored(client: TestClient) -> None:
    response = client.get("/api/v1/nonexistent", headers={"X-Request-ID": "attacker-chosen"})

    assert response.headers["x-request-id"] != "attacker-chosen"
    assert response.json()["error"]["request_id"] != "attacker-chosen"
