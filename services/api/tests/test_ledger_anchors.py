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
        self.key = kwargs["Key"]
        return {"VersionId": "unit-version"}

    def list_object_versions(self, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["Prefix"] == f"anchors/{TENANT}/"
        return {
            "IsTruncated": False,
            "Versions": [
                {
                    "Key": self.key,
                    "VersionId": "unit-version",
                    "LastModified": self.last_modified,
                }
            ]
            if self.body
            else [],
        }

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


def test_inventory_discovers_pinned_version_and_checks_freshness() -> None:
    from app.ledger_inventory import CheckpointInventory

    store, _, entries, head, reference = setup()
    inventory = CheckpointInventory(store)
    checkpoint = inventory.latest(TENANT)
    assert checkpoint is not None and checkpoint.reference == reference
    assert (
        inventory.verify_latest(
            entries, TENANT, head, now=datetime(2026, 1, 1, 2, tzinfo=UTC)
        ).status
        == "VERIFIED"
    )
    result = inventory.verify_latest(
        entries, TENANT, head, now=datetime(2026, 1, 3, tzinfo=UTC)
    )
    assert result.status == "UNVERIFIED" and "stale" in result.reason


def test_inventory_pagination_and_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ledger_inventory import CheckpointInventory

    store, s3, _, _, reference = setup()
    calls: list[dict[str, Any]] = []

    def pages(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        if "KeyMarker" not in kwargs:
            return {
                "IsTruncated": True,
                "NextKeyMarker": "page-one",
                "NextVersionIdMarker": "version-one",
            }
        assert kwargs["VersionIdMarker"] == "version-one"
        return {
            "IsTruncated": False,
            "Versions": [
                {
                    "Key": reference.key,
                    "VersionId": reference.version_id,
                    "LastModified": s3.last_modified,
                }
            ],
        }

    monkeypatch.setattr(s3, "list_object_versions", pages)
    assert CheckpointInventory(store).latest(TENANT) is not None
    assert len(calls) == 2
    monkeypatch.setattr(
        s3,
        "list_object_versions",
        lambda **kwargs: {
            "IsTruncated": True,
            "NextKeyMarker": "same",
            "NextVersionIdMarker": "same",
        },
    )
    with pytest.raises(ValueError, match="pagination"):
        CheckpointInventory(store).latest(TENANT)


def test_inventory_does_not_ignore_invalid_or_hidden_checkpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ledger_inventory import CheckpointInventory

    store, s3, entries, head, _ = setup()
    monkeypatch.setattr(
        s3,
        "list_object_versions",
        lambda **kwargs: {"DeleteMarkers": [{"Key": "hidden"}]},
    )
    assert (
        CheckpointInventory(store).verify_latest(entries, TENANT, head).status
        == "UNVERIFIED"
    )
    monkeypatch.setattr(
        s3,
        "list_object_versions",
        lambda **kwargs: {
            "Versions": [
                {
                    "Key": f"anchors/{TENANT}/2026-01-01/999-" + "0" * 64 + ".json",
                    "VersionId": "unit-version",
                    "LastModified": s3.last_modified,
                }
            ]
        },
    )
    assert (
        CheckpointInventory(store).verify_latest(entries, TENANT, head).status
        == "UNVERIFIED"
    )


def test_version_two_seal_refresh_preserves_version_one_encoding() -> None:
    from app.ledger_anchors import anchor_key

    entries, head = chain()
    legacy = create_anchor(entries, TENANT, head, DAY, Signer())
    assert b"sealed_at" not in canonical(legacy)
    sealed = create_anchor(
        entries,
        TENANT,
        head,
        DAY,
        Signer(),
        sealed_at=datetime(2026, 1, 2, 0, 30, tzinfo=UTC),
    )
    refreshed = create_anchor(
        entries,
        TENANT,
        head,
        DAY,
        Signer(),
        sealed_at=datetime(2026, 1, 3, 0, 30, tzinfo=UTC),
    )
    assert sealed.manifest.version == 2
    assert anchor_key(sealed) != anchor_key(refreshed)
    assert SignedAnchor.model_validate_json(canonical(legacy)) == legacy


def test_worker_is_idempotent_within_daily_slot() -> None:
    from typing import cast

    from app.ledger_store import LedgerStore
    from app.ledger_worker import AnchorJob, run

    entries, head = chain()

    class Reader:
        signer = Signer()

        def read(
            self, tenant_id: UUID, max_events: int
        ) -> tuple[list[SignedEntry], Head]:
            assert tenant_id == TENANT and max_events == 200
            return entries, head

    s3 = S3()
    now = datetime(2026, 1, 2, 6, tzinfo=UTC)
    s3.last_modified = now
    store = AnchorStore(s3, "unit-bucket", KEY, Signer())
    assert (
        run(AnchorJob(), TENANT, cast(LedgerStore, Reader()), store, now).status
        == "SEALED"
    )
    assert (
        run(AnchorJob(), TENANT, cast(LedgerStore, Reader()), store, now).status
        == "SEALED"
    )


def test_worker_does_not_reseal_an_empty_database_with_retained_history() -> None:
    from typing import cast

    from app.ledger_store import LedgerStore
    from app.ledger_worker import AnchorJob, run

    store, _, _, _, _ = setup()

    class Reader:
        signer = Signer()

        def read(
            self, tenant_id: UUID, max_events: int
        ) -> tuple[list[SignedEntry], Head]:
            return [], Head(seq=0, hash=GENESIS)

    with pytest.raises(ValueError, match="retained checkpoint history"):
        run(
            AnchorJob(),
            TENANT,
            cast(LedgerStore, Reader()),
            store,
            datetime(2026, 1, 2, tzinfo=UTC),
        )


def test_worker_rejects_tenant_override_before_aws_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import boto3  # type: ignore[import-untyped]
    from app.ledger_worker import handler

    def unexpected_client(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Invalid job reached AWS")

    monkeypatch.setattr(boto3, "client", unexpected_client)
    with pytest.raises(RuntimeError, match="could not complete"):
        handler({"job": "checkpoint", "tenant_id": str(UUID(int=2))}, None)
