"""Unit-only FHIR fixtures and AWS double for immutable generation publication."""

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError
from simulator import hosted_synthea
from simulator.hosted_synthea import GenerationJob, upload


class S3:
    def __init__(self, version: str = "version-1", fail_metadata: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.version = version
        self.fail_metadata = fail_metadata

    def put_object(self, **kwargs: Any) -> dict[str, str]:
        if self.fail_metadata and kwargs["Key"].endswith("cohort.json"):
            raise RuntimeError("unit test provider failure")
        body = kwargs["Body"]
        self.calls.append(
            {**kwargs, "Body": body.read() if hasattr(body, "read") else body}
        )
        return {"VersionId": self.version}


def job() -> GenerationJob:
    return GenerationJob(
        job_id=UUID("a1f8c390-1607-4a48-8774-8ecc30813bb0"), population=1
    )


def source(tmp_path: Path) -> Path:
    path = tmp_path / "unit.ndjson"
    path.write_text(
        '{"resourceType":"Patient","id":"unit-patient"}\n', encoding="utf-8"
    )
    return path


def test_immutable_encrypted_upload_publishes_ready_last(tmp_path: Path) -> None:
    client = S3()
    receipt = upload(
        client, job(), source(tmp_path), "unit-bucket", "unit-key", "111111111111"
    )
    assert len(client.calls) == 3
    assert client.calls[-1]["Key"].endswith("metadata/ready.json")
    assert receipt["source_version_id"] == "version-1"
    assert "unit-patient" not in json.dumps(receipt)
    for call in client.calls:
        assert call["ServerSideEncryption"] == "aws:kms"
        assert call["SSEKMSKeyId"] == "unit-key"
        assert call["ExpectedBucketOwner"] == "111111111111"
        assert call["IfNoneMatch"] == "*"
        assert call["ChecksumSHA256"]


@pytest.mark.parametrize("version", ["", "null"])
def test_unversioned_storage_never_publishes_receipt(
    tmp_path: Path, version: str
) -> None:
    client = S3(version=version)
    with pytest.raises(ValueError, match="Versioned"):
        upload(
            client, job(), source(tmp_path), "unit-bucket", "unit-key", "111111111111"
        )
    assert len(client.calls) == 1


def test_partial_failure_never_publishes_ready(tmp_path: Path) -> None:
    client = S3(fail_metadata=True)
    with pytest.raises(RuntimeError):
        upload(
            client, job(), source(tmp_path), "unit-bucket", "unit-key", "111111111111"
        )
    assert len(client.calls) == 1


@pytest.mark.parametrize("population", [0, 51, True, "50"])
def test_population_bounds_reject_untrusted_control_input(population: Any) -> None:
    with pytest.raises(ValidationError):
        GenerationJob(job_id=job().job_id, population=population)


def test_extra_fields_cannot_select_another_tenant_or_bucket() -> None:
    with pytest.raises(ValidationError):
        GenerationJob.model_validate(
            {"job_id": str(job().job_id), "population": 1, "bucket": "other-tenant"}
        )


def test_generation_failure_logs_only_static_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("JOB_ID", str(job().job_id))
    monkeypatch.setenv("POPULATION", "1")

    def fail(*args: Any, **kwargs: Any) -> Path:
        raise RuntimeError("sensitive-clinical-marker")

    monkeypatch.setattr(hosted_synthea, "generate", fail)
    assert hosted_synthea.main() == 1
    output = capsys.readouterr()
    assert "sensitive-clinical-marker" not in output.out + output.err
    assert "GENERATION_FAILED" in output.out
    assert "SyntheaGenerationFailures" in output.out
