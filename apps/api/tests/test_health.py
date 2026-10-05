from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient


def test_health_is_public_and_returns_ok(client: TestClient) -> None:
    response = client.get("/api/v1/health")  # no Authorization header (D-24)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_successful_responses_also_carry_a_request_id(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert UUID(response.headers["x-request-id"]).version == 7
