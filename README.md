# ChartVigil / VeriMed

The workspace contains the deployed dev foundations and an in-progress Phase 1 platform. See docs/IMPLEMENTATION_STATUS.md and docs/BLOCKERS.md for exact acceptance gaps. HIPAA-aligned design, synthetic data only. Install GNU Make, Node.js 24, pnpm at the version in package.json, uv, Git, and Docker with Compose v2. Copy .env.example to .env and set fresh local PostgreSQL and MinIO credentials. Run with synthetic data only.

```sh
make bootstrap
make lint
make test
make synth
```

The first Compose build compiles the pinned MinIO Community source. See [blockers](docs/BLOCKERS.md) for workflows that still need a VeriMed AWS account or live validation.

On Windows PowerShell, the following commands run the same unit tests and CDK synthesis as `make test` and `make synth`. Run them from the repository root.

```powershell
pnpm install --frozen-lockfile
pnpm --filter @verimed/cdk test
pnpm --filter @verimed/cdk exec cdk synth HubFoundation CellFoundation
```

If the workspace dependencies are already installed and PowerShell cannot find pnpm, run `npm.cmd --prefix infra/cdk test`. To synthesize with those same installed dependencies, run `npm.cmd --prefix infra/cdk run build`, change into `infra/cdk`, and run `& .\node_modules\.bin\cdk.cmd synth HubFoundation CellFoundation --app 'node dist/app.js'`.

For the Phase 0 AWS handoff, verify the deployed dev cell with the authorized profile.

```sh
aws cloudformation describe-stacks --stack-name CellFoundation --profile default --region us-east-1 --query 'Stacks[0].StackStatus' --output text
```

Expect `CREATE_COMPLETE`. Local `make test` runs the Python unit suite and CDK infrastructure tests. `make synth` should synthesize both foundation stacks with cdk-nag enabled. The [spike evidence](docs/spikes/README.md) tracks the live checks and outstanding acceptance work.

The HAPI benchmark uses the same Synthea cohort as HealthLake. With Docker Compose running and a fresh HAPI database, run the following command against the local prepared fixture.

```powershell
uv run --locked python spikes/s4_prepare_synthea.py .phase0-synthea/generated/fhir .phase0-synthea/benchmark-with-support
uv run --locked python spikes/s4_hapi_import.py .phase0-synthea/benchmark-with-support/hapi --request-timeout 600 --output docs/spikes/s4-hapi.json
```

Skip the preparation command if that output directory already exists. The loader imports Synthea's hospital and practitioner bundles first, verifies that the dedicated HAPI database contains 50 patients, and writes the elapsed import time.
