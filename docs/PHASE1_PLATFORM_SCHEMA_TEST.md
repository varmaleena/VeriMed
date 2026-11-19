# Phase 1 platform schema verification

The dev cell is at Alembic revision 003_platform. There are 26 clinical tables, all with non-null tenant
keys and forced RLS, and 31 tenant-composite foreign keys. The remaining spec-defined Phase 1 tables
are now present, including users/roles, transcripts, note versions, audits, claims/evidence, flags,
reviews, policies, knowledge chunks, anchors, evaluation and usage.

The six live checks passed: cross-tenant reads, cross-tenant writes, cross-tenant foreign keys,
exact claim spans, append-only notes and note hash validation. Test inputs are generated in the
integration harness and never committed. Diagnostic grants are rolled back with their transactions.
The real report is platform-schema-verification.json; it is not a fabricated product response.

Commands from repository root:

    ./scripts/Test-PlatformSchema.ps1
    ./scripts/Test-PlatformSchema.ps1 -ApplySchema
    .venv/Scripts/alembic.exe -c services/api/alembic.ini upgrade head --sql

On systems with Make, make dev starts the web app on loopback; make test-int discovers the dev-cell
database outputs and runs the rollback-only integration checks. The integration entry point refuses
non-dev stack tags or a tenant tag that differs from CELL. AWS credentials and a deployed CellWorklist
stack are required. Windows users can run uv run --all-packages python services/api/test_integration.py.

The Data API runner records source checksums, takes an advisory transaction lock and applies missing
revisions atomically. A second live run applied no revisions and confirmed matching checksums.
Alembic and the Data API runner share the same SQL sources and checksum history.
The generated 003_platform.sql snapshot is immutable after deployment; new changes need a new revision.
SQLAlchemy-generated trailing spaces are preserved by a path-specific Git whitespace attribute.

The administrative platform_meta schema stores revision IDs/checksums only. Public clinical tables
have tenant RLS; platform_meta is revoked from PUBLIC and has no clinical data.
The current app database credential remains read-only. Future ingestion/audit/signing writers must
receive their own least-privilege roles; this migration does not grant the app broad mutation rights.

Notes are append-only. A human edit creates another version, and human/final versions require an author.
Claim offsets use Unicode code points and are checked against the stored canonical note text.
Policy content is immutable within a version. Missing costs/confidence remain unknown rather than zero.
This database foundation does not implement auditing, clinical safety or sign-off.

Validation: 150 Python unit tests passed, Ruff and strict mypy passed, and Alembic offline SQL rendered.
A real PostgreSQL/Alembic clean-install CI job is configured but not run: no Git remote or hosted CI is
configured. Docker/WSL remain unavailable locally. The Aurora live migration and checks did run.
Existing framework deprecation warnings remain. No AWS resource was added by the schema migration;
incremental Aurora/Data API validation spend is estimated below $0.02, not a refreshed billing measurement.
