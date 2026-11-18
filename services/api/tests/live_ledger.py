"""Exercise real KMS with ephemeral diagnostic events; never writes product data."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import boto3  # type: ignore[import-untyped]
import structlog
from app.ledger import GENESIS, Head, KmsSigner, LedgerEvent, sign_event, verify_chain


def main() -> None:
    structlog.configure(processors=[structlog.processors.JSONRenderer()])
    tenant = UUID(os.environ["TENANT_ID"])
    signer = KmsSigner(boto3.client("kms"), os.environ["LEDGER_SIGNING_KEY_ARN"])
    head = Head(seq=0, hash=GENESIS)
    entries = []
    for seq in range(1, 4):
        event = LedgerEvent(
            tenant_id=tenant,
            seq=seq,
            type="system.ledger_probe",
            created_at=datetime.now(UTC),
            payload={"nonce": str(uuid4()), "purpose": "cryptographic self-test"},
        )
        entry = sign_event(event, head, signer)
        entries.append(entry)
        head = Head(seq=seq, hash=entry.hash)
    verified = verify_chain(entries, tenant, signer, head)
    truncated = verify_chain(entries[:-1], tenant, signer, head)
    wrong_tenant = verify_chain(entries, uuid4(), signer, head)
    bad_signature = entries[1].model_copy(update={"signature": entries[0].signature})
    invalid_signature = verify_chain(
        [entries[0], bad_signature, entries[2]], tenant, signer, head
    )
    entries[1].event.payload["purpose"] = "changed after signing"
    tampered = verify_chain(entries, tenant, signer, head)
    checks = {
        "real_kms_chain": verified.status,
        "truncated_chain": truncated.status,
        "wrong_tenant": wrong_tenant.status,
        "invalid_signature": invalid_signature.status,
        "tampered_payload": tampered.status,
    }
    assert checks == {
        "real_kms_chain": "VERIFIED",
        "truncated_chain": "BROKEN",
        "wrong_tenant": "BROKEN",
        "invalid_signature": "BROKEN",
        "tampered_payload": "BROKEN",
    }
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "checks": checks,
        "signed_events": 3,
        "product_records_written": 0,
        "scope": "Cryptographic primitives only; persistence, Object Lock anchors, and sign-off remain pending",
    }
    Path("docs/ledger-verification.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
