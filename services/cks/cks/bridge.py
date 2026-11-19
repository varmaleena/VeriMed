"""IAM-only bounded Lambda bridge for fixed-host public reference retrieval."""

import asyncio
from typing import Any, Literal, TypeVar

import httpx
import structlog
from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]
from opentelemetry import trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from pydantic import Field, ValidationError

from .client import KnowledgeClient
from .schemas import (
    ClassesResult,
    DrugQuery,
    LabelQuery,
    LabelsResult,
    NormalizationResult,
    RxCuiQuery,
    StrictModel,
)

Operation = Literal["normalize", "classes", "labels"]
Result = TypeVar("Result", NormalizationResult, ClassesResult, LabelsResult)
tracer = trace.get_tracer("verimed.cks.bridge")
MAX_BYTES = 2_000_000
from .telemetry import configure


class RpcRequest(StrictModel):
    operation: Operation
    query: dict[str, object]
    traceparent: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{2}-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$"
    )


async def collect(
    request: RpcRequest,
) -> NormalizationResult | ClassesResult | LabelsResult:
    async with httpx.AsyncClient(
        timeout=10, follow_redirects=False, limits=httpx.Limits(max_connections=4)
    ) as http:
        client = KnowledgeClient(http)
        if request.operation == "normalize":
            drug = DrugQuery.model_validate(request.query)
            return await client.normalize_drug(drug.drug_text)
        if request.operation == "classes":
            rxcui = RxCuiQuery.model_validate(request.query)
            return await client.drug_classes(rxcui.rxcui)
        label = LabelQuery.model_validate(request.query)
        return await client.label_sections(label.rxcui, list(label.sections))


async def bounded_collect(request: RpcRequest) -> dict[str, object]:
    try:
        async with asyncio.timeout(15):
            result = await collect(request)
        return result.model_dump(mode="json")
    except TimeoutError:
        return {"status": "UNVERIFIED", "reason": "REFERENCE_WORKER_TIMEOUT"}
    except (ValidationError, ValueError, TypeError):
        return {"status": "UNVERIFIED", "reason": "INVALID_REFERENCE_REQUEST"}
    except Exception:  # noqa: BLE001 -- Do not let unexpected provider errors leak payloads into Lambda error logs.
        return {"status": "UNVERIFIED", "reason": "REFERENCE_WORKER_UNAVAILABLE"}


def handler(event: dict[str, object], context: Any) -> dict[str, object]:
    # No Function URL, API trigger or public event source: invocation is IAM-only.
    # Never log the event or serialize validation exception text.
    structlog.configure(processors=[structlog.processors.JSONRenderer()])
    try:
        request = RpcRequest.model_validate(event)
    except ValidationError:
        return {"status": "UNVERIFIED", "reason": "INVALID_REFERENCE_REQUEST"}
    configure()
    parent = TraceContextTextMapPropagator().extract(
        {"traceparent": request.traceparent} if request.traceparent else {}
    )
    with tracer.start_as_current_span(
        "cks.reference.worker",
        context=parent,
        record_exception=False,
        set_status_on_exception=False,
    ):
        return asyncio.run(bounded_collect(request))


class RemoteKnowledgeClient:
    def __init__(self, client: Any, function_arn: str) -> None:
        self.client = client
        self.function_arn = function_arn

    async def aclose(self) -> None:
        await asyncio.to_thread(self.client.close)

    def _call(self, request: RpcRequest) -> bytes:
        response = self.client.invoke(
            FunctionName=self.function_arn,
            InvocationType="RequestResponse",
            LogType="None",
            Payload=request.model_dump_json(exclude_none=True).encode(),
        )
        stream = response.get("Payload")
        if stream is None:
            raise ValueError("Reference worker returned no payload")
        try:
            if response.get("StatusCode") != 200 or response.get("FunctionError"):
                raise ValueError("Reference worker failed")
            data = stream.read(MAX_BYTES + 1)
            if not isinstance(data, bytes) or len(data) > MAX_BYTES:
                raise ValueError("Invalid reference worker payload")
            return data
        finally:
            stream.close()

    async def _invoke(
        self, operation: Operation, query: StrictModel, model: type[Result]
    ) -> Result:
        with tracer.start_as_current_span(
            "cks.reference.invoke",
            record_exception=False,
            set_status_on_exception=False,
        ):
            try:
                carrier: dict[str, str] = {}
                TraceContextTextMapPropagator().inject(carrier)
                request = RpcRequest(
                    operation=operation,
                    query=query.model_dump(mode="json"),
                    traceparent=carrier.get("traceparent"),
                )
                raw = await asyncio.to_thread(self._call, request)
                result = model.model_validate_json(raw)
            except (
                BotoCoreError,
                ClientError,
                ValueError,
                TypeError,
                KeyError,
                AttributeError,
                OSError,
            ):
                result = model(
                    status="UNVERIFIED", reason="REFERENCE_WORKER_UNAVAILABLE"
                )
            return KnowledgeClient._finish(operation, result)

    async def normalize_drug(self, drug_text: str) -> NormalizationResult:
        try:
            query = DrugQuery(drug_text=drug_text)
        except ValidationError:
            return NormalizationResult(
                status="UNVERIFIED", reason="INVALID_DRUG_ONLY_INPUT"
            )
        return await self._invoke("normalize", query, NormalizationResult)

    async def drug_classes(self, rxcui: str) -> ClassesResult:
        try:
            query = RxCuiQuery(rxcui=rxcui)
        except ValidationError:
            return ClassesResult(status="UNVERIFIED", reason="INVALID_RXCUI")
        return await self._invoke("classes", query, ClassesResult)

    async def label_sections(self, rxcui: str, sections: list[str]) -> LabelsResult:
        try:
            query = LabelQuery.model_validate({"rxcui": rxcui, "sections": sections})
        except ValidationError:
            return LabelsResult(status="UNVERIFIED", reason="INVALID_LABEL_QUERY")
        return await self._invoke("labels", query, LabelsResult)
