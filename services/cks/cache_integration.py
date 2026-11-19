"""Exercise real Valkey expiry and live RxNorm cache reuse; no service doubles."""

import argparse
import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
from cks.cache import CachedKnowledgeClient, ValkeyStore, canonical
from cks.client import KnowledgeClient
from cks.schemas import DrugQuery
from valkey.exceptions import ValkeyError


async def verify(output: Path, allow_local: bool) -> int:
    # Never print this URL: it may contain an ACL password.
    store = ValkeyStore(os.environ["VALKEY_URL"], allow_local=allow_local)
    drug = DrugQuery(drug_text="metformin 500 mg tablet")
    key = (
        "cks:v1:normalize:"
        + hashlib.sha256(canonical(drug.model_dump(mode="json"))).hexdigest()
    )
    probe_key = "cks:integration:" + uuid4().hex
    requests = 0

    async def count(request: httpx.Request) -> None:
        nonlocal requests
        requests += 1

    try:
        # Unique transport probe; no synthetic clinical records or fabricated references.
        await store.put(probe_key, b"transport-check", 1)
        roundtrip = await store.get(probe_key) == b"transport-check"
        await asyncio.sleep(1.2)
        expiry = await store.get(probe_key) is None
        await store.client.delete(key)
        async with httpx.AsyncClient(event_hooks={"request": [count]}) as http:
            client = CachedKnowledgeClient(KnowledgeClient(http), store)
            first = await client.normalize_drug(drug.drug_text)
            after_first = requests
            second = await client.normalize_drug(drug.drug_text)
        reused = (
            after_first > 0
            and requests == after_first
            and first == second
            and bool(first.sources)
        )
        passed = roundtrip and expiry and reused
        report = {
            "checked_at": datetime.now(UTC).isoformat(),
            "real_valkey_roundtrip": roundtrip,
            "real_valkey_expiry": expiry,
            "live_rxnorm_cache_reused": reused,
            "first_provider_requests": after_first,
            "second_provider_requests": requests - after_first,
            "normalization_status": first.status,
            "original_provenance_preserved": first.sources == second.sources,
            "status": "PASSED" if passed else "INCOMPLETE",
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0 if passed else 1
    finally:
        try:
            await store.client.delete(key, probe_key)
        finally:
            await store.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-local", action="store_true")
    parser.add_argument(
        "--output", type=Path, default=Path("docs/cks-cache-verification.json")
    )
    args = parser.parse_args()
    try:
        code = asyncio.run(verify(args.output, args.allow_local))
    except (ValkeyError, httpx.HTTPError, OSError, ValueError, KeyError, TimeoutError):
        # Library/connection exceptions can contain endpoint credentials or drug query strings.
        print(
            "CKS cache integration failed; verify VALKEY_URL and provider connectivity. No error payload logged."
        )
        code = 1
    raise SystemExit(code)
