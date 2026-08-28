"""Authenticated household identity and ownership-scoped query helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeVar
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.models import Household
from app.db.session import build_async_session_factory


_bearer_scheme = HTTPBearer(auto_error=False)
ModelT = TypeVar("ModelT")


@dataclass(frozen=True, slots=True)
class CurrentHousehold:
    """Verified request identity; household ownership is never client input."""

    household_id: UUID
    subject: str | None
    is_development_stub: bool = False


def _unauthorized(message: str = "Invalid or missing bearer token.") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=message,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _household_id_from_claims(claims: dict[str, Any]) -> UUID:
    """Read the household claim injected into a Supabase access token."""
    raw_household_id = claims.get("household_id")
    if raw_household_id is None:
        app_metadata = claims.get("app_metadata")
        if isinstance(app_metadata, dict):
            raw_household_id = app_metadata.get("household_id")
    if not isinstance(raw_household_id, str):
        raise _unauthorized("Bearer token has no household identity.")
    try:
        return UUID(raw_household_id)
    except ValueError as exc:
        raise _unauthorized("Bearer token has an invalid household identity.") from exc


async def get_current_household(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> CurrentHousehold:
    """Verify a Supabase access token and derive the caller's household.

    In ``ENVIRONMENT=dev`` only, the fixed frontend development token is
    accepted without JWT verification and resolves to the seeded dev household.
    Every other token must be a non-expired HS256 JWT signed by the configured
    Supabase JWT secret.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized("Missing bearer token.")

    token = credentials.credentials
    if settings.environment.casefold() == "dev" and token == settings.dev_stub_token:
        return CurrentHousehold(
            household_id=settings.dev_stub_household_id,
            subject="development-stub",
            is_development_stub=True,
        )

    if not settings.supabase_jwt_secret:
        raise RuntimeError("SUPABASE_JWT_SECRET must be configured for JWT authentication.")

    try:
        claims = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience=settings.supabase_jwt_audience,
        )
    except JWTError as exc:
        raise _unauthorized() from exc

    return CurrentHousehold(
        household_id=_household_id_from_claims(claims),
        subject=claims.get("sub") if isinstance(claims.get("sub"), str) else None,
    )


async def seed_development_household() -> None:
    """Create the fixed dev household once, without adding demo data in production."""
    settings = get_settings()
    if settings.environment.casefold() != "dev" or not settings.database_url:
        return

    session_factory = build_async_session_factory()
    async with session_factory() as session:
        if await session.get(Household, settings.dev_stub_household_id) is None:
            session.add(Household(id=settings.dev_stub_household_id))
            await session.commit()


async def get_household_owned_or_404(
    session: AsyncSession,
    model: type[ModelT],
    resource_id: UUID,
    current: CurrentHousehold,
) -> ModelT:
    """Fetch a household-owned resource, concealing cross-household existence.

    Use this for tables with direct ``id`` and ``household_id`` columns, such as
    ``Document``, ``Member``, and ``Policy``. Other resources should be joined
    through their owning policy/document and filtered with the same predicate.
    """
    statement = select(model).where(  # type: ignore[arg-type, union-attr]
        model.id == resource_id,  # type: ignore[attr-defined]
        model.household_id == current.household_id,  # type: ignore[attr-defined]
    )
    resource = await session.scalar(statement)
    if resource is None:
        # Deliberately identical for "does not exist" and "belongs elsewhere".
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found.")
    return resource
