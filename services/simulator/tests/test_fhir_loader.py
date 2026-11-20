"""Only unit tests use SDK doubles; product imports use real HealthLake."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from simulator.fhir_loader import inspect, submit
from simulator.fhir_schemas import ImportConfig

STORE = "0" * 32


def config() -> ImportConfig:
    return ImportConfig(
        tenant_id=uuid4(),
        tenant_slug="a",
        region="us-east-1",
        datastore_id=STORE,
        datastore_arn="arn:aws:healthlake:us-east-1:111111111111:datastore/fhir/"
        + STORE,
        endpoint="https://healthlake.us-east-1.amazonaws.com/datastore/"
        + STORE
        + "/r4",
        bucket="unit-input",
        key_arn="arn:aws:kms:us-east-1:111111111111:key/unit",
        role_arn="arn:aws:iam::111111111111:role/unit",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        estimated_usd=0.05,
    )


def source(tmp_path: Path) -> Path:
    path = tmp_path / "unit.ndjson"
    path.write_text(
        json.dumps({"resourceType": "Patient", "id": "unit-patient"}) + "\n",
        encoding="utf-8",
    )
    return path


def test_inspection_uses_actual_source_hash_and_count(tmp_path: Path) -> None:
    path = source(tmp_path)
    cohort = inspect(path, 1)
    assert cohort.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert cohort.resource_count == 1 and cohort.patient_ids == ["unit-patient"]


@pytest.mark.parametrize(
    "rows",
    [
        [{"resourceType": "Patient", "id": "../../other"}],
        [
            {"resourceType": "Patient", "id": "same"},
            {"resourceType": "Patient", "id": "same"},
        ],
        [{"resourceType": "Observation", "id": "unit"}],
        ["sensitive input"],
    ],
)
def test_invalid_cohorts_rejected_without_provider_calls(
    tmp_path: Path, rows: list[Any]
) -> None:
    path = tmp_path / "invalid.ndjson"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    with pytest.raises((ValueError, TypeError)):
        inspect(path, 1)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://attacker.invalid/datastore/" + STORE + "/r4",
        "http://healthlake.us-east-1.amazonaws.com/datastore/" + STORE + "/r4",
        "https://healthlake.us-east-1.amazonaws.com/datastore/"
        + STORE
        + "/r4?patient=unit",
    ],
)
def test_endpoint_substitution_rejected(endpoint: str) -> None:
    values = config().model_dump()
    values["endpoint"] = endpoint
    with pytest.raises(ValueError):
        ImportConfig.model_validate(values)


def test_expired_job_does_not_contact_aws(tmp_path: Path) -> None:
    values = config().model_dump()
    values["expires_at"] = datetime.now(UTC) - timedelta(seconds=1)
    expired = ImportConfig.model_validate(values)

    class Session:
        def client(self, *args: Any, **kwargs: Any) -> Any:
            pytest.fail("Expired job reached AWS")

    path = source(tmp_path)
    with pytest.raises(ValueError):
        submit(Session(), expired, path, inspect(path, 1))


def test_idempotent_import_has_strict_validation_and_pinned_source(
    tmp_path: Path,
) -> None:
    cfg = config()
    calls: list[dict[str, Any]] = []

    class Sdk:
        def get_caller_identity(self) -> dict[str, str]:
            return {"Account": "111111111111"}

        def describe_fhir_datastore(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "DatastoreProperties": {
                    "DatastoreStatus": "ACTIVE",
                    "DatastoreArn": cfg.datastore_arn,
                    "DatastoreEndpoint": cfg.endpoint,
                }
            }

        def list_tags_for_resource(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "Tags": [
                    {"Key": k, "Value": v}
                    for k, v in {
                        "Project": "verimed",
                        "Env": "dev",
                        "Tenant": "a",
                    }.items()
                ]
            }

        def put_object(self, **kwargs: Any) -> dict[str, str]:
            assert (
                kwargs["IfNoneMatch"] == "*"
                and kwargs["ExpectedBucketOwner"] == "111111111111"
            )
            assert (
                kwargs["ServerSideEncryption"] == "aws:kms" and kwargs["ChecksumSHA256"]
            )
            return {"VersionId": "unit-version"}

        def start_fhir_import_job(self, **kwargs: Any) -> dict[str, str]:
            calls.append(kwargs)
            return {"JobId": "unit-job"}

    class Session:
        def client(self, *args: Any, **kwargs: Any) -> Sdk:
            return Sdk()

    path = source(tmp_path)
    cohort = inspect(path, 1)
    first = submit(Session(), cfg, path, cohort)
    second = submit(Session(), cfg, path, cohort)
    assert first.job_id == second.job_id and first.source_key == second.source_key
    assert first.source_version_id == "unit-version"
    assert calls[0] == calls[1] and calls[0]["ValidationLevel"] == "strict"
