"""Read-only Worklist API, reached through API Gateway's Cognito authorizer."""

import json
import os
import time
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

import boto3  # type: ignore[import-untyped]
import structlog
from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from mangum import Mangum
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from pydantic import AwareDatetime, BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("verimed.api")
structlog.configure(processors=[structlog.processors.JSONRenderer()])
logger = structlog.get_logger()
app = FastAPI(title="ChartVigil cell API", version="0.1.0", root_path="/v1")
bearer = HTTPBearer(auto_error=False)
Status = Literal[
    "INGESTING", "READY_FOR_AUDIT", "AUDITING", "IN_REVIEW", "SIGNED", "FAILED"
]


class Principal(BaseModel):
    sub: str
    tenant_id: UUID
    roles: list[str]


class Encounter(BaseModel):
    id: UUID
    patient_token: str
    birth_year: int | None
    sex: str | None
    started_at: AwareDatetime
    status: Status
    scribe_adapter: str
    assigned_user_id: UUID | None


class EncounterPage(BaseModel):
    items: list[Encounter]
    has_more: bool


def aws_client(service: str) -> Any:
    return boto3.client(service)


def begin_read_transaction(client: Any, connection: dict[str, str]) -> str:
    for delay in (2, 4, 8):
        try:
            return str(client.begin_transaction(**connection)["transactionId"])
        except ClientError as error:
            if error.response["Error"]["Code"] != "DatabaseResumingException":
                raise
            time.sleep(delay)
    return str(client.begin_transaction(**connection)["transactionId"])


def principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Principal:
    event = request.scope.get("aws.event", {})
    claims = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
    )
    if (
        credentials is None
        or not claims.get("sub")
        or claims.get("token_use") != "access"
    ):
        raise HTTPException(401, "A valid Cognito access token is required")
    if claims.get("client_id") != os.environ["COGNITO_CLIENT_ID"]:
        raise HTTPException(401, "The token was issued for a different client")
    roles = claims.get("cognito:groups", [])
    if isinstance(roles, str):
        # HTTP API exposes array claims as JSON strings or bracketed values.
        try:
            roles = json.loads(roles)
        except json.JSONDecodeError:
            roles = roles.strip("[]").split(",")
    if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
        raise HTTPException(403, "No valid clinical role is assigned")
    return Principal(
        sub=claims["sub"], tenant_id=UUID(os.environ["TENANT_ID"]), roles=roles
    )


def authorize(user: Principal) -> None:
    tenant = str(user.tenant_id)
    with tracer.start_as_current_span(
        "authorization.list_encounters",
        record_exception=False,
        set_status_on_exception=False,
    ):
        result = aws_client("verifiedpermissions").is_authorized(
            policyStoreId=os.environ["POLICY_STORE_ID"],
            principal={"entityType": "VeriMed::User", "entityId": user.sub},
            action={"actionType": "VeriMed::Action", "actionId": "ListEncounters"},
            resource={"entityType": "VeriMed::Tenant", "entityId": tenant},
            entities={
                "entityList": [
                    {
                        "identifier": {
                            "entityType": "VeriMed::User",
                            "entityId": user.sub,
                        },
                        "attributes": {
                            "tenant": {"string": tenant},
                            "roles": {"set": [{"string": role} for role in user.roles]},
                        },
                        "parents": [],
                    },
                    {
                        "identifier": {
                            "entityType": "VeriMed::Tenant",
                            "entityId": tenant,
                        },
                        "attributes": {"tenant": {"string": tenant}},
                        "parents": [],
                    },
                ]
            },
        )
    if result["decision"] != "ALLOW" or result.get("errors"):
        raise HTTPException(403, "Worklist access is not permitted")


def list_encounters(
    user: Principal, status: Status | None, limit: int
) -> EncounterPage:
    client = aws_client("rds-data")
    connection = {
        "resourceArn": os.environ["DATABASE_CLUSTER_ARN"],
        "secretArn": os.environ["DATABASE_SECRET_ARN"],
        "database": "verimed",
    }
    with tracer.start_as_current_span(
        "database.encounters.list",
        record_exception=False,
        set_status_on_exception=False,
    ):
        transaction = begin_read_transaction(client, connection)
        try:
            client.execute_statement(
                **connection,
                transactionId=transaction,
                sql="SET LOCAL ROLE verimed_api",
            )
            client.execute_statement(
                **connection,
                transactionId=transaction,
                sql="SELECT set_config('app.tenant_id', :tenant, true)",
                parameters=[
                    {"name": "tenant", "value": {"stringValue": str(user.tenant_id)}}
                ],
            )
            # RLS scopes both tables. Composite foreign keys enforce matching tenant ownership.
            statement = """
                SELECT e.id::text, p.display_token AS patient_token, p.birth_year, p.sex,
                       to_char(e.started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS started_at,
                       e.status, e.scribe_adapter, e.assigned_user_id::text
                FROM encounters e JOIN patients p
                ON p.id = e.patient_id AND p.tenant_id = e.tenant_id
                WHERE (:status = '' OR e.status = :status)
                ORDER BY e.started_at DESC, e.id DESC LIMIT :page_size
            """
            result = client.execute_statement(
                **connection,
                transactionId=transaction,
                sql=statement,
                parameters=[
                    {"name": "status", "value": {"stringValue": status or ""}},
                    {"name": "page_size", "value": {"longValue": limit + 1}},
                ],
                formatRecordsAs="JSON",
            )
            items = [
                Encounter.model_validate(row)
                for row in json.loads(result["formattedRecords"])
            ]
            client.commit_transaction(
                resourceArn=connection["resourceArn"],
                secretArn=connection["secretArn"],
                transactionId=transaction,
            )
        except Exception:
            client.rollback_transaction(
                resourceArn=connection["resourceArn"],
                secretArn=connection["secretArn"],
                transactionId=transaction,
            )
            raise
    return EncounterPage(items=items[:limit], has_more=len(items) > limit)


@app.exception_handler(StarletteHTTPException)
def http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        media_type="application/problem+json",
        content={
            "type": "about:blank",
            "title": str(error.detail),
            "status": error.status_code,
        },
    )


@app.exception_handler(Exception)
def unexpected_error(request: Request, error: Exception) -> JSONResponse:
    # Do not serialize exception text, request content, tokens or clinical records.
    logger.error("request_failed", error_type=type(error).__name__)
    return JSONResponse(
        status_code=503,
        media_type="application/problem+json",
        content={
            "type": "about:blank",
            "title": "Encounter service is temporarily unavailable",
            "status": 503,
        },
    )


@app.exception_handler(RequestValidationError)
def invalid_request(request: Request, error: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        media_type="application/problem+json",
        content={
            "type": "about:blank",
            "title": "Invalid request parameters",
            "status": 422,
        },
    )


@app.get("/health", tags=["operations"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/encounters", response_model=EncounterPage, tags=["encounters"])
def encounters(
    user: Annotated[Principal, Depends(principal)],
    status: Status | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> EncounterPage:
    with tracer.start_as_current_span(
        "api.encounters.list", record_exception=False, set_status_on_exception=False
    ):
        authorize(user)
        result = list_encounters(user, status, limit)
        logger.info(
            "worklist_read",
            outcome="success",
            _aws={
                "Timestamp": int(datetime.now().timestamp() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": "VeriMed",
                        "Dimensions": [[]],
                        "Metrics": [{"Name": "WorklistReads", "Unit": "Count"}],
                    }
                ],
            },
            WorklistReads=1,
        )
        return result


handler = Mangum(app, api_gateway_base_path="/v1", lifespan="off")
