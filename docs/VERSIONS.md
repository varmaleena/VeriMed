# Phase 0 versions

npm stable release metadata verified on November 16, 2026. pnpm 12.21.0, AWS CDK library 2.277.0, CDK CLI 2.1148.1, cdk-nag 3.0.2, constructs 10.8.1, TypeScript 7.0.2, Node types 26.6.6, ESLint 10.15.0, Prettier 3.10.1.

PyPI release metadata verified the same day. Ruff 0.17.5, mypy 2.4.1, pre-commit 4.7.0. Python stays on the specified 3.12 line.

S2 uses Strands 1.65.0, Pydantic 2.14.3, and LiteLLM 1.106.10 in the client environment. Strands requires LiteLLM below 1.107. The separately installed proxy uses LiteLLM 1.109.1.

The S4 benchmark uses the checksum-verified [Synthea v4.0.0 release](https://github.com/synthetichealth/synthea/releases/tag/v4.0.0).

Upstream releases verified the same day. uv 0.13.8, pgvector 0.8.3, Valkey 9.1.3, HAPI FHIR 8.10.3, OTel Collector 0.165.0, Gitleaks 8.30.1, Trivy 0.76.2, Semgrep 1.185.0.

The last upstream MinIO Community source release is [RELEASE.2025-10-15T17-29-55Z](https://github.com/minio/minio/releases/tag/RELEASE.2025-10-15T17-29-55Z). Compose builds that source with upstream's declared Go 1.24.8 toolchain. Container tag availability and devcontainer feature digests are pending verification.
