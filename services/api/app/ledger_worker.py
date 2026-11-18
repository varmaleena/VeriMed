"""IAM-invoked cell-fixed daily ledger anchoring worker."""

import os
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

import boto3  # type: ignore[import-untyped]
import structlog
from botocore.config import Config  # type: ignore[import-untyped]
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from pydantic import BaseModel, ConfigDict

from app.ledger import KmsSigner, verify_chain
from app.ledger_anchors import AnchorStore, create_anchor
from app.ledger_inventory import CheckpointInventory
from app.ledger_store import LedgerStore

structlog.configure(processors=[structlog.processors.JSONRenderer()])
logger = structlog.get_logger()
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
# The Lambda handler is loaded separately from the API process.
tracer = provider.get_tracer("verimed.ledger.worker")


class AnchorJob(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job: Literal["daily", "checkpoint"] = "daily"


class JobResult(BaseModel):
    status: Literal["SEALED", "EMPTY", "WAITING"]
    checked: int


def run(
    job: AnchorJob,
    tenant: UUID,
    reader: LedgerStore,
    anchors: AnchorStore,
    now: datetime,
) -> JobResult:
    entries, head = reader.read(tenant, max_events=200)
    inventory = CheckpointInventory(anchors)
    checkpoint = inventory.latest(tenant)
    if not entries:
        if checkpoint is not None or head.seq:
            raise ValueError("Ledger is empty but retained checkpoint history exists")
        return JobResult(status="EMPTY", checked=0)
    if verify_chain(entries, tenant, reader.signer, head).status != "VERIFIED":
        raise ValueError("Database chain verification failed")
    if checkpoint is not None:
        prefix = [
            entry
            for entry in entries
            if entry.event.seq <= checkpoint.anchor.manifest.head.seq
        ]
        if (
            anchors.verify(
                prefix, tenant, checkpoint.anchor.manifest.head, checkpoint.reference
            ).status
            != "VERIFIED"
        ):
            raise ValueError("Database chain contradicts retained checkpoint history")
    limit = now.date() if job.job == "checkpoint" else now.date() - timedelta(days=1)
    days = sorted(
        {
            entry.event.created_at.astimezone(UTC).date()
            for entry in entries
            if entry.event.created_at.astimezone(UTC).date() <= limit
        }
    )
    if not days:
        return JobResult(status="WAITING", checked=len(entries))
    # One deterministic seal time per UTC daily run gives quiet chains fresh receipts.
    slot = now.replace(hour=0, minute=30, second=0, microsecond=0)
    if slot > now:
        slot -= timedelta(days=1)
    anchor = create_anchor(
        entries, tenant, head, days[-1], reader.signer, sealed_at=slot
    )
    reference = anchors.put(anchor)
    if anchors.verify(entries, tenant, head, reference).status != "VERIFIED":
        raise ValueError("Published checkpoint could not be verified")
    return JobResult(status="SEALED", checked=len(entries))


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    try:
        job = AnchorJob.model_validate(event)
        tenant = UUID(os.environ["TENANT_ID"])
        config = Config(connect_timeout=3, read_timeout=10, retries={"max_attempts": 2})
        signer = KmsSigner(
            boto3.client("kms", config=config), os.environ["LEDGER_SIGNING_KEY_ARN"]
        )
        reader = LedgerStore(
            boto3.client("rds-data", config=config),
            {
                "resourceArn": os.environ["DATABASE_CLUSTER_ARN"],
                "secretArn": os.environ["DATABASE_SECRET_ARN"],
                "database": "verimed",
            },
            signer,
        )
        anchors = AnchorStore(
            boto3.client("s3", config=config),
            os.environ["LEDGER_ANCHOR_BUCKET"],
            os.environ["LEDGER_ANCHOR_KEY_ARN"],
            signer,
        )
        with tracer.start_as_current_span(
            "ledger.daily_anchor", record_exception=False, set_status_on_exception=False
        ):
            result = run(job, tenant, reader, anchors, datetime.now(UTC))
    except Exception as error:  # noqa: BLE001 -- Sanitize all runtime failures before Lambda retries or DLQ delivery.
        logger.error("ledger_anchor_job_failed", error_type=type(error).__name__)
        raise RuntimeError("Ledger anchoring could not complete") from None
    logger.info(
        "ledger_anchor_job_completed",
        outcome=result.status,
        checked=result.checked,
        _aws={
            "Timestamp": int(datetime.now(UTC).timestamp() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": "VeriMed",
                    "Dimensions": [[]],
                    "Metrics": [{"Name": "LedgerAnchorJobSuccess", "Unit": "Count"}],
                }
            ],
        },
        LedgerAnchorJobSuccess=1,
    )
    return result.model_dump()
