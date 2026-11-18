"""Tenant-scoped transactional ledger append/read adapter for Aurora Data API."""

import base64
import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import structlog
from opentelemetry import trace
from pydantic import JsonValue

from app.database import begin_transaction
from app.ledger import GENESIS, DigestSigner, Head, LedgerEvent, SignedEntry, sign_event

tracer = trace.get_tracer("verimed.ledger.store")
logger = structlog.get_logger()

ENTRY_COLUMNS = """
jsonb_build_object(
 'event', jsonb_build_object('version', version, 'tenant_id', tenant_id::text,
   'seq', seq, 'encounter_id', encounter_id::text, 'type', type, 'payload', payload,
   'created_at', to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')),
 'prev_hash', prev_hash, 'hash', hash, 'signature', signature, 'key_id', key_id,
 'algorithm', 'ECDSA_SHA_256')::text AS entry
"""


class IdempotencyConflict(ValueError):
    """An existing event identifier was reused with different content."""


class LedgerStore:
    def __init__(
        self,
        client: Any,
        connection: dict[str, str],
        signer: DigestSigner,
        *,
        writer: bool = False,
    ) -> None:
        self.client = client
        self.connection = dict(connection)
        self.signer = signer
        self.writer = writer

    def execute(
        self, transaction: str, sql: str, **parameters: str | int
    ) -> dict[str, Any]:
        values = [
            {
                "name": name,
                "value": {"longValue": value}
                if isinstance(value, int)
                else {"stringValue": value},
            }
            for name, value in parameters.items()
        ]
        return cast(
            dict[str, Any],
            self.client.execute_statement(
                **self.connection,
                transactionId=transaction,
                sql=sql,
                parameters=values,
                formatRecordsAs="JSON",
            ),
        )

    @contextmanager
    def transaction(self, tenant_id: UUID, *, append: bool = False) -> Iterator[str]:
        transaction = begin_transaction(self.client, self.connection)
        finish = {
            "resourceArn": self.connection["resourceArn"],
            "secretArn": self.connection["secretArn"],
            "transactionId": transaction,
        }
        try:
            if not append:
                self.execute(
                    transaction,
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY",
                )
            self.execute(
                transaction,
                "SET LOCAL ROLE "
                + ("verimed_ledger_append" if append or self.writer else "verimed_api"),
            )
            self.execute(transaction, "SET LOCAL lock_timeout = '5s'")
            self.execute(transaction, "SET LOCAL statement_timeout = '15s'")
            self.execute(
                transaction,
                "SELECT set_config('app.tenant_id', :tenant, true)",
                tenant=str(tenant_id),
            )
            yield transaction
            self.client.commit_transaction(**finish)
        except Exception:
            try:
                self.client.rollback_transaction(**finish)
            except Exception as rollback_error:  # noqa: BLE001 -- Preserve the original failure, including an uncertain commit outcome.
                logger.error(
                    "ledger_rollback_failed", error_type=type(rollback_error).__name__
                )
            raise

    def rows(
        self, transaction: str, sql: str, **parameters: str | int
    ) -> list[dict[str, Any]]:
        return cast(
            list[dict[str, Any]],
            json.loads(
                self.execute(transaction, sql, **parameters).get(
                    "formattedRecords", "[]"
                )
            ),
        )

    def head(self, transaction: str) -> Head:
        rows = self.rows(transaction, "SELECT seq, hash FROM public.ledger_heads")
        if len(rows) > 1:
            raise RuntimeError("Ledger tenant isolation failed")
        return Head.model_validate(rows[0]) if rows else Head(seq=0, hash=GENESIS)

    def validate_entry(self, entry: SignedEntry) -> None:
        digest = hashlib.sha256(
            bytes.fromhex(entry.prev_hash) + entry.event.canonical()
        ).digest()
        if (
            entry.key_id != self.signer.key_id
            or entry.hash != digest.hex()
            or not self.signer.verify(
                digest, base64.b64decode(entry.signature, validate=True)
            )
        ):
            raise RuntimeError("Stored ledger entry could not be verified")

    def append(
        self,
        tenant_id: UUID,
        event_id: UUID,
        event_type: str,
        payload: dict[str, JsonValue],
        encounter_id: UUID | None = None,
    ) -> SignedEntry:
        candidate = LedgerEvent(
            tenant_id=tenant_id,
            seq=1,
            type=event_type,
            payload=payload,
            encounter_id=encounter_id,
            created_at=datetime.now(UTC),
        )
        candidate.canonical()  # Validate size and representation before acquiring a DB lock.
        replay = False
        with (
            tracer.start_as_current_span(
                "ledger.store.append",
                record_exception=False,
                set_status_on_exception=False,
            ),
            self.transaction(tenant_id, append=True) as transaction,
        ):
            self.execute(
                transaction,
                "SELECT pg_advisory_xact_lock(hashtextextended(:tenant, 44801754))",
                tenant=str(tenant_id),
            )
            existing = self.rows(
                transaction,
                f"SELECT {ENTRY_COLUMNS} FROM public.ledger_events WHERE id = CAST(:id AS uuid)",
                id=str(event_id),
            )
            if existing:
                entry = SignedEntry.model_validate_json(existing[0]["entry"])
                if (
                    entry.event.type != candidate.type
                    or entry.event.payload != candidate.payload
                    or entry.event.encounter_id != candidate.encounter_id
                ):
                    raise IdempotencyConflict(
                        "Event identifier already belongs to different content"
                    )
                self.validate_entry(entry)
                replay = True
            else:
                previous = self.head(transaction)
                if previous.seq:
                    last = self.rows(
                        transaction,
                        f"SELECT {ENTRY_COLUMNS} FROM public.ledger_events WHERE seq = :seq",
                        seq=previous.seq,
                    )
                    if len(last) != 1:
                        raise RuntimeError("Stored ledger head has no matching event")
                    last_entry = SignedEntry.model_validate_json(last[0]["entry"])
                    if last_entry.hash != previous.hash:
                        raise RuntimeError(
                            "Stored ledger head does not match its event"
                        )
                    self.validate_entry(last_entry)
                entry = sign_event(
                    candidate.model_copy(update={"seq": previous.seq + 1}),
                    previous,
                    self.signer,
                )
                self.execute(
                    transaction,
                    """
                  INSERT INTO public.ledger_events (tenant_id, id, seq, encounter_id, version, type,
                    payload, prev_hash, hash, signature, key_id, created_at)
                  SELECT (data->'event'->>'tenant_id')::uuid, CAST(:id AS uuid),
                    (data->'event'->>'seq')::bigint, (data->'event'->>'encounter_id')::uuid,
                    (data->'event'->>'version')::integer, data->'event'->>'type', data->'event'->'payload',
                    data->>'prev_hash', data->>'hash', data->>'signature', data->>'key_id',
                    (data->'event'->>'created_at')::timestamptz
                  FROM (SELECT CAST(:entry AS jsonb) AS data) AS input
                """,
                    id=str(event_id),
                    entry=entry.model_dump_json(),
                )
        logger.info(
            "ledger_append",
            outcome="replayed" if replay else "committed",
            _aws={
                "Timestamp": int(datetime.now(UTC).timestamp() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": "VeriMed",
                        "Dimensions": [[]],
                        "Metrics": [{"Name": "LedgerAppends", "Unit": "Count"}],
                    }
                ],
            },
            LedgerAppends=int(not replay),
        )
        return entry

    def read(
        self, tenant_id: UUID, max_events: int = 10000
    ) -> tuple[list[SignedEntry], Head]:
        if not 1 <= max_events <= 10000:
            raise ValueError("Ledger read bound must be between 1 and 10000")
        with (
            tracer.start_as_current_span(
                "ledger.store.read",
                record_exception=False,
                set_status_on_exception=False,
            ),
            self.transaction(tenant_id) as transaction,
        ):
            head = self.head(transaction)
            entries: list[SignedEntry] = []
            after = 0
            while True:
                rows = self.rows(
                    transaction,
                    f"SELECT {ENTRY_COLUMNS} FROM public.ledger_events WHERE seq > :after ORDER BY seq LIMIT :limit",
                    after=after,
                    limit=min(20, max_events + 1 - len(entries)),
                )
                if not rows:
                    break
                entries.extend(
                    SignedEntry.model_validate_json(row["entry"]) for row in rows
                )
                if len(entries) > max_events:
                    raise RuntimeError("Ledger verification read limit exceeded")
                after = entries[-1].event.seq
            return entries, head
