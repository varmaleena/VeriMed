"""Real container smoke test: generate one patient with no AWS calls or data output."""

from pathlib import Path

from .fhir_loader import inspect
from .synthea import generate

if __name__ == "__main__":
    path = generate(Path("/opt/synthea.jar"), Path("/work/smoke"), population=1)
    cohort = inspect(path, expected_patients=1)
    if not cohort.resource_count:
        raise RuntimeError("Synthetic FHIR generation did not produce resources")
    print("Real one-patient Synthea container generation passed.")
