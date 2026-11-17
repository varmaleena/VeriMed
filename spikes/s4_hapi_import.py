"""Time the import of exactly 50 Synthea patient bundles into a dedicated local HAPI store."""

import argparse
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundles", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--request-timeout", type=float, default=120)
    args = parser.parse_args()
    bundles = []
    support = []
    patients: set[str] = set()
    for source in sorted(args.bundles.glob("*.json")):
        raw = source.read_bytes()
        bundle = json.loads(raw)
        entries = [entry["resource"] for entry in bundle.get("entry", [])]
        ids = [
            entry["id"] for entry in entries if entry.get("resourceType") == "Patient"
        ]
        if not ids:
            if bundle.get("type") in {"transaction", "batch"} and entries:
                support.append((raw, len(entries), f"{bundle['type']}-response"))
            continue
        if bundle.get("type") != "transaction" or len(ids) != 1 or ids[0] in patients:
            parser.error(
                "expected one unique Patient per Synthea FHIR transaction bundle"
            )
        patients.add(ids[0])
        bundles.append((raw, len(entries), "transaction-response"))
    if len(patients) != 50:
        parser.error(f"expected 50 distinct patients, found {len(patients)}")

    print("Estimated AWS spend for local HAPI leg: $0.")
    started = time.monotonic()
    for raw, entry_count, response_type in [*support, *bundles]:
        request = Request(
            "http://127.0.0.1:8080/fhir",
            data=raw,
            headers={"Content-Type": "application/fhir+json"},
            method="POST",
        )
        with urlopen(request, timeout=args.request_timeout) as response:
            result = json.load(response)
        responses = result.get("entry", [])
        if (
            result.get("type") != response_type
            or len(responses) != entry_count
            or not all(
                entry.get("response", {}).get("status", "").startswith("2")
                for entry in responses
            )
        ):
            raise RuntimeError("HAPI did not confirm the complete FHIR transaction")
    elapsed = time.monotonic() - started
    with urlopen(
        "http://127.0.0.1:8080/fhir/Patient?_summary=count", timeout=30
    ) as response:
        stored_patients = json.load(response).get("total")
    if stored_patients != len(patients):
        raise RuntimeError(
            "The dedicated HAPI store did not contain exactly 50 patients"
        )
    report = {
        "backend": "hapi",
        "patients": len(patients),
        "seconds": elapsed,
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
