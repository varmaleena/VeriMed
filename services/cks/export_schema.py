"""Export the CKS adapter DTO contracts without publishing an unauthenticated API."""

import json
from pathlib import Path

from cks.bridge import RpcRequest
from cks.schemas import CksContracts
from cks.service import create_app

if __name__ == "__main__":
    Path("packages/api-client/cks.schema.json").write_text(
        json.dumps(CksContracts.model_json_schema(), indent=2) + "\n", encoding="utf-8"
    )

    Path("packages/api-client/cks.openapi.json").write_text(
        json.dumps(create_app().openapi(), indent=2) + "\n", encoding="utf-8"
    )

    Path("packages/api-client/cks-reference-request.schema.json").write_text(
        json.dumps(RpcRequest.model_json_schema(), indent=2) + "\n", encoding="utf-8"
    )
