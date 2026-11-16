# AGENTS.md — VeriMed build rules (Codex: read this first, every session)

## Mission
Build **VeriMed**: a multi-tenant, MSP-operated "AI Clinical Governance Firewall" that independently audits ambient-AI-scribe clinical notes against (1) encounter audio/ASR evidence, (2) the patient's FHIR chart, and (3) deterministic drug-knowledge rules, then blocks sign-off on unresolved critical findings and records a tamper-evident audit trail.

This is an enterprise-grade SaaS, not a demo. It is built for the AWS MSP AI Hackathon (Track 2) — submission deadline **Dec 11, 2026 12:00 pm PT**; internal target **Dec 10**.

## Read order
1. `docs/01_ARCHITECTURE.md` — what and why (topology, flows, ADRs, verified platform facts)
2. `docs/02_TECH_STACK.md` — every technology choice, repo layout
3. `docs/03_DATA_AGENTS_API.md` — data strategy, schema, agents, tools, RAG, API
4. `docs/04_UI_SPEC.md` — screens, layout, interactions, design system
5. `docs/05_NFR_SECURITY_OPS_TESTING.md` — security, observability, evaluation, testing, CI/CD
6. `docs/06_PHASES.md` — the ordered build plan. **Work one phase at a time.**

## Non-negotiable rules
1. **No mock data in product code paths.** No hardcoded patients, notes, flags, scores, or API responses. All demo data is produced by the live simulator pipeline (`services/simulator`) through the same ingestion path real customers use. Test doubles are allowed only inside unit tests.
2. **Synthetic is not mock.** Synthetic patients/audio are generated at runtime by real tools (Synthea, an LLM, Amazon Polly) and processed by real services (HealthScribe/Transcribe, Bedrock, FHIR store). Never ship pre-baked result JSON.
3. **Fail closed.** If any check errors, times out, or is uncertain, the claim becomes `UNVERIFIED`/AMBER with a reason. Never silently pass a claim.
4. **LLMs propose, rules verify, humans decide.** Deterministic checks (numbers, drug classes, FHIR facts) always override LLM prose. Only a human can sign a note.
5. **Tenant isolation is structural**, not conditional: one AWS account (a "cell") per tenant, plus `tenant_id` + Postgres RLS inside the cell.
6. **No PHI in logs, traces, error trackers, or prompts beyond minimum necessary.** Direct identifiers are tokenized before any LLM call. See `docs/05`.
7. **Verify platform APIs against current AWS docs before coding.** AgentCore, HealthScribe, HealthLake, Bedrock model IDs and Guardrails APIs change. Do not code from memory. If docs and this spec disagree, follow docs and record an ADR in `docs/adr/`.
8. **Model IDs are config, never constants.** Use the aliases in `docs/02` (`MODEL_REASONING_ID`, etc.). Resolve real IDs with `aws bedrock list-foundation-models` / `list-inference-profiles` at deploy time.
9. **Everything is infrastructure-as-code** (AWS CDK, TypeScript). No console-click resources.
10. **Do not claim compliance.** Use "HIPAA-aligned design, synthetic data only" in all copy.

## Working method
- One phase at a time (`docs/06_PHASES.md`). A phase is done only when every acceptance test in it passes in CI and the phase demo script runs against a deployed dev environment.
- Small commits, conventional commit messages, PRs per task. Update docs when behavior changes.
- Record every deviation from the spec as an ADR (`docs/adr/NNN-title.md`, 10–20 lines).
- Every new endpoint/agent/tool ships with: types, tests, OTel spans, structured logs, authz check, and an OpenAPI/schema entry.
- When blocked by missing credentials, quotas, or a service not enabled, stop and write exactly what is needed in `docs/BLOCKERS.md`; continue with unblocked work.

## Definition of Done (per task)
- [ ] Type-checks (`mypy --strict` / `tsc --strict`), lint clean, formatted
- [ ] Unit + integration tests added and passing; coverage not reduced
- [ ] Authz and tenant-scoping tested (negative test included)
- [ ] OTel trace + structured log + metric emitted where applicable
- [ ] No secrets, PHI, or model IDs hardcoded
- [ ] IaC updated; `cdk-nag` clean (or suppression justified in comment)
- [ ] Docs/OpenAPI updated

## Standard commands (create in Phase 0, keep stable)
`make bootstrap` · `make dev` · `make lint` · `make test` · `make test-int` · `make eval-smoke` · `make eval-full` · `make synth` · `make deploy ENV=dev CELL=a` · `make destroy ENV=dev CELL=b`

## Core environment variables
`VERIMED_ENV` · `AWS_REGION` (default `us-east-1`) · `TENANT_SLUG` · `MODEL_REASONING_ID` · `MODEL_FAST_ID` · `MODEL_CHALLENGER_ID` · `MODEL_EMBED_ID` · `MODEL_RERANK_ID` · `MODEL_JUDGE_ID` · `MODEL_GATEWAY_URL` · `GUARDRAIL_ID` · `GUARDRAIL_VERSION` · `DATABASE_URL` (from Secrets Manager) · `VALKEY_URL` · `FHIR_BACKEND` (`healthlake`|`hapi`) · `AGENTCORE_GATEWAY_URL` · `CKS_BASE_URL` · `SENTRY_DSN` · `OTEL_EXPORTER_OTLP_ENDPOINT`
