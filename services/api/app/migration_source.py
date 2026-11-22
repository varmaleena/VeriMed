"""Versioned SQL sources and common metadata shared by Alembic and Data API."""

import hashlib
from pathlib import Path

REVISIONS = ("001_worklist", "002_ledger", "003_platform")
ROOT = Path(__file__).resolve().parents[1] / "migrations"
METADATA = [
    "CREATE SCHEMA IF NOT EXISTS platform_meta",
    "REVOKE ALL ON SCHEMA platform_meta FROM PUBLIC",
    """CREATE TABLE IF NOT EXISTS platform_meta.alembic_version (
        version_num varchar(32) PRIMARY KEY)""",
    """CREATE TABLE IF NOT EXISTS platform_meta.applied_revisions (
        revision varchar(32) PRIMARY KEY, sha256 varchar(64) NOT NULL,
        applied_at timestamptz NOT NULL DEFAULT now())""",
    "REVOKE ALL ON ALL TABLES IN SCHEMA platform_meta FROM PUBLIC",
]


def checksum(revision: str) -> str:
    if revision not in REVISIONS:
        raise ValueError("Unknown migration revision")
    return hashlib.sha256(
        (ROOT / (revision + ".sql")).read_text(encoding="utf-8").encode()
    ).hexdigest()


def statements(name: str) -> list[str]:
    if name.removesuffix(".sql") not in REVISIONS:
        raise ValueError("Unknown migration source")
    source = (ROOT / name).read_text(encoding="utf-8")
    if name == "001_worklist.sql":
        prefix, body, suffix = source.split("$$")
        result = [
            item.strip()
            for item in prefix.rsplit("DO", 1)[0].split(";")
            if item.strip()
        ]
        result.append("DO $$" + body + "$$")
        result.extend(item.strip() for item in suffix.split(";") if item.strip())
        return result
    return [item.strip() for item in source.split("-- statement-break") if item.strip()]


def alembic_upgrade(revision: str) -> None:
    from alembic import op

    digest = checksum(revision)
    for statement in METADATA:
        op.execute(statement)
    # checksum() accepts only REVISIONS and produces a hex digest; this offline DDL has no external input.
    # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query, python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
    op.execute(f"""DO $$ BEGIN
IF EXISTS (SELECT 1 FROM platform_meta.applied_revisions
           WHERE revision='{revision}' AND sha256<>'{digest}') THEN
 RAISE EXCEPTION 'Applied migration checksum mismatch';
END IF;
END $$""")
    for statement in statements(revision + ".sql"):
        op.execute(statement)
    # Same finite revision allowlist and hex digest as above; Alembic offline SQL must contain literals.
    # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query, python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
    op.execute(f"""INSERT INTO platform_meta.applied_revisions(revision,sha256)
VALUES ('{revision}','{digest}') ON CONFLICT (revision) DO NOTHING""")
