"""Export the CKS adapter DTO contracts without publishing an unauthenticated API."""

import json
from pathlib import Path

from cks.schemas import CksContracts

if __name__ == "__main__":
    Path("packages/api-client/cks.schema.json").write_text(
        json.dumps(CksContracts.model_json_schema(), indent=2) + "\n", encoding="utf-8"
    )
