"""Inspect real NDJSON and submit idempotent, encrypted HealthLake imports."""

import base64
import hashlib
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import structlog
from botocore.auth import SigV4Auth  # type: ignore[import-untyped]
from botocore.awsrequest import AWSRequest  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from opentelemetry import trace

from .fhir_schemas import Cohort, ImportConfig, ImportState

tracer = trace.get_tracer("verimed.fhir.import")
logger = structlog.get_logger()
RESOURCE_ID = re.compile(r"^[A-Za-z0-9.-]{1,64}$")


def inspect(path: Path, expected_patients: int = 50) -> Cohort:
    if not path.is_file() or not 0 < path.stat().st_size <= 536870912:
        raise ValueError("FHIR input size is outside the permitted bounds")
    patients: set[str] = set()
    seen: set[tuple[str, str]] = set()
    digest = hashlib.sha256()
    count = 0
    with path.open("rb") as stream:
        while line := stream.readline(16_777_217):
            if len(line) > 16_777_216:
                raise ValueError("FHIR resource exceeds the input bound")
            digest.update(line)
            resource = json.loads(line)
            if not isinstance(resource, dict):
                raise TypeError("FHIR resource must be an object")
            resource_type, resource_id = (
                resource.get("resourceType"),
                resource.get("id"),
            )
            if (
                not isinstance(resource_type, str)
                or not re.fullmatch(r"[A-Z][A-Za-z]+", resource_type)
                or not isinstance(resource_id, str)
                or not RESOURCE_ID.fullmatch(resource_id)
            ):
                raise ValueError("FHIR input contains an invalid resource identity")
            identity = (resource_type, resource_id)
            if identity in seen:
                raise ValueError("FHIR import contains duplicate resource identities")
            seen.add(identity)
            if resource_type == "Patient":
                patients.add(resource_id)
            count += 1
    if len(patients) != expected_patients:
        raise ValueError("FHIR cohort does not contain the expected patient count")
    return Cohort(
        sha256=digest.hexdigest(),
        resource_count=count,
        byte_count=path.stat().st_size,
        patient_ids=sorted(patients),
    )


def submit(
    session: Any, config: ImportConfig, source: Path, cohort: Cohort
) -> ImportState:
    with tracer.start_as_current_span(
        "fhir.import.submit", record_exception=False, set_status_on_exception=False
    ):
        if config.expires_at <= datetime.now(UTC):
            raise ValueError("Synthetic import window has ended")
        healthlake = session.client("healthlake", region_name=config.region)
        account = session.client(
            "sts", region_name=config.region
        ).get_caller_identity()["Account"]
        if any(
            arn.split(":")[4] != account
            for arn in (config.datastore_arn, config.role_arn, config.key_arn)
        ):
            raise ValueError("AWS caller and datastore accounts differ")
        properties = healthlake.describe_fhir_datastore(
            DatastoreId=config.datastore_id
        )["DatastoreProperties"]
        if properties["DatastoreStatus"] != "ACTIVE" or properties[
            "DatastoreEndpoint"
        ].rstrip("/") != config.endpoint.rstrip("/"):
            raise ValueError("Configured FHIR destination is not the active datastore")
        tags = {
            entry["Key"]: entry["Value"]
            for entry in healthlake.list_tags_for_resource(
                ResourceARN=config.datastore_arn
            )["Tags"]
        }
        if (
            tags.get("Project") != "verimed"
            or tags.get("Env") != "dev"
            or tags.get("Tenant") != config.tenant_slug
        ):
            raise ValueError("Synthetic import requires the tagged dev datastore")
        token = hashlib.sha256(
            (
                cohort.sha256
                + config.key_arn
                + config.datastore_arn
                + config.bucket
                + config.role_arn
                + str(config.tenant_id)
            ).encode()
        ).hexdigest()[:32]
        prefix = "imports/" + str(config.tenant_id) + "/" + token
        key = prefix + "/input/resources.ndjson"
        s3 = session.client("s3", region_name=config.region)
        with source.open("rb") as stream:
            try:
                upload = s3.put_object(
                    Bucket=config.bucket,
                    ExpectedBucketOwner=account,
                    Key=key,
                    Body=stream,
                    IfNoneMatch="*",
                    ServerSideEncryption="aws:kms",
                    SSEKMSKeyId=config.key_arn,
                    ContentType="application/fhir+ndjson",
                    ChecksumSHA256=base64.b64encode(
                        bytes.fromhex(cohort.sha256)
                    ).decode(),
                    Metadata={"sha256": cohort.sha256, "synthetic": "true"},
                )
                version = upload["VersionId"]
            except ClientError as error:
                if error.response["ResponseMetadata"]["HTTPStatusCode"] != 412:
                    raise
                existing = s3.head_object(
                    Bucket=config.bucket,
                    Key=key,
                    ExpectedBucketOwner=account,
                    ChecksumMode="ENABLED",
                )
                if (
                    existing["ContentLength"] != cohort.byte_count
                    or existing.get("Metadata", {}).get("sha256") != cohort.sha256
                    or existing.get("ChecksumSHA256")
                    != base64.b64encode(bytes.fromhex(cohort.sha256)).decode()
                ):
                    raise ValueError(
                        "FHIR input key conflicts with existing content"
                    ) from None
                version = existing["VersionId"]
        if not isinstance(version, str) or not version or version == "null":
            raise ValueError("FHIR source must have a pinned S3 version")
        job = healthlake.start_fhir_import_job(
            JobName="fhir-" + token,
            ClientToken=token,
            DatastoreId=config.datastore_id,
            DataAccessRoleArn=config.role_arn,
            ValidationLevel="strict",
            InputDataConfig={"S3Uri": "s3://" + config.bucket + "/" + key},
            JobOutputDataConfig={
                "S3Configuration": {
                    "S3Uri": "s3://" + config.bucket + "/" + prefix + "/output/",
                    "KmsKeyId": config.key_arn,
                }
            },
        )
        logger.info(
            "fhir_import_submitted",
            _aws={
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": "VeriMed/Data",
                        "Dimensions": [[]],
                        "Metrics": [
                            {"Name": "FHIRImportSubmissions", "Unit": "Count"},
                            {"Name": "FHIRImportResources", "Unit": "Count"},
                        ],
                    }
                ],
            },
            FHIRImportSubmissions=1,
            FHIRImportResources=cohort.resource_count,
            resource_count=cohort.resource_count,
            patient_count=len(cohort.patient_ids),
            estimated_usd=config.estimated_usd,
        )
        return ImportState(
            config=config,
            cohort=cohort,
            job_id=job["JobId"],
            source_key=key,
            source_version_id=version,
            submitted_at=datetime.now(UTC),
        )


