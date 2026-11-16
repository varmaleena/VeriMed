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
    args = parser.parse_args()
    bundles = []
    patients: set[str] = set()
    for source in sorted(args.bundles.glob("*.json")):
        raw = source.read_bytes()
        bundle = json.loads(raw)
        entries = [entry["resource"] for entry in bundle.get("entry", [])]
        ids = [
            entry["id"] for entry in entries if entry.get("resourceType") == "Patient"
        ]
        if not ids:
            continue
        if bundle.get("type") != "transaction" or len(ids) != 1 or ids[0] in patients:
            parser.error(
                "expected one unique Patient per Synthea FHIR transaction bundle"
            )
        patients.add(ids[0])
        bundles.append(raw)
    if len(patients) != 50:
        parser.error(f"expected 50 distinct patients, found {len(patients)}")

    print("Estimated AWS spend for local HAPI leg: $0.")
    started = time.monotonic()
    for raw in bundles:
        request = Request(
            "http://127.0.0.1:8080/fhir",
            data=raw,
            headers={"Content-Type": "application/fhir+json"},
            method="POST",
        )
        with urlopen(request, timeout=120) as response:
            result = json.load(response)
        if result.get("type") != "transaction-response" or not all(
            entry.get("response", {}).get("status", "").startswith("2")
            for entry in result.get("entry", [{}])
        ):
            raise RuntimeError("HAPI did not confirm the complete FHIR transaction")
    report = {
        "backend": "hapi",
        "patients": len(patients),
        "seconds": time.monotonic() - started,
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
