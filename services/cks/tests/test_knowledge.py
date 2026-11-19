"""All response doubles live exclusively in this unit-test module."""

import asyncio
import json

import httpx
import pytest
from cks.client import KnowledgeClient


def props(rxcui: str = "12345") -> dict[str, object]:
    return {
        "properties": {
            "rxcui": rxcui,
            "name": "Unit drug 5 MG Oral Tablet",
            "tty": "SCD",
            "suppress": "N",
        }
    }


def test_exact_unique_reference_and_source_hash() -> None:
    calls: list[httpx.Request] = []

    def provider(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("properties.json"):
            return httpx.Response(200, json=props())
        assert request.url.params["search"] == "0"
        return httpx.Response(200, json={"idGroup": {"rxnormId": ["12345"]}})

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as http:
            result = await KnowledgeClient(http).normalize_drug("Unit drug 5 mg tablet")
        assert result.status == "RESOLVED" and result.rxcui == "12345"
        assert len(result.sources) == 2 and len(result.sources[0].response_sha256) == 64

    asyncio.run(run())
    assert len(calls) == 2


@pytest.mark.parametrize("ambiguous", [False, True])
def test_normalized_or_ambiguous_drugs_are_never_auto_selected(ambiguous: bool) -> None:
    def provider(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("properties.json"):
            return httpx.Response(200, json=props(request.url.path.split("/")[3]))
        if request.url.params["search"] == "0":
            return httpx.Response(200, json={"idGroup": {}})
        return httpx.Response(
            200,
            json={
                "idGroup": {"rxnormId": ["12345", "67890"] if ambiguous else ["12345"]}
            },
        )

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as http:
            result = await KnowledgeClient(http).normalize_drug("Unit drug")
        assert result.status == "REVIEW_REQUIRED" and result.rxcui is None
        assert len(result.candidates) == (2 if ambiguous else 1)

    asyncio.run(run())


@pytest.mark.parametrize(
    "text",
    [
        "patient John MRN 12345",
        "drug\npatient: John",
        "person@example.com",
        "x" * 161,
        "",
    ],
)
def test_drug_only_boundary_rejects_before_network(text: str) -> None:
    def provider(request: httpx.Request) -> httpx.Response:
        pytest.fail("Rejected drug query reached network")

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as http:
            result = await KnowledgeClient(http).normalize_drug(text)
        assert (
            result.status == "UNVERIFIED" and result.reason == "INVALID_DRUG_ONLY_INPUT"
        )

    asyncio.run(run())


def test_missing_matches_are_not_safety_approval() -> None:
    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"idGroup": {}})
            )
        ) as http:
            result = await KnowledgeClient(http).normalize_drug("unitunknown")
        assert result.status == "NOT_FOUND" and result.rxcui is None

    asyncio.run(run())


@pytest.mark.parametrize(
    "mode", ["timeout", "rate_limit", "redirect", "malformed", "identity_mismatch"]
)
def test_provider_failures_never_become_resolved(mode: str) -> None:
    calls = 0

    def provider(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if mode == "timeout":
            raise httpx.ConnectError("unit outage", request=request)
        if mode == "rate_limit":
            return httpx.Response(429)
        if mode == "redirect":
            return httpx.Response(302, headers={"location": "https://example.invalid"})
        if mode == "malformed":
            return httpx.Response(200, json={"idGroup": []})
        if request.url.path.endswith("properties.json"):
            return httpx.Response(200, json=props("99999"))
        return httpx.Response(200, json={"idGroup": {"rxnormId": ["12345"]}})

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as http:
            result = await KnowledgeClient(http).normalize_drug("unitdrug")
        assert result.status == "UNVERIFIED"

    asyncio.run(run())
    assert calls == (
        3
        if mode in ("timeout", "rate_limit")
        else 2
        if mode == "identity_mismatch"
        else 1
    )


def test_class_relationship_provenance_and_empty_result() -> None:
    row = {
        "minConcept": {"rxcui": "777", "tty": "IN"},
        "rxclassMinConceptItem": {
            "classId": "unit-class",
            "className": "Unit class",
            "classType": "EPC",
        },
        "rela": "has_EPC",
        "relaSource": "DAILYMED",
    }

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, json={"rxclassDrugInfoList": {"rxclassDrugInfo": [row, row]}}
                )
            )
        ) as http:
            result = await KnowledgeClient(http).drug_classes("12345")
        assert result.status == "RESOLVED" and len(result.items) == 1
        assert (
            result.items[0].relationship == "has_EPC"
            and result.items[0].member_rxcui == "777"
        )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))
        ) as http:
            empty = await KnowledgeClient(http).drug_classes("12345")
        assert empty.status == "NOT_FOUND" and "MANUAL_REVIEW" in empty.reason

    asyncio.run(run())


