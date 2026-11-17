"""Time one encrypted NDJSON import into a dedicated, empty HealthLake benchmark store."""

import argparse
import json
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ndjson", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--estimated-usd", required=True, type=float)
    for option in ("profile", "account", "datastore", "bucket", "role-arn", "key-arn"):
        parser.add_argument(f"--{option}", required=True)
    args = parser.parse_args()
    if not 0 < args.estimated_usd:
        parser.error("provide a positive benchmark cost estimate")
    with args.ndjson.open(encoding="utf-8") as lines:
        patients = {
            resource["id"]
            for resource in map(json.loads, lines)
            if resource["resourceType"] == "Patient"
        }
    if len(patients) != 50:
        parser.error(f"expected 50 distinct synthetic patients, found {len(patients)}")

    aws = ["aws", "--profile", args.profile, "--region", "us-east-1", "--no-cli-pager"]

    def call(*command: str) -> Any:
        response = subprocess.check_output([*aws, *command, "--output", "json"])
        return json.loads(response) if response.strip() else None

    if call("sts", "get-caller-identity")["Account"] != args.account:
        parser.error("the AWS profile does not match the expected account")
    store = call(
        "healthlake", "describe-fhir-datastore", "--datastore-id", args.datastore
    )
    properties = store["DatastoreProperties"]
    if (
        properties["DatastoreName"] != "verimed-phase0-fhir-spike"
        or properties["DatastoreStatus"] != "ACTIVE"
    ):
        parser.error(
            "an active dedicated verimed-phase0-fhir-spike datastore is required"
        )

    job_name = f"verimed-s4-{uuid.uuid4().hex}"
    source = f"s3://{args.bucket}/{job_name}/input/resources.ndjson"
    print(
        f"Estimated benchmark cost including sandbox runtime: ${args.estimated_usd:.2f}."
    )
    subprocess.run(
        [
            *aws,
            "s3",
            "cp",
            str(args.ndjson),
            source,
            "--sse",
            "aws:kms",
            "--sse-kms-key-id",
            args.key_arn,
            "--only-show-errors",
        ],
        check=True,
    )
    started = time.monotonic()
    job = call(
        "healthlake",
        "start-fhir-import-job",
        "--datastore-id",
        args.datastore,
        "--job-name",
        job_name,
        "--input-data-config",
        f"S3Uri={source}",
        "--job-output-data-config",
        f"S3Configuration={{S3Uri=s3://{args.bucket}/{job_name}/output/,KmsKeyId={args.key_arn}}}",
        "--data-access-role-arn",
        args.role_arn,
    )
    for _ in range(120):
        details = call(
            "healthlake",
            "describe-fhir-import-job",
            "--datastore-id",
            args.datastore,
            "--job-id",
            job["JobId"],
        )["ImportJobProperties"]
        status = details["JobStatus"]
        if status in {"COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED"}:
            break
        if status not in {"SUBMITTED", "QUEUED", "IN_PROGRESS"}:
            raise RuntimeError(f"HealthLake import ended with status {status}")
        time.sleep(10)
    else:
        raise TimeoutError("HealthLake import did not finish in 20 minutes")

    progress = details.get("JobProgressReport", {})
    report = {
        "backend": "healthlake",
        "submitted_patients": len(patients),
        "seconds": time.monotonic() - started,
        "job_status": status,
        "resources_imported": progress.get("TotalNumberOfResourcesImported"),
        "resources_rejected": progress.get("TotalNumberOfResourcesWithCustomerError"),
        "estimated_usd": args.estimated_usd,
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if status != "COMPLETED":
        raise RuntimeError(f"HealthLake import ended with status {status}")


if __name__ == "__main__":
    main()
