"""Export the IAM-invoked anchor worker's strict input schema."""

import json
from pathlib import Path

from app.ledger_worker import AnchorJob

if __name__ == "__main__":
    Path("packages/api-client/ledger-anchor-job.schema.json").write_text(
        json.dumps(AnchorJob.model_json_schema(), indent=2) + "\n", encoding="utf-8"
    )
