"""Generate a fresh bounded Synthea cohort with a verified upstream artifact."""

import argparse
from pathlib import Path

from simulator.fhir_loader import inspect
from simulator.synthea import generate

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--population", type=int, default=50)
    args = parser.parse_args()
    try:
        source = generate(args.jar, args.output, args.population)
        cohort = inspect(source, args.population)
        print(
            "Generated real Synthea cohort: "
            + str(len(cohort.patient_ids))
            + " patients, "
            + str(cohort.resource_count)
            + " resources."
        )
        print("NDJSON generation completed; submit it through run_fhir_loader.py.")
    except Exception:  # noqa: BLE001 -- Keep synthetic identifiers and paths out of application logs.
        print(
            "Synthea run failed; verify the JAR checksum, Java runtime and new output directory."
        )
        raise SystemExit(1) from None
