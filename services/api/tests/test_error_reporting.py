"""Prove the actual SDK envelope excludes sensitive scope and exception data."""

import json

import sentry_sdk
from app.error_reporting import report, scrub_event
from sentry_sdk.envelope import Envelope
from sentry_sdk.transport import Transport


def test_scrubber_rebuilds_and_drops_unknown_events() -> None:
    assert scrub_event({"message": "patient secret"}, {}) is None
    assert (
        scrub_event({"message": "API_UNAVAILABLE"}, {"attachments": [object()]}) is None
    )
    assert scrub_event(
        {"message": "API_UNAVAILABLE", "extra": {"note": "private"}}, {}
    ) == {"message": "API_UNAVAILABLE", "level": "error", "platform": "python"}


def test_actual_sdk_envelope_has_no_scope_data() -> None:
    packets: list[bytes] = []

    class RecordingTransport(Transport):
        def capture_envelope(self, envelope: Envelope) -> None:
            packets.append(envelope.serialize())

    with (
        sentry_sdk.init(
            dsn="https://public@example.invalid/1",
            transport=RecordingTransport,
            default_integrations=False,
            auto_enabling_integrations=False,
            send_client_reports=False,
            before_send=scrub_event,
        ),
        sentry_sdk.isolation_scope() as scope,
    ):
        scope.set_user({"email": "sensitive-marker@example.invalid"})
        scope.set_extra("clinical_note", "sensitive-marker")
        scope.set_context("request", {"authorization": "sensitive-marker"})
        scope.add_breadcrumb(message="sensitive-marker")
        assert report("TELEMETRY_SELF_TEST") is not None
        sentry_sdk.capture_exception(ValueError("sensitive-marker"))
    assert len(packets) == 1
    assert b"sensitive-marker" not in packets[0]
    event = json.loads(packets[0].splitlines()[-1])
    assert event["message"] == "TELEMETRY_SELF_TEST"
    assert (
        not {"user", "extra", "contexts", "breadcrumbs", "exception", "request"}
        & event.keys()
    )
