"""Database engine and the per-request session dependency."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def create_engine(database_url: str) -> AsyncEngine:
    """Create the engine. No connection is opened until the first query.

    pool_pre_ping checks a pooled connection is still alive before using it,
    because Supabase closes idle connections. The pool is kept small: the
    free-tier session pooler allows only a limited number of connections.
    """
    return create_async_engine(database_url, pool_pre_ping=True, pool_size=5, max_overflow=0)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False keeps loaded objects readable after commit, which
    # is needed to build the response from them.
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One session per request, closed when the request ends."""
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        yield session
