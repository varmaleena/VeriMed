"""Verify the deployed Patient API against the live synthetic HealthLake store."""

import json
import os
from urllib.parse import urlencode

import boto3  # type: ignore[import-untyped]


def main() -> None:
    client = boto3.client("lambda")

    def invoke(role: str, cursor: str | None = None) -> dict[str, object]:
        event = {
            "version": "2.0",
            "routeKey": "GET /v1/patients",
            "rawPath": "/v1/patients",
            "rawQueryString": urlencode({"cursor": cursor}) if cursor else "",
            "headers": {
                "authorization": "Bearer integration-test-event",
                "host": "test.invalid",
            },
            "requestContext": {
                "stage": "$default",
                "requestId": "patient-integration",
                "http": {
                    "method": "GET",
                    "path": "/v1/patients",
                    "protocol": "HTTP/1.1",
                    "sourceIp": "127.0.0.1",
                    "userAgent": "integration-test",
                },
                "authorizer": {
                    "jwt": {
                        "claims": {
                            "sub": "patient-integration-principal",
                            "token_use": "access",
                            "client_id": os.environ["COGNITO_CLIENT_ID"],
                            "cognito:groups": json.dumps([role]),
                        }
                    }
                },
            },
            "isBase64Encoded": False,
        }
        result = client.invoke(
            FunctionName=os.environ["API_FUNCTION_NAME"],
            Payload=json.dumps(event).encode(),
        )
        return dict(json.load(result["Payload"]))

    response = invoke("PHYSICIAN")
    if response.get("statusCode") != 200:
        raise RuntimeError(f"Patient read returned {response.get('statusCode')}")
    page = json.loads(str(response["body"]))
    if not page["items"]:
        raise RuntimeError("The synthetic preload returned no Patient records")
    if any(
        "name" in item or not item["display_token"].startswith("PT-")
        for item in page["items"]
    ):
        raise RuntimeError("Unexpected patient presentation fields")
    next_count = None
    if page["next_cursor"]:
        second = invoke("PHYSICIAN", page["next_cursor"])
        if second.get("statusCode") != 200:
            raise RuntimeError("Live FHIR pagination failed")
        second_page = json.loads(str(second["body"]))
        next_count = len(second_page["items"])
        if {row["id"] for row in page["items"]} & {
            row["id"] for row in second_page["items"]
        }:
            raise RuntimeError("Live FHIR pages overlapped")
    if invoke("UNKNOWN").get("statusCode") != 403:
        raise RuntimeError("The patient endpoint allowed an unrecognized clinical role")
    report = {
        "live_first_page_records": len(page["items"]),
        "live_second_page_records": next_count,
        "reported_total": page["total"],
        "role_denial": "passed",
        "expires_at": page["expires_at"],
        "browser_flow": "pending user test",
    }
    from pathlib import Path

    Path("docs/patient-verification.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
