"""Manual allowlisted spans, W3C propagation and role-signed CloudWatch OTLP."""

import hashlib
import os
import re
import time
from collections.abc import MutableMapping, Sequence
from typing import Any

import boto3  # type: ignore[import-untyped]
import requests
import structlog
from botocore.auth import SigV4Auth  # type: ignore[import-untyped]
from botocore.awsrequest import AWSRequest  # type: ignore[import-untyped]
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.sdk.util.instrumentation import InstrumentationScope
from opentelemetry.trace import SpanContext, Status, StatusCode, TraceFlags, TraceState
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from requests.auth import AuthBase
from starlette.types import ASGIApp, Message, Receive, Scope, Send

NAMES = frozenset(
    {
        "api.request",
        "api.encounters.list",
        "api.patients.list",
        "authorization.list_encounters",
        "authorization.list_patients",
        "database.encounters.list",
        "fhir.patients.list",
        "telemetry.probe",
    }
)


def clean_context(context: SpanContext | None) -> SpanContext | None:
    if context is None:
        return None
    return SpanContext(
        context.trace_id,
        context.span_id,
        context.is_remote,
        TraceFlags(context.trace_flags & TraceFlags.SAMPLED),
        TraceState(),
    )


def clean_span(span: ReadableSpan, resource: Resource) -> ReadableSpan:
    """Reconstruct, rather than redact, every packet before it reaches any exporter."""
    attributes: dict[str, int | str] = {}
    code = (span.attributes or {}).get("http.response.status_code")
    if type(code) is int and 100 <= code <= 599:
        attributes["http.response.status_code"] = code
    if (span.attributes or {}).get("db.system.name") == "postgresql":
        attributes["db.system.name"] = "postgresql"
    return ReadableSpan(
        name=span.name if span.name in NAMES else "operation",
        context=clean_context(span.context),
        parent=clean_context(span.parent),
        resource=resource,
        attributes=attributes,
        events=(),
        links=(),
        kind=span.kind,
        status=Status(span.status.status_code),
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=InstrumentationScope("verimed.api"),
    )


class SafeExporter(SpanExporter):
    def __init__(self, delegate: SpanExporter, resource: Resource) -> None:
        self.delegate, self.resource = delegate, resource

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        try:
            result = self.delegate.export(
                [clean_span(span, self.resource) for span in spans]
            )
        except Exception:  # noqa: BLE001 -- never log exporter exceptions or HTTP response data
            result = SpanExportResult.FAILURE
        if result is SpanExportResult.FAILURE:
            structlog.get_logger().error(
                "trace_export_failed",
                error_code="TRACE_EXPORT_FAILED",
                TraceExportFailures=1,
                _aws={
                    "Timestamp": int(time.time() * 1000),
                    "CloudWatchMetrics": [
                        {
                            "Namespace": "VeriMed",
                            "Dimensions": [[]],
                            "Metrics": [
                                {"Name": "TraceExportFailures", "Unit": "Count"}
                            ],
                        }
                    ],
                },
            )
        return result

    def shutdown(self) -> None:
        self.delegate.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.delegate.force_flush(timeout_millis)


class RoleAuth(AuthBase):
    def __init__(self, session: Any, region: str, endpoint: str) -> None:
        self.session, self.region, self.endpoint = session, region, endpoint

    def __call__(self, request: requests.PreparedRequest) -> requests.PreparedRequest:
        if request.url != self.endpoint or request.method != "POST":
            raise ValueError("Unexpected telemetry destination")
        credentials = self.session.get_credentials()
        if credentials is None:
            raise ValueError("AWS role credentials are unavailable")
        signed = AWSRequest(
            method="POST",
            url=request.url,
            data=request.body,
            headers=dict(request.headers),
        )
        SigV4Auth(credentials.get_frozen_credentials(), "xray", self.region).add_auth(
            signed
        )
        request.headers.update(dict(signed.headers))
        return request


class SignedSession(requests.Session):
    def __init__(self, session: Any, region: str) -> None:
        super().__init__()
        if not re.fullmatch(r"[a-z]{2}-[a-z]+-[0-9]+", region):
            raise ValueError("Invalid AWS telemetry region")
        self.endpoint = f"https://xray.{region}.amazonaws.com/v1/traces"
        self.auth = RoleAuth(session, region, self.endpoint)
        self.trust_env = False

    def request(
        self, method: str | bytes, url: str | bytes, *args: Any, **kwargs: Any
    ) -> requests.Response:
        if (
            args
            or not isinstance(method, str)
            or method.upper() != "POST"
            or url != self.endpoint
        ):
            raise ValueError("Unexpected telemetry destination")
        kwargs["allow_redirects"], kwargs["verify"] = False, True
        response = super().request(method, url, **kwargs)
        if not 200 <= response.status_code < 300:
            # The exporter must not log an AWS error response containing credential metadata.
            response._content = b""
            response.reason = "Telemetry destination unavailable"
        return response


def configure() -> TracerProvider:
    stage = os.environ.get("VERIMED_ENV", "dev")
    attributes = {
        "service.name": "chartvigil-api",
        "deployment.environment.name": stage
        if stage in {"dev", "demo", "prod"}
        else "unknown",
    }
    tenant = os.environ.get("TENANT_ID")
    if tenant:
        attributes["tenant.hash"] = hashlib.sha256(tenant.encode()).hexdigest()[:16]
    resource = Resource(attributes)
    provider = TracerProvider(
        resource=resource, sampler=ParentBased(TraceIdRatioBased(0.05))
    )
    if os.environ.get("VERIMED_TRACE_EXPORTER") == "aws":
        session = SignedSession(
            boto3.Session(), os.environ.get("AWS_REGION", "us-east-1")
        )
        exporter = OTLPSpanExporter(
            endpoint=session.endpoint,
            session=session,
            timeout=2,
            headers={"Content-Type": "application/x-protobuf"},
        )
        provider.add_span_processor(
            BatchSpanProcessor(
                SafeExporter(exporter, resource),
                max_queue_size=512,
                max_export_batch_size=128,
                schedule_delay_millis=100,
                export_timeout_millis=2000,
            )
        )
    else:
        provider.add_span_processor(
            SimpleSpanProcessor(SafeExporter(ConsoleSpanExporter(), resource))
        )
    trace.set_tracer_provider(provider)
    return provider


def log_trace_ids(
    logger: Any, method: str, event: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    context = trace.get_current_span().get_span_context()
    if context.is_valid:
        event["trace_id"] = f"{context.trace_id:032x}"
        event["span_id"] = f"{context.span_id:016x}"
    return event


class TraceMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # Exclude baggage and tracestate, including vendor values containing identifiers.
        parents = [
            value.decode("ascii", errors="ignore")
            for key, value in scope.get("headers", [])
            if key.lower() == b"traceparent" and len(value) == 55
        ]
        carrier = {"traceparent": parents[0]} if len(parents) == 1 else {}
        context = TraceContextTextMapPropagator().extract(carrier)
        with trace.get_tracer("verimed.api").start_as_current_span(
            "api.request",
            context=context,
            kind=trace.SpanKind.SERVER,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:

            async def traced_send(message: Message) -> None:
                if message["type"] == "http.response.start":
                    span.set_attribute("http.response.status_code", message["status"])
                await send(message)

            try:
                await self.app(scope, receive, traced_send)
            except BaseException:
                span.set_status(Status(StatusCode.ERROR))
                raise
