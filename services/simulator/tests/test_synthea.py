import json
from pathlib import Path

import pytest
from simulator.synthea import generate, prepare


def test_unverified_jar_never_runs_java(tmp_path: Path) -> None:
    jar = tmp_path / "invalid.jar"
    jar.write_bytes(b"unit-not-a-real-jar")
    with pytest.raises(ValueError):
        generate(jar, tmp_path / "output", 1)
    assert not (tmp_path / "output").exists()


def test_unresolved_reference_does_not_publish_partial_dataset(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "bundle.json").write_text(
        json.dumps(
            {
                "resourceType": "Bundle",
                "type": "transaction",
                "entry": [
                    {
                        "fullUrl": "urn:uuid:unit",
                        "resource": {"resourceType": "Patient", "id": "unit"},
                    },
                    {
                        "resource": {
                            "resourceType": "Procedure",
                            "id": "unit-procedure",
                            "subject": {"reference": "urn:uuid:missing"},
                        }
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    destination = tmp_path / "resources.ndjson"
    with pytest.raises(ValueError):
        prepare(source, destination, 1)
    assert not destination.exists()


def test_prepare_rewrites_actual_bundle_references(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "bundle.json").write_text(
        json.dumps(
            {
                "resourceType": "Bundle",
                "type": "transaction",
                "entry": [
                    {
                        "fullUrl": "urn:uuid:unit",
                        "resource": {"resourceType": "Patient", "id": "unit"},
                    },
                    {
                        "resource": {
                            "resourceType": "Observation",
                            "id": "unit-observation",
                            "subject": {"reference": "urn:uuid:unit"},
                        }
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    destination = prepare(source, tmp_path / "resources.ndjson", 1)
    rows = [json.loads(line) for line in destination.read_text().splitlines()]
    observation = next(row for row in rows if row["resourceType"] == "Observation")
    assert observation["subject"]["reference"] == "Patient/unit"
