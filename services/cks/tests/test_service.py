"""Only unit tests inject trusted gateway metadata or substitute the reference client."""

from typing import Any
from uuid import UUID

import pytest
from cks.schemas import ClassesResult, LabelsResult, NormalizationResult
from cks.service import Caller, Settings, authorize, create_app
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

TENANT = UUID("97d7aa7f-d4a0-4af0-ae84-131142081e90")


def settings() -> Settings:
    return Settings(
        api_id="unitapi",
        hub_account_id="111111111111",
        stage="v1",
        callers=[
            Caller(
                role_arn="arn:aws:iam::222222222222:role/cells/reference-client",
                tenant_id=TENANT,
                endpoint_ids=["vpce-unit-a"],
                operations=["normalize", "classes", "labels"],
            )
        ],
    )


def context() -> dict[str, Any]:
    return {
        "apiId": "unitapi",
        "accountId": "111111111111",
        "stage": "v1",
        "identity": {
            "accountId": "222222222222",
            "caller": "unit-session",
            "userArn": "arn:aws:sts::222222222222:assumed-role/reference-client/unit-session",
            "vpceId": "vpce-unit-a",
        },
    }


class Gateway:
    def __init__(self, app: ASGIApp, event: dict[str, Any]) -> None:
        self.app, self.event = app, event

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            scope["aws.event"] = self.event
        await self.app(scope, receive, send)


class Reference:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail = False

    async def normalize_drug(self, drug_text: str) -> NormalizationResult:
        self.calls.append("normalize")
        if self.fail:
            raise RuntimeError("unit-private-error-payload")
        return NormalizationResult(
            status="UNVERIFIED", reason="UNIT_PROVIDER_UNAVAILABLE"
        )

    async def drug_classes(self, rxcui: str) -> ClassesResult:
        self.calls.append("classes")
        return ClassesResult(status="NOT_FOUND", reason="UNIT_NO_REFERENCE")

    async def label_sections(self, rxcui: str, sections: list[str]) -> LabelsResult:
        self.calls.append("labels")
        return LabelsResult(status="REVIEW_REQUIRED", reason="UNIT_PARTIAL_REFERENCE")


def test_unsigned_http_and_forged_headers_do_not_authenticate() -> None:
    app = create_app(settings())
    with TestClient(app) as client:
        fake = Reference()
        app.state.knowledge = fake
        response = client.post(
            "/normalize",
            json={"drug_text": "unit-drug"},
            headers={
                "Authorization": "AWS4-HMAC-SHA256 unit-fake",
                "x-tenant-id": str(TENANT),
                "x-user-arn": context()["identity"]["userArn"],
            },
        )
    assert response.status_code == 401 and not fake.calls
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "change",
    [
        "api",
        "stage",
        "hub",
        "role",
        "account",
        "endpoint",
        "identity_account",
        "no_caller",
        "no_identity",
    ],
)
def test_invalid_gateway_identity_cannot_reach_provider(change: str) -> None:
    ctx = context()
    if change == "api":
        ctx["apiId"] = "different"
    elif change == "stage":
        ctx["stage"] = "different"
    elif change == "hub":
        ctx["accountId"] = "999999999999"
    elif change == "role":
        ctx["identity"]["userArn"] = (
            "arn:aws:sts::222222222222:assumed-role/other/unit-session"
        )
    elif change == "account":
        ctx["identity"]["userArn"] = (
            "arn:aws:sts::333333333333:assumed-role/reference-client/unit-session"
        )
    elif change == "endpoint":
        ctx["identity"]["vpceId"] = "vpce-unit-b"
    elif change == "identity_account":
        ctx["identity"]["accountId"] = "333333333333"
    elif change == "no_caller":
        del ctx["identity"]["caller"]
    else:
        ctx["identity"] = {}
    app = create_app(settings())
    with TestClient(Gateway(app, {"requestContext": ctx})) as client:
        fake = Reference()
        app.state.knowledge = fake
        response = client.post("/normalize", json={"drug_text": "unit-drug"})
    assert response.status_code in {401, 403} and not fake.calls
    assert response.headers["content-type"] == "application/problem+json"


