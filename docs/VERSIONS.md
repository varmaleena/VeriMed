# Phase 0 versions

The Worklist slice pins FastAPI 0.163.2, Mangum 0.22.0, boto3 1.44.5, OpenTelemetry SDK 1.45.2, structlog 26.1.0, pytest 9.2.0, and httpx 0.28.1. The OpenAPI generator is openapi-typescript 7.13.0. These releases were verified against the package registries on November 18, 2026. Aurora PostgreSQL 17.11 was verified through the regional RDS engine inventory.

The first Phase 1 UI slice pins Next.js 16.4.6, React and React DOM 19.3.1, React type definitions 19.3.0, and Auth.js 5.0.0-beta.32. npm release metadata was checked on November 18, 2026. Auth.js v5 is a prerelease required by the specification. TypeScript checks application source strictly and skips third-party declaration checking because the Auth.js package includes unresolved optional provider declarations.

npm stable release metadata verified on November 16, 2026. pnpm 12.21.0, AWS CDK library 2.277.0, CDK CLI 2.1148.1, cdk-nag 3.0.2, constructs 10.8.1, TypeScript 7.0.2, Node types 26.6.6, ESLint 10.15.0, Prettier 3.10.1.

PyPI release metadata verified the same day. Ruff 0.17.5, mypy 2.4.1, pre-commit 4.7.0. Python stays on the specified 3.12 line.

S2 uses Strands 1.65.0, Pydantic 2.14.3, and LiteLLM 1.106.10 in the client environment. Strands requires LiteLLM below 1.107. The separately installed proxy uses LiteLLM 1.109.1.

The S4 benchmark uses the checksum-verified [Synthea v4.0.0 release](https://github.com/synthetichealth/synthea/releases/tag/v4.0.0).

Upstream releases verified the same day. uv 0.13.8, pgvector 0.8.3, Valkey 9.1.3, OTel Collector 0.165.0, Gitleaks 8.30.1, Trivy 0.76.2, Semgrep 1.185.0. The HAPI FHIR Compose image uses the verified starter tag `hapiproject/hapi:v8.12.0-2`.

The last upstream MinIO Community source release is [RELEASE.2025-10-15T17-29-55Z](https://github.com/minio/minio/releases/tag/RELEASE.2025-10-15T17-29-55Z). Compose builds that source with upstream's declared Go 1.24.8 toolchain. Container tag availability and devcontainer feature digests are pending verification.

The appearance slice adds eslint-config-next 16.4.6, matching the installed framework. Its published version and ESLint/TypeScript peer ranges were verified with npm registry metadata on November 18, 2026. The installed Next.js guide confirms ESLint 10 support. The repository now applies the framework's Core Web Vitals/React rules to the web app and the recommended TypeScript rules to source files; generated declarations and build outputs are excluded.

The Phase 1 CKS reference client reuses the previously verified pins: httpx 0.28.1,
Pydantic 2.14.3, OpenTelemetry API 1.45.2, structlog 26.1.0, and pytest 9.2.0.
No additional package version was introduced for this slice.

CKS caching pins valkey (valkey-py) 6.2.0, verified as the stable PyPI release on
November 19, 2026, with Python >=3.11 support. The installed client source was checked
for async APIs and TLS defaults; hostname verification is explicitly enabled by our adapter.

The CKS service boundary reuses FastAPI 0.163.2, Mangum 0.22.0 and OpenTelemetry SDK 1.45.2,
already verified for the cell API. No additional version was introduced for private ingress.
