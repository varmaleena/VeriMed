# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["strands-agents[litellm]==1.65.0", "litellm==1.106.10", "pydantic==2.14.3"]
# ///
"""Check Strands structured output through a local LiteLLM Bedrock proxy."""

import argparse
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from pydantic import BaseModel
from strands import Agent  # type: ignore[import-not-found]
from strands.models.litellm import LiteLLMModel  # type: ignore[import-not-found]


class Result(BaseModel):
    value: int


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    token = os.environ["VERIMED_SPIKE_PROXY_KEY"]
    endpoint = "http://127.0.0.1:4000/v1"
    model = LiteLLMModel(
        model_id="openai/verimed-spike",
        client_args={"api_base": endpoint, "api_key": token},
        params={"max_tokens": 128},
    )
    print(
        "Estimated inference and Guardrails spend: under $0.10 for two short requests."
    )
    result = Agent(model=model, callback_handler=None).structured_output(
        Result, "Return the integer seven as the value."
    )
    if result.value != 7:
        raise RuntimeError(
            "The structured response did not contain the expected value."
        )

    # Loopback-only spike proxy; no production or remote HTTP transport is permitted here.
    # nosemgrep: python.lang.security.audit.insecure-transport.urllib.insecure-request-object.insecure-request-object
    request = Request(
        f"{endpoint}/chat/completions",
        data=json.dumps(
            {
                "model": "verimed-spike",
                "messages": [{"role": "user", "content": "verimedspikeblocktoken"}],
                "max_tokens": 16,
            }
        ).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        # This request can reach only the literal 127.0.0.1 proxy above.
        # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        with urlopen(request, timeout=30):
            raise RuntimeError("The guardrail sentinel was not blocked.")
    except HTTPError as error:
        body = error.read().decode()
        if error.code != 400 or "verimed-spike-input-blocked" not in body:
            raise RuntimeError(
                f"Unexpected proxy response status {error.code}."
            ) from None
    args.output.write_text(
        json.dumps(
            {"structured_output": "passed", "bedrock_guardrail": "blocked"}, indent=2
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
