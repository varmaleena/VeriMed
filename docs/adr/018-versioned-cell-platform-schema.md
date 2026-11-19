# ADR 018 — Versioned cell platform schema and Data API migrations

- Date: 2026-11-19. Status: accepted and applied to dev revision 003_platform.
- Define the remaining Phase 1 tables with SQLAlchemy Core metadata and Alembic revisions.
- Keep the existing Data API dev adapter; online Alembic also supports an explicit private asyncpg URL.
- Record standard Alembic head and source checksums in an admin-only platform_meta schema.
- Operational migration metadata has no clinical rows and is intentionally outside tenant-scoped public tables.
- Reapply existing idempotent Worklist/ledger baselines once to adopt an unversioned dev database.
- Apply all missing revisions atomically under the existing advisory lock; checksum mismatch fails closed.
- Preserve applied SQL snapshots; later changes require new revisions rather than editing the baseline.
- Every clinical table has a tenant key, forced RLS and explicit tenant-composite foreign keys.
- Only SELECT is granted to the current API role; later writers require separate reviewed grants/policies.
- Notes are append-only; stored hashes must match text; claims must exactly match canonical note spans.
- Canonical offsets count Unicode code points, matching PostgreSQL char_length and Python indexing.
- Policy-content edits require a new version; activating a version remains a separate operation.
- Unknown costs/confidence stay nullable and new claims default UNVERIFIED.
- Real Aurora checks use runtime-generated non-clinical diagnostic rows and temporary grants, all rolled back.
- Clean-install PostgreSQL CI is added; hosted execution remains blocked by absent remote/runner setup.
- Sources: [row security](https://www.postgresql.org/docs/17/ddl-rowsecurity.html), [Alembic offline SQL](https://alembic.sqlalchemy.org/en/latest/offline.html), [Aurora Data API](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/data-api.html).
