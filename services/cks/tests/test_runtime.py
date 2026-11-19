import asyncio
import json
from typing import Any

import pytest
from cks import runtime
from cks.schemas import ClassesResult, LabelsResult, NormalizationResult
from cks.service import create_app
from fastapi.testclient import TestClient


@pytest.mark.parametrize("model", [NormalizationResult, ClassesResult, LabelsResult])
def test_resolved_without_evidence_is_rejected(model: Any) -> None:
    with pytest.raises(ValueError):
        model(status="RESOLVED", reason="UNIT_UNSUPPORTED")


def test_review_result_cannot_select_a_concept() -> None:
    with pytest.raises(ValueError):
        NormalizationResult(
            status="REVIEW_REQUIRED", reason="UNIT_AMBIGUOUS", rxcui="12345"
        )


def test_private_runtime_never_falls_back_to_direct_internet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cks.service import Settings

    monkeypatch.setenv("CKS_PRIVATE_MODE", "true")
    monkeypatch.delenv("CKS_REFERENCE_WORKER_ARN", raising=False)
    config = Settings.model_validate(
        {
            "api_id": "unit",
            "hub_account_id": "111111111111",
            "stage": "v1",
            "callers": [
                {
                    "role_arn": "arn:aws:iam::222222222222:role/unit",
                    "tenant_id": "97d7aa7f-d4a0-4af0-ae84-131142081e90",
                    "endpoint_ids": ["vpce-unit"],
                    "operations": ["normalize"],
                }
            ],
        }
    )
    with (
        pytest.raises(ValueError, match="requires a reference worker"),
        TestClient(create_app(config)),
    ):
        pytest.fail("Private runtime started without a reference worker")


def test_cache_credentials_loaded_from_secret_and_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Secrets:
        closed = False

        def get_secret_value(self, **kwargs: str) -> dict[str, str]:
            assert kwargs == {"SecretId": "unit-secret-arn"}
            return {
                "SecretString": json.dumps(
                    {"username": "cks", "password": "unit-password-for-testing-only"}
                )
            }

        def close(self) -> None:
            self.closed = True

    sdk = Secrets()
    monkeypatch.setattr("cks.runtime.boto3.client", lambda *args, **kwargs: sdk)

    async def run() -> None:
        store = await runtime.secret_store("unit-secret-arn", "unit-cache.internal")
        options = store.client.connection_pool.connection_kwargs
        assert options["username"] == "cks" and options["ssl_check_hostname"] is True
        assert options["password"] == "unit-password-for-testing-only"
        assert sdk.closed
        await store.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("host", ["host/path", "host?tls=false", "host@other", ""])
def test_invalid_cache_host_rejected_before_secret_call(
    host: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "cks.runtime.boto3.client",
        lambda *args, **kwargs: pytest.fail("Invalid host reached SDK"),
    )
    with pytest.raises(ValueError):
        asyncio.run(runtime.secret_store("unit", host))
