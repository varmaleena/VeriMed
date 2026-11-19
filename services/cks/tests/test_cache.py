"""Cache doubles are confined to unit tests; integration uses a real Valkey server."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from cks.cache import CachedKnowledgeClient, ValkeyStore, canonical
from cks.client import KnowledgeClient
from valkey.exceptions import ConnectionError as CacheConnectionError


class Store:
    def __init__(self) -> None:
        self.entries: dict[str, bytes] = {}
        self.ttls: list[int] = []
        self.fail_read = False
        self.fail_write = False

    async def get(self, key: str) -> bytes | None:
        if self.fail_read:
            raise CacheConnectionError("unit-sensitive-cache-error")
        return self.entries.get(key)

    async def put(self, key: str, value: bytes, ttl: int) -> None:
        if self.fail_write:
            raise CacheConnectionError("unit-sensitive-cache-error")
        self.entries[key] = value
        self.ttls.append(ttl)


def provider(calls: list[httpx.Request]) -> Any:
    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("properties.json"):
            return httpx.Response(
                200,
                json={
                    "properties": {
                        "rxcui": "12345",
                        "name": "Unit drug",
                        "tty": "SCD",
                        "suppress": "N",
                    }
                },
            )
        return httpx.Response(200, json={"idGroup": {"rxnormId": ["12345"]}})

    return respond


def test_hit_preserves_original_provenance_and_hashed_key() -> None:
    async def run() -> None:
        calls: list[httpx.Request] = []
        store = Store()
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(provider(calls))
        ) as http:
            client = CachedKnowledgeClient(KnowledgeClient(http), store)
            first = await client.normalize_drug("unit-drug")
            second = await client.normalize_drug("unit-drug")
        assert second == first and len(calls) == 2
        assert 0 < store.ttls[0] <= 3600
        key = next(iter(store.entries))
        assert key.startswith("cks:v1:normalize:") and "unit-drug" not in key
        assert second.sources[0].retrieved_at == first.sources[0].retrieved_at

    asyncio.run(run())


@pytest.mark.parametrize(
    "damage",
    [
        "bad_json",
        "expired",
        "future",
        "long_ttl",
        "wrong_key",
        "digest",
        "old_source",
        "future_source",
        "missing_source",
        "bad_schema",
        "unverified",
        "oversized",
    ],
)
def test_invalid_cached_entry_fetches_fresh_provider(damage: str) -> None:
    async def run() -> None:
        calls: list[httpx.Request] = []
        store = Store()
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(provider(calls))
        ) as http:
            client = CachedKnowledgeClient(KnowledgeClient(http), store)
            await client.normalize_drug("unit-drug")
            key = next(iter(store.entries))
            data = json.loads(store.entries[key])
            now = datetime.now(UTC)
            if damage == "expired":
                data["expires_at"] = (now - timedelta(seconds=1)).isoformat()
            elif damage == "future":
                data["stored_at"] = (now + timedelta(seconds=60)).isoformat()
            elif damage == "long_ttl":
                data["expires_at"] = (now + timedelta(days=2)).isoformat()
            elif damage == "wrong_key":
                data["key"] = "different-query"
            elif damage == "digest":
                data["payload_sha256"] = "0" * 64
            elif damage in {"old_source", "future_source"}:
                offset = -7200 if damage == "old_source" else 60
                data["payload"]["sources"][0]["retrieved_at"] = (
                    now + timedelta(seconds=offset)
                ).isoformat()
            elif damage == "missing_source":
                data["payload"]["sources"] = []
            elif damage == "bad_schema":
                data["payload"]["unexpected"] = True
            elif damage == "unverified":
                data["payload"]["status"] = "UNVERIFIED"
            if damage != "digest":
                data["payload_sha256"] = hashlib.sha256(
                    canonical(data["payload"])
                ).hexdigest()
            store.entries[key] = (
                b"invalid"
                if damage == "bad_json"
                else b"x" * 2_000_001
                if damage == "oversized"
                else json.dumps(data).encode()
            )
            result = await client.normalize_drug("unit-drug")
        assert result.status == "RESOLVED" and len(calls) == 4

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["read", "write", "both"])
def test_cache_outage_uses_provider_without_logging_errors(
    failure: str, capsys: pytest.CaptureFixture[str]
) -> None:
    async def run() -> None:
        calls: list[httpx.Request] = []
        store = Store()
        store.fail_read = failure in {"read", "both"}
        store.fail_write = failure in {"write", "both"}
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(provider(calls))
        ) as http:
            result = await CachedKnowledgeClient(
                KnowledgeClient(http), store
            ).normalize_drug("unit-drug")
        assert result.status == "RESOLVED" and len(calls) == 2

    asyncio.run(run())
    assert "unit-sensitive-cache-error" not in capsys.readouterr().out


@pytest.mark.parametrize("upstream", ["missing", "outage", "malformed"])
def test_negative_and_failed_responses_are_not_cached(upstream: str) -> None:
    async def run() -> None:
        store = Store()

        def respond(request: httpx.Request) -> httpx.Response:
            if upstream == "outage":
                raise httpx.ConnectError("unit", request=request)
            return httpx.Response(
                200, json={"idGroup": {}} if upstream == "missing" else []
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            result = await CachedKnowledgeClient(
                KnowledgeClient(http), store
            ).normalize_drug("unit-drug")
        assert result.status in {"NOT_FOUND", "UNVERIFIED"} and not store.entries

    asyncio.run(run())


def test_invalid_drug_never_reaches_cache_or_provider() -> None:
    class RejectStore(Store):
        async def get(self, key: str) -> bytes | None:
            pytest.fail("Invalid input reached cache")

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: pytest.fail("Invalid input reached network")
            )
        ) as http:
            result = await CachedKnowledgeClient(
                KnowledgeClient(http), RejectStore()
            ).normalize_drug("patient MRN 123")
        assert result.status == "UNVERIFIED"

    asyncio.run(run())


@pytest.mark.parametrize(
    "url",
    [
        "valkey://cache.internal:6379",
        "http://localhost:6379",
        "valkeys://cache.internal:6379?ssl_cert_reqs=none",
        "valkeys:///0",
    ],
)
def test_insecure_or_overriding_connection_urls_rejected(url: str) -> None:
    with pytest.raises(ValueError):
        ValkeyStore(url, allow_local=True)


def test_local_plaintext_requires_explicit_opt_in() -> None:
    with pytest.raises(ValueError):
        ValkeyStore("valkey://127.0.0.1:6379")

    async def run() -> None:
        store = ValkeyStore("valkey://127.0.0.1:6379", allow_local=True)
        await store.aclose()

    asyncio.run(run())


def test_cache_outage_and_provider_outage_remain_unverified() -> None:
    async def run() -> None:
        store = Store()
        store.fail_read = True

        def respond(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("unit", request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            result = await CachedKnowledgeClient(
                KnowledgeClient(http), store
            ).normalize_drug("unit-drug")
        assert result.status == "UNVERIFIED" and not store.entries

    asyncio.run(run())


def test_class_and_label_cache_keys_are_separate_and_review_is_preserved() -> None:
    async def run() -> None:
        store = Store()
        calls: list[httpx.Request] = []

        def respond(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if "rxclass" in request.url.path:
                return httpx.Response(
                    200,
                    json={
                        "rxclassDrugInfoList": {
                            "rxclassDrugInfo": [
                                {
                                    "minConcept": {"rxcui": "777", "tty": "IN"},
                                    "rxclassMinConceptItem": {
                                        "classId": "unit",
                                        "className": "Unit class",
                                        "classType": "ATC",
                                    },
                                    "rela": "",
                                    "relaSource": "ATC",
                                }
                            ]
                        }
                    },
                )
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": "unit-label",
                            "set_id": "unit-set",
                            "version": "1",
                            "effective_time": "20260101",
                            "openfda": {"rxcui": ["12345"]},
                            "contraindications": ["Unit source text"],
                        }
                    ],
                    "meta": {"results": {"total": 5}},
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client = CachedKnowledgeClient(KnowledgeClient(http), store)
            first = await client.drug_classes("12345")
            assert await client.drug_classes("12345") == first
            label = await client.label_sections(
                "12345", ["warnings", "contraindications"]
            )
            assert (
                await client.label_sections("12345", ["contraindications", "warnings"])
                == label
            )
            assert len(calls) == 2 and len(store.entries) == 2
            assert first.status == label.status == "REVIEW_REQUIRED"
            assert label.truncated and label.items[0].missing_sections == ["warnings"]
            await client.label_sections("12345", ["contraindications"])
            assert len(calls) == 3

    asyncio.run(run())


def test_tls_checks_certificate_and_hostname() -> None:
    async def run() -> None:
        store = ValkeyStore("valkeys://cache.internal:6379")
        options = store.client.connection_pool.connection_kwargs
        assert options["ssl_check_hostname"] is True
        assert options["ssl_cert_reqs"] == "required"
        assert options["socket_connect_timeout"] == options["socket_timeout"] == 1
        await store.aclose()

    asyncio.run(run())
