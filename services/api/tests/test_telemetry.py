"""Real SDK serialization and signed transport boundary; network doubles only here."""

from typing import Any

import pytest
import requests
from app import telemetry
from botocore.credentials import Credentials  # type: ignore[import-untyped]
from opentelemetry import trace as otel_trace
from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import Event, ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.trace import SpanContext, Status, StatusCode, TraceFlags, TraceState
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient


class WireExporter(SpanExporter):
    def __init__(self) -> None:
        self.spans: list[ReadableSpan] = []
        self.wire: list[bytes] = []

    def export(self, spans: Any) -> SpanExportResult:
        self.spans.extend(spans)
        self.wire.append(encode_spans(spans).SerializeToString())
        return SpanExportResult.SUCCESS


def test_real_protobuf_contains_only_allowlisted_fields() -> None:
    marker = "sensitive-clinical-marker"
    context = SpanContext(1, 2, False, TraceFlags(1), TraceState([("vendor", marker)]))
    span = ReadableSpan(
        marker,
        context=context,
        parent=context,
        resource=Resource({"patient": marker}),
        attributes={"db.statement": marker, "http.response.status_code": 503},
        events=[Event(marker, {"exception.message": marker})],
        status=Status(StatusCode.ERROR, marker),
        start_time=1,
        end_time=2,
    )
    target = WireExporter()
    exporter = telemetry.SafeExporter(
        target, Resource({"service.name": "chartvigil-api"})
    )
    assert exporter.export([span]) is SpanExportResult.SUCCESS
    assert marker.encode() not in target.wire[0]
    safe = target.spans[0]
    assert safe.name == "operation" and not safe.events and not safe.links
    assert safe.status.description is None
    assert safe.context is not None and not list(safe.context.trace_state.items())
    assert safe.attributes == {"http.response.status_code": 503}


def test_exporter_failure_is_static_and_emits_metric(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class Failed(SpanExporter):
        def export(self, spans: Any) -> SpanExportResult:
            raise RuntimeError("sensitive-provider-marker")

    result = telemetry.SafeExporter(
        Failed(), Resource({"service.name": "chartvigil-api"})
    ).export([])
    assert result is SpanExportResult.FAILURE
    output = capsys.readouterr()
    assert "sensitive-provider-marker" not in output.out + output.err
    assert "TraceExportFailures" in output.out


class RoleSession:
    def __init__(self) -> None:
        self.calls = 0

    def get_credentials(self) -> Credentials:
        self.calls += 1
        return Credentials("unit-access", "unit-secret", "unit-session")


def test_signer_refreshes_credentials_and_rejects_other_destinations() -> None:
    role = RoleSession()
    auth = telemetry.RoleAuth(
        role, "us-east-1", "https://xray.us-east-1.amazonaws.com/v1/traces"
    )
    for _ in range(2):
        request = requests.Request("POST", auth.endpoint, data=b"unit-packet").prepare()
        signed = auth(request)
        assert "xray/aws4_request" in signed.headers["Authorization"]
        assert signed.headers["X-Amz-Security-Token"] == "unit-session"
    assert role.calls == 2
    with pytest.raises(ValueError, match="destination"):
        auth(requests.Request("POST", "https://other.invalid", data=b"unit").prepare())
    assert role.calls == 2


def test_transport_enforces_tls_no_redirects_and_scrubs_error_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options: dict[str, Any] = {}

    def request(self: Any, method: str, url: str, **kwargs: Any) -> requests.Response:
        options.update(kwargs)
        response = requests.Response()
        response.status_code = 403
        response._content = b"sensitive-credential-marker"
        response.reason = "sensitive-credential-marker"
        return response

    monkeypatch.setattr(requests.Session, "request", request)
    client = telemetry.SignedSession(RoleSession(), "us-east-1")
    response = client.post(
        client.endpoint, data=b"unit", verify=False, allow_redirects=True
    )
    assert options["verify"] is True and options["allow_redirects"] is False
    assert response.content == b"" and "sensitive" not in response.reason
    assert client.trust_env is False
    with pytest.raises(ValueError):
        client.post("http://xray.us-east-1.amazonaws.com/v1/traces")


@pytest.mark.parametrize(
    "parent,valid",
    [
        ("00-" + "1" * 32 + "-" + "2" * 16 + "-01", True),
        ("00-" + "0" * 32 + "-" + "2" * 16 + "-01", False),
        ("sensitive-invalid-parent", False),
    ],
)
def test_request_propagation_excludes_baggage_and_query(
    monkeypatch: pytest.MonkeyPatch, parent: str, valid: bool
) -> None:
    provider = TracerProvider()
    target = WireExporter()
    provider.add_span_processor(
        SimpleSpanProcessor(
            telemetry.SafeExporter(target, Resource({"service.name": "chartvigil-api"}))
        )
    )
    monkeypatch.setattr(otel_trace, "get_tracer", provider.get_tracer)

    async def endpoint(request: Request) -> JSONResponse:
        with provider.get_tracer("unit").start_as_current_span(
            "database.encounters.list"
        ):
            return JSONResponse({"status": "ok"})

    app = Starlette(routes=[Route("/health", endpoint)])
    app.add_middleware(telemetry.TraceMiddleware)
    with TestClient(app) as client:
        response = client.get(
            "/health?patient=sensitive-marker",
            headers={
                "traceparent": parent,
                "baggage": "patient=sensitive-marker",
                "tracestate": "vendor=sensitive-marker",
            },
        )
    assert response.status_code == 200
    assert len(target.spans) == 2
    roots = [span for span in target.spans if span.name == "api.request"]
    assert len(roots) == 1
    assert bool(roots[0].parent) is valid
    if valid:
        assert roots[0].parent is not None and roots[0].parent.trace_id == int(
            "1" * 32, 16
        )
    assert all(b"sensitive-marker" not in packet for packet in target.wire)
    provider.shutdown()
