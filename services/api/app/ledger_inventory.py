"""Bounded, tenant-scoped checkpoint discovery from retained S3 object versions."""

import hashlib
import re
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict

from app.ledger import Head, SignedEntry, Verification
from app.ledger_anchors import AnchorReference, AnchorStore, SignedAnchor


class Checkpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    reference: AnchorReference
    anchor: SignedAnchor
    stored_at: AwareDatetime


class CheckpointInventory:
    def __init__(self, store: AnchorStore) -> None:
        self.store = store

    def latest(self, tenant_id: UUID, max_versions: int = 10000) -> Checkpoint | None:
        if not 1 <= max_versions <= 10000:
            raise ValueError("Checkpoint inventory limit must be between 1 and 10000")
        prefix = f"anchors/{tenant_id}/"
        pattern = re.compile(
            re.escape(prefix) + r"\d{4}-\d{2}-\d{2}/([1-9][0-9]*)-[0-9a-f]{64}\.json"
        )
        markers: dict[str, str] = {}
        seen: set[tuple[str, str]] = set()
        count = 0
        best: tuple[int, datetime, str, str] | None = None
        while True:
            page = self.store.client.list_object_versions(
                Bucket=self.store.bucket,
                Prefix=prefix,
                MaxKeys=1000,
                ExpectedBucketOwner=self.store.owner,
                **markers,
            )
            if page.get("DeleteMarkers"):
                raise ValueError(
                    "Checkpoint inventory contains unexpected delete markers"
                )
            for version in page.get("Versions", []):
                count += 1
                if count > max_versions:
                    raise ValueError(
                        "Checkpoint inventory exceeds its verification limit"
                    )
                key, version_id = version["Key"], version["VersionId"]
                match = pattern.fullmatch(key)
                if match is None or version_id == "null":
                    raise ValueError(
                        "Malformed checkpoint version in retained inventory"
                    )
                candidate = (
                    int(match.group(1)),
                    version["LastModified"],
                    key,
                    version_id,
                )
                if best is None or candidate > best:
                    best = candidate
            if not page.get("IsTruncated"):
                break
            marker = (
                page.get("NextKeyMarker", ""),
                page.get("NextVersionIdMarker", ""),
            )
            if not marker[0] or marker in seen:
                raise ValueError("Invalid checkpoint inventory pagination")
            seen.add(marker)
            markers = {"KeyMarker": marker[0], "VersionIdMarker": marker[1]}
        if best is None:
            return None
        seq, stored_at, key, version_id = best
        response = self.store.client.get_object(
            Bucket=self.store.bucket,
            Key=key,
            VersionId=version_id,
            ExpectedBucketOwner=self.store.owner,
        )
        with response["Body"] as stream:
            body = stream.read(65537)
        if len(body) > 65536:
            raise ValueError("Checkpoint inventory object exceeds size limit")
        reference = AnchorReference(
            bucket=self.store.bucket,
            key=key,
            version_id=version_id,
            body_sha256=hashlib.sha256(body).hexdigest(),
        )
        anchor = self.store.load(reference, tenant_id)
        if anchor.manifest.head.seq != seq:
            raise ValueError("Checkpoint key sequence does not match signed content")
        return Checkpoint(reference=reference, anchor=anchor, stored_at=stored_at)

    def verify_latest(
        self,
        entries: list[SignedEntry],
        tenant_id: UUID,
        head: Head,
        *,
        now: datetime | None = None,
        max_age: timedelta = timedelta(hours=36),
    ) -> Verification:
        clock = now or datetime.now(UTC)
        try:
            checkpoint = self.latest(tenant_id)
            if checkpoint is None:
                if not entries and head.seq == 0:
                    return Verification(
                        status="EMPTY",
                        checked=0,
                        reason="No events or retained checkpoints exist",
                    )
                return Verification(
                    status="UNVERIFIED",
                    checked=0,
                    reason="No retained checkpoint exists",
                )
            # Always compare before freshness: a stale checkpoint can still prove truncation.
            result = self.store.verify(entries, tenant_id, head, checkpoint.reference)
            if result.status != "VERIFIED":
                return result
            seal = checkpoint.anchor.manifest.sealed_at or checkpoint.stored_at
            if (
                max_age <= timedelta(0)
                or clock - checkpoint.stored_at > max_age
                or clock - seal > max_age
                or checkpoint.stored_at > clock + timedelta(minutes=5)
                or seal > checkpoint.stored_at + timedelta(minutes=5)
            ):
                return Verification(
                    status="UNVERIFIED",
                    checked=len(entries),
                    reason="Checkpoint is stale or has an invalid publication time",
                )
            return result
        except Exception:  # noqa: BLE001 -- Discovery or validation errors must never become a verified result.
            return Verification(
                status="UNVERIFIED",
                checked=0,
                reason="Retained checkpoint discovery could not complete",
            )
