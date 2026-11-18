"""Verify the deployed daily worker, independent inventory and IAM boundaries."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import boto3  # type: ignore[import-untyped]
import structlog
from app.ledger import KmsSigner
from app.ledger_anchors import AnchorReference, AnchorStore
from app.ledger_inventory import CheckpointInventory
from app.ledger_store import LedgerStore


def main() -> None:
    structlog.configure(processors=[structlog.processors.JSONRenderer()])
    cfn = boto3.client("cloudformation")

    def outputs(stack: str) -> dict[str, str]:
        return {
            row["OutputKey"]: row["OutputValue"]
            for row in cfn.describe_stacks(StackName=stack)["Stacks"][0]["Outputs"]
        }

    ledger, data = outputs("CellLedger"), outputs("CellWorklist")
    client = boto3.client("lambda")
    configuration = client.get_function_configuration(
        FunctionName=ledger["AnchorWorkerName"]
    )
    settings = configuration["Environment"]["Variables"]
    tenant = UUID(settings["TENANT_ID"])
    assert settings["DATABASE_SECRET_ARN"] == data["RuntimeSecretArn"]

    def invoke(payload: dict[str, str], *, denied: bool = False) -> dict[str, object]:
        result = client.invoke(
            FunctionName=ledger["AnchorWorkerName"],
            InvocationType="RequestResponse",
            Payload=json.dumps(payload).encode(),
        )
        body: dict[str, object] = json.load(result["Payload"])
        if denied:
            assert (
                result.get("FunctionError") and body.get("errorType") == "RuntimeError"
            )
        elif result.get("FunctionError"):
            raise RuntimeError(
                "The deployed ledger worker returned a sanitized execution error"
            )
        return body

    initial = invoke({"job": "daily"})
    signer = KmsSigner(boto3.client("kms"), ledger["SigningKeyArn"])
    db = boto3.client("rds-data")
    common = {"resourceArn": data["ClusterArn"], "database": "verimed"}
    writer = LedgerStore(
        db, dict(common, secretArn=data["LedgerWriterSecretArn"]), signer, writer=True
    )
    reader = LedgerStore(db, dict(common, secretArn=data["RuntimeSecretArn"]), signer)
    # This is a real operational self-test event in the configured cell, not a clinical fixture.
    writer.append(
        tenant,
        uuid4(),
        "system.ledger_probe",
        {"purpose": "scheduled checkpoint self-test", "nonce": str(uuid4())},
    )
    sealed = invoke({"job": "checkpoint"})
    assert sealed["status"] == "SEALED"
    anchors = AnchorStore(
        boto3.client("s3"),
        ledger["AnchorBucketName"],
        ledger["AnchorEncryptionKeyArn"],
        signer,
    )
    inventory = CheckpointInventory(anchors)
    checkpoint = inventory.latest(tenant)
    assert checkpoint is not None and checkpoint.anchor.manifest.version == 2
    assert invoke({"job": "checkpoint"})["status"] == "SEALED"
    repeated = inventory.latest(tenant)
    assert repeated is not None and repeated.reference == checkpoint.reference
    entries, head = reader.read(tenant)
    assert inventory.verify_latest(entries, tenant, head).status == "VERIFIED"
    assert (
        inventory.verify_latest(
            entries, tenant, head, now=datetime.now(UTC) + timedelta(hours=37)
        ).status
        == "UNVERIFIED"
    )
    invoke({"job": "checkpoint", "tenant_id": str(uuid4())}, denied=True)
    iam = boto3.client("iam")
    denials = [
        ("secretsmanager:GetSecretValue", data["LedgerWriterSecretArn"]),
        ("secretsmanager:GetSecretValue", data["SecretArn"]),
        (
            "s3:PutObject",
            f"arn:aws:s3:::{ledger['AnchorBucketName']}/anchors/{uuid4()}/probe.json",
        ),
    ]
    for action, resource in denials:
        evaluations = iam.simulate_principal_policy(
            PolicySourceArn=ledger["AnchorWorkerRoleArn"],
            ActionNames=[action],
            ResourceArns=[resource],
        )["EvaluationResults"]
        assert evaluations and all(
            row["EvalDecision"] in ("implicitDeny", "explicitDeny")
            for row in evaluations
        )
    schedule = boto3.client("events").describe_rule(Name=ledger["AnchorScheduleName"])
    assert (
        schedule["State"] == "ENABLED"
        and schedule["ScheduleExpression"] == "cron(30 0 * * ? *)"
    )
    queue = boto3.client("sqs").get_queue_attributes(
        QueueUrl=ledger["AnchorDeadLetterQueueUrl"],
        AttributeNames=["KmsMasterKeyId", "MessageRetentionPeriod"],
    )["Attributes"]
    assert (
        queue["KmsMasterKeyId"] == ledger["AnchorEncryptionKeyArn"]
        and queue["MessageRetentionPeriod"] == "1209600"
    )
    async_config = client.get_function_event_invoke_config(
        FunctionName=ledger["AnchorWorkerName"]
    )
    assert (
        async_config["MaximumRetryAttempts"] == 2
        and async_config["MaximumEventAgeInSeconds"] == 7200
        and async_config["DestinationConfig"]["OnFailure"]["Destination"]
    )
    # Check the v1 receipt created before this schema upgrade without writing another object.
    legacy_path = Path(".phase1-api/anchor-test-receipt.json")
    legacy_checked = False
    if legacy_path.exists():
        reference = AnchorReference.model_validate_json(legacy_path.read_text())
        anchors.load(reference, UUID(reference.key.split("/")[1]))
        legacy_checked = True
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "initial_daily_status": initial["status"],
        "worker_checkpoint_status": sealed["status"],
        "worker_checked_events": sealed["checked"],
        "operational_diagnostic_events_written": 1,
        "clinical_records_written": 0,
        "schedule_utc": "00:30 daily",
        "schedule_ist": "06:00 daily",
        "checks": {
            name: "passed"
            for name in [
                "deployed_worker_read_only_login",
                "real_worker_kms_s3_checkpoint",
                "daily_slot_idempotency",
                "independent_version_inventory",
                "fresh_checkpoint_verification",
                "stale_checkpoint_fail_closed",
                "tenant_override_rejection",
                "writer_secret_iam_denial",
                "admin_secret_iam_denial",
                "other_tenant_prefix_iam_denial",
                "enabled_daily_schedule",
                "encrypted_terminal_queue",
                "async_retry_and_failure_configuration",
            ]
        },
        "legacy_receipt_checked": legacy_checked,
        "next_scheduled_delivery": "not yet observed",
        "dlq_delivery": "configured, exhaustion path not exercised live",
        "alarm_notifications": "operator destination pending",
    }
    Path("docs/ledger-worker-verification.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
