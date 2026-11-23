"""Real hosted Cognito authorization-code/PKCE check; temporary identity, no token output."""

import argparse
import json
import secrets
import time
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import boto3  # type: ignore[import-untyped]
import httpx
from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from trace_probe import inspect_span_names


class Forms(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.forms: list[dict[str, Any]] = []
        self.current: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "form":
            self.current = {
                "action": attributes.get("action", ""),
                "fields": {},
                "password": False,
            }
            self.forms.append(self.current)
        elif tag in {"input", "button"} and self.current is not None:
            name = attributes.get("name")
            if name:
                self.current["fields"][name] = attributes.get("value") or ""
            if attributes.get("type") == "password":
                self.current["password"] = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self.current = None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-trace", action="store_true")
    args = parser.parse_args()
    session = boto3.Session(profile_name="default", region_name="us-east-1")
    cf, cognito = session.client("cloudformation"), session.client("cognito-idp")
    report: dict[str, Any] = {
        "status": "FAIL",
        "verified_at": datetime.now(UTC).isoformat(),
        "web_trace_verified": False,
    }
    stage, username, pool = "preflight", "", ""
    state = Path(".phase1-api/web-probe-cleanup.json")
    try:
        stack = cf.describe_stacks(StackName="CellWeb")["Stacks"][0]
        if stack["StackStatus"] not in {"CREATE_COMPLETE", "UPDATE_COMPLETE"}:
            raise RuntimeError("Hosted stack is not ready")
        tags = {item["Key"]: item["Value"] for item in stack["Tags"]}
        if any(
            tags.get(k) != v
            for k, v in {"Project": "verimed", "Env": "dev", "Tenant": "a"}.items()
        ):
            raise ValueError("Only the authorized dev cell may be probed")
        outputs = {item["OutputKey"]: item["OutputValue"] for item in stack["Outputs"]}
        origin = outputs["WebUrl"]
        identity = {
            item["OutputKey"]: item["OutputValue"]
            for item in cf.describe_stacks(StackName="CellIdentity")["Stacks"][0][
                "Outputs"
            ]
        }
        pool = identity["UserPoolId"]
        configuration = cognito.describe_user_pool_client(
            UserPoolId=pool, ClientId=identity["ClientId"]
        )["UserPoolClient"]
        if origin + "/api/auth/callback/cognito" not in configuration.get(
            "CallbackURLs", []
        ):
            raise RuntimeError("Hosted callback is not configured")
        allowed = {
            urlsplit(origin).hostname,
            urlsplit(identity["LoginDomainUrl"]).hostname,
        }
        report["url"] = origin
        with httpx.Client(
            timeout=60, trust_env=False, follow_redirects=False
        ) as client:
            anonymous = client.get(origin + "/worklist")
            if anonymous.status_code not in {302, 303, 307}:
                raise RuntimeError("Clinical route accepted an anonymous request")
            report["anonymous_clinical_redirect"] = True
            direct = client.get("https://" + outputs["OriginDomain"] + "/login")
            if direct.status_code != 403:
                raise RuntimeError("Direct origin access was accepted")
            report["anonymous_origin_status"] = direct.status_code
            stage = "create_suppressed_identity"
            email = "web-probe-" + secrets.token_hex(10) + "@example.invalid"
            password = secrets.token_urlsafe(32) + "Aa1!"
            created = cognito.admin_create_user(
                UserPoolId=pool,
                Username=email,
                MessageAction="SUPPRESS",
                UserAttributes=[
                    {"Name": "email", "Value": email},
                    {"Name": "email_verified", "Value": "true"},
                ],
            )
            username = created["User"]["Username"]
            state.write_text(
                json.dumps({"pool": pool, "username": username}), encoding="utf-8"
            )
            cognito.admin_set_user_password(
                UserPoolId=pool, Username=username, Password=password, Permanent=True
            )
            cognito.admin_add_user_to_group(
                UserPoolId=pool, Username=username, GroupName="PHYSICIAN"
            )
            stage = "start_authorization_code"
            csrf = client.get(origin + "/api/auth/csrf").json()["csrfToken"]
            response = client.post(
                origin + "/api/auth/signin/cognito",
                data={"csrfToken": csrf, "callbackUrl": origin + "/worklist"},
                headers={"X-Auth-Return-Redirect": "1", "Origin": origin},
            )
            authorization = response.json()["url"]

            def follow(url: str) -> httpx.Response:
                for _ in range(12):
                    parsed = urlsplit(url)
                    if parsed.scheme != "https" or parsed.hostname not in allowed:
                        raise ValueError("Unexpected OAuth redirect destination")
                    page = client.get(url)
                    if page.status_code not in {301, 302, 303, 307, 308}:
                        return page
                    url = urljoin(str(page.url), page.headers["location"])
                raise RuntimeError("OAuth redirect limit reached")

            stage = "managed_login_form"
            page = follow(authorization)
            report["managed_login_page_status"] = page.status_code
            forms = Forms()
            forms.feed(page.text)
            matches = [
                form
                for form in forms.forms
                if form["password"]
                and "username" in form["fields"]
                and urlsplit(urljoin(str(page.url), form["action"])).path == "/login"
            ]
            report["managed_password_forms"] = len(matches)
            if page.status_code != 200 or not matches:
                raise RuntimeError("Managed login form is unavailable")
            form = matches[0]
            action = urljoin(str(page.url), form["action"])
            if (
                urlsplit(action).hostname
                != urlsplit(identity["LoginDomainUrl"]).hostname
            ):
                raise ValueError("Unexpected managed login submission destination")
            fields = dict(form["fields"])
            fields.update({"username": email, "password": password})
            fields.setdefault("signInSubmitButton", "Sign in")
            stage = "managed_login_submit"
            submitted = client.post(
                action, data=fields, headers={"Origin": identity["LoginDomainUrl"]}
            )
            report["managed_login_submit_status"] = submitted.status_code
            report["managed_login_returned_code"] = "code=" in submitted.headers.get(
                "location", ""
            )
            if submitted.status_code not in {302, 303}:
                raise RuntimeError(
                    "Managed sign-in did not return an authorization code"
                )
            stage = "code_exchange_and_worklist"
            result = follow(urljoin(str(submitted.url), submitted.headers["location"]))
            report["callback_result_status"] = result.status_code
            path = urlsplit(str(result.url)).path
            report["callback_result_path"] = (
                path
                if path in {"/login", "/worklist", "/api/auth/error", "/error"}
                else "other"
            )
            if (
                result.status_code != 200
                or urlsplit(str(result.url)).path != "/worklist"
            ):
                raise RuntimeError("Hosted authorization-code exchange failed")
            # Actual empty data is expected; no synthetic encounter results are injected.
            if "No encounters in this view" not in result.text:
                raise RuntimeError("Actual Worklist read did not complete")
            report["real_code_pkce_sign_in"] = True
            report["worklist_status"] = result.status_code
            cookies = [
                cookie
                for cookie in client.cookies.jar
                if cookie.name.startswith("__Secure-authjs.session-token")
            ]
            if not cookies or not all(
                cookie.secure and cookie.has_nonstandard_attr("HttpOnly")
                for cookie in cookies
            ):
                raise RuntimeError("Secure HttpOnly session cookie is missing")
            report["secure_http_only_session"] = True
            if args.with_trace:
                stage = "web_api_database_trace"
                trace_id = secrets.token_hex(16)
                start = int(time.time() * 1000)
                traced = client.get(
                    origin + "/worklist",
                    headers={
                        "traceparent": f"00-{trace_id}-{secrets.token_hex(8)}-01",
                        "baggage": "privacy-test=unit-private-marker",
                    },
                )
                if (
                    traced.status_code != 200
                    or "No encounters in this view" not in traced.text
                ):
                    raise RuntimeError("Traced clinical read failed")
                names: set[str] = set()
                required = {
                    "web.cell.read",
                    "api.request",
                    "api.encounters.list",
                    "authorization.list_encounters",
                    "database.encounters.list",
                }
                logs = session.client("logs")
                for _ in range(24):
                    events = logs.filter_log_events(
                        logGroupName="aws/spans",
                        startTime=start,
                        filterPattern=f"%{trace_id}|1-{trace_id[:8]}-{trace_id[8:]}%",
                        limit=100,
                    )
                    for event in events.get("events", []):
                        if "unit-private-marker" in event["message"]:
                            raise RuntimeError(
                                "Baggage marker appeared in exported spans"
                            )
                        inspect_span_names(json.loads(event["message"]), names)
                    if required <= names:
                        break
                    time.sleep(5)
                report["trace_id"] = trace_id
                report["observed_span_names"] = sorted(names)
                report["web_trace_verified"] = required <= names
                report["baggage_marker_absent"] = True
                if not report["web_trace_verified"]:
                    raise RuntimeError("Distributed trace did not arrive")
            patients = client.get(origin + "/patients")
            report["expired_fhir_ui_verified"] = (
                patients.status_code == 200
                and "The synthetic-data test window has ended" in patients.text
            )
            if not report["expired_fhir_ui_verified"]:
                raise RuntimeError("Expired FHIR state was not preserved")
            stage = "session_integrity"
            for cookie in cookies:
                value = cookie.value
                if not isinstance(value, str) or len(value) < 22:
                    raise TypeError("Session cookie is invalid")
                cookie.value = (
                    value[:20] + ("a" if value[20] != "a" else "b") + value[21:]
                )
            tampered = client.get(origin + "/worklist")
            if tampered.status_code not in {302, 303, 307}:
                raise RuntimeError("Altered session was accepted")
            report["altered_session_rejected"] = True
            report["status"] = "PASS"
    except Exception as error:  # noqa: BLE001 - never print OAuth exceptions or response bodies
        report["failure_stage"] = stage
        report["error_type"] = type(error).__name__
    finally:
        if username:
            try:
                cognito.admin_user_global_sign_out(UserPoolId=pool, Username=username)
                cognito.admin_delete_user(UserPoolId=pool, Username=username)
                try:
                    cognito.admin_get_user(UserPoolId=pool, Username=username)
                except ClientError as error:
                    if error.response["Error"]["Code"] != "UserNotFoundException":
                        raise
                    report["temporary_identity_removed"] = True
                    state.unlink(missing_ok=True)
                else:
                    raise RuntimeError("Temporary identity still exists")
            except Exception:  # noqa: BLE001 - retain cleanup state and fail the probe on every cleanup error
                report["status"] = "FAIL"
                report["temporary_identity_removed"] = False
    Path("docs/web-verification.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                key: report.get(key)
                for key in (
                    "status",
                    "failure_stage",
                    "error_type",
                    "temporary_identity_removed",
                )
            }
        )
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
