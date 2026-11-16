# VeriMed Phase 0

The workspace contains the Phase 0 foundation. Install GNU Make, Node.js 24, pnpm at the version in package.json, uv, Git, and Docker with Compose v2. Copy .env.example to .env and set fresh local PostgreSQL and MinIO credentials. Run with synthetic data only.

```sh
make bootstrap
make lint
make test
make synth
```

The first Compose build compiles the pinned MinIO Community source. See [blockers](docs/BLOCKERS.md) for workflows that still need a VeriMed AWS account or live validation.
