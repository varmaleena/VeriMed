# Phase 1 error reporting

The API reports only `API_UNAVAILABLE`; an internal smoke test may report
`TELEMETRY_SELF_TEST`. Neither accepts free text. Unknown events are dropped.
The SDK envelope test injects a sensitive marker into user, request, extra,
breadcrumb and exception context, then checks the serialized event excludes it.

Run `.venv\Scripts\python.exe -m pytest services/api/tests/test_error_reporting.py -q`.
There is no new public telemetry endpoint. Existing request authentication is unchanged.
The existing structured `request_failed` log now uses a fixed error code rather than
an exception class name. Automatic SDK integrations are disabled.

Remote delivery has not been tested: no Sentry project/DSN is configured.
Provision the project, deliver its DSN through deployment configuration, send the fixed
smoke-test code and verify the received packet before accepting this phase requirement.
Browser error reporting and distributed web/API/database tracing remain outstanding.