def check(session: Any, state: ImportState) -> dict[str, object]:
    config = state.config
    with tracer.start_as_current_span(
        "fhir.import.check", record_exception=False, set_status_on_exception=False
    ):
        details = session.client(
            "healthlake", region_name=config.region
        ).describe_fhir_import_job(
            DatastoreId=config.datastore_id,
            JobId=state.job_id,
        )["ImportJobProperties"]
        status = details["JobStatus"]
        progress = details.get("JobProgressReport", {})
        verified = 0
        if status == "COMPLETED":
            if (
                progress.get("TotalNumberOfResourcesWithCustomerError") != 0
                or progress.get("TotalNumberOfResourcesImported")
                != state.cohort.resource_count
            ):
                raise ValueError("FHIR import did not accept the entire cohort")
            with httpx.Client(timeout=15, follow_redirects=False) as http:
                for patient in state.cohort.patient_ids:
                    url = config.endpoint.rstrip("/") + "/Patient/" + patient
                    request = AWSRequest(method="GET", url=url)
                    SigV4Auth(
                        session.get_credentials().get_frozen_credentials(),
                        "healthlake",
                        config.region,
                    ).add_auth(request)
                    response = http.get(url, headers=dict(request.headers))
                    if response.status_code != 200:
                        raise ValueError("Imported FHIR patient cannot be read")
                    resource = response.json()
                    if (
                        resource.get("resourceType") != "Patient"
                        or resource.get("id") != patient
                    ):
                        raise ValueError("Imported FHIR patient identity differs")
                    verified += 1
        return {
            "checked_at": datetime.now(UTC).isoformat(),
            "backend": "healthlake",
            "job_id": state.job_id,
            "job_status": status,
            "submitted_patients": len(state.cohort.patient_ids),
            "verified_patients": verified,
            "resources_submitted": state.cohort.resource_count,
            "resources_imported": progress.get("TotalNumberOfResourcesImported"),
            "resources_rejected": progress.get(
                "TotalNumberOfResourcesWithCustomerError"
            ),
            "input_sha256": state.cohort.sha256,
            "source_version_pinned": bool(state.source_version_id),
            "estimated_incremental_usd": config.estimated_usd,
            "status": "PASSED"
            if status == "COMPLETED" and verified == len(state.cohort.patient_ids)
            else "INCOMPLETE",
        }
