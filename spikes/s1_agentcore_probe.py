"""Verify that the spike runtime rejects anonymous calls and returns Gateway tool evidence."""

import argparse
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-arn", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not args.runtime_arn.startswith("arn:aws:bedrock-agentcore:us-east-1:"):
        parser.error("provide the VeriMed spike runtime ARN in us-east-1")
    token = os.environ["VERIMED_SPIKE_COGNITO_TOKEN"]
    runtime = quote(args.runtime_arn, safe="")
    url = f"https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/{runtime}/invocations?qualifier=DEFAULT"
    print(
        "Estimated Runtime, Gateway and inference cost: under $0.10 for one short request."
    )
    data = b'{"prompt":"Call the hello tool and return its greeting."}'

    def invoke(bearer: str | None) -> bytes:
        headers = {"Content-Type": "application/json"}
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        request = Request(url, data=data, headers=headers, method="POST")
        # Host is a literal regional AWS HTTPS endpoint; only the quoted validated ARN varies.
        # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        with urlopen(request, timeout=90) as response:
            return bytes(response.read())

    try:
        invoke(None)
    except HTTPError as error:
        if error.code not in (401, 403):
            raise
        unauthenticated_status = error.code
    else:
        raise RuntimeError("The runtime accepted an unauthenticated request.")
    result = json.loads(invoke(token))
    if result.get("gateway_tool_result") != "hello-from-verimed-gateway":
        raise RuntimeError("The runtime did not return the expected MCP tool result.")
    args.output.write_text(
        json.dumps(
            {
                "anonymous_status": unauthenticated_status,
                "gateway_tool_result": "verified",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
