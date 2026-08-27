"""Alembic environment configured for SQLAlchemy's async engine."""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings


config = context.config
target_metadata = None


def _database_url() -> str:
    database_url = get_settings().database_url
    if not database_url:
        raise RuntimeError("DATABASE_URL must be set before running Alembic.")
    return database_url


def run_migrations_offline() -> None:
    """Generate SQL without opening an async database connection."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations using Alembic's synchronous bridge connection."""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Open an asyncpg-backed engine and execute the migration chain."""
    config.set_main_option("sqlalchemy.url", _database_url())
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
