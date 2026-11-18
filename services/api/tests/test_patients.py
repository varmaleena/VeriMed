import base64
import io
import json
from typing import Any
from uuid import uuid4

import boto3  # type: ignore[import-untyped]
import pytest
from app import fhir, main
from botocore.credentials import Credentials  # type: ignore[import-untyped]
from fastapi.testclient import TestClient


def test_patient_records_are_live_inputs_and_names_are_not_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "FHIR_ENDPOINT", "https://healthlake.us-east-1.amazonaws.com/datastore/test/r4/"
    )
    monkeypatch.setenv("TENANT_ID", "tenant-a")
    monkeypatch.setenv("FHIR_EXPIRES_AT", "2099-01-01T00:00:00Z")

    class Session:
        def get_credentials(self) -> Credentials:
            return Credentials("unit-access", "unit-secret")

    monkeypatch.setattr(boto3, "Session", Session)

    def response(request: Any, timeout: int) -> io.StringIO:
        assert request.full_url.endswith(
            ("/Patient?_count=20", "/Patient?_count=20&page=token%3A%2F%3D")
        )
        assert request.get_header("Authorization").startswith("AWS4-HMAC-SHA256")
        return io.StringIO(
            json.dumps(
                {
                    "resourceType": "Bundle",
                    "total": 1,
                    "entry": [
                        {
                            "resource": {
                                "resourceType": "Patient",
                                "id": "unit-patient",
                                "birthDate": "1984-05-10",
                                "gender": "female",
                                "name": [{"text": "Excluded Identifier"}],
                            }
                        }
                    ],
                }
            )
        )

    monkeypatch.setattr(fhir, "urlopen", response)
    first = fhir.read_patients()
    assert first.items[0].birth_year == 1984
    assert first.items[0].sex == "female"
    assert "Excluded Identifier" not in first.model_dump_json()
    monkeypatch.setenv("TENANT_ID", "tenant-b")
    second = fhir.read_patients()
    assert first.items[0].display_token != second.items[0].display_token
    cursor = base64.urlsafe_b64encode(
        b"https://healthlake.us-east-1.amazonaws.com/datastore/test/r4/Patient?_count=20&page=token:/="
    ).decode()
    assert len(fhir.read_patients(cursor).items) == 1


def test_pagination_cannot_send_credentials_to_another_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "FHIR_ENDPOINT", "https://healthlake.us-east-1.amazonaws.com/datastore/test/r4/"
    )
    cursor = base64.urlsafe_b64encode(b"https://example.invalid/Patient").decode()
    with pytest.raises(ValueError, match="does not belong"):
        fhir.read_patients(cursor)


def test_patient_endpoint_requires_authentication() -> None:
    with TestClient(main.app) as client:
        assert client.get("/patients").status_code == 401


def test_expired_window_does_not_query_fhir(monkeypatch: pytest.MonkeyPatch) -> None:
    user = main.Principal(sub="test", tenant_id=uuid4(), roles=["PHYSICIAN"])
    main.app.dependency_overrides[main.principal] = lambda: user
    monkeypatch.setenv("FHIR_EXPIRES_AT", "2020-01-01T00:00:00Z")
    monkeypatch.setattr(main, "authorize", lambda user, action: None)

    def unexpected_read(cursor: str | None) -> None:
        pytest.fail("An expired window queried the FHIR store")

    monkeypatch.setattr(main, "read_patients", unexpected_read)
    try:
        with TestClient(main.app) as client:
            assert client.get("/patients").status_code == 410
    finally:
        main.app.dependency_overrides.clear()
