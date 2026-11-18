"""Verify dev gateway denial, deployed authorization and empty read response."""

import json
import os
import time
from urllib.error import HTTPError
from urllib.request import urlopen

import boto3  # type: ignore[import-untyped]


def main() -> None:
    try:
        with urlopen(os.environ["CELL_API_URL"] + "/encounters", timeout=30):
            raise RuntimeError("The gateway accepted an anonymous request")
    except HTTPError as error:
        if error.code != 401:
            raise
    client = boto3.client("lambda")
    for role, expected in [("PHYSICIAN", 200), ("UNKNOWN", 403)]:
        event = {
            "version": "2.0",
            "routeKey": "GET /v1/encounters",
            "rawPath": "/v1/encounters",
            "rawQueryString": "",
            "headers": {
                "authorization": "Bearer integration-test-event",
                "host": "test.invalid",
            },
            "requestContext": {
                "stage": "$default",
                "requestId": "phase-one-integration",
                "http": {
                    "method": "GET",
                    "path": "/v1/encounters",
                    "protocol": "HTTP/1.1",
                    "sourceIp": "127.0.0.1",
                    "userAgent": "integration-test",
                },
                "authorizer": {
                    "jwt": {
                        "claims": {
                            "sub": "phase-one-test-principal",
                            "token_use": "access",
                            "client_id": os.environ["COGNITO_CLIENT_ID"],
                            "cognito:groups": json.dumps([role]),
                        }
                    }
                },
            },
            "isBase64Encoded": False,
        }
        # Direct IAM invocation exercises the deployed service. The browser sign-in
        # test separately verifies the real Cognito-to-Gateway token path.
        for attempt in range(4):
            result = client.invoke(
                FunctionName=os.environ["API_FUNCTION_NAME"],
                Payload=json.dumps(event).encode(),
            )
            response = json.load(result["Payload"])
            if response.get("statusCode") != 503 or attempt == 3:
                break
            time.sleep(10)
        if response.get("statusCode") != expected:
            raise RuntimeError(
                f"Expected {expected} for {role}, got {response.get('statusCode')}"
            )
        if expected == 200:
            body = json.loads(response["body"])
            if body != {"items": [], "has_more": False}:
                raise RuntimeError("The new cell Worklist is not empty")
    print(
        "Gateway anonymous denial, deployed physician read, and denied-role checks passed."
    )


if __name__ == "__main__":
    main()
