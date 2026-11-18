"""Unit-only S3/signing doubles for retained checkpoint verification."""

import base64
import hashlib
import hmac
import io
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from app.ledger import GENESIS, Head, LedgerEvent, SignedEntry, sign_event
from app.ledger_anchors import (
    DOMAIN,
    AnchorReference,
    AnchorStore,
    SignedAnchor,
    canonical,
    create_anchor,
    merkle_root,
)
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

TENANT = UUID(int=1)
KEY = "arn:aws:kms:us-east-1:000000000000:key/00000000-0000-0000-0000-000000000001"
DAY = date(2026, 1, 1)


class Signer:
    key_id = KEY

    def sign(self, digest: bytes) -> bytes:
        return hmac.digest(b"unit-only-anchor-key", digest, "sha256")

    def verify(self, digest: bytes, signature: bytes) -> bool:
        return hmac.compare_digest(self.sign(digest), signature)


class S3:
    def __init__(self) -> None:
        self.body = b""
        self.mode = "COMPLIANCE"
        self.retained_days = 2560
        self.requests: list[dict[str, Any]] = []
        self.last_modified = datetime(2026, 1, 1, tzinfo=UTC)

    def put_object(self, **kwargs: Any) -> dict[str, str]:
        self.requests.append(kwargs)
        assert kwargs["IfNoneMatch"] == "*"
        assert (
            kwargs["ChecksumSHA256"]
            == base64.b64encode(hashlib.sha256(kwargs["Body"]).digest()).decode()
        )
        if self.body:
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        self.body = kwargs["Body"]
        return {"VersionId": "unit-version"}

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self.requests.append(kwargs)
        return {
            "Body": io.BytesIO(self.body),
            "VersionId": "unit-version",
            "LastModified": self.last_modified,
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": KEY,
        }

    def get_object_retention(self, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["VersionId"] == "unit-version"
        return {
            "Retention": {
                "Mode": self.mode,
                "RetainUntilDate": self.last_modified
                + timedelta(days=self.retained_days),
            }
        }


def chain(count: int = 3) -> tuple[list[SignedEntry], Head]:
    entries = []
    head = Head(seq=0, hash=GENESIS)
    for seq in range(1, count + 1):
        event = LedgerEvent(
            tenant_id=TENANT,
            seq=seq,
            type="unit.probe",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            payload={"number": seq},
        )
        entry = sign_event(event, head, Signer())
        entries.append(entry)
        head = Head(seq=seq, hash=entry.hash)
    return entries, head


def setup() -> tuple[AnchorStore, S3, list[SignedEntry], Head, AnchorReference]:
    s3 = S3()
    store = AnchorStore(s3, "unit-bucket", KEY, Signer())
    entries, head = chain()
    reference = store.put(create_anchor(entries, TENANT, head, DAY, Signer()))
    return store, s3, entries, head, reference


def test_merkle_domain_separation_and_odd_leaf_duplication() -> None:
    hashes = ["01" * 32, "02" * 32, "03" * 32]
    leaves = [
        hashlib.sha256(b"\x00" + bytes.fromhex(value)).digest() for value in hashes
    ]
    left = hashlib.sha256(b"\x01" + leaves[0] + leaves[1]).digest()
    right = hashlib.sha256(b"\x01" + leaves[2] + leaves[2]).digest()
    assert merkle_root(hashes) == hashlib.sha256(b"\x01" + left + right).hexdigest()
    with pytest.raises(ValueError, match="empty day"):
        merkle_root([])


def test_pinned_object_version_verifies_and_retry_is_idempotent() -> None:
    store, s3, entries, head, reference = setup()
    assert store.verify(entries, TENANT, head, reference).status == "VERIFIED"
    # A second ECDSA signature can differ; idempotency is by signed checkpoint content.
    assert store.put(create_anchor(entries, TENANT, head, DAY, Signer())) == reference
    assert any(call.get("VersionId") == reference.version_id for call in s3.requests)


@pytest.mark.parametrize(
    "change", ["tenant", "bucket", "version", "body", "mode", "retention", "calendar"]
)
def test_wrong_tenant_reference_or_missing_protection_fails_closed(change: str) -> None:
    store, s3, entries, head, reference = setup()
    tenant = TENANT
    if change == "tenant":
        tenant = UUID(int=2)
    elif change == "bucket":
        reference = reference.model_copy(update={"bucket": "other-bucket"})
    elif change == "version":
        reference = reference.model_copy(update={"version_id": "null"})
    elif change == "body":
        s3.body += b"changed"
    elif change == "mode":
        s3.mode = "GOVERNANCE"
    elif change == "retention":
        s3.retained_days = 1
    elif change == "calendar":
        s3.retained_days = 365 * 7
    assert store.verify(entries, tenant, head, reference).status == "UNVERIFIED"


def test_database_tail_rewrite_is_detected_by_independent_anchor() -> None:
    store, _, entries, _, reference = setup()
    truncated = entries[:-1]
    rewritten_database_head = Head(seq=2, hash=truncated[-1].hash)
    assert (
        store.verify(truncated, TENANT, rewritten_database_head, reference).status
        == "BROKEN"
    )


def test_newer_entries_are_not_claimed_as_anchored() -> None:
    store, _, _, _, reference = setup()
    longer, head = chain(4)
    assert store.verify(longer, TENANT, head, reference).status == "UNVERIFIED"


def test_valid_signature_does_not_override_wrong_merkle_root() -> None:
    s3 = S3()
    store = AnchorStore(s3, "unit-bucket", KEY, Signer())
    entries, head = chain()
    anchor = create_anchor(entries, TENANT, head, DAY, Signer())
    wrong_manifest = anchor.manifest.model_copy(update={"merkle_root": "0" * 64})
    signed_wrong = SignedAnchor(
        manifest=wrong_manifest,
        key_id=KEY,
        signature=base64.b64encode(
            Signer().sign(hashlib.sha256(DOMAIN + canonical(wrong_manifest)).digest())
        ).decode(),
    )
    reference = store.put(signed_wrong)
    assert store.verify(entries, TENANT, head, reference).status == "BROKEN"


def test_cannot_anchor_empty_day_or_invalid_chain() -> None:
    entries, head = chain()
    with pytest.raises(ValueError, match="empty day"):
        create_anchor(entries, TENANT, head, date(2025, 12, 31), Signer())
    entries[0].event.payload["number"] = 999
    with pytest.raises(ValueError, match="complete verified chain"):
        create_anchor(entries, TENANT, head, DAY, Signer())


def test_storage_outage_never_returns_verified(monkeypatch: pytest.MonkeyPatch) -> None:
    store, s3, entries, head, reference = setup()

    def unavailable(**kwargs: Any) -> dict[str, Any]:
        raise TimeoutError("unit storage outage")

    monkeypatch.setattr(s3, "get_object", unavailable)
    assert store.verify(entries, TENANT, head, reference).status == "UNVERIFIED"


def test_retention_timestamp_rounding_tolerance_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, s3, entries, head, reference = setup()
    deadline = s3.last_modified.replace(year=s3.last_modified.year + 7)

    def within_rounding(**kwargs: Any) -> dict[str, Any]:
        return {
            "Retention": {
                "Mode": "COMPLIANCE",
                "RetainUntilDate": deadline - timedelta(milliseconds=500),
            }
        }

    monkeypatch.setattr(s3, "get_object_retention", within_rounding)
    assert store.verify(entries, TENANT, head, reference).status == "VERIFIED"

    def too_short(**kwargs: Any) -> dict[str, Any]:
        return {
            "Retention": {
                "Mode": "COMPLIANCE",
                "RetainUntilDate": deadline - timedelta(seconds=2),
            }
        }

    monkeypatch.setattr(s3, "get_object_retention", too_short)
    assert store.verify(entries, TENANT, head, reference).status == "UNVERIFIED"
