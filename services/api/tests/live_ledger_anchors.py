"""Test real retained anchors using fresh non-clinical operational diagnostics."""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import boto3  # type: ignore[import-untyped]
import structlog
from app.ledger import Head, KmsSigner
from app.ledger_anchors import AnchorStore, create_anchor
from app.ledger_store import LedgerStore
from botocore.exceptions import ClientError  # type: ignore[import-untyped]


def main() -> None:
    structlog.configure(processors=[structlog.processors.JSONRenderer()])
    s3 = boto3.client("s3")
    signer = KmsSigner(boto3.client("kms"), os.environ["LEDGER_SIGNING_KEY_ARN"])
    connection = {
        "resourceArn": os.environ["DATABASE_CLUSTER_ARN"],
        "database": "verimed",
    }
    client = boto3.client("rds-data")
    writer = LedgerStore(
        client,
        dict(connection, secretArn=os.environ["DATABASE_LEDGER_SECRET_ARN"]),
        signer,
        writer=True,
    )
    reader = LedgerStore(
        client,
        dict(connection, secretArn=os.environ["DATABASE_RUNTIME_SECRET_ARN"]),
        signer,
    )
    tenant = uuid4()
    run = str(uuid4())
    for index in range(3):
        writer.append(
            tenant,
            uuid4(),
            "system.ledger_probe",
            {"run": run, "purpose": "retained anchor self-test", "index": index},
        )
    entries, head = reader.read(tenant)
    day = entries[-1].event.created_at.astimezone(UTC).date()
    anchor = create_anchor(entries, tenant, head, day, signer)
    store = AnchorStore(
        s3,
        os.environ["LEDGER_ANCHOR_BUCKET"],
        os.environ["LEDGER_ANCHOR_KEY_ARN"],
        signer,
    )
    reference = store.put(anchor)
    assert store.verify(entries, tenant, head, reference).status == "VERIFIED"
    assert store.put(create_anchor(entries, tenant, head, day, signer)) == reference
    retained = s3.get_object_retention(
        Bucket=reference.bucket,
        Key=reference.key,
        VersionId=reference.version_id,
        ExpectedBucketOwner=store.owner,
    )["Retention"]
    assert retained["Mode"] == "COMPLIANCE"
    assert retained["RetainUntilDate"] > datetime.now(UTC) + timedelta(days=365 * 7 - 1)

    def expect_access_denied(operation: str, **kwargs: object) -> None:
        try:
            getattr(s3, operation)(
                Bucket=reference.bucket,
                Key=reference.key,
                ExpectedBucketOwner=store.owner,
                **kwargs,
            )
        except ClientError as error:
            assert error.response["Error"]["Code"] == "AccessDenied"
        else:
            raise RuntimeError("A protected anchor mutation was allowed")

    expect_access_denied("delete_object", VersionId=reference.version_id)
    expect_access_denied(
        "delete_object"
    )  # Bucket policy prevents hiding the version with a marker.
    expect_access_denied(
        "put_object_retention",
        VersionId=reference.version_id,
        Retention={
            "Mode": "COMPLIANCE",
            "RetainUntilDate": datetime.now(UTC) + timedelta(days=1),
        },
    )
    expect_access_denied(
        "put_object", Body=b"overwrite-probe", ChecksumAlgorithm="SHA256"
    )
    assert store.verify(entries, tenant, head, reference).status == "VERIFIED"
    assert store.verify(entries, uuid4(), head, reference).status == "UNVERIFIED"
    truncated = entries[:-1]
    rewritten_head = Head(seq=truncated[-1].event.seq, hash=truncated[-1].hash)
    assert store.verify(truncated, tenant, rewritten_head, reference).status == "BROKEN"
    writer.append(
        tenant,
        uuid4(),
        "system.ledger_probe",
        {"run": run, "purpose": "unanchored tail self-test"},
    )
    later, later_head = reader.read(tenant)
    assert store.verify(later, tenant, later_head, reference).status == "UNVERIFIED"
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "anchored_events": 3,
        "retained_anchor_objects": 1,
        "diagnostic_events_written": 4,
        "clinical_records_written": 0,
        "retention_mode": retained["Mode"],
        "retain_until": retained["RetainUntilDate"].isoformat(),
        "checks": {
            name: "passed"
            for name in [
                "durable_chain_to_merkle_anchor",
                "kms_signed_manifest",
                "pinned_s3_version_read",
                "conditional_retry_idempotency",
                "sse_kms_and_retention_metadata",
                "calendar_year_retention",
                "version_delete_denial",
                "delete_marker_denial",
                "retention_shortening_denial",
                "unconditional_overwrite_denial",
                "cross_tenant_reference_denial",
                "rewritten_database_head_detection",
                "unanchored_tail_fail_closed",
            ]
        },
        "scheduled_daily_job": "pending",
    }
    Path("docs/ledger-anchor-verification.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    # Keep the version-pinned test receipt out of Git and application logs.
    Path(".phase1-api").mkdir(exist_ok=True)
    Path(".phase1-api/anchor-test-receipt.json").write_text(
        reference.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