def test_role_operation_permissions_and_tenant_binding() -> None:
    config = settings()
    config.callers[0].operations = ["normalize"]
    app = create_app(config)
    with TestClient(Gateway(app, {"requestContext": context()})) as client:
        fake = Reference()
        app.state.knowledge = fake
        denied = client.post("/classes", json={"rxcui": "12345"})
        allowed = client.post("/normalize", json={"drug_text": "unit-drug"})
        request = Request(
            {"type": "http", "app": app, "aws.event": {"requestContext": context()}}
        )
        assert authorize(request, "normalize").tenant_id == TENANT
    assert denied.status_code == 403
    assert allowed.status_code == 200 and allowed.json()["status"] == "UNVERIFIED"
    assert fake.calls == ["normalize"]


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/normalize", {"drug_text": "patient MRN 12345"}),
        ("/normalize", {"drug_text": "unit-drug", "tenant_id": str(TENANT)}),
        ("/classes", {"rxcui": '123" OR *'}),
        ("/labels", {"rxcui": "12345", "sections": ["unknown"]}),
    ],
)
def test_invalid_drug_only_payload_is_redacted(
    path: str, payload: dict[str, Any]
) -> None:
    app = create_app(settings())
    with TestClient(Gateway(app, {"requestContext": context()})) as client:
        fake = Reference()
        app.state.knowledge = fake
        response = client.post(path, json=payload)
    assert response.status_code == 422 and not fake.calls
    assert response.json()["title"] == "Invalid drug-only request"
    assert "patient" not in response.text and "12345" not in response.text


def test_provider_exception_returns_redacted_problem(
    capsys: pytest.CaptureFixture[str],
) -> None:
    app = create_app(settings())
    with TestClient(Gateway(app, {"requestContext": context()})) as client:
        fake = Reference()
        fake.fail = True
        app.state.knowledge = fake
        response = client.post("/normalize", json={"drug_text": "unit-secret-drug"})
    assert response.status_code == 503 and response.json()["trace_id"]
    assert "unit-private-error-payload" not in response.text
    output = capsys.readouterr().out
    assert (
        "unit-private-error-payload" not in output and "unit-secret-drug" not in output
    )
    assert response.headers["X-Request-ID"] == response.json()["trace_id"]


def test_bounded_body_no_query_and_no_public_schema() -> None:
    app = create_app(settings())
    with TestClient(app) as client:
        large = client.post("/normalize", content=b"x" * 16385)
        query = client.post("/normalize?drug=unit-sensitive")
        schema = client.get("/openapi.json")
    assert large.status_code == 413
    assert query.status_code == 400 and "unit-sensitive" not in query.text
    assert schema.status_code == 404


def test_all_operations_preserve_unverified_or_review_result() -> None:
    app = create_app(settings())
    with TestClient(Gateway(app, {"requestContext": context()})) as client:
        fake = Reference()
        app.state.knowledge = fake
        classes = client.post("/classes", json={"rxcui": "12345"})
        labels = client.post(
            "/labels", json={"rxcui": "12345", "sections": ["warnings"]}
        )
    assert classes.json()["status"] == "NOT_FOUND"
    assert labels.json()["status"] == "REVIEW_REQUIRED"
    for item in app.openapi()["paths"].values():
        operation = item["post"]
        assert operation["security"] == [{"sigv4": []}]
        assert "503" in operation["responses"]


def test_duplicate_role_tenant_bindings_rejected() -> None:
    config = settings().model_dump()
    config["callers"] *= 2
    with pytest.raises(ValueError):
        Settings.model_validate(config)


def test_request_timeout_returns_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from cks import service

    class SlowReference(Reference):
        async def normalize_drug(self, drug_text: str) -> NormalizationResult:
            await asyncio.sleep(0.05)
            return NormalizationResult(status="RESOLVED", reason="UNIT_LATE")

    monkeypatch.setattr(service, "REQUEST_TIMEOUT", 0.01)
    app = create_app(settings())
    with TestClient(Gateway(app, {"requestContext": context()})) as client:
        app.state.knowledge = SlowReference()
        response = client.post("/normalize", json={"drug_text": "unit-drug"})
    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    assert "UNIT_LATE" not in response.text
