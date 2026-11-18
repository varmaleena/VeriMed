"""Test doubles are confined to this unit module."""

import hashlib
import hmac
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import pytest
from app.ledger import (
    GENESIS,
    Head,
    KmsSigner,
    LedgerEvent,
    SignedEntry,
    sign_event,
    verify_chain,
)
from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from pydantic import ValidationError

TENANT = UUID("00000000-0000-0000-0000-000000000001")
KEY = "arn:aws:kms:us-east-1:000000000000:key/00000000-0000-0000-0000-000000000001"


class TestSigner:
    __test__ = False
    key_id = KEY

    def sign(self, digest: bytes) -> bytes:
        return hmac.digest(b"unit-test-only", digest, "sha256")

    def verify(self, digest: bytes, signature: bytes) -> bool:
        return hmac.compare_digest(self.sign(digest), signature)


def chain() -> tuple[list[SignedEntry], Head]:
    entries = []
    head = Head(seq=0, hash=GENESIS)
    for seq in range(1, 4):
        event = LedgerEvent(
            tenant_id=TENANT,
            seq=seq,
            type="unit.probe",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            payload={"n": seq},
        )
        entry = sign_event(event, head, TestSigner())
        entries.append(entry)
        head = Head(seq=seq, hash=entry.hash)
    return entries, head


def test_chain_passes_with_pinned_tenant_key_and_head() -> None:
    entries, head = chain()
    assert verify_chain(entries, TENANT, TestSigner(), head).status == "VERIFIED"


@pytest.mark.parametrize(
    "change",
    [
        "payload",
        "signature",
        "reorder",
        "missing",
        "truncate",
        "tenant",
        "key",
        "prev_hash",
    ],
)
def test_tampering_is_detected(change: str) -> None:
    entries, head = chain()
    if change == "payload":
        entries[1].event.payload["n"] = 999
    elif change == "signature":
        entries[1] = entries[1].model_copy(update={"signature": "AAAA"})
    elif change == "reorder":
        entries[0], entries[1] = entries[1], entries[0]
    elif change == "missing":
        del entries[1]
    elif change == "truncate":
        entries.pop()
    elif change == "tenant":
        return_result = verify_chain(entries, UUID(int=2), TestSigner(), head)
        assert return_result.status == "BROKEN"
        return
    elif change == "key":
        entries[1] = entries[1].model_copy(update={"key_id": "untrusted"})
    elif change == "prev_hash":
        entries[1] = entries[1].model_copy(update={"prev_hash": GENESIS})
    result = verify_chain(entries, TENANT, TestSigner(), head)
    assert result.status == "BROKEN"
    assert result.first_broken_seq is not None


def test_unavailable_verifier_never_passes() -> None:
    class Unavailable(TestSigner):
        def verify(self, digest: bytes, signature: bytes) -> bool:
            raise TimeoutError("unit timeout")

    entries, head = chain()
    assert verify_chain(entries, TENANT, Unavailable(), head).status == "UNVERIFIED"


def test_empty_chain_is_not_verified() -> None:
    assert (
        verify_chain([], TENANT, TestSigner(), Head(seq=0, hash=GENESIS)).status
        == "EMPTY"
    )


def test_canonical_encoding_is_order_and_timezone_independent() -> None:
    event = LedgerEvent(
        tenant_id=TENANT,
        seq=1,
        type="unit.probe",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        payload={"z": "é", "a": 1},
    )
    same = event.model_copy(
        update={
            "created_at": event.created_at.astimezone(
                timezone(timedelta(hours=5, minutes=30))
            ),
            "payload": {"a": 1, "z": "é"},
        }
    )
    assert event.canonical() == same.canonical()
    assert b'"version":1' in event.canonical()
    assert len(hashlib.sha256(event.canonical()).digest()) == 32


def test_rejects_float_payload_naive_timestamp_and_wrong_sequence() -> None:
    entries, _ = chain()
    data = entries[0].event.model_dump()
    with pytest.raises(ValidationError):
        LedgerEvent.model_validate({**data, "payload": {"nested": [0.1]}})
    with pytest.raises(ValidationError):
        LedgerEvent.model_validate({**data, "created_at": datetime(2026, 1, 1)})
    with pytest.raises(ValueError, match="does not extend"):
        sign_event(entries[1].event, Head(seq=0, hash=GENESIS), TestSigner())


def test_kms_uses_digest_and_only_invalid_signature_becomes_false() -> None:
    class Client:
        def sign(self, **kwargs: Any) -> dict[str, Any]:
            assert kwargs["MessageType"] == "DIGEST"
            assert len(kwargs["Message"]) == 32
            assert kwargs["SigningAlgorithm"] == "ECDSA_SHA_256"
            return {
                "KeyId": KEY,
                "SigningAlgorithm": "ECDSA_SHA_256",
                "Signature": b"unit-signature",
            }

        def verify(self, **kwargs: Any) -> dict[str, Any]:
            assert kwargs["KeyId"] == KEY
            assert kwargs["MessageType"] == "DIGEST"
            raise ClientError(
                {"Error": {"Code": "KMSInvalidSignatureException"}}, "Verify"
            )

    signer = KmsSigner(Client(), KEY)
    assert signer.sign(b"a" * 32) == b"unit-signature"
    assert signer.verify(b"a" * 32, b"invalid") is False
    with pytest.raises(ValueError, match="full KMS key ARN"):
        KmsSigner(Client(), "alias/mutable")
