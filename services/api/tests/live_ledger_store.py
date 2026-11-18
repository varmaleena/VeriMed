"""Verify real ledger persistence/guards using non-clinical diagnostic tenants."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import boto3  # type: ignore[import-untyped]
import structlog
from app.database import begin_transaction
from app.ledger import GENESIS, KmsSigner, verify_chain
from app.ledger_store import IdempotencyConflict, LedgerStore
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]


def main() -> None:
    structlog.configure(processors=[structlog.processors.JSONRenderer()])
    client = boto3.client(
        "rds-data",
        config=Config(connect_timeout=5, read_timeout=25, retries={"max_attempts": 2}),
    )
    signer = KmsSigner(boto3.client("kms"), os.environ["LEDGER_SIGNING_KEY_ARN"])
    common = {"resourceArn": os.environ["DATABASE_CLUSTER_ARN"], "database": "verimed"}
    writer = LedgerStore(
        client,
        dict(common, secretArn=os.environ["DATABASE_LEDGER_SECRET_ARN"]),
        signer,
        writer=True,
    )
    reader = LedgerStore(
        client,
        dict(common, secretArn=os.environ["DATABASE_RUNTIME_SECRET_ARN"]),
        signer,
    )
    tenant_a, tenant_b, tenant_c = uuid4(), uuid4(), uuid4()
    event_ids = [uuid4() for _ in range(3)]
    run = str(uuid4())

    def append(index: int) -> int:
        return writer.append(
            tenant_a,
            event_ids[index],
            "system.ledger_probe",
            {"run": run, "producer": index},
        ).event.seq

    with ThreadPoolExecutor(max_workers=3) as pool:
        sequences = list(pool.map(append, range(3)))
    assert sorted(sequences) == [1, 2, 3]
    entries, head = reader.read(tenant_a)
    assert (
        len(entries) == 3
        and verify_chain(entries, tenant_a, signer, head).status == "VERIFIED"
    )
    replay = writer.append(
        tenant_a, event_ids[0], "system.ledger_probe", {"run": run, "producer": 0}
    )
    assert replay.event.seq == sequences[0]
    try:
        writer.append(
            tenant_a, event_ids[0], "system.ledger_probe", {"run": run, "producer": 999}
        )
    except IdempotencyConflict:
        pass
    else:
        raise RuntimeError("Ledger accepted conflicting idempotency content")
    writer.append(
        tenant_b,
        uuid4(),
        "system.ledger_probe",
        {"run": run, "purpose": "tenant isolation"},
    )
    b_entries, b_head = reader.read(tenant_b)
    assert (
        len(b_entries) == 1
        and verify_chain(b_entries, tenant_b, signer, b_head).status == "VERIFIED"
    )
    with reader.transaction(tenant_a) as transaction:
        count = reader.rows(
            transaction,
            "SELECT count(*) AS n FROM public.ledger_events WHERE tenant_id = CAST(:tenant AS uuid)",
            tenant=str(tenant_b),
        )[0]["n"]
        assert count == 0
        guards = reader.rows(
            transaction,
            "SELECT count(*) AS n FROM pg_class WHERE oid IN ('public.ledger_events'::regclass, 'public.ledger_heads'::regclass) AND relrowsecurity AND relforcerowsecurity",
        )[0]["n"]
        assert guards == 2

    def expect_denial(sql: str, *, admin: bool = False) -> None:
        config = (
            dict(common, secretArn=os.environ["DATABASE_SECRET_ARN"])
            if admin
            else writer.connection
        )
        tx = begin_transaction(client, config)
        try:
            if not admin:
                client.execute_statement(
                    **config,
                    transactionId=tx,
                    sql="SET LOCAL ROLE verimed_ledger_append",
                )
            client.execute_statement(
                **config,
                transactionId=tx,
                sql="SELECT set_config('app.tenant_id', :tenant, true)",
                parameters=[
                    {"name": "tenant", "value": {"stringValue": str(tenant_a)}}
                ],
            )
            try:
                client.execute_statement(**config, transactionId=tx, sql=sql)
            except ClientError as error:
                message = error.response["Error"]["Message"].lower()
                assert "append-only" in message or "permission denied" in message
            else:
                raise RuntimeError("Ledger mutation was permitted")
        finally:
            client.rollback_transaction(
                resourceArn=config["resourceArn"],
                secretArn=config["secretArn"],
                transactionId=tx,
            )

    for sql in (
        "UPDATE public.ledger_events SET type = type",
        "DELETE FROM public.ledger_events",
        "TRUNCATE public.ledger_events",
        "UPDATE public.ledger_heads SET seq = seq",
    ):
        expect_denial(sql)
    expect_denial("UPDATE public.ledger_events SET type = type", admin=True)
    expect_denial("TRUNCATE public.ledger_events", admin=True)
    try:
        with writer.transaction(tenant_a, append=True) as transaction:
            writer.execute(
                transaction,
                """INSERT INTO public.ledger_events (tenant_id, id, seq, version, type, payload, prev_hash, hash, signature, key_id, created_at)
                VALUES (CAST(:tenant AS uuid), CAST(:id AS uuid), 2, 1, 'system.ledger_probe', '{}', :previous, :hash, :signature, :key, now())""",
                tenant=str(tenant_b),
                id=str(uuid4()),
                previous=b_head.hash,
                hash=b_head.hash,
                signature=b_entries[0].signature,
                key=signer.key_id,
            )
    except ClientError as error:
        assert "tenant context mismatch" in error.response["Error"]["Message"].lower()
    else:
        raise RuntimeError("Cross-tenant ledger insert was allowed")
    try:
        reader.append(tenant_a, uuid4(), "system.ledger_probe", {"run": run})
    except ClientError as error:
        assert "permission denied" in error.response["Error"]["Message"].lower()
    else:
        raise RuntimeError("Read-only API login appended to ledger")
    try:
        reader.read(tenant_a, max_events=2)
    except RuntimeError as error:
        assert "read limit exceeded" in str(error)
    else:
        raise RuntimeError("Bounded read returned a misleading partial chain")
    # A real KMS failure must roll back the append. An encryption key cannot sign.
    encryption_key = boto3.client("secretsmanager").describe_secret(
        SecretId=os.environ["DATABASE_LEDGER_SECRET_ARN"]
    )["KmsKeyId"]
    bad_signer = KmsSigner(boto3.client("kms"), encryption_key)
    failed = LedgerStore(client, writer.connection, bad_signer, writer=True)
    try:
        failed.append(tenant_c, uuid4(), "system.ledger_probe", {"run": run})
    except ClientError as error:
        assert error.response["Error"]["Code"] == "InvalidKeyUsageException"
    else:
        raise RuntimeError("Encryption-only KMS key signed an event")
    empty, empty_head = reader.read(tenant_c)
    assert empty == [] and empty_head.seq == 0 and empty_head.hash == GENESIS
    # Verify a stable read snapshot while another transaction appends.
    with reader.transaction(tenant_a) as transaction:
        snapshot_head = reader.head(transaction)
        writer.append(
            tenant_a,
            uuid4(),
            "system.ledger_probe",
            {"run": run, "purpose": "snapshot"},
        )
        assert reader.head(transaction) == snapshot_head
        assert (
            reader.rows(transaction, "SELECT count(*) AS n FROM public.ledger_events")[
                0
            ]["n"]
            == 3
        )
    entries, head = reader.read(tenant_a)
    assert (
        len(entries) == 4
        and verify_chain(entries, tenant_a, signer, head).status == "VERIFIED"
    )
    entries[1].event.payload["purpose"] = "altered after read"
    assert verify_chain(entries, tenant_a, signer, head).status == "BROKEN"
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "concurrent_appends": 3,
        "durable_diagnostic_events": 5,
        "clinical_records_written": 0,
        "checks": {
            name: "passed"
            for name in [
                "concurrent_sequence",
                "kms_signatures_after_read",
                "idempotent_retry",
                "idempotency_conflict",
                "forced_rls",
                "cross_tenant_read_denial",
                "cross_tenant_insert_denial",
                "writer_update_delete_truncate_denial",
                "head_update_denial",
                "owner_mutation_trigger",
                "reader_write_denial",
                "bounded_read",
                "real_kms_failure_rollback",
                "repeatable_read_snapshot",
                "tamper_detection",
            ]
        },
        "independent_object_lock_anchors": "pending",
    }
    Path("docs/ledger-storage-verification.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
