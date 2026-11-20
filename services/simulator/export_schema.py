"""Export the internal FHIR import contract, without any patient instances."""

import json
from pathlib import Path

from simulator.fhir_schemas import ImportState
from simulator.hosted_synthea import GenerationJob

if __name__ == "__main__":
    Path("packages/api-client/fhir-import-job.schema.json").write_text(
        json.dumps(ImportState.model_json_schema(), indent=2) + "\n",
        encoding="utf-8",
    )
    Path("packages/api-client/synthea-generation-job.schema.json").write_text(
        json.dumps(GenerationJob.model_json_schema(), indent=2) + "\n", encoding="utf-8"
    )
