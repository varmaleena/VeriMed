"""Manual, categorical error telemetry: no exception or request data is accepted."""

import os
import re
from typing import Literal

import sentry_sdk
from sentry_sdk.types import Event, Hint

ErrorCode = Literal["API_UNAVAILABLE", "TELEMETRY_SELF_TEST"]
_CODES = frozenset({"API_UNAVAILABLE", "TELEMETRY_SELF_TEST"})


def scrub_event(event: Event, hint: Hint) -> Event | None:
    """Rebuild the packet; scopes, processors and caller context are untrusted."""
    if hint.get("attachments"):
        return None
    message = event.get("message")
    if not isinstance(message, str) or message not in _CODES:
        return None
    clean: Event = {"message": message, "level": "error", "platform": "python"}
    event_id = event.get("event_id")
    if isinstance(event_id, str) and re.fullmatch(r"[0-9a-f]{32}", event_id):
        clean["event_id"] = event_id
    return clean


def configure() -> bool:
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return False
    sentry_sdk.init(
        dsn=dsn,
        default_integrations=False,
        auto_enabling_integrations=False,
        send_default_pii=False,
        include_local_variables=False,
        max_request_body_size="never",
        max_breadcrumbs=0,
        traces_sample_rate=0.0,
        profiles_sample_rate=0.0,
        enable_logs=False,
        send_client_reports=False,
        before_send=scrub_event,
    )
    return True


def report(code: ErrorCode) -> str | None:
    """Return an SDK event ID, which is not a remote-delivery acknowledgement."""
    if code not in _CODES or not sentry_sdk.is_initialized():
        return None
    try:
        return sentry_sdk.capture_message(code, level="error")
    except Exception:  # noqa: BLE001 -- telemetry cannot replace the API failure response
        # An unavailable telemetry destination must not replace the API response.
        return None
