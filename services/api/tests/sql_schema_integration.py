"""Real PostgreSQL/Alembic clean-install verification for CI; no service doubles."""

import asyncio
import os

from app.schema import NEW_TABLES
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def main() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"], echo=False)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text("""SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public' AND c.relkind='r'""")
            )
            rows = result.mappings().all()
            expected = {table.name for table in NEW_TABLES} | {
                "patients",
                "encounters",
                "ledger_events",
                "ledger_heads",
            }
            if {row["relname"] for row in rows} != expected or not all(
                row["relrowsecurity"] and row["relforcerowsecurity"] for row in rows
            ):
                raise RuntimeError("Clean-install clinical RLS verification failed")
            head = await connection.scalar(
                text("SELECT version_num FROM platform_meta.alembic_version")
            )
            history = await connection.scalar(
                text("SELECT count(*) FROM platform_meta.applied_revisions")
            )
            if head != "003_platform" or history != 3:
                raise RuntimeError(
                    "Clean-install migration history verification failed"
                )
            print(
                "Real PostgreSQL clean install verified: 26 forced-RLS clinical tables, 3 checksum-recorded revisions."
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
