"""Fresh-only public-reference caching; never caches clinical state or failures."""

import asyncio
import hashlib
import json
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Literal, Protocol, TypeVar, cast
from urllib.parse import urlsplit

from opentelemetry import trace
from pydantic import AwareDatetime, Field, ValidationError
from valkey.asyncio import Valkey
from valkey.exceptions import ValkeyError

from .client import ReferenceClient, logger
from .schemas import (
    ClassesResult,
    DrugQuery,
    LabelQuery,
    LabelsResult,
    NormalizationResult,
    RxCuiQuery,
    StrictModel,
)

Result = TypeVar("Result", NormalizationResult, ClassesResult, LabelsResult)
tracer = trace.get_tracer("verimed.cks.cache")
MAX_BYTES = 2_000_000
TTL = 3600


class CacheStore(Protocol):
    async def get(self, key: str) -> bytes | None: ...

    async def put(self, key: str, value: bytes, ttl: int) -> None: ...


class ValkeyStore:
    """Owns a bounded async pool. TLS is mandatory outside explicit loopback dev."""

    def __init__(self, url: str, *, allow_local: bool = False) -> None:
        parsed = urlsplit(url)
        local = (
            allow_local
            and parsed.hostname in {"127.0.0.1", "::1", "localhost"}
            and parsed.scheme == "valkey"
        )
        # Query-string options can override client security/timeouts; forbid them.
        if (
            not parsed.hostname
            or parsed.query
            or parsed.fragment
            or (parsed.scheme != "valkeys" and not local)
        ):
            raise ValueError("Cache requires TLS or explicitly enabled loopback dev")
        if parsed.scheme == "valkeys":
            self.client = Valkey.from_url(
                url,
                decode_responses=False,
                socket_connect_timeout=1,
                socket_timeout=1,
                max_connections=8,
                ssl_check_hostname=True,
                ssl_cert_reqs="required",
            )
        else:
            self.client = Valkey.from_url(
                url,
                decode_responses=False,
                socket_connect_timeout=1,
                socket_timeout=1,
                max_connections=8,
            )

    async def get(self, key: str) -> bytes | None:
        value = await self.client.get(key)
        if value is not None and not isinstance(value, bytes):
            raise ValueError("Cache returned non-binary data")
        return value

    async def put(self, key: str, value: bytes, ttl: int) -> None:
        await self.client.set(key, value, ex=ttl)

    async def aclose(self) -> None:
        await self.client.aclose()


class Envelope(StrictModel):
    version: Literal[1] = 1
    key: str
    stored_at: AwareDatetime
    expires_at: AwareDatetime
    payload: dict[str, object]
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


class CachedKnowledgeClient:
    def __init__(self, upstream: ReferenceClient, store: CacheStore) -> None:
        self.upstream = upstream
        self.store = store

    @staticmethod
    def _observe(operation: str, outcome: str) -> None:
        logger.info(
            "cks_cache",
            operation=operation,
            outcome=outcome,
            _aws={
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": "VeriMed/CKS",
                        "Dimensions": [["operation", "outcome"]],
                        "Metrics": [{"Name": "CacheOperations", "Unit": "Count"}],
                    }
                ],
            },
            CacheOperations=1,
        )

    async def _lookup(
        self,
        operation: str,
        query: StrictModel,
        model: type[Result],
        fetch: Callable[[], Awaitable[Result]],
    ) -> Result:
        key = (
            "cks:v1:"
            + operation
            + ":"
            + hashlib.sha256(canonical(query.model_dump(mode="json"))).hexdigest()
        )
        with tracer.start_as_current_span(
            "cks.cache.lookup", record_exception=False, set_status_on_exception=False
        ):
            try:
                async with asyncio.timeout(1.5):
                    raw = await self.store.get(key)
                if raw is not None:
                    if len(raw) > MAX_BYTES:
                        raise ValueError("Oversized cache entry")
                    envelope = Envelope.model_validate_json(raw)
                    checked_at = datetime.now(UTC).timestamp()
                    start = envelope.stored_at.timestamp()
                    end = envelope.expires_at.timestamp()
                    if (
                        envelope.key != key
                        or not start <= checked_at < end
                        or not 0 < end - start <= TTL
                        or hashlib.sha256(canonical(envelope.payload)).hexdigest()
                        != envelope.payload_sha256
                    ):
                        raise ValueError("Invalid cache envelope")
                    result = model.model_validate(envelope.payload)
                    if not self._fresh(result, checked_at):
                        raise ValueError("Expired or incomplete cache provenance")
                    self._observe(operation, "HIT")
                    return result
                self._observe(operation, "MISS")
            except (ValkeyError, OSError, TimeoutError, ValueError, TypeError):
                # Never serve stale data or turn an infrastructure error into a pass.
                self._observe(operation, "BYPASS")
            result = await fetch()
            now = datetime.now(UTC)
            if self._fresh(result, now.timestamp()):
                payload = result.model_dump(mode="json")
                # The oldest original source sets expiry, not the cache insertion.
                expiry = min(s.retrieved_at.timestamp() for s in result.sources) + TTL
                envelope = Envelope(
                    key=key,
                    stored_at=now,
                    expires_at=datetime.fromtimestamp(expiry, UTC),
                    payload=payload,
                    payload_sha256=hashlib.sha256(canonical(payload)).hexdigest(),
                )
                raw = envelope.model_dump_json().encode()
                if len(raw) <= MAX_BYTES:
                    try:
                        async with asyncio.timeout(1.5):
                            await self.store.put(
                                key, raw, max(1, int(expiry - now.timestamp()))
                            )
                        self._observe(operation, "STORED")
                    except (ValkeyError, OSError, TimeoutError, ValueError, TypeError):
                        self._observe(operation, "WRITE_FAILED")
            return result

    @staticmethod
    def _fresh(
        result: NormalizationResult | ClassesResult | LabelsResult, now: float
    ) -> bool:
        return (
            result.status in {"RESOLVED", "REVIEW_REQUIRED"}
            and bool(result.sources)
            and all(0 <= now - s.retrieved_at.timestamp() < TTL for s in result.sources)
        )

    async def normalize_drug(self, drug_text: str) -> NormalizationResult:
        try:
            query = DrugQuery(drug_text=drug_text)
        except ValidationError:
            return await self.upstream.normalize_drug(drug_text)
        return await self._lookup(
            "normalize",
            query,
            NormalizationResult,
            lambda: self.upstream.normalize_drug(query.drug_text),
        )

    async def drug_classes(self, rxcui: str) -> ClassesResult:
        try:
            query = RxCuiQuery(rxcui=rxcui)
        except ValidationError:
            return await self.upstream.drug_classes(rxcui)
        return await self._lookup(
            "classes",
            query,
            ClassesResult,
            lambda: self.upstream.drug_classes(query.rxcui),
        )

    async def label_sections(self, rxcui: str, sections: list[str]) -> LabelsResult:
        try:
            query = LabelQuery.model_validate({"rxcui": rxcui, "sections": sections})
        except ValidationError:
            return await self.upstream.label_sections(rxcui, sections)
        query.sections = sorted(set(query.sections))
        return await self._lookup(
            "labels",
            query,
            LabelsResult,
            lambda: self.upstream.label_sections(
                query.rxcui, cast(list[str], query.sections)
            ),
        )
