# ADR 011 — Transactional ledger persistence

Status: accepted for the incremental Phase 1 storage slice, November 18, 2026.
Use the existing Aurora Data API dev adapter described in ADR 008; async SQLAlchemy/Alembic remain pending.
Use per-tenant bigint sequences maintained by a locked head instead of the spec's global bigserial.
This preserves contiguous tenant chains without sequence gaps after transaction rollback.
Acquire one transaction-scoped advisory lock per tenant before reading its head and signing the next event.
A SECURITY DEFINER insert trigger enforces tenant context, validates sequence/previous hash, and advances the head atomically.
The trigger has a fixed search path; writer roles have no direct head-update or schema-creation rights.
Force RLS on both ledger tables; keep composite encounter foreign keys tenant-scoped.
Give the writer SELECT/INSERT only on events and SELECT only on heads, with a separate generated credential.
Reject UPDATE, DELETE, and TRUNCATE through statement triggers as well as restricted grants.
Do not grant this writer secret or KMS signing rights to the read-only web API.
Event IDs make retries idempotent; reuse with different content fails. Never blindly retry an uncertain write.
Read chains using repeatable-read snapshots and bounded batches; exceeding the bound fails explicitly.
Cap canonical events at 16 KiB to leave room for signatures and JSON escaping under Data API's per-row limit.
Database heads provide consistency but cannot prove completeness against a privileged administrator rewriting both tables.
Independent Object Lock anchors, key-version registries, and signed human receipts remain pending.
Live integration tests retain real non-clinical diagnostic events under fresh test tenants; no patient/encounter rows are fabricated.
Sources: [RDS Data API](https://docs.aws.amazon.com/rdsdataservice/latest/APIReference/API_ExecuteStatement.html), [Data API limits](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/data-api.troubleshooting.html), [PostgreSQL triggers](https://www.postgresql.org/docs/17/sql-createtrigger.html).
