# ADR 013 — Scheduled checkpoint refresh and S3 inventory

Status: accepted for the incremental Phase 1 worker slice, November 18, 2026.
Run a cell-fixed IAM Lambda at 00:30 UTC with a read-only database secret and tenant-prefixed S3 access.
The job schema rejects tenant/date overrides; operational checkpoint requests use the same fixed cell tenant.
Daily mode anchors the most recent non-empty closed UTC day; checkpoint mode can cover today's real events.
Version 2 manifests add a signed daily seal time; version 1 bytes remain unchanged by omitting absent fields.
One deterministic daily slot makes retries idempotent while allowing quiet chains to receive fresh checkpoints.
Discover checkpoints from retained S3 object versions, choosing the highest sequence then newest stored version.
Validate the pinned manifest, key namespace, KMS signature, retention and database prefix before refreshing it.
Freshness requires both S3 stored time and signed seal time within 36 hours; newer ledger events remain UNVERIFIED.
Bound inventory discovery to 10,000 versions and the initial worker to 200 events; exceedance fails explicitly.
A five-minute timeout, two-hour retry age, two retries, encrypted terminal DLQ and CloudWatch alarms bound failures.
The dev account reports only 10 concurrent Lambda executions, preventing a reservation while leaving AWS's required 100 unreserved.
Use explicit `ledgerUseUnreserved=true` for this dev account; normal deployments reserve one slot.
Idempotent conditional writes tolerate duplicate workers; raise the account quota before reserving production concurrency.
The worker cannot fetch the writer/admin credentials or write/delete the database, and has no public URL.
Alarm notifications require an operator destination; local/live checks do not prove a future scheduled firing or DLQ delivery.
Sources: [Lambda reservations](https://docs.aws.amazon.com/lambda/latest/dg/configuration-concurrency.html), [S3 version inventory](https://docs.aws.amazon.com/AmazonS3/latest/API/API_ListObjectVersions.html), [EventBridge target retries](https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.aws_events_targets.TargetBaseProps.html).
