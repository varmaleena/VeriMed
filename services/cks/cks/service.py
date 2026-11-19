"""Private CKS boundary. IAM authentication is performed by API Gateway, never headers."""

import asyncio
import json
import logging
import os
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Literal
from uuid import UUID, uuid4

import httpx
import structlog
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from mangum import Mangum
from opentelemetry import trace
from pydantic import Field, model_validator
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from .bridge import RemoteKnowledgeClient
from .cache import CachedKnowledgeClient, ValkeyStore
from .client import KnowledgeClient, ReferenceClient
from .runtime import remote_client, secret_store
from .schemas import (
    ClassesResult,
    DrugQuery,
    LabelQuery,
    LabelsResult,
    NormalizationResult,
    RxCuiQuery,
    StrictModel,
)
from .telemetry import configure

Operation = Literal["normalize", "classes", "labels"]
ROLE = re.compile(
    r"^arn:aws:iam::([0-9]{12}):role/(?:[A-Za-z0-9+=,.@_-]+/)*([A-Za-z0-9+=,.@_-]+)$"
)
SESSION = re.compile(
    r"^arn:aws:sts::([0-9]{12}):assumed-role/([A-Za-z0-9+=,.@_-]+)/[A-Za-z0-9+=,.@_-]+$"
)
REQUEST_TIMEOUT = 20.0
logger = structlog.get_logger()
configure()
tracer = trace.get_tracer("verimed.cks.service")


class Caller(StrictModel):
    role_arn: str = Field(pattern=ROLE.pattern)
    tenant_id: UUID
    endpoint_ids: list[str] = Field(min_length=1, max_length=10)
    operations: list[Operation] = Field(min_length=1, max_length=3)


class Settings(StrictModel):
    api_id: str = Field(min_length=1)
    hub_account_id: str = Field(pattern=r"^[0-9]{12}$")
    stage: str = Field(min_length=1)
    callers: list[Caller] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_roles(self) -> "Settings":
        if len({c.role_arn for c in self.callers}) != len(self.callers):
            raise ValueError("Each caller role must have exactly one tenant binding")
        return self

    @classmethod
    def environment(cls) -> "Settings":
        return cls(
            api_id=os.environ["CKS_API_ID"],
            hub_account_id=os.environ["CKS_HUB_ACCOUNT_ID"],
            stage=os.environ["CKS_STAGE"],
            callers=json.loads(os.environ["CKS_CALLERS_JSON"]),
        )


Knowledge = ReferenceClient


def authorize(request: Request, operation: Operation) -> Caller:
    # aws.event is injected by Mangum from Lambda's trusted proxy event.
    # HTTP headers/body cannot create it. Deployment must restrict Lambda invocation to the gateway.
    event = request.scope.get("aws.event", {})
    context = event.get("requestContext", {})
    identity = context.get("identity", {})
    settings: Settings = request.app.state.settings
    if (
        context.get("apiId") != settings.api_id
        or context.get("accountId") != settings.hub_account_id
        or context.get("stage") != settings.stage
        or not identity.get("caller")
    ):
        raise HTTPException(401, "Authenticated private service request required")
    arn = identity.get("userArn", "")
    if not isinstance(arn, str):
        raise HTTPException(401, "Authenticated private service request required")
    session = SESSION.fullmatch(arn)
    for caller in settings.callers:
        role = ROLE.fullmatch(caller.role_arn)
        assert role is not None
        matches = arn == caller.role_arn or (
            session is not None
            and session.group(1) == role.group(1)
            and session.group(2) == role.group(2)
        )
        if matches:
            if (
                identity.get("accountId") != role.group(1)
                or identity.get("vpceId") not in caller.endpoint_ids
                or operation not in caller.operations
            ):
                raise HTTPException(403, "Service operation not permitted")
            return caller
    raise HTTPException(403, "Service operation not permitted")


def gate(operation: Operation) -> Callable[[Request], Caller]:
    def check(request: Request) -> Caller:
        return authorize(request, operation)

    return check


