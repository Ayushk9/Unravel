"""Who is making this request, and which household do they belong to?

Identity comes only from the `Authorization: Bearer <token>` header
(D-09, D-10). No endpoint accepts a household id as a parameter: if it did,
anyone could ask for another household's medical documents by changing a
number in the URL.

The token is a Supabase Auth JWT. This project signs tokens with an ECC
P-256 private key (algorithm ES256) that only Supabase holds. The API
downloads the matching PUBLIC keys from the project's JWKS address and uses
them to check the signature. The API therefore stores no secret that could
be used to forge a token.

Two steps, as two FastAPI dependencies:

    get_authenticated_user_id   token -> Supabase user id      (no database)
    get_current_household       user id -> household           (one query)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.db.models import Household
from app.db.session import get_session

# The web app sends this fixed token until real sign-in exists
# (apps/web/src/api/client.ts). It is accepted only when ENVIRONMENT=dev and
# maps to the household created by scripts/seed.py.
STUB_TOKEN = "mock-household-token"
STUB_AUTH_USER_ID = UUID("01920000-0000-7000-8000-00000000a001")

# Supabase sets the audience of a signed-in user's token to this value.
_EXPECTED_AUDIENCE = "authenticated"


class TokenVerifier:
    """Checks a Supabase JWT and returns the user id it was issued to."""

    def __init__(self, supabase_url: str) -> None:
        base_url = supabase_url.rstrip("/")
        self._issuer = f"{base_url}/auth/v1"
        # Downloads the public keys on first use and caches them, so most
        # requests make no network call.
        self._jwks_client = jwt.PyJWKClient(f"{base_url}/auth/v1/.well-known/jwks.json", cache_keys=True)

    def verify(self, token: str) -> UUID:
        """Return the token's user id, or raise ApiError.

        This does blocking network I/O when the key cache is cold, so async
        code calls it through run_in_threadpool.
        """
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                # Only ES256 is accepted. Listing the algorithm explicitly is
                # what stops a forged token that claims a weaker algorithm.
                algorithms=["ES256"],
                audience=_EXPECTED_AUDIENCE,
                issuer=self._issuer,
                options={"require": ["exp", "sub"]},
            )
            return UUID(claims["sub"])
        except jwt.PyJWKClientConnectionError as exc:
            # We could not reach Supabase to fetch the keys. That is our
            # problem, not a bad token, so the client is told to retry.
            raise ApiError(
                503, "auth_unavailable", "Sign-in could not be checked right now. Try again.", retryable=True
            ) from exc
        except (jwt.PyJWTError, ValueError) as exc:
            # Bad signature, expired, wrong audience or issuer, missing
            # claims, unknown key, or a `sub` that is not a UUID. The client
            # is not told which: that detail only helps someone forging tokens.
            raise _unauthorized("That sign-in token is not valid.") from exc


def _unauthorized(message: str) -> ApiError:
    return ApiError(401, "unauthorized", message, headers={"WWW-Authenticate": "Bearer"})


def _bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization")
    if header is None:
        raise _unauthorized("Missing bearer token.")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _unauthorized("The Authorization header must be 'Bearer <token>'.")
    return token.strip()


async def get_authenticated_user_id(request: Request) -> UUID:
    """Dependency: the Supabase user id proven by the request's token."""
    token = _bearer_token(request)

    if request.app.state.settings.environment == "dev" and token == STUB_TOKEN:
        return STUB_AUTH_USER_ID

    verifier: TokenVerifier = request.app.state.token_verifier
    return await run_in_threadpool(verifier.verify, token)


@dataclass(frozen=True)
class CurrentHousehold:
    household_id: UUID
    auth_user_id: UUID


async def get_current_household(
    auth_user_id: Annotated[UUID, Depends(get_authenticated_user_id)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CurrentHousehold:
    """Dependency: the household every query in this request is scoped to."""
    household_id = await session.scalar(select(Household.id).where(Household.auth_user_id == auth_user_id))
    if household_id is None:
        # The token is genuine but this user has no household yet.
        raise ApiError(403, "no_household", "This account is not linked to a household.")
    return CurrentHousehold(household_id=household_id, auth_user_id=auth_user_id)
