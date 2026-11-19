"""Run drug-only reference probes; never writes clinical product data."""

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import structlog
from cks.client import KnowledgeClient


async def verify(drug: str) -> int:
    structlog.configure(processors=[structlog.processors.JSONRenderer()])
    async with httpx.AsyncClient(
        timeout=10, follow_redirects=False, limits=httpx.Limits(max_connections=5)
    ) as http:
        client = KnowledgeClient(http)
        original = await client.normalize_drug(drug)
        canonical = original
        # Diagnostic canonical-name round trip; this does not accept a normalized
        # match for a clinical caller or alter the original lookup's review status.
        if original.status == "REVIEW_REQUIRED" and len(original.candidates) == 1:
            canonical = await client.normalize_drug(original.candidates[0].name)

        candidates = {
            item.rxcui: item
            for result in (original, canonical)
            for item in result.candidates
        }
        probes = []
        sources = original.sources + canonical.sources
        for rxcui in list(candidates)[:3]:
            classes = await client.drug_classes(rxcui)
            labels = await client.label_sections(
                rxcui, ["contraindications", "dosage_and_administration"]
            )
            sources += classes.sources + labels.sources
            probes.append(
                {
                    "reference_probe_rxcui": rxcui,
                    "class_status": classes.status,
                    "class_reason": classes.reason,
                    "class_count": len(classes.items),
                    "unspecified_relationships": sum(
                        item.relationship is None for item in classes.items
                    ),
                    "class_relationship_sources": sorted(
                        {item.relationship_source for item in classes.items}
                    ),
                    "label_status": labels.status,
                    "label_count": len(labels.items),
                    "label_total": labels.total,
                    "label_results_truncated": labels.truncated,
                }
            )
    passed = any(probe["class_count"] and probe["label_count"] for probe in probes)
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "input_sha256": hashlib.sha256(drug.encode()).hexdigest(),
        "original_status": original.status,
        "original_reason": original.reason,
        "selected_rxcui": original.rxcui,
        "original_candidate_count": len(original.candidates),
        "canonical_round_trip_status": canonical.status,
        "canonical_round_trip_candidates": len(canonical.candidates),
        "candidate_reference_probes": probes,
        "source_response_hashes": [source.response_sha256 for source in sources],
        "live_reference_transport_and_parsing": "PASSED" if passed else "INCOMPLETE",
        "candidate_probes_are_clinical_selections": False,
        "hub_private_link": "BLOCKED: separate hub account not configured",
        "valkey_cache_and_reference_mirror": "pending hub runtime",
        "clinical_safety_verdicts": "not implemented in this reference client",
    }
    Path("docs/cks-verification.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--drug", required=True, help="De-identified drug name/strength only"
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(verify(args.drug)))
