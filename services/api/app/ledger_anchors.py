"""Signed daily Merkle checkpoints stored as pinned S3 Object Lock versions."""

import base64
import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

import structlog
from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict, Field

from app.ledger import (
    ALGORITHM,
    DigestSigner,
    Head,
    SignedEntry,
    Verification,
    verify_chain,
)

tracer = trace.get_tracer("verimed.ledger.anchors")
logger = structlog.get_logger()
DOMAIN = b"chartvigil.ledger.anchor.v1\x00"


def canonical(model: BaseModel) -> bytes:
    return json.dumps(
        model.model_dump(mode="json"),
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")


def merkle_root(hashes: list[str]) -> str:
    if not hashes:
        raise ValueError("Cannot anchor an empty day")
    nodes = [
        hashlib.sha256(b"\x00" + bytes.fromhex(value)).digest() for value in hashes
    ]
    while len(nodes) > 1:
        if len(nodes) % 2:
            nodes.append(nodes[-1])
        nodes = [
            hashlib.sha256(b"\x01" + nodes[i] + nodes[i + 1]).digest()
            for i in range(0, len(nodes), 2)
        ]
    return nodes[0].hex()


class AnchorManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal[1] = 1
    tenant_id: UUID
    day: date
    head: Head
    count: int = Field(gt=0, le=10000, strict=True)
    merkle_root: str = Field(pattern=r"^[0-9a-f]{64}$")


class SignedAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    manifest: AnchorManifest
    key_id: str
    algorithm: Literal["ECDSA_SHA_256"] = ALGORITHM
    signature: str = Field(min_length=1, max_length=8192)


class AnchorReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    bucket: str
    key: str
    version_id: str = Field(min_length=1)
    body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def create_anchor(
    entries: list[SignedEntry],
    tenant_id: UUID,
    head: Head,
    day: date,
    signer: DigestSigner,
) -> SignedAnchor:
    result = verify_chain(entries, tenant_id, signer, head)
    if result.status != "VERIFIED":
        raise ValueError("Only a complete verified chain can be anchored")
    daily_hashes = [
        entry.hash
        for entry in entries
        if entry.event.created_at.astimezone(UTC).date() == day
    ]
    manifest = AnchorManifest(
        tenant_id=tenant_id,
        day=day,
        head=head,
        count=len(daily_hashes),
        merkle_root=merkle_root(daily_hashes),
    )
    signature = signer.sign(hashlib.sha256(DOMAIN + canonical(manifest)).digest())
    return SignedAnchor(
        manifest=manifest,
        key_id=signer.key_id,
        signature=base64.b64encode(signature).decode("ascii"),
    )


def validate_signature(
    anchor: SignedAnchor, tenant_id: UUID, signer: DigestSigner
) -> None:
    if anchor.manifest.tenant_id != tenant_id or anchor.key_id != signer.key_id:
        raise ValueError("Anchor tenant or pinned key mismatch")
    digest = hashlib.sha256(DOMAIN + canonical(anchor.manifest)).digest()
    if not signer.verify(digest, base64.b64decode(anchor.signature, validate=True)):
        raise ValueError("Invalid anchor signature")


def anchor_key(anchor: SignedAnchor) -> str:
    manifest = anchor.manifest
    return f"anchors/{manifest.tenant_id}/{manifest.day.isoformat()}/{manifest.head.seq}-{hashlib.sha256(canonical(manifest)).hexdigest()}.json"


class AnchorStore:
    def __init__(
        self, client: Any, bucket: str, encryption_key_arn: str, signer: DigestSigner
    ) -> None:
        if ":kms:" not in encryption_key_arn or ":key/" not in encryption_key_arn:
            raise ValueError("A pinned encryption key ARN is required")
        self.client = client
        self.bucket = bucket
        self.encryption_key_arn = encryption_key_arn
        self.owner = encryption_key_arn.split(":")[4]
        self.signer = signer

    def load(self, reference: AnchorReference, tenant_id: UUID) -> SignedAnchor:
        if (
            reference.bucket != self.bucket
            or reference.version_id == "null"
            or not reference.key.startswith(f"anchors/{tenant_id}/")
        ):
            raise ValueError("Anchor reference does not belong to this tenant bucket")
        with tracer.start_as_current_span(
            "ledger.anchor.read", record_exception=False, set_status_on_exception=False
        ):
            response = self.client.get_object(
                Bucket=self.bucket,
                Key=reference.key,
                VersionId=reference.version_id,
                ExpectedBucketOwner=self.owner,
            )
            with response["Body"] as stream:
                body = stream.read(65537)
            if (
                len(body) > 65536
                or hashlib.sha256(body).hexdigest() != reference.body_sha256
            ):
                raise ValueError("Anchor body checksum mismatch")
            if (
                response.get("ServerSideEncryption") != "aws:kms"
                or response.get("SSEKMSKeyId") != self.encryption_key_arn
            ):
                raise ValueError("Anchor encryption key mismatch")
            retention = self.client.get_object_retention(
                Bucket=self.bucket,
                Key=reference.key,
                VersionId=reference.version_id,
                ExpectedBucketOwner=self.owner,
            )["Retention"]
        created = response["LastModified"]
        try:
            minimum_retention = created.replace(year=created.year + 7)
        except ValueError:  # Clamp February 29 when the target year is not a leap year.
            minimum_retention = created.replace(year=created.year + 7, day=28)
        if (
            retention.get("Mode") != "COMPLIANCE"
            # S3 LastModified is whole-second precision; retention can include milliseconds.
            or retention["RetainUntilDate"] < minimum_retention - timedelta(seconds=1)
        ):
            raise ValueError("Anchor lacks the required compliance retention")
        anchor = SignedAnchor.model_validate_json(body)
        validate_signature(anchor, tenant_id, self.signer)
        if reference.key != anchor_key(anchor):
            raise ValueError("Anchor key does not match its signed manifest")
        return anchor

    def put(self, anchor: SignedAnchor) -> AnchorReference:
        validate_signature(anchor, anchor.manifest.tenant_id, self.signer)
        body = canonical(anchor)
        key = anchor_key(anchor)
        with tracer.start_as_current_span(
            "ledger.anchor.write", record_exception=False, set_status_on_exception=False
        ):
            try:
                result = self.client.put_object(
                    Bucket=self.bucket,
                    Key=key,
                    Body=body,
                    ContentType="application/json",
                    ServerSideEncryption="aws:kms",
                    SSEKMSKeyId=self.encryption_key_arn,
                    ChecksumAlgorithm="SHA256",
                    ChecksumSHA256=base64.b64encode(
                        hashlib.sha256(body).digest()
                    ).decode("ascii"),
                    IfNoneMatch="*",
                    ExpectedBucketOwner=self.owner,
                )
                version_id = str(result["VersionId"])
            except ClientError as error:
                if error.response["Error"]["Code"] != "PreconditionFailed":
                    raise
                result = self.client.get_object(
                    Bucket=self.bucket, Key=key, ExpectedBucketOwner=self.owner
                )
                with result["Body"] as stream:
                    body = stream.read(65537)
                if len(body) > 65536:
                    raise ValueError("Existing anchor exceeds size limit")
                version_id = str(result["VersionId"])
        reference = AnchorReference(
            bucket=self.bucket,
            key=key,
            version_id=version_id,
            body_sha256=hashlib.sha256(body).hexdigest(),
        )
        stored = self.load(reference, anchor.manifest.tenant_id)
        if stored.manifest != anchor.manifest:
            raise ValueError("Existing anchor belongs to another checkpoint")
        logger.info(
            "ledger_anchor_stored",
            outcome="success",
            _aws={
                "Timestamp": int(datetime.now(UTC).timestamp() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": "VeriMed",
                        "Dimensions": [[]],
                        "Metrics": [{"Name": "LedgerAnchorsStored", "Unit": "Count"}],
                    }
                ],
            },
            LedgerAnchorsStored=1,
        )
        return reference

    def verify(
        self,
        entries: list[SignedEntry],
        tenant_id: UUID,
        current_head: Head,
        reference: AnchorReference,
    ) -> Verification:
        with tracer.start_as_current_span(
            "ledger.anchor.verify",
            record_exception=False,
            set_status_on_exception=False,
        ):
            result = self._verify(entries, tenant_id, current_head, reference)
        logger.info(
            "ledger_anchor_verification",
            outcome=result.status,
            _aws={
                "Timestamp": int(datetime.now(UTC).timestamp() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": "VeriMed",
                        "Dimensions": [[]],
                        "Metrics": [
                            {
                                "Name": "LedgerAnchorVerificationFailures",
                                "Unit": "Count",
                            }
                        ],
                    }
                ],
            },
            LedgerAnchorVerificationFailures=int(
                result.status in ("BROKEN", "UNVERIFIED")
            ),
        )
        return result

    def _verify(
        self,
        entries: list[SignedEntry],
        tenant_id: UUID,
        current_head: Head,
        reference: AnchorReference,
    ) -> Verification:
        try:
            anchor = self.load(reference, tenant_id)
            result = verify_chain(entries, tenant_id, self.signer, current_head)
            if result.status != "VERIFIED":
                return result
            manifest = anchor.manifest
            prefix = [
                entry for entry in entries if entry.event.seq <= manifest.head.seq
            ]
            result = verify_chain(prefix, tenant_id, self.signer, manifest.head)
            if result.status != "VERIFIED":
                return result
            daily = [
                entry.hash
                for entry in prefix
                if entry.event.created_at.astimezone(UTC).date() == manifest.day
            ]
            if (
                len(daily) != manifest.count
                or merkle_root(daily) != manifest.merkle_root
            ):
                return Verification(
                    status="BROKEN",
                    checked=len(prefix),
                    reason="Daily Merkle checkpoint mismatch",
                )
            if current_head != manifest.head:
                return Verification(
                    status="UNVERIFIED",
                    checked=len(entries),
                    reason="Valid anchored prefix; newer events require a new checkpoint",
                )
            return Verification(
                status="VERIFIED",
                checked=len(entries),
                reason="Chain matches the pinned retained S3 checkpoint",
            )
        except Exception:  # noqa: BLE001 -- Any storage, signature, retention or parsing error fails closed without logging contents.
            logger.error("ledger_anchor_unverified")
            return Verification(
                status="UNVERIFIED",
                checked=0,
                reason="Retained checkpoint verification could not complete",
            )
