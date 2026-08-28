"""Async SQLAlchemy engine and request-session factory."""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings


@lru_cache
def build_async_session_factory() -> async_sessionmaker[AsyncSession]:
    """Build the asyncpg-backed session factory used by FastAPI dependencies."""
    database_url = get_settings().database_url
    if not database_url:
        raise RuntimeError("DATABASE_URL must be configured before creating database sessions.")

    engine = create_async_engine(database_url, pool_pre_ping=True)
    return async_sessionmaker(engine, expire_on_commit=False)


async def session_scope() -> AsyncIterator[AsyncSession]:
    """Yield one transaction-capable AsyncSession for a request."""
    session_factory = build_async_session_factory()
    async with session_factory() as session:
        yield session
