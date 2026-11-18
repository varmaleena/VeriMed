"""Export the cell API contract without contacting AWS."""

import json
from pathlib import Path

from app.main import app

target = Path(__file__).resolve().parents[2] / "packages/api-client/openapi.json"
target.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
