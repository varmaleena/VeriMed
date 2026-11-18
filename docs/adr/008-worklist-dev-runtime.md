# 008 — Incremental Worklist API runtime

The first Worklist slice uses the real Aurora PostgreSQL database and Cognito access tokens.
Aurora Serverless v2 is reached through RDS Data API during the dev slice.
API Gateway validates the cell Cognito issuer and application client.
FastAPI runs in Lambda through Mangum while the ECS application infrastructure is pending.
Verified Permissions evaluates the authenticated principal's clinical roles before database access.
Read transactions set a restricted database role and transaction-local tenant context.
The runtime uses a separate generated read-only database login and cannot read the admin secret.
Forced RLS and composite tenant foreign keys enforce cell data scope.
The Data API adapter is isolated in the repository function for replacement by the specified async SQLAlchemy adapter.
Schema changes are transactionally applied by the migration runner until the Alembic migration stack is added.
These are temporary implementation deviations to make the Worklist independently testable.
Production runtime, migrations, tracing export, and API integration tests remain Phase 1 acceptance work.
