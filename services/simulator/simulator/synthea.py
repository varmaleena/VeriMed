"""Synthea v4 runner and FHIR NDJSON preparation. All clinical content comes from Synthea."""

import hashlib
import json
import secrets
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

SYNTHEA_SHA256 = "33b36f37163db67d36fb5ff515027fee666933ddad2a37628708abcec4f8005b"


def generate(jar: Path, output: Path, population: int = 50) -> Path:
    if not 1 <= population <= 50:
        raise ValueError("Synthetic population must be between 1 and 50")
    with jar.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != SYNTHEA_SHA256:
            raise ValueError("Synthea JAR does not match the verified security rebuild")
    output.mkdir(parents=True, exist_ok=False)
    seed, clinician_seed = secrets.randbits(63), secrets.randbits(63)
    reference_date = datetime.now(UTC).strftime("%Y%m%d")
    command = [
        "java",
        "-Xmx1024m",
        "-jar",
        str(jar.resolve()),
        "-p",
        str(population),
        "--generate.only_alive_patients=true",
        "-s",
        str(seed),
        "-cs",
        str(clinician_seed),
        "-r",
        reference_date,
        "-e",
        reference_date,
        "--exporter.baseDirectory=" + str(output.resolve()),
        "--exporter.fhir.export=true",
        "--exporter.fhir.transaction_bundle=true",
        "--exporter.fhir.bulk_data=false",
        "--exporter.hospital.fhir.export=true",
        "--exporter.practitioner.fhir.export=true",
    ]
    # Synthea's normal console output includes synthetic names; do not forward it to app logs.
    result = subprocess.run(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=1800,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("Synthea generation failed")
    dataset = prepare(output / "fhir", output / "resources.ndjson", population)
    (output / "generation.json").write_text(
        json.dumps(
            {
                "generator": "Synthea v4.0.0 security.1",
                "jar_sha256": SYNTHEA_SHA256,
                "seed": seed,
                "clinician_seed": clinician_seed,
                "reference_date": reference_date,
                "requested_population": population,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return dataset


def prepare(source: Path, destination: Path, population: int = 50) -> Path:
    if destination.exists() or not 1 <= population <= 50:
        raise ValueError("Use a new NDJSON destination and a bounded population")
    support: list[list[dict[str, Any]]] = []
    patients: list[list[dict[str, Any]]] = []
    selected: set[str] = set()
    for path in sorted(source.glob("*.json")):
        if path.stat().st_size > 33_554_432:
            raise ValueError("Synthetic FHIR bundle exceeds the size bound")
        bundle = json.loads(path.read_bytes())
        if bundle.get("resourceType") != "Bundle" or bundle.get("type") not in {
            "transaction",
            "batch",
        }:
            raise ValueError("Expected actual Synthea FHIR transaction bundles")
        entries = bundle["entry"]
        patient_ids = [
            entry["resource"]["id"]
            for entry in entries
            if entry["resource"]["resourceType"] == "Patient"
        ]
        if not patient_ids:
            support.append(entries)
        elif len(patient_ids) != 1 or bundle["type"] != "transaction":
            raise ValueError("Expected one patient per synthetic transaction")
        elif patient_ids[0] not in selected and len(selected) < population:
            patients.append(entries)
            selected.add(patient_ids[0])
    if len(selected) != population:
        raise ValueError("Synthea did not produce enough distinct patients")
    references: dict[str, str] = {}
    resources: dict[str, dict[str, Any]] = {}
    for entries in [*support, *patients]:
        for entry in entries:
            resource = entry["resource"]
            full_url = entry.get("fullUrl")
            identity = resource.get("id")
            if not identity:
                if not isinstance(full_url, str):
                    raise ValueError("Synthetic resource is missing its identity")
                identity = str(uuid5(NAMESPACE_URL, full_url))
                resource["id"] = identity
            address = resource["resourceType"] + "/" + identity
            if full_url:
                references[full_url] = address
            resources.setdefault(address, resource)

    def rewrite(value: Any) -> None:
        if isinstance(value, list):
            for child in value:
                rewrite(child)
        elif isinstance(value, dict):
            ref = value.get("reference")
            if isinstance(ref, str):
                if ref in references:
                    value["reference"] = references[ref]
                elif ref.startswith("urn:uuid:"):
                    raise ValueError(
                        "Synthetic chart has an unresolved internal reference"
                    )
            for child in value.values():
                rewrite(child)

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + "." + uuid4().hex + ".partial")
    with temporary.open("x", encoding="utf-8", newline="\n") as stream:
        for address in sorted(resources):
            resource = resources[address]
            rewrite(resource)
            stream.write(
                json.dumps(resource, separators=(",", ":"), sort_keys=True) + "\n"
            )
    temporary.rename(destination)
    return destination
