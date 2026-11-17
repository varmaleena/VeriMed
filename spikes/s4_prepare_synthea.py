"""Prepare equivalent synthetic FHIR R4 inputs for HAPI and HealthLake."""

import argparse
import json
import uuid
from pathlib import Path
from typing import Any


def rewrite_references(value: Any, references: dict[str, str]) -> None:
    if isinstance(value, list):
        for item in value:
            rewrite_references(item, references)
    elif isinstance(value, dict):
        ref = value.get("reference")
        if isinstance(ref, str) and ref in references:
            value["reference"] = references[ref]
        for item in value.values():
            rewrite_references(item, references)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("synthea_fhir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    bundles = []
    patients: set[str] = set()
    support = []
    for path in sorted(args.synthea_fhir.glob("*.json")):
        bundle = json.loads(path.read_bytes())
        if bundle.get("type") != "transaction":
            continue
        entries = bundle["entry"]
        entries_with_patient = [
            entry for entry in entries if entry["resource"]["resourceType"] == "Patient"
        ]
        if not entries_with_patient:
            support.append(entries)
            continue
        if len(entries_with_patient) != 1:
            parser.error("expected one patient per Synthea transaction bundle")
        patient = entries_with_patient[0]["resource"]["id"]
        if patient not in patients and len(patients) < 50:
            patients.add(patient)
            bundles.append((path, entries))
    if len(patients) != 50:
        parser.error(f"expected at least 50 distinct patients, found {len(patients)}")

    references: dict[str, str] = {}
    resources: dict[str, dict[str, Any]] = {}
    for entries in [*support, *(entries for _, entries in bundles)]:
        for entry in entries:
            resource = entry["resource"]
            full_url = entry.get("fullUrl")
            resource_id = resource.get("id")
            if not resource_id:
                if not full_url:
                    parser.error(
                        "cannot assign a stable ID to a resource without id or fullUrl"
                    )
                resource_id = str(uuid.uuid5(uuid.NAMESPACE_URL, full_url))
                resource["id"] = resource_id
            address = f"{resource['resourceType']}/{resource_id}"
            if full_url:
                references[full_url] = address
            resources.setdefault(address, resource)

    hapi = args.output / "hapi"
    healthlake = args.output / "healthlake"
    hapi.mkdir(parents=True)
    healthlake.mkdir()
    for path, _ in bundles:
        (hapi / path.name).write_bytes(path.read_bytes())
    for path in sorted(args.synthea_fhir.glob("*.json")):
        bundle = json.loads(path.read_bytes())
        if bundle.get("type") == "transaction" and not any(
            entry["resource"]["resourceType"] == "Patient" for entry in bundle["entry"]
        ):
            (hapi / path.name).write_bytes(path.read_bytes())
    with (healthlake / "resources.ndjson").open(
        "w", encoding="utf-8", newline="\n"
    ) as stream:
        for resource in resources.values():
            rewrite_references(resource, references)
            stream.write(json.dumps(resource, separators=(",", ":")) + "\n")
    print(
        f"Prepared {len(patients)} synthetic patients and {len(resources)} FHIR resources."
    )


if __name__ == "__main__":
    main()
