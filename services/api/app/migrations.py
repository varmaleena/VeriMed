"""Apply checksum-verified revisions over Data API, atomically and without SQL logging."""

import json
import time
from typing import Any

import structlog
from opentelemetry import trace

from app.database import begin_transaction
from app.migration_source import METADATA, REVISIONS, checksum, statements


class MigrationFailure(RuntimeError):
    pass


def _apply(client: Any, connection: dict[str, str]) -> list[str]:
    transaction = begin_transaction(client, connection)
    finish = {key: connection[key] for key in ("resourceArn", "secretArn")}
    finish["transactionId"] = transaction
    revision = "metadata"
    position = 0
    applied: list[str] = []

    def execute(sql: str, parameters: list[dict[str, Any]] | None = None) -> Any:
        return client.execute_statement(
            **connection,
            transactionId=transaction,
            sql=sql,
            parameters=parameters or [],
            formatRecordsAs="JSON",
        )

    try:
        execute("SELECT pg_advisory_xact_lock(44801753)")
        for sql in METADATA:
            execute(sql)
        rows = json.loads(
            execute("SELECT version_num FROM platform_meta.alembic_version")[
                "formattedRecords"
            ]
        )
        if len(rows) > 1:
            raise MigrationFailure("Multiple migration heads require operator review")
        head = rows[0]["version_num"] if rows else None
        history = json.loads(
            execute("SELECT revision,sha256 FROM platform_meta.applied_revisions")[
                "formattedRecords"
            ]
        )
        recorded = {row["revision"]: row["sha256"] for row in history}
        if head not in (None, *REVISIONS) or any(
            key not in REVISIONS for key in recorded
        ):
            raise MigrationFailure(
                "Unknown migration history; use the matching deployment revision"
            )
        for revision in REVISIONS:
            digest = checksum(revision)
            if revision in recorded:
                if recorded[revision] != digest:
                    raise MigrationFailure("Applied migration checksum mismatch")
                continue
            expected_previous = (
                None
                if revision == REVISIONS[0]
                else REVISIONS[REVISIONS.index(revision) - 1]
            )
            if head != expected_previous:
                raise MigrationFailure(
                    "Migration history is incomplete or inconsistent"
                )
            for position, sql in enumerate(statements(revision + ".sql"), start=1):
                execute(sql)
            execute(
                "INSERT INTO platform_meta.applied_revisions(revision,sha256) VALUES (:revision,:digest)",
                [
                    {"name": "revision", "value": {"stringValue": revision}},
                    {"name": "digest", "value": {"stringValue": digest}},
                ],
            )
            execute("DELETE FROM platform_meta.alembic_version")
            execute(
                "INSERT INTO platform_meta.alembic_version(version_num) VALUES (:revision)",
                [{"name": "revision", "value": {"stringValue": revision}}],
            )
            head = revision
            applied.append(revision)
        if head != REVISIONS[-1]:
            raise MigrationFailure("Migration head does not match this deployment")
        client.commit_transaction(**finish)
        return applied
    except Exception:  # noqa: BLE001 -- Never expose SQL/provider error bodies, credentials, or tenant records.
        try:
            client.rollback_transaction(**finish)
        except Exception:  # noqa: BLE001 -- Preserve the redacted migration failure if rollback also fails.
            structlog.get_logger().error("migration_rollback_unconfirmed")
        raise MigrationFailure(
            f"Platform migration failed at {revision} statement {position}; transaction rolled back or closed"
        ) from None


def apply(client: Any, connection: dict[str, str]) -> list[str]:
    logger = structlog.get_logger()
    with trace.get_tracer("verimed.migrations").start_as_current_span(
        "platform.schema.migrate", record_exception=False, set_status_on_exception=False
    ):
        try:
            result = _apply(client, connection)
            failed = 0
        except MigrationFailure:
            logger.error("migration_failed", outcome="FAILED")
            raise
        except Exception:  # noqa: BLE001 -- Only emit redacted operational metadata.
            logger.error("migration_failed", outcome="FAILED")
            raise MigrationFailure(
                "Platform migration failed; inspect revision/checksum state and connectivity"
            ) from None
        logger.info(
            "migration_complete",
            revisions=result,
            _aws={
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": "VeriMed/Platform",
                        "Dimensions": [[]],
                        "Metrics": [{"Name": "SchemaMigrations", "Unit": "Count"}],
                    }
                ],
            },
            SchemaMigrations=1,
            failures=failed,
        )
        return result
