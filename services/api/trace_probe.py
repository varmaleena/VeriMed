"""Real dev Cognito SRP -> Gateway -> API -> Aurora trace check; no token output."""

import argparse
import json
import secrets
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import boto3  # type: ignore[import-untyped]
import httpx
from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from pycognito import Cognito  # type: ignore[import-untyped]


def outputs(stack: dict[str, Any]) -> dict[str, str]:
    return {item["OutputKey"]: item["OutputValue"] for item in stack["Outputs"]}


def inspect_span_names(value: Any, names: set[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if (
                key.lower() == "name"
                and isinstance(child, str)
                and child
                in {
                    "api.request",
                    "web.cell.read",
                    "api.encounters.list",
                    "authorization.list_encounters",
                    "database.encounters.list",
                }
            ):
                names.add(child)
            inspect_span_names(child, names)
    elif isinstance(value, list):
        for child in value:
            inspect_span_names(child, names)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="default")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument(
        "--output", type=Path, default=Path("docs/tracing-verification.json")
    )
    args = parser.parse_args()
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    cognito = session.client("cognito-idp")
    report: dict[str, Any] = {
        "status": "FAIL",
        "verified_at": datetime.now(UTC).isoformat(),
        "region": args.region,
        "web_hop_verified": False,
    }
    stage, created, username, pool_id = "preflight", False, "", ""
    state = Path(".phase1-api/trace-probe-cleanup.json")
    try:
        cf = session.client("cloudformation")
        worklist = cf.describe_stacks(StackName="CellWorklist")["Stacks"][0]
        tags = {tag["Key"]: tag["Value"] for tag in worklist.get("Tags", [])}
        if any(
            tags.get(k) != v
            for k, v in {"Project": "verimed", "Env": "dev", "Tenant": "a"}.items()
        ):
            raise ValueError("Only the tagged dev cell is eligible")
        api = outputs(worklist)
        identity = outputs(cf.describe_stacks(StackName="CellIdentity")["Stacks"][0])
        pool_id, client_id = identity["UserPoolId"], identity["ClientId"]
        client = cognito.describe_user_pool_client(
            UserPoolId=pool_id, ClientId=client_id
        )["UserPoolClient"]
        pool = cognito.describe_user_pool(UserPoolId=pool_id)["UserPool"]
        if pool.get("MfaConfiguration") != "OFF" or pool.get("LambdaConfig"):
            raise ValueError(
                "This probe requires the existing trigger-free, explicitly MFA-off dev configuration"
            )
        if (
            session.client("xray").get_trace_segment_destination()["Destination"]
            != "CloudWatchLogs"
        ):
            raise ValueError("OTLP trace storage is not enabled")
        base = api["ApiUrl"]
        url = urlsplit(base)
        if url.scheme != "https" or not (url.hostname or "").endswith(
            f".execute-api.{args.region}.amazonaws.com"
        ):
            raise ValueError("Unexpected dev API destination")
        username = "trace-probe-" + secrets.token_hex(12) + "@example.invalid"
        password = secrets.token_urlsafe(36) + "Aa1!"
        stage = "create_identity"
        result = cognito.admin_create_user(
            UserPoolId=pool_id,
            Username=username,
            TemporaryPassword=password,
            MessageAction="SUPPRESS",
            ForceAliasCreation=False,
            UserAttributes=[
                {"Name": "email", "Value": username},
                {"Name": "email_verified", "Value": "true"},
            ],
        )
        username = result["User"]["Username"]
        created = True
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(
            json.dumps(
                {"pool_id": pool_id, "username": username, "region": args.region}
            ),
            encoding="utf-8",
        )
        cognito.admin_set_user_password(
            UserPoolId=pool_id, Username=username, Password=password, Permanent=True
        )

        def authenticate() -> str:
            user = Cognito(
                pool_id,
                client_id,
                username=username,
                client_secret=client["ClientSecret"],
                session=session,
            )
            user.authenticate(password=password)
            token = user.access_token
            if not isinstance(token, str):
                raise TypeError("A genuine Cognito access token is required")
            return token

        stage = "authenticate_srp"
        token = authenticate()
        with httpx.Client(timeout=60, follow_redirects=False, trust_env=False) as http:
            stage = "gateway_negative"
            if http.get(base + "/encounters").status_code != 401:
                raise ValueError("Anonymous access was not denied")
            if (
                http.get(
                    base + "/encounters", headers={"Authorization": "Bearer " + token}
                ).status_code
                != 403
            ):
                raise ValueError("An unassigned role reached clinical data")
            report["anonymous_status"], report["unassigned_role_status"] = 401, 403
            cognito.admin_add_user_to_group(
                UserPoolId=pool_id, Username=username, GroupName="PHYSICIAN"
            )
            token = authenticate()
            parts = token.split(".")
            parts[2] = ("A" if parts[2][0] != "A" else "B") + parts[2][1:]
            if (
                http.get(
                    base + "/encounters",
                    headers={"Authorization": "Bearer " + ".".join(parts)},
                ).status_code
                != 401
            ):
                raise ValueError("A tampered token was not denied")
            report["tampered_token_status"] = 401
            stage = "authorized_read"
            trace_id = secrets.token_hex(16)
            parent = "00-" + trace_id + "-" + secrets.token_hex(8) + "-01"
            start_ms = int(time.time() * 1000) - 1000
            headers = {"Authorization": "Bearer " + token, "traceparent": parent}
            for attempt in range(4):
                response = http.get(base + "/encounters", headers=headers)
                if response.status_code != 503 or attempt == 3:
                    break
                time.sleep(3)
            if response.status_code != 200:
                raise ValueError("The real authorized worklist read failed")
            body = response.json()
            if not isinstance(body.get("items"), list) or not isinstance(
                body.get("has_more"), bool
            ):
                raise TypeError("The actual response contract is invalid")
            report.update(
                {
                    "physician_status": 200,
                    "worklist_item_count": len(body["items"]),
                    "trace_id": trace_id,
                    "authentication": "real Cognito USER_SRP_AUTH; no injected claims",
                }
            )
            if (
                http.get(
                    base + "/patients", headers={"Authorization": "Bearer " + token}
                ).status_code
                != 410
            ):
                raise ValueError("The expired FHIR window was not preserved")
            report["expired_fhir_status"] = 410

        stage = "trace_delivery"
        logs = session.client("logs")
        names: set[str] = set()
        expected = {
            "api.request",
            "api.encounters.list",
            "authorization.list_encounters",
            "database.encounters.list",
        }
        for _ in range(18):
            parameters: dict[str, Any] = {
                "logGroupName": "aws/spans",
                "startTime": start_ms,
                "filterPattern": f"%{trace_id}|1-{trace_id[:8]}-{trace_id[8:]}%",
                "limit": 100,
            }
            for _page in range(10):
                page = logs.filter_log_events(**parameters)
                for event in page["events"]:
                    inspect_span_names(json.loads(event["message"]), names)
                if not page.get("nextToken"):
                    break
                parameters["nextToken"] = page["nextToken"]
            if expected <= names:
                break
            time.sleep(5)
        report["observed_span_names"] = sorted(names)
        if not expected <= names:
            raise ValueError("Required spans were not visible in CloudWatch")
        groups = [
            g
            for g in logs.describe_log_groups(logGroupNamePrefix="aws/spans")[
                "logGroups"
            ]
            if g["logGroupName"] == "aws/spans"
        ]
        if (
            len(groups) != 1
            or not groups[0].get("kmsKeyId")
            or groups[0].get("retentionInDays") != 30
        ):
            raise ValueError("Encrypted trace retention configuration is invalid")
        report.update(
            {
                "status": "PASS",
                "span_storage_kms_verified": True,
                "span_retention_days": 30,
            }
        )
    except Exception:  # noqa: BLE001 -- credentials, tokens, identities and AWS responses must not be logged
        report["failure_stage"] = stage
    finally:
        if created:
            try:
                cognito.admin_delete_user(UserPoolId=pool_id, Username=username)
                try:
                    cognito.admin_get_user(UserPoolId=pool_id, Username=username)
                    report["status"] = "FAIL"
                    report["temporary_identity_removed"] = False
                except ClientError as error:
                    if error.response["Error"]["Code"] != "UserNotFoundException":
                        raise
                    report["temporary_identity_removed"] = True
                    state.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001 -- leave metadata-only cleanup state, never a credential
                report["temporary_identity_removed"] = False
                report["status"] = "FAIL"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": report["status"],
                "stage": report.get("failure_stage", "complete"),
                "temporary_identity_removed": report.get("temporary_identity_removed"),
            }
        )
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
