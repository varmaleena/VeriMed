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

The us-east-1 ElastiCache engine catalog was queried on November 19, 2026 and returned
Valkey 7.2, 8.0, 8.1, 8.2, 9.0 and 9.1. CKS_CACHE_MAJOR_VERSION is explicit deployment
configuration; catalog listing does not prove serverless-cache creation in a new hub account.
The CKS bridge reuses the previously verified boto3 1.44.5 pin.

Phase 1 schema tooling pins SQLAlchemy 2.1.9 (asyncio extra), asyncpg 0.32.0 and Alembic 1.20.1.
These stable release versions and Python requirements were verified through PyPI on November 19, 2026.
The asyncio extra locks greenlet 3.5.6 transitively. Alembic path_separator=os handles Windows workspace
paths containing spaces.

Synthea v4.0.0 release metadata was rechecked on November 20, 2026. The local JAR exactly matched
the upstream SHA-256 digest ed43c20ad40ba5c3bc724503a5af032715fe3c491620b766148e7c2361e6ecc1.
The runner's actual CLI/exporter options were checked against its shipped help and properties.
The simulator/loader reuses boto3 1.44.5, Pydantic 2.14.3, httpx 0.28.1, OTel SDK 1.45.2 and structlog 26.1.0.

API manual error reporting pins sentry-sdk 2.75.0, verified through PyPI on November 20, 2026.
The installed 2.x SDK options were checked directly; newer documentation-only 3.x options are not used.

Synthea container base digests were verified against Docker Hub on November 20, 2026.
The initial Debian-based candidate was rejected after its ECR scan; the current runtime uses:

- python:3.12-alpine @ sha256:c5ba3deef00c7758561a0f03c26f44f10589263d40e732b8748e0d1f38f6dd89
- eclipse-temurin:21-jre-alpine @ sha256:ac05c3c42b7c2f1a52c9bd52f01041fa1958231b15ebeae7420429cbc5baf474

AWS list-curated-environment-images confirmed aws/codebuild/amazonlinux-aarch64-standard:4.0.
The build host receives AWS security patches; the application image is deployed by immutable digest.
GitHub's current runner reference confirms ubuntu-24.04-arm supports native ARM image validation.
The replacement ARM image generated a real patient and completed ECR basic scanning with zero findings.
That OS scan does not substitute for the broader Trivy/Java/Python dependency checks in CI.

Tracing pins opentelemetry-exporter-otlp-proto-http 1.45.2 and requests 2.34.2, matching
the registry-verified SDK line. Development typing uses types-requests 2.33.0.20261030.
The live SRP probe uses development-only pycognito 2024.5.1; its registry metadata and
client-secret/SRP implementation were checked on November 22. It is excluded from API bundles.
The pinned pnpm 12.21.0 bootstrap metadata was restored in the lockfile; frozen installation passed.
