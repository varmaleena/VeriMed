# ADR 020: Categorical error telemetry

Date: 2026-11-20
Status: Accepted for the API; remote delivery pending configuration.

Clinical error messages, stack locals and request context can contain PHI or credentials.
Use manual Sentry events with a closed set of operational error codes.
Disable automatic integrations, request bodies, breadcrumbs, tracing, profiling and SDK logs.
Rebuild outbound events from an allowlist; discard unknown messages and attachments.
Preserve only a validated SDK event ID alongside the fixed message, level and platform.
Never capture the original exception, user, request, note, tenant identifier or scope context.
The API returns its existing unavailable response even when error telemetry fails.
This deliberately trades stack-level diagnostics for a smaller disclosure surface.
Unit tests inspect a real SDK envelope through an in-memory transport.
No browser SDK is enabled yet; authenticated browser reporting remains outstanding.
Remote delivery requires an operator-provided Sentry project/DSN and a scrubbed smoke test.
An SDK event ID is not proof that Sentry received an event.
Reference: https://docs.sentry.io/platforms/python/data-management/sensitive-data/
