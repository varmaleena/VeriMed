"""On-demand cell task: real Synthea generation and immutable encrypted upload."""

import base64
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any
from uuid import UUID

import boto3  # type: ignore[import-untyped]
import structlog
from botocore.config import Config  # type: ignore[import-untyped]
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from pydantic import Field

from .fhir_loader import inspect
from .fhir_schemas import StrictModel
from .synthea import generate

logger = structlog.get_logger()
tracer = trace.get_tracer("verimed.synthea.task")


class GenerationJob(StrictModel):
    job_id: UUID
    population: int = Field(ge=1, le=50, strict=True)


def upload(
    client: Any,
    job: GenerationJob,
    source: Path,
    bucket: str,
    key_arn: str,
    account: str,
) -> dict[str, str | int]:
    """Publish the receipt last; consumers must never treat partial uploads as ready."""
    cohort = inspect(source, job.population)
    prefix = f"imports/{job.job_id}"
    common = {
        "Bucket": bucket,
        "ExpectedBucketOwner": account,
        "ServerSideEncryption": "aws:kms",
        "SSEKMSKeyId": key_arn,
        "IfNoneMatch": "*",
    }
    with source.open("rb") as stream:
        response = client.put_object(
            **common,
            Key=f"{prefix}/input/resources.ndjson",
            Body=stream,
            ContentType="application/fhir+ndjson",
            ChecksumSHA256=base64.b64encode(bytes.fromhex(cohort.sha256)).decode(),
        )
    version = response.get("VersionId")
    if not isinstance(version, str) or not version or version == "null":
        raise ValueError("Versioned transfer storage is required")
    # IDs are stored in the cell's encrypted metadata, never emitted to telemetry.
    metadata = cohort.model_dump_json().encode()
    client.put_object(
        **common,
        Key=f"{prefix}/metadata/cohort.json",
        Body=metadata,
        ContentType="application/json",
        ChecksumSHA256=base64.b64encode(hashlib.sha256(metadata).digest()).decode(),
    )
    receipt: dict[str, str | int] = {
        "job_id": str(job.job_id),
        "source_key": f"{prefix}/input/resources.ndjson",
        "source_version_id": version,
        "sha256": cohort.sha256,
        "patient_count": job.population,
        "resource_count": cohort.resource_count,
        "byte_count": cohort.byte_count,
        "status": "GENERATED",
    }
    payload = json.dumps(receipt, sort_keys=True).encode()
    client.put_object(
        **common,
        Key=f"{prefix}/metadata/ready.json",
        Body=payload,
        ContentType="application/json",
        ChecksumSHA256=base64.b64encode(hashlib.sha256(payload).digest()).decode(),
    )
    return receipt


def main() -> int:
    structlog.configure(processors=[structlog.processors.JSONRenderer()])
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    try:
        # Validate control input before generating clinical content or opening AWS clients.
        job = GenerationJob(
            job_id=UUID(os.environ["JOB_ID"]),
            population=int(os.environ["POPULATION"]),
        )
        with tracer.start_as_current_span(
            "synthea.generate_upload",
            record_exception=False,
            set_status_on_exception=False,
        ):
            source = generate(
                Path("/opt/synthea.jar"), Path("/work/cohort"), job.population
            )
            client = boto3.client(
                "s3",
                region_name=os.environ["AWS_REGION"],
                config=Config(
                    connect_timeout=5, read_timeout=60, retries={"max_attempts": 3}
                ),
            )
            result = upload(
                client,
                job,
                source,
                os.environ["TRANSFER_BUCKET"],
                os.environ["TRANSFER_KEY_ARN"],
                os.environ["CELL_ACCOUNT"],
            )
        logger.info(
            "synthea_generation_completed",
            patient_count=job.population,
            resource_count=result["resource_count"],
            **metric("SyntheaGenerations"),
        )
        return 0
    except Exception:  # noqa: BLE001 -- never serialize generator/provider exception data
        logger.error(
            "synthea_generation_failed",
            error_code="GENERATION_FAILED",
            **metric("SyntheaGenerationFailures"),
        )
        return 1


def metric(name: str) -> dict[str, Any]:
    return {
        name: 1,
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": "VeriMed",
                    "Dimensions": [[]],
                    "Metrics": [{"Name": name, "Unit": "Count"}],
                }
            ],
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
