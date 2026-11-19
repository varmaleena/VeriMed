"""Bounded asynchronous public-reference lookups; never interprets clinical safety."""

import asyncio
import hashlib
import json
import time
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, TypeVar

import httpx
import structlog
from opentelemetry import trace
from pydantic import ValidationError

from .schemas import (
    ClassesResult,
    ClassMembership,
    DrugConcept,
    DrugQuery,
    LabelDocument,
    LabelQuery,
    LabelsResult,
    NormalizationResult,
    RxCuiQuery,
    Source,
)

tracer = trace.get_tracer("verimed.cks")
logger = structlog.get_logger()
Result = TypeVar("Result", NormalizationResult, ClassesResult, LabelsResult)
RXNAV = "https://rxnav.nlm.nih.gov/REST/"
FDA = "https://api.fda.gov/drug/label.json"


class ReferenceClient(Protocol):
    async def normalize_drug(self, drug_text: str) -> NormalizationResult: ...
    async def drug_classes(self, rxcui: str) -> ClassesResult: ...
    async def label_sections(self, rxcui: str, sections: list[str]) -> LabelsResult: ...


class UpstreamUnavailable(RuntimeError):
    """No provider error text or query is exposed to logs."""


class KnowledgeClient:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http = http
        self._lock = asyncio.Lock()
        self._last_request = 0.0

    async def _get(
        self,
        provider: Literal["RXNORM", "RXCLASS", "OPENFDA"],
        path: str,
        params: dict[str, str],
    ) -> tuple[dict[str, Any], Source, int]:
        if provider == "OPENFDA":
            if path:
                raise ValueError("Unknown reference endpoint")
            url = FDA
        else:
            # Callers supply only fixed endpoint suffixes and validated numeric RxCUIs.
            url = RXNAV + path
        for attempt in range(3):
            async with self._lock:
                wait = 0.3 - (time.monotonic() - self._last_request)
                if wait > 0:
                    await asyncio.sleep(wait)
                self._last_request = time.monotonic()
            try:
                with tracer.start_as_current_span(
                    "cks.reference.fetch",
                    record_exception=False,
                    set_status_on_exception=False,
                ):
                    async with self.http.stream(
                        "GET", url, params=params, timeout=10, follow_redirects=False
                    ) as response:
                        if response.status_code in (429, 500, 502, 503, 504):
                            if attempt == 2:
                                raise UpstreamUnavailable(
                                    "Reference provider unavailable"
                                )
                            await asyncio.sleep(0.25 * (2**attempt))
                            continue
                        if response.status_code != 200 and not (
                            provider == "OPENFDA" and response.status_code == 404
                        ):
                            raise UpstreamUnavailable(
                                "Reference provider rejected lookup"
                            )
                        body = bytearray()
                        async for chunk in response.aiter_bytes(chunk_size=65536):
                            body.extend(chunk)
                            if len(body) > 2_000_000:
                                raise UpstreamUnavailable(
                                    "Reference response exceeds size limit"
                                )
                        data = json.loads(body)
                        if not isinstance(data, dict):
                            raise ValueError("Reference provider returned a non-object")  # noqa: TRY004 -- Treat invalid provider JSON as a fail-closed validation result.
                        source = Source(
                            provider=provider,
                            url=str(response.url),
                            retrieved_at=datetime.now(UTC),
                            response_sha256=hashlib.sha256(body).hexdigest(),
                        )
                        return data, source, response.status_code
            except httpx.RequestError:
                if attempt == 2:
                    raise UpstreamUnavailable(
                        "Reference transport unavailable"
                    ) from None
                await asyncio.sleep(0.25 * (2**attempt))
        raise UpstreamUnavailable("Reference lookup exhausted retries")

    @staticmethod
    def _finish(operation: str, result: Result) -> Result:
        logger.info(
            "cks_lookup",
            trace_id=format(
                trace.get_current_span().get_span_context().trace_id, "032x"
            ),
            operation=operation,
            outcome=result.status,
            _aws={
                "Timestamp": int(datetime.now(UTC).timestamp() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": "VeriMed/CKS",
                        "Dimensions": [["operation"]],
                        "Metrics": [
                            {"Name": "ReferenceLookups", "Unit": "Count"},
                            {"Name": "UnverifiedLookups", "Unit": "Count"},
                        ],
                    }
                ],
            },
            ReferenceLookups=1,
            UnverifiedLookups=int(result.status == "UNVERIFIED"),
        )
        return result

    async def normalize_drug(self, drug_text: str) -> NormalizationResult:
        sources: list[Source] = []
        try:
            query = DrugQuery(drug_text=drug_text)
        except ValidationError:
            return self._finish(
                "normalize",
                NormalizationResult(
                    status="UNVERIFIED", reason="INVALID_DRUG_ONLY_INPUT"
                ),
            )
        try:
            for mode in ("0", "1"):
                data, source, _ = await self._get(
                    "RXNORM",
                    "rxcui.json",
                    {"name": query.drug_text, "search": mode, "allsrc": "0"},
                )
                sources.append(source)
                ids = data["idGroup"].get("rxnormId", []) or []
                if not isinstance(ids, list) or len(ids) > 10:
                    raise ValueError("Unexpected concept result count")
                if not ids:
                    continue
                ids = list(
                    dict.fromkeys(RxCuiQuery(rxcui=value).rxcui for value in ids)
                )
                candidates = []
                for rxcui in ids:
                    properties, source, _ = await self._get(
                        "RXNORM", f"rxcui/{rxcui}/properties.json", {}
                    )
                    sources.append(source)
                    item = properties["properties"]
                    if item.get("rxcui") != rxcui or item.get("suppress", "N") != "N":
                        raise ValueError("Reference concept identity mismatch")
                    candidates.append(
                        DrugConcept(
                            rxcui=rxcui, name=item["name"], term_type=item["tty"]
                        )
                    )
                exact_unique = mode == "0" and len(candidates) == 1
                return self._finish(
                    "normalize",
                    NormalizationResult(
                        status="RESOLVED" if exact_unique else "REVIEW_REQUIRED",
                        reason="EXACT_UNIQUE"
                        if exact_unique
                        else (
                            "AMBIGUOUS"
                            if len(candidates) > 1
                            else "NORMALIZED_MATCH_REQUIRES_REVIEW"
                        ),
                        rxcui=candidates[0].rxcui if exact_unique else None,
                        candidates=candidates,
                        sources=sources,
                    ),
                )
            return self._finish(
                "normalize",
                NormalizationResult(
                    status="NOT_FOUND",
                    reason="NO_EXACT_OR_NORMALIZED_MATCH",
                    sources=sources,
                ),
            )
        except (UpstreamUnavailable, httpx.HTTPError):
            return self._finish(
                "normalize",
                NormalizationResult(status="UNVERIFIED", reason="UPSTREAM_UNAVAILABLE"),
            )
        except (ValueError, KeyError, TypeError, AttributeError):
            return self._finish(
                "normalize",
                NormalizationResult(
                    status="UNVERIFIED", reason="MALFORMED_UPSTREAM_RESPONSE"
                ),
            )

    async def drug_classes(self, rxcui: str) -> ClassesResult:
        try:
            query = RxCuiQuery(rxcui=rxcui)
        except ValidationError:
            return self._finish(
                "classes", ClassesResult(status="UNVERIFIED", reason="INVALID_RXCUI")
            )
        try:
            data, source, _ = await self._get(
                "RXCLASS", "rxclass/class/byRxcui.json", {"rxcui": query.rxcui}
            )
            group = data.get("rxclassDrugInfoList", {})
            rows = group.get("rxclassDrugInfo", []) if group else []
            if not isinstance(rows, list) or len(rows) > 1000:
                raise ValueError("Unexpected class result count")
            items = []
            seen = set()
            for row in rows:
                concept, member = row["rxclassMinConceptItem"], row["minConcept"]
                item = ClassMembership(
                    class_id=concept["classId"],
                    class_name=concept["className"],
                    class_type=concept["classType"],
                    relationship=row.get("rela") or None,
                    relationship_source=row["relaSource"],
                    member_rxcui=member["rxcui"],
                    member_term_type=member["tty"],
                )
                key = (
                    item.class_id,
                    item.class_type,
                    item.relationship,
                    item.relationship_source,
                    item.member_rxcui,
                )
                if key not in seen:
                    items.append(item)
                    seen.add(key)
            return self._finish(
                "classes",
                ClassesResult(
                    status=(
                        "REVIEW_REQUIRED"
                        if any(item.relationship is None for item in items)
                        else "RESOLVED"
                    )
                    if items
                    else "NOT_FOUND",
                    reason=(
                        "UNSPECIFIED_RELATION_REQUIRES_REVIEW"
                        if any(item.relationship is None for item in items)
                        else "DIRECT_MEMBERSHIPS_RETURNED"
                    )
                    if items
                    else "NO_CLASS_DATA_REQUIRES_MANUAL_REVIEW",
                    items=items,
                    sources=[source],
                ),
            )
        except (UpstreamUnavailable, httpx.HTTPError):
            return self._finish(
                "classes",
                ClassesResult(status="UNVERIFIED", reason="UPSTREAM_UNAVAILABLE"),
            )
        except (ValueError, KeyError, TypeError, AttributeError):
            return self._finish(
                "classes",
                ClassesResult(
                    status="UNVERIFIED", reason="MALFORMED_UPSTREAM_RESPONSE"
                ),
            )

    async def label_sections(self, rxcui: str, sections: list[str]) -> LabelsResult:
        try:
            query = LabelQuery.model_validate({"rxcui": rxcui, "sections": sections})
        except ValidationError:
            return self._finish(
                "labels",
                LabelsResult(status="UNVERIFIED", reason="INVALID_LABEL_QUERY"),
            )
        try:
            data, source, code = await self._get(
                "OPENFDA",
                "",
                {
                    "search": f'openfda.rxcui:"{query.rxcui}"',
                    "limit": "3",
                    "sort": "effective_time:desc",
                },
            )
            if code == 404:
                if data.get("error", {}).get("code") != "NOT_FOUND":
                    raise ValueError("Unknown label provider error")
                return self._finish(
                    "labels",
                    LabelsResult(
                        status="NOT_FOUND",
                        reason="NO_HARMONIZED_LABEL_REQUIRES_MANUAL_REVIEW",
                        sources=[source],
                    ),
                )
            rows = data["results"]
            if not isinstance(rows, list) or not rows or len(rows) > 3:
                raise ValueError("Unexpected label result count")
            items = []
            for row in rows:
                if query.rxcui not in row.get("openfda", {}).get("rxcui", []):
                    raise ValueError("Label does not cite requested RxCUI")
                selected: dict[str, list[str]] = {}
                missing: list[str] = []
                for section in query.sections:
                    if section in row:
                        texts = row[section]
                        if not isinstance(texts, list) or any(
                            not isinstance(text, str) or not text.strip()
                            for text in texts
                        ):
                            raise ValueError("Malformed label section")
                        if texts:
                            selected[section] = texts
                        else:
                            missing.append(section)
                    else:
                        missing.append(section)
                datetime.strptime(row["effective_time"], "%Y%m%d")
                items.append(
                    LabelDocument(
                        id=row["id"],
                        set_id=row["set_id"],
                        version=row["version"],
                        effective_time=row["effective_time"],
                        sections=selected,
                        missing_sections=missing,
                    )
                )
            total = data.get("meta", {}).get("results", {}).get("total")
            if total is not None and (not isinstance(total, int) or total < len(items)):
                raise ValueError("Invalid label total")
            incomplete = (
                total is None
                or total > len(items)
                or any(item.missing_sections for item in items)
            )
            return self._finish(
                "labels",
                LabelsResult(
                    status="REVIEW_REQUIRED" if incomplete else "RESOLVED",
                    reason="PARTIAL_REFERENCE_COVERAGE"
                    if incomplete
                    else "SOURCE_TEXT_ONLY_NOT_A_SAFETY_VERDICT",
                    items=items,
                    total=total,
                    truncated=total is None or total > len(items),
                    sources=[source],
                ),
            )
        except (UpstreamUnavailable, httpx.HTTPError):
            return self._finish(
                "labels",
                LabelsResult(status="UNVERIFIED", reason="UPSTREAM_UNAVAILABLE"),
            )
        except (ValueError, KeyError, TypeError, AttributeError):
            return self._finish(
                "labels",
                LabelsResult(status="UNVERIFIED", reason="MALFORMED_UPSTREAM_RESPONSE"),
            )
