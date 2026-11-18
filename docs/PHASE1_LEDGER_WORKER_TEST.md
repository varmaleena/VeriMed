# Phase 1 scheduled ledger worker test

The dev cell now has a cell-fixed daily anchor worker, retained-version checkpoint discovery, and a 36-hour freshness check. EventBridge invokes it at **00:30 UTC / 06:00 IST**. It reads the configured cell tenant only and cannot fetch the writer/admin secrets. The worker uses the temporary Lambda/Data API architecture described in ADR 008; full Phase 1 production-runtime work remains pending.

Run local tests from PowerShell in `F:\AWS MSP`:

```powershell
.\.venv\Scripts\python.exe -m pytest services/api/tests/test_ledger_anchors.py -q
```

Exercise the deployed worker and IAM boundaries:

```powershell
.\scripts\Test-LedgerWorker.ps1 -AwsProfile default -Region us-east-1
```

Each live run appends one real `system.ledger_probe` operational self-test event in the configured dev tenant. It generates no patients, clinical notes or findings. It then invokes the checkpoint operation through IAM, checks that the retained checkpoint is discoverable without an Aurora index, and verifies its signatures/retention/freshness. The object is retained for seven years. The test verifies retry idempotency, rejects a tenant override, simulates denial of writer/admin secret access and another tenant's S3 prefix, and reads the live schedule, retry configuration and encrypted queue attributes. It also checks the older local version-1 receipt when present.

Input is described by `packages/api-client/ledger-anchor-job.schema.json`: only `job: daily|checkpoint` is accepted. Tenant IDs and dates cannot be provided. `daily` uses the latest non-empty closed UTC day; `checkpoint` can seal today's real operational events. Empty cells return EMPTY, and cells with only today's events can return WAITING until the closed-day run. Checkpoints include the full verified chain head, even when the daily Merkle root names an earlier non-empty day.

Version 2 adds a signed daily seal timestamp while preserving version 1 encoding. A fixed daily slot makes retries return the same immutable object version; the next daily slot creates a fresh checkpoint even when the head is unchanged. Discovery lists versions only inside the tenant prefix and selects the highest sequence then newest stored version. It rejects malformed keys, delete markers, broken pagination and inventory overflow; it validates the selected pinned version, key/sequence, KMS signature, encryption and retention. It does not trust a mutable database pointer or the unversioned latest-object URL.

Freshness requires S3 stored time and the signed seal time to be no older than 36 hours, with a five-minute future-clock tolerance. Newer unanchored events stay UNVERIFIED. A retained checkpoint that contradicts a truncated/replaced database chain fails before the job is allowed to issue a replacement. Discovery is bounded at 10,000 versions. The initial five-minute worker verifies at most 200 events and fails explicitly above that limit; streaming verification/checkpoint reuse must be implemented before higher-volume production use.

EventBridge delivery and Lambda execution each have two retries and a two-hour maximum event age. Both route exhausted failures to an encrypted, 14-day SQS terminal queue. CloudWatch alarms cover function errors, queued failures and 36 missing hourly heartbeat datapoints. This live test directly invokes the function; the next automatic daily firing and actual exhausted-retry DLQ delivery are not claimed as observed. Operator notification subscriptions remain pending in `docs/BLOCKERS.md`. The deliberate invalid-input test may temporarily trigger the function-error alarm.

The account's concurrency quota is 10. Deployment uses the explicit dev-only `ledgerUseUnreserved=true` context because AWS requires 100 executions to remain unreserved before accepting a function reservation. Normal CDK configuration reserves one slot. Conditional writes preserve idempotency when duplicate dev workers run. A quota increase is needed before reserving the production slot; this task did not request one.

The initial CDK client's final status poll expired its AWS signature after deployment. A fresh CloudFormation read confirmed UPDATE_COMPLETE, and the deployed worker passed the live checks. This was a status-poll failure, not a rolled-back stack.

Verification outcomes are written to `docs/ledger-worker-verification.json`. No event payloads, signatures, patient identifiers or secret values are logged. This slice reuses existing keys and credentials; it adds usage-based Lambda/SQS/CloudWatch charges and a daily Aurora wake-up, with no new always-on compute.