def problem(request: Request, status: int, title: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={
            "type": "about:blank",
            "title": title,
            "status": status,
            "trace_id": getattr(request.state, "trace_id", "unavailable"),
        },
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings or Settings.environment()
        structlog.configure(processors=[structlog.processors.JSONRenderer()])
        for name in ("httpx", "httpcore"):
            logging.getLogger(name).setLevel(logging.WARNING)
        async with httpx.AsyncClient(
            timeout=10, follow_redirects=False, limits=httpx.Limits(max_connections=8)
        ) as http:
            store: ValkeyStore | None = None
            remote: RemoteKnowledgeClient | None = None
            try:
                upstream: ReferenceClient
                if os.environ.get("CKS_REFERENCE_WORKER_ARN"):
                    remote = remote_client(os.environ["CKS_REFERENCE_WORKER_ARN"])
                    upstream = remote
                elif os.environ.get("CKS_PRIVATE_MODE") == "true":
                    raise ValueError("Private CKS requires a reference worker")
                else:
                    upstream = KnowledgeClient(http)
                if os.environ.get("CKS_CACHE_SECRET_ARN"):
                    store = await secret_store(
                        os.environ["CKS_CACHE_SECRET_ARN"], os.environ["CKS_CACHE_HOST"]
                    )
                    app.state.knowledge = CachedKnowledgeClient(upstream, store)
                elif os.environ.get("VALKEY_URL"):
                    store = ValkeyStore(os.environ["VALKEY_URL"])
                    app.state.knowledge = CachedKnowledgeClient(upstream, store)
                else:
                    app.state.knowledge = upstream
                yield
            finally:
                if store is not None:
                    await store.aclose()
                if remote is not None:
                    await remote.aclose()

    app = FastAPI(
        title="ChartVigil private reference API",
        version="0.1.0",
        description="HIPAA-aligned design, synthetic data only. Drug-only service requests.",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.middleware("http")
    async def bounded_request(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.trace_id = uuid4().hex
        started = time.monotonic()
        status = 503
        with tracer.start_as_current_span(
            "cks.service.request", record_exception=False, set_status_on_exception=False
        ) as span:
            request.state.trace_id = format(span.get_span_context().trace_id, "032x")
            span.set_attribute("request.id", request.state.trace_id)
            try:
                # Queries are drug-only POST bodies; never permit URL query text.
                if request.query_params:
                    response: Response = problem(
                        request, 400, "Query parameters are not accepted"
                    )
                else:
                    async with asyncio.timeout(REQUEST_TIMEOUT):
                        body = bytearray()
                        async for chunk in request.stream():
                            body.extend(chunk)
                            if len(body) > 16384:
                                break
                        if len(body) > 16384:
                            response = problem(request, 413, "Request body too large")
                        else:
                            request._body = bytes(body)
                            response = await call_next(request)
                status = response.status_code
            except TimeoutError:
                response = problem(
                    request,
                    503,
                    "Reference request timed out; verification unavailable",
                )
            except Exception:  # noqa: BLE001 -- Boundary must not leak credentials, drug text, or provider exceptions.
                response = problem(request, 503, "Reference service unavailable")
            span.set_attribute("http.response.status_code", response.status_code)
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Request-ID"] = request.state.trace_id
            logger.info(
                "cks_request",
                trace_id=request.state.trace_id,
                status=response.status_code,
                duration_ms=round((time.monotonic() - started) * 1000),
                _aws={
                    "Timestamp": int(time.time() * 1000),
                    "CloudWatchMetrics": [
                        {
                            "Namespace": "VeriMed/CKS",
                            "Dimensions": [[]],
                            "Metrics": [
                                {"Name": "ServiceRequests", "Unit": "Count"},
                                {"Name": "ServiceFailures", "Unit": "Count"},
                            ],
                        }
                    ],
                },
                ServiceRequests=1,
                ServiceFailures=int(status >= 500),
            )
            return response

    @app.exception_handler(StarletteHTTPException)
    async def denied(request: Request, error: StarletteHTTPException) -> JSONResponse:
        titles = {
            401: "Authenticated private service request required",
            403: "Service operation not permitted",
            404: "Reference route not found",
            405: "Method not permitted",
        }
        return problem(
            request,
            error.status_code,
            titles.get(error.status_code, "Request rejected"),
        )

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, error: RequestValidationError) -> JSONResponse:
        return problem(request, 422, "Invalid drug-only request")

    def knowledge(request: Request) -> Knowledge:
        return request.app.state.knowledge  # type: ignore[no-any-return]

    @app.post(
        "/normalize",
        response_model=NormalizationResult,
        dependencies=[Depends(gate("normalize"))],
    )
    async def normalize(
        query: DrugQuery, client: Annotated[Knowledge, Depends(knowledge)]
    ) -> NormalizationResult:
        return await client.normalize_drug(query.drug_text)

    @app.post(
        "/classes",
        response_model=ClassesResult,
        dependencies=[Depends(gate("classes"))],
    )
    async def classes(
        query: RxCuiQuery, client: Annotated[Knowledge, Depends(knowledge)]
    ) -> ClassesResult:
        return await client.drug_classes(query.rxcui)

    @app.post(
        "/labels", response_model=LabelsResult, dependencies=[Depends(gate("labels"))]
    )
    async def labels(
        query: LabelQuery, client: Annotated[Knowledge, Depends(knowledge)]
    ) -> LabelsResult:
        return await client.label_sections(query.rxcui, list(query.sections))

    schema = app.openapi()
    schema.setdefault("components", {})["securitySchemes"] = {
        "sigv4": {
            "type": "apiKey",
            "name": "Authorization",
            "in": "header",
            "description": "AWS SigV4 execute-api. API Gateway AWS_IAM verifies the signature.",
            "x-amazon-apigateway-authtype": "awsSigv4",
        }
    }
    for item in schema["paths"].values():
        for operation in item.values():
            operation["security"] = [{"sigv4": []}]
            for code in ("400", "401", "403", "413", "422", "503"):
                operation["responses"][code] = {
                    "description": "Redacted problem response; no clinical verification implied",
                    "content": {
                        "application/problem+json": {"schema": {"type": "object"}}
                    },
                }
    app.openapi_schema = schema
    return app


app = create_app()
handler = Mangum(app, lifespan="on")
