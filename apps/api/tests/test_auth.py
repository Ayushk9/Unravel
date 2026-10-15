"""Auth: only a genuine, current Supabase token (or the dev stub) gets in.

Real tokens are signed by Supabase with an ECC P-256 private key. These
tests generate their own key pair, sign tokens with the private half, and
hand the verifier the public half, which is exactly the relationship the
API has with Supabase in production.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Annotated, Any
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.auth import (
    STUB_AUTH_USER_ID,
    STUB_TOKEN,
    CurrentHousehold,
    get_authenticated_user_id,
    get_current_household,
)
from app.core.config import Settings
from app.db.session import get_session
from app.main import API_PREFIX, create_app

SUPABASE_URL = "https://test-project.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"
USER_ID = UUID("01920000-0000-7000-8000-0000000000aa")
HOUSEHOLD_ID = UUID("01920000-0000-7000-8000-0000000000bb")

SIGNING_KEY = ec.generate_private_key(ec.SECP256R1())
ATTACKER_KEY = ec.generate_private_key(ec.SECP256R1())


def _claims(**overrides: Any) -> dict[str, Any]:
    claims = {"sub": str(USER_ID), "aud": "authenticated", "iss": ISSUER, "exp": int(time.time()) + 3600}
    claims.update(overrides)
    return {key: value for key, value in claims.items() if value is not None}


def _token(key: ec.EllipticCurvePrivateKey = SIGNING_KEY, **overrides: Any) -> str:
    return jwt.encode(_claims(**overrides), key, algorithm="ES256")


class _FakeSession:
    """Stands in for the database: answers the one household lookup."""

    def __init__(self, household_id: UUID | None) -> None:
        self._household_id = household_id

    async def scalar(self, statement: Any) -> UUID | None:
        return self._household_id


def _build_app(environment: str, household_id: UUID | None = HOUSEHOLD_ID) -> FastAPI:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://test:test@localhost:5432/unravel_test",
        supabase_url=SUPABASE_URL,
        gemini_api_key="test",
        environment=environment,
    )
    app = create_app(settings)

    # Give the verifier our public key instead of downloading Supabase's.
    public_key = SIGNING_KEY.public_key()
    app.state.token_verifier._jwks_client.get_signing_key_from_jwt = lambda token: SimpleNamespace(key=public_key)

    async def fake_session() -> _FakeSession:
        return _FakeSession(household_id)

    app.dependency_overrides[get_session] = fake_session

    router = APIRouter(prefix="/_test")

    @router.get("/user")
    async def user(user_id: Annotated[UUID, Depends(get_authenticated_user_id)]) -> dict[str, str]:
        return {"user_id": str(user_id)}

    @router.get("/household")
    async def household(current: Annotated[CurrentHousehold, Depends(get_current_household)]) -> dict[str, str]:
        return {"household_id": str(current.household_id)}

    app.include_router(router, prefix=API_PREFIX)
    return app


@pytest.fixture
def prod_client() -> TestClient:
    return TestClient(_build_app("prod"), raise_server_exceptions=False)


def _assert_401(response: Any) -> None:
    assert response.status_code == 401
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "unauthorized"
    assert set(body["error"]) == {"code", "message", "field_errors", "request_id", "retryable"}
    assert response.headers["www-authenticate"] == "Bearer"


def test_missing_authorization_header_is_401(prod_client: TestClient) -> None:
    _assert_401(prod_client.get("/api/v1/_test/user"))


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/v1/household", None),
        ("PATCH", "/api/v1/household", {"city_tier": "metro"}),
        ("PATCH", "/api/v1/policies/01920000-0000-7000-8000-0000000000a1", {"start_date": "2024-03-14"}),
    ],
)
def test_household_and_policy_date_routes_need_a_token(prod_client: TestClient, method: str, path: str, body: Any) -> None:
    _assert_401(prod_client.request(method, path, json=body))


@pytest.mark.parametrize("header", ["Basic dXNlcjpwYXNz", "Bearer", "Bearer    ", "token-without-scheme"])
def test_malformed_authorization_header_is_401(prod_client: TestClient, header: str) -> None:
    _assert_401(prod_client.get("/api/v1/_test/user", headers={"Authorization": header}))


def test_garbage_token_is_401(prod_client: TestClient) -> None:
    _assert_401(prod_client.get("/api/v1/_test/user", headers={"Authorization": "Bearer not.a.jwt"}))


def test_valid_token_returns_its_user_id(prod_client: TestClient) -> None:
    response = prod_client.get("/api/v1/_test/user", headers={"Authorization": f"Bearer {_token()}"})

    assert response.status_code == 200
    assert response.json() == {"user_id": str(USER_ID)}


def test_token_signed_by_another_key_is_401(prod_client: TestClient) -> None:
    forged = _token(key=ATTACKER_KEY)

    _assert_401(prod_client.get("/api/v1/_test/user", headers={"Authorization": f"Bearer {forged}"}))


def test_expired_token_is_401(prod_client: TestClient) -> None:
    expired = _token(exp=int(time.time()) - 60)

    _assert_401(prod_client.get("/api/v1/_test/user", headers={"Authorization": f"Bearer {expired}"}))


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "anon"},  # not a signed-in user's token
        {"iss": "https://someone-else.supabase.co/auth/v1"},  # another project
        {"exp": None},  # never expires
        {"sub": None},  # names no user
        {"sub": "not-a-uuid"},
    ],
)
def test_token_with_wrong_or_missing_claims_is_401(prod_client: TestClient, overrides: dict[str, Any]) -> None:
    token = _token(**overrides)

    _assert_401(prod_client.get("/api/v1/_test/user", headers={"Authorization": f"Bearer {token}"}))


def test_token_using_a_shared_secret_algorithm_is_401(prod_client: TestClient) -> None:
    """A token signed with HS256 must not be accepted just because it is well-formed."""
    hs256 = jwt.encode(_claims(), "a-guessable-shared-secret-of-some-length", algorithm="HS256")

    _assert_401(prod_client.get("/api/v1/_test/user", headers={"Authorization": f"Bearer {hs256}"}))


def test_unsigned_token_is_401(prod_client: TestClient) -> None:
    unsigned = jwt.encode(_claims(), key="", algorithm="none")

    _assert_401(prod_client.get("/api/v1/_test/user", headers={"Authorization": f"Bearer {unsigned}"}))


# --- the dev stub token ---


def test_stub_token_is_accepted_in_dev() -> None:
    client = TestClient(_build_app("dev"))

    response = client.get("/api/v1/_test/user", headers={"Authorization": f"Bearer {STUB_TOKEN}"})

    assert response.status_code == 200
    assert response.json() == {"user_id": str(STUB_AUTH_USER_ID)}


@pytest.mark.parametrize("environment", ["test", "prod"])
def test_stub_token_is_rejected_outside_dev(environment: str) -> None:
    client = TestClient(_build_app(environment), raise_server_exceptions=False)

    _assert_401(client.get("/api/v1/_test/user", headers={"Authorization": f"Bearer {STUB_TOKEN}"}))


def test_real_tokens_still_work_in_dev() -> None:
    client = TestClient(_build_app("dev"))

    response = client.get("/api/v1/_test/user", headers={"Authorization": f"Bearer {_token()}"})

    assert response.json() == {"user_id": str(USER_ID)}


# --- user -> household ---


def test_valid_token_resolves_to_its_household(prod_client: TestClient) -> None:
    response = prod_client.get("/api/v1/_test/household", headers={"Authorization": f"Bearer {_token()}"})

    assert response.status_code == 200
    assert response.json() == {"household_id": str(HOUSEHOLD_ID)}


def test_valid_token_with_no_household_is_403() -> None:
    client = TestClient(_build_app("prod", household_id=None), raise_server_exceptions=False)

    response = client.get("/api/v1/_test/household", headers={"Authorization": f"Bearer {_token()}"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "no_household"


def test_household_route_without_a_token_is_401_before_any_lookup(prod_client: TestClient) -> None:
    _assert_401(prod_client.get("/api/v1/_test/household"))


def test_members_route_requires_a_token(prod_client: TestClient) -> None:
    """The real protected endpoint, not a test route."""
    _assert_401(prod_client.get("/api/v1/members"))


def test_health_needs_no_token(prod_client: TestClient) -> None:
    assert prod_client.get("/api/v1/health").status_code == 200
