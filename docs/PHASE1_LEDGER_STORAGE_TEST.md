# Phase 1 ledger storage test

This slice adds durable Aurora ledger storage and a separate generated writer credential. It does not expose a public append endpoint or enable clinical sign-off. Independent Object Lock checkpoints are now available through the [on-demand anchor foundation](PHASE1_LEDGER_ANCHOR_TEST.md); automatic scheduling and checkpoint inventory remain pending. Phase 1 remains in progress.

From PowerShell in `F:\AWS MSP`, run the unit tests:

```powershell
.\.venv\Scripts\python.exe -m pytest services/api/tests/test_ledger.py services/api/tests/test_ledger_store.py -q
```

Repeat the deployed Aurora/KMS integration test:

```powershell
.\scripts\Test-LedgerStorage.ps1 -AwsProfile default -Region us-east-1
```

The script reads only resource identifiers from CloudFormation outputs. It does not print secret values. The profile must be authorized for the dev stack's Data API cluster, admin/reader/writer secrets, and signing key. Add `-ApplySchema` to transactionally reapply the checked-in idempotent ledger migration. The deployed Worklist schema is a prerequisite. This continues the temporary migration approach in ADR 008 until Alembic integration.

The live test appends fresh `system.ledger_probe` diagnostics under new test tenants, using real KMS signatures and transactions. Each successful run retains five small diagnostic events. It generates no patients, encounters, notes or findings. Outcomes and counts are saved in `docs/ledger-storage-verification.json`; ledger payloads, tenant identifiers and signatures are excluded from the report and logs.

Expected checks:

- Three concurrent writes receive consecutive sequences and survive a fresh database read with valid signatures.
- Replaying an event ID returns its original event; changing its content fails.
- Forced RLS hides the other tenant's events and rejects cross-tenant insertion.
- The writer cannot update/delete/truncate events or directly update heads. The API reader cannot append.
- Statement triggers reject owner-level mutation as well. The test does not disable triggers or bypass protections.
- A real KMS signing failure rolls back without advancing the chain.
- A repeatable-read snapshot remains stable while another transaction appends.
- Bounded reads fail rather than returning partial verification data; in-memory tampering is detected.

Each append takes a tenant-scoped advisory transaction lock. A fixed-search-path SECURITY DEFINER insert trigger atomically validates and advances the head. Events and heads have forced RLS. Writer grants are limited to event SELECT/INSERT and head SELECT; only the trigger updates heads. Locks/timeouts are bounded. Callers must retry uncertain operations with the same event ID; the adapter does not blindly retry writes.

The database head is a consistency checkpoint, not an independent proof against a privileged administrator rewriting both tables. Immutable external anchors and a trusted key-version registry remain required before production sign-off. The read path currently caps verification at 10,000 events and fails explicitly beyond that limit; larger production chains need streaming verification and checkpointing.

Cost: this slice reuses the existing Aurora cluster and KMS keys. One additional encrypted Secrets Manager credential is approximately $0.40/month, prorated, plus API requests. Aurora wake-up time and KMS/Data API calls add usage charges. No new always-on compute is created. [Secrets Manager pricing](https://aws.amazon.com/secrets-manager/pricing/).
