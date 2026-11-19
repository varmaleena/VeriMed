"""Offline SQL review; online migrations require an explicit private async database URL."""

import asyncio
import os

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine


def migrate(connection: Connection | None = None) -> None:
    if connection is None:
        context.configure(
            dialect_name="postgresql",
            literal_binds=True,
            version_table_schema="platform_meta",
        )
    else:
        context.configure(connection=connection, version_table_schema="platform_meta")
    with context.begin_transaction():
        context.execute("CREATE SCHEMA IF NOT EXISTS platform_meta")
        context.execute("REVOKE ALL ON SCHEMA platform_meta FROM PUBLIC")
        context.run_migrations()


async def online() -> None:
    engine = create_async_engine(
        os.environ["DATABASE_URL"], poolclass=pool.NullPool, echo=False
    )
    async with engine.connect() as connection:
        await connection.run_sync(migrate)
    await engine.dispose()


if context.is_offline_mode():
    migrate()
else:
    asyncio.run(online())
