"""Only unit tests replace Lambda SDK transport and public-reference collectors."""

import asyncio
import io
import json
import re
from typing import Any

import pytest
from cks import bridge
from cks.bridge import RemoteKnowledgeClient
from cks.schemas import NormalizationResult


class Lambda:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def invoke(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.response


def test_bridge_preserves_review_state_and_uses_sync_iam_invocation() -> None:
    stream = io.BytesIO(
        json.dumps(
            {
                "status": "REVIEW_REQUIRED",
                "reason": "UNIT_AMBIGUOUS",
                "candidates": [
                    {"rxcui": "12345", "name": "Unit drug", "term_type": "IN"}
                ],
            }
        ).encode()
    )
    sdk = Lambda({"StatusCode": 200, "Payload": stream})
    result = asyncio.run(
        RemoteKnowledgeClient(sdk, "unit-worker").normalize_drug("unit-drug")
    )
    assert result.status == "REVIEW_REQUIRED" and result.rxcui is None and stream.closed
    request = sdk.calls[0]
    assert (
        request["InvocationType"] == "RequestResponse" and request["LogType"] == "None"
    )
    packet = json.loads(request["Payload"])
    assert packet["operation"] == "normalize" and packet["query"] == {
        "drug_text": "unit-drug"
    }
    assert re.fullmatch(
        r"[0-9a-f]{2}-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}", packet["traceparent"]
    )


@pytest.mark.parametrize(
    "case",
    [
        "function_error",
        "bad_json",
        "bad_schema",
        "oversized",
        "missing",
        "async_status",
    ],
)
def test_bridge_failures_are_unverified_and_streams_closed(case: str) -> None:
    body = (
        b"bad"
        if case == "bad_json"
        else b"x" * 2_000_001
        if case == "oversized"
        else b"{}"
    )
    stream = io.BytesIO(body)
    response: dict[str, Any] = {"StatusCode": 200, "Payload": stream}
    if case == "function_error":
        response["FunctionError"] = "Unhandled"
    if case == "missing":
        response.pop("Payload")
    if case == "async_status":
        response["StatusCode"] = 202
    result = asyncio.run(
        RemoteKnowledgeClient(Lambda(response), "unit-worker").drug_classes("12345")
    )
    assert result.status == "UNVERIFIED"
    assert stream.closed or case == "missing"


def test_invalid_inputs_do_not_invoke_worker() -> None:
    async def run() -> None:
        sdk = Lambda({})
        client = RemoteKnowledgeClient(sdk, "unit-worker")
        assert (await client.normalize_drug("patient MRN 12345")).status == "UNVERIFIED"
        assert (await client.drug_classes("x")).status == "UNVERIFIED"
        assert (
            await client.label_sections("12345", ["unknown"])
        ).status == "UNVERIFIED"
        assert not sdk.calls

    asyncio.run(run())


@pytest.mark.parametrize(
    "event",
    [
        {"operation": "delete", "query": {}},
        {
            "operation": "normalize",
            "query": {"drug_text": "unit-drug"},
            "tenant_id": "other",
        },
        {"operation": "normalize", "query": {"drug_text": "patient MRN 12345"}},
    ],
)
def test_worker_rejects_unsupported_or_identifying_request(
    event: dict[str, Any],
) -> None:
    result = bridge.handler(event, None)
    assert (
        result["status"] == "UNVERIFIED"
        and result["reason"] == "INVALID_REFERENCE_REQUEST"
    )


def test_unexpected_collector_error_is_not_serialized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing(request: bridge.RpcRequest) -> NormalizationResult:
        raise RuntimeError("unit-sensitive-upstream-body")

    monkeypatch.setattr(bridge, "collect", failing)
    result = bridge.handler(
        {"operation": "normalize", "query": {"drug_text": "unit-drug"}}, None
    )
    assert result == {"status": "UNVERIFIED", "reason": "REFERENCE_WORKER_UNAVAILABLE"}


def test_worker_accepts_only_validated_query_before_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing(request: bridge.RpcRequest) -> NormalizationResult:
        raise TimeoutError

    monkeypatch.setattr(bridge, "collect", failing)
    result = bridge.handler({"operation": "classes", "query": {"rxcui": "12345"}}, None)
    assert result == {"status": "UNVERIFIED", "reason": "REFERENCE_WORKER_TIMEOUT"}


def test_trace_context_survives_worker_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opentelemetry import trace

    captured: dict[str, str] = {}

    async def collect(request: bridge.RpcRequest) -> NormalizationResult:
        captured["worker_trace"] = format(
            trace.get_current_span().get_span_context().trace_id, "032x"
        )
        return NormalizationResult(status="UNVERIFIED", reason="UNIT_TRACE_PROBE")

    monkeypatch.setattr(bridge, "collect", collect)

    class Transport:
        def invoke(self, **kwargs: Any) -> dict[str, Any]:
            request = json.loads(kwargs["Payload"])
            captured["caller_trace"] = request["traceparent"].split("-")[1]
            result = bridge.handler(request, None)
            return {
                "StatusCode": 200,
                "Payload": io.BytesIO(json.dumps(result).encode()),
            }

    result = asyncio.run(
        RemoteKnowledgeClient(Transport(), "unit-worker").normalize_drug("unit-drug")
    )
    assert (
        result.status == "UNVERIFIED"
        and captured["worker_trace"] == captured["caller_trace"]
    )