@pytest.mark.parametrize("missing", [False, True])
def test_label_identity_sections_and_partial_coverage(missing: bool) -> None:
    row = {
        "id": "unit-label",
        "set_id": "unit-set",
        "version": "1",
        "effective_time": "20260101",
        "openfda": {"rxcui": ["12345"]},
        "contraindications": ["Unit source text."],
    }

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={
                        "results": [row],
                        "meta": {"results": {"total": 2 if missing else 1}},
                    },
                )
            )
        ) as http:
            result = await KnowledgeClient(http).label_sections(
                "12345",
                ["contraindications", "boxed_warning"]
                if missing
                else ["contraindications"],
            )
        assert result.status == ("REVIEW_REQUIRED" if missing else "RESOLVED")
        assert result.items[0].sections["contraindications"] == ["Unit source text."]
        assert result.truncated is missing
        assert result.items[0].missing_sections == (
            ["boxed_warning"] if missing else []
        )

    asyncio.run(run())


def test_label_wrong_rxcui_and_missing_coverage_fail_closed() -> None:
    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, json={"results": [{"openfda": {"rxcui": ["999"]}}]}
                )
            )
        ) as http:
            result = await KnowledgeClient(http).label_sections(
                "12345", ["contraindications"]
            )
        assert result.status == "UNVERIFIED"
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    404, json={"error": {"code": "NOT_FOUND"}}
                )
            )
        ) as http:
            result = await KnowledgeClient(http).label_sections(
                "12345", ["contraindications"]
            )
        assert result.status == "NOT_FOUND" and "MANUAL_REVIEW" in result.reason

    asyncio.run(run())


def test_numeric_query_prevents_provider_search_injection() -> None:
    def provider(request: httpx.Request) -> httpx.Response:
        pytest.fail("Invalid RxCUI reached provider")

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as http:
            client = KnowledgeClient(http)
            assert (await client.drug_classes('123" OR *')).status == "UNVERIFIED"
            assert (
                await client.label_sections("12345", ["unknown_section"])
            ).status == "UNVERIFIED"

    asyncio.run(run())


def test_logs_do_not_include_lookup_text_or_provider_body(
    capsys: pytest.CaptureFixture[str],
) -> None:
    import structlog

    structlog.configure(processors=[structlog.processors.JSONRenderer()])

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(503, text="unit-sensitive-provider-body")
            )
        ) as http:
            await KnowledgeClient(http).normalize_drug("unit-private-drug-text")

    asyncio.run(run())
    output = capsys.readouterr().out
    assert (
        "unit-private-drug-text" not in output
        and "unit-sensitive-provider-body" not in output
    )
    assert json.loads(output)["outcome"] == "UNVERIFIED"


def test_documented_empty_class_relationship_requires_review() -> None:
    row = {
        "minConcept": {"rxcui": "777", "tty": "IN"},
        "rxclassMinConceptItem": {
            "classId": "unit-atc",
            "className": "Unit class",
            "classType": "ATC",
        },
        "rela": "",
        "relaSource": "ATC",
    }

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, json={"rxclassDrugInfoList": {"rxclassDrugInfo": [row]}}
                )
            )
        ) as http:
            result = await KnowledgeClient(http).drug_classes("12345")
        assert result.status == "REVIEW_REQUIRED"
        assert (
            result.items[0].relationship is None
            and result.items[0].relationship_source == "ATC"
        )

    asyncio.run(run())
