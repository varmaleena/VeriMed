"""Versioned hash-chain and KMS signature primitives; persistence is separate."""

import base64
import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from uuid import UUID

import structlog
from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from opentelemetry import trace
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
)

GENESIS = "0" * 64
ALGORITHM: Literal["ECDSA_SHA_256"] = "ECDSA_SHA_256"
tracer = trace.get_tracer("verimed.ledger")
logger = structlog.get_logger()


class LedgerEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal[1] = 1
    tenant_id: UUID
    seq: int = Field(ge=1, strict=True)
    encounter_id: UUID | None = None
    type: str = Field(pattern=r"^[a-z][a-z0-9_.]{0,79}$")
    created_at: AwareDatetime
    payload: dict[str, JsonValue]

    @field_validator("payload")
    @classmethod
    def no_floats(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        def check(item: JsonValue) -> None:
            if isinstance(item, float):
                raise ValueError(  # noqa: TRY004 -- Pydantic validators use ValueError for invalid field values.
                    "Use integer quantities or decimal strings in ledger payloads"
                )
            if isinstance(item, dict):
                for child in item.values():
                    check(child)
            if isinstance(item, list):
                for child in item:
                    check(child)

        check(value)
        return value

    def canonical(self) -> bytes:
        # Version 1: sorted keys, ASCII escapes, compact separators, UTC microseconds.
        data = self.model_dump(mode="json")
        data["created_at"] = (
            self.created_at.astimezone(UTC)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
        result = json.dumps(
            data,
            sort_keys=True,
            ensure_ascii=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
        if len(result) > 16384:
            raise ValueError("Ledger event exceeds 16 KiB")
        return result


class SignedEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    event: LedgerEvent
    prev_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    signature: str = Field(min_length=1, max_length=8192)
    key_id: str
    algorithm: Literal["ECDSA_SHA_256"] = ALGORITHM


class Head(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    seq: int = Field(ge=0, strict=True)
    hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class Verification(BaseModel):
    status: Literal["VERIFIED", "BROKEN", "UNVERIFIED", "EMPTY"]
    checked: int
    first_broken_seq: int | None = None
    reason: str


class DigestSigner(Protocol):
    key_id: str

    def sign(self, digest: bytes) -> bytes: ...
    def verify(self, digest: bytes, signature: bytes) -> bool: ...


class KmsSigner:
    def __init__(self, client: Any, key_id: str) -> None:
        if not re.fullmatch(
            r"arn:[a-z-]+:kms:[a-z0-9-]+:[0-9]{12}:key/[a-f0-9-]{36}", key_id
        ):
            raise ValueError("Pin the full KMS key ARN; aliases are not immutable")
        self.client = client
        self.key_id = key_id

    def sign(self, digest: bytes) -> bytes:
        with tracer.start_as_current_span(
            "ledger.kms.sign", record_exception=False, set_status_on_exception=False
        ):
            result = self.client.sign(
                KeyId=self.key_id,
                Message=digest,
                MessageType="DIGEST",
                SigningAlgorithm=ALGORITHM,
            )
        if (
            result.get("KeyId") != self.key_id
            or result.get("SigningAlgorithm") != ALGORITHM
            or not isinstance(result.get("Signature"), bytes)
        ):
            raise ValueError("Unexpected KMS signing response")
        return bytes(result["Signature"])

    def verify(self, digest: bytes, signature: bytes) -> bool:
        with tracer.start_as_current_span(
            "ledger.kms.verify", record_exception=False, set_status_on_exception=False
        ):
            try:
                result = self.client.verify(
                    KeyId=self.key_id,
                    Message=digest,
                    MessageType="DIGEST",
                    SigningAlgorithm=ALGORITHM,
                    Signature=signature,
                )
            except ClientError as error:
                if error.response["Error"]["Code"] == "KMSInvalidSignatureException":
                    return False
                raise
        return (
            result.get("SignatureValid") is True
            and result.get("KeyId") == self.key_id
            and result.get("SigningAlgorithm") == ALGORITHM
        )


def sign_event(event: LedgerEvent, previous: Head, signer: DigestSigner) -> SignedEntry:
    event = LedgerEvent.model_validate(event.model_dump())
    if event.seq != previous.seq + 1 or (
        previous.seq == 0 and previous.hash != GENESIS
    ):
        raise ValueError("The event does not extend the provided chain head")
    digest = hashlib.sha256(bytes.fromhex(previous.hash) + event.canonical()).digest()
    return SignedEntry(
        event=event,
        prev_hash=previous.hash,
        hash=digest.hex(),
        signature=base64.b64encode(signer.sign(digest)).decode("ascii"),
        key_id=signer.key_id,
    )


def verify_chain(
    entries: list[SignedEntry],
    tenant_id: UUID,
    signer: DigestSigner,
    expected_head: Head,
) -> Verification:
    """Verify a complete tenant chain against an independently trusted head.

    Filtering a chain to one encounter breaks continuity. Verify the tenant chain
    first, then select encounter entries. A supplied head is not an external anchor.
    """
    with tracer.start_as_current_span(
        "ledger.chain.verify", record_exception=False, set_status_on_exception=False
    ):
        result = _verify_chain(entries, tenant_id, signer, expected_head)
    logger.info(
        "ledger_verification",
        outcome=result.status,
        checked=result.checked,
        first_broken_seq=result.first_broken_seq,
        _aws={
            "Timestamp": int(datetime.now(UTC).timestamp() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": "VeriMed",
                    "Dimensions": [[]],
                    "Metrics": [
                        {"Name": "LedgerVerificationFailures", "Unit": "Count"}
                    ],
                }
            ],
        },
        LedgerVerificationFailures=int(result.status in ("BROKEN", "UNVERIFIED")),
    )
    return result


def _verify_chain(
    entries: list[SignedEntry],
    tenant_id: UUID,
    signer: DigestSigner,
    expected_head: Head,
) -> Verification:
    previous = Head(seq=0, hash=GENESIS)
    checked = 0
    for entry in entries:
        seq = entry.event.seq
        if entry.event.tenant_id != tenant_id or entry.key_id != signer.key_id:
            return Verification(
                status="BROKEN",
                checked=checked,
                first_broken_seq=seq,
                reason="Tenant or signing key mismatch",
            )
        if seq != previous.seq + 1 or entry.prev_hash != previous.hash:
            return Verification(
                status="BROKEN",
                checked=checked,
                first_broken_seq=previous.seq + 1,
                reason="Sequence or previous hash mismatch",
            )
        try:
            digest = hashlib.sha256(
                bytes.fromhex(previous.hash) + entry.event.canonical()
            ).digest()
            if entry.hash != digest.hex():
                return Verification(
                    status="BROKEN",
                    checked=checked,
                    first_broken_seq=seq,
                    reason="Event hash mismatch",
                )
            signature = base64.b64decode(entry.signature, validate=True)
            valid = signer.verify(digest, signature)
        except Exception:  # noqa: BLE001 -- Every verifier error must fail closed without logging payloads or provider error text.
            return Verification(
                status="UNVERIFIED",
                checked=checked,
                first_broken_seq=seq,
                reason="Signature verification could not complete",
            )
        if not valid:
            return Verification(
                status="BROKEN",
                checked=checked,
                first_broken_seq=seq,
                reason="Invalid signature",
            )
        checked += 1
        previous = Head(seq=seq, hash=entry.hash)
    if previous != expected_head:
        return Verification(
            status="BROKEN",
            checked=checked,
            first_broken_seq=previous.seq + 1,
            reason="Trusted head mismatch or truncated chain",
        )
    if not entries:
        return Verification(
            status="EMPTY", checked=0, reason="No signed events to verify"
        )
    return Verification(
        status="VERIFIED",
        checked=checked,
        reason="Chain and KMS signatures match the supplied trusted head",
    )
