# 02 — Tech Stack (authoritative)

Pin exact versions in Phase 0 by checking current stable releases; record them in `docs/VERSIONS.md`. Never hardcode Bedrock model IDs.

## 1. Stack by layer

### Frontend
| Concern | Choice | Notes |
|---|---|---|
| Framework | **Next.js (current stable, App Router) + React + TypeScript (strict)** | Standalone output, containerized on ECS Fargate behind CloudFront |
| Styling / components | **Tailwind CSS + shadcn/ui (Radix)** in `packages/ui` | Design tokens in `04_UI_SPEC.md` |
| Server state | **TanStack Query** | SSE-driven cache updates for audits |
| Client state | **Zustand** (UI-only: selected flag, panel tabs, playhead) | |
| Forms/validation | **react-hook-form + zod** | zod schemas generated from OpenAPI where possible |
| Tables | **TanStack Table** | worklist, queues, ledger |
| Note editor | **TipTap (ProseMirror)** with custom decorations/marks for claim spans | Claim spans addressed by `char_start/char_end` into canonical note text |
| Audio | **wavesurfer.js** (Regions + Timeline plugins) + Web Audio | Flag regions on waveform; click-to-play clip; playback speed 0.75–1.5× |
| Charts | **visx or Recharts** for in-app; **Amazon Quick embedded dashboards** (`amazon-quicksight-embedding-sdk`) for tenant/fleet analytics | |
| Auth client | **Auth.js (NextAuth v5) OIDC with Cognito**, Authorization Code + PKCE, httpOnly encrypted session cookie (BFF) | Browser never sees access tokens |
| API client | **OpenAPI → TypeScript client** generated into `packages/api-client` (`openapi-typescript` + `openapi-fetch`) | CI fails on drift |
| Realtime | **SSE** via same-origin streaming route handler | Resumable with `Last-Event-ID` |
| Frontend errors/RUM | **Sentry browser SDK** (PHI-scrubbed) + CloudWatch RUM (optional) | |

### Backend (cell API, control API, CKS, workers)
| Concern | Choice |
|---|---|
| Language | **Python 3.12**, `uv` for deps/venv |
| Framework | **FastAPI** + Uvicorn (ASGI), Pydantic v2, `pydantic-settings` |
| API style | REST (OpenAPI 3.1) + SSE; FHIR R4 resources at import/export boundaries (`fhir.resources`) |
| ORM / migrations | **SQLAlchemy 2 (async) + asyncpg + Alembic** |
| HTTP/retries | `httpx` (async) + `tenacity` |
| AWS SDK | `boto3` / `aioboto3`; `aws-lambda-powertools` in Lambdas |
| Logging | `structlog` JSON with trace/span ids; PHI redaction processor |
| Linting/typing | `ruff`, `mypy --strict` (or pyright strict) |
| Background work | SQS consumers on ECS Fargate (workers) + Lambda for small tools; Step Functions for durable pipelines |

### Agents
| Concern | Choice |
|---|---|
| Agent framework | **Strands Agents SDK (Python)** — Graph pattern for the audit swarm; agents-as-tools for sub-reasoners; structured output via Pydantic models |
| Hosting | **Amazon Bedrock AgentCore Runtime** (ARM64 container or direct code deploy, per current docs) |
| Tool protocol | **MCP** through **AgentCore Gateway** (Lambda targets + OpenAPI targets), JWT inbound auth from the cell's Cognito pool |
| Agent-to-agent | **A2A** (challenger agent as a separate Runtime) |
| Identity | **AgentCore Identity** (workload identity, OAuth/OIDC brokering) |
| Memory | **AgentCore Memory** — session memory for audit runs; long-term memory for reviewer-feedback calibration (stretch; may never suppress RED) |
| Tool policy | **AgentCore Policy** (if available in region) to constrain tool calls; otherwise enforce in tool Lambdas |
| Observability | **AgentCore Observability** + OpenTelemetry (ADOT) → CloudWatch/X-Ray |
| Agent evaluation | AgentCore Evaluations if available, plus the custom Eval Lab (see `05`) |

### Models, gateway, guardrails
| Alias (env var) | Role | Selection rule |
|---|---|---|
| `MODEL_REASONING_ID` | adjudication, NLI on hard cases, explanations | newest **Sonnet-class Claude** available in region |
| `MODEL_FAST_ID` | claim extraction, simple NLI, omission candidates | **Haiku-class Claude** or **Amazon Nova 2 Lite** |
| `MODEL_CHALLENGER_ID` | independent RED re-verification | different family than reasoning model (e.g., Nova 2/Opus-class/other on Bedrock) |
| `MODEL_JUDGE_ID` | LLM-as-judge in evals | different family than the system under test |
| `MODEL_EMBED_ID` | embeddings | Amazon Titan Text Embeddings V2 (1024-d) or Nova multimodal embeddings; keep dimension in config |
| `MODEL_RERANK_ID` | reranking | Bedrock rerank model (Amazon/Cohere) if available |

- **Provider:** Amazon Bedrock only in production cells (data stays in AWS). Provider abstraction preserved for tests/eval.
- **Model gateway:** **LiteLLM proxy** (ECS Fargate, 1 task) with virtual key per tenant, budgets, RPM/TPM limits, fallbacks (reasoning → alternate model), request/usage logging to Postgres + OTel. Strands uses it via its LiteLLM model provider. *Phase-0 spike decides go/no-go; fallback = Strands `BedrockModel` + Bedrock application inference profiles tagged per tenant.*
- **Guardrails:** Amazon Bedrock Guardrails on all model calls: prompt-attack filter, denied topics (no diagnosis/treatment advice), contextual-grounding check on explanations, output PII check. Direct identifiers are tokenized upstream (see `05`).
- **Prompt caching** on static system prompts; **prompts are files** in `agents/shared/prompts/*.md`, hashed and recorded in the ledger.

### Speech, scribe, TTS
| Need | Service |
|---|---|
| Ambient scribe adapter #1 | **AWS HealthScribe** (batch job from S3) |
| Scribe adapter #2 | **Transcribe (diarization) + Bedrock LLM scribe** (own prompt) — proves vendor neutrality |
| Dual-ASR consensus | **Amazon Transcribe** batch/slice with **custom vocabulary** (RxNorm drug names) and word alternatives |
| Synthetic encounter audio | **Amazon Polly (neural)** two+ voices, ffmpeg mixing/noise |

### RAG, parsing, knowledge
| Concern | Choice |
|---|---|
| Vector DB | **Aurora PostgreSQL + pgvector (HNSW)** — in cell (tenant docs) and in hub CKS schema (public drug labels) |
| Retrieval | Hybrid: pgvector cosine + Postgres full-text (`tsvector`), **Reciprocal Rank Fusion**, rerank top-k (Bedrock rerank) |
| Embeddings | `MODEL_EMBED_ID` through the gateway; batch via workers |
| Chunking | Section-aware (SPL section codes / headings), 300–600 tokens, overlap 10–15%, metadata: `set_id`, `version`, `section_code`, `rxcuis[]`, `tenant_id` |
| Document parsing | **Docling** (PDF/DOCX/HTML → structured markdown) in workers; **Amazon Textract** fallback for scanned PDFs; **lxml** SPL XML parser for DailyMed |
| Corpora | DailyMed SPL labels (subset: top ~300 outpatient drugs, configurable) + tenant-uploaded policy/formulary docs |

### Data stores, cache, queues, workflow
| Concern | Choice |
|---|---|
| Relational | **Aurora PostgreSQL Serverless v2** (cell and hub), Row-Level Security |
| FHIR store | **AWS HealthLake** or **HAPI FHIR (ECS + Postgres)** behind `FHIR_BACKEND` |
| Cache / pub-sub / streams | **ElastiCache Serverless for Valkey**: API response cache (CKS lookups), idempotency keys, rate limits, audit event streams, locks |
| Object storage | **S3** (SSE-KMS per-tenant CMK, versioning, lifecycle, presigned URLs); separate **S3 Object Lock (compliance mode)** bucket for ledger anchors (7-year retention) |
| Queues/events | **SQS** (+DLQs), **EventBridge** (cross-account bus to hub), **Step Functions Standard** |
| Secrets/config | Secrets Manager, SSM Parameter Store, AppConfig (feature flags/policy packs) |

### Identity & authorization
| Concern | Choice |
|---|---|
| Users | **Amazon Cognito** user pool per cell (+ per hub for MSP staff); TOTP MFA required; optional SAML/OIDC federation; hosted UI via Auth.js |
| Service auth | IAM roles (ECS task roles), AgentCore Identity for agent→tool, Cognito M2M client credentials for jobs |
| Fine-grained authz | **Amazon Verified Permissions (Cedar)** policy store per cell — RBAC+ABAC (role, department, encounter assignment) |
| Cross-account | `sts:AssumeRole` with ExternalId from hub; permission boundaries; SCPs |
| Step-up | Cognito re-auth/TOTP challenge before dismissing RED flags and signing |

### Evaluation, monitoring, errors
| Concern | Choice |
|---|---|
| Offline evals | Custom harness (`eval/harness`, pytest-driven) over simulator-labeled datasets + **promptfoo** for prompt-level regression in CI |
| Online quality | Reviewer feedback (accept/dismiss/false-positive) logged → Analytics; drift alarms |
| LLM-as-judge | `MODEL_JUDGE_ID` (cross-family) with rubric files in `eval/rubrics` |
| Tracing/metrics/logs | **OpenTelemetry** (ADOT collector sidecar) → **CloudWatch + X-Ray**; CloudWatch EMF custom metrics; AgentCore Observability |
| Error tracking | **Sentry** (frontend + backend) with `send_default_pii=False`, PHI scrubbing hooks, no request bodies |
| Synthetic monitoring | CloudWatch Synthetics canary running a golden audit hourly |
| Alerting | CloudWatch Alarms → SNS → Slack/PagerDuty |
| BI | **Amazon Quick** dashboards (tenant analytics, fleet/FinOps) |

### Testing
`pytest` + `pytest-asyncio` + `hypothesis` (number/unit parsers) · `testcontainers` (Postgres+pgvector, Valkey) · `vitest` + React Testing Library · **Playwright** (E2E incl. audio playback & keyboard flows) · `schemathesis` (API fuzz from OpenAPI) · `k6` (load) · CDK assertions + `cdk-nag` · `axe-core` (a11y) · eval gates in CI. No mocks of VeriMed's own services in integration tests.

### Containerization, CI/CD, IaC, infra
| Concern | Choice |
|---|---|
| Containers | Multi-stage Dockerfiles, **ARM64 (Graviton)**, non-root, distroless/slim; **ECR** with scan-on-push, immutable tags (git SHA) |
| Local dev | `docker compose`: Postgres+pgvector, Valkey, HAPI FHIR, MinIO, LiteLLM, OTel collector; real AWS (dev account) for Bedrock/HealthScribe/Polly; devcontainer provided |
| Runtime | **ECS Fargate** (web, api, workers, gateway, hapi), **Lambda** (tools), **AgentCore Runtime** (agents), CloudFront + WAF + ALB |
| IaC | **AWS CDK v2 (TypeScript)**, `cdk-nag`; stacks: `HubFoundation`, `HubControl`, `HubCKS`, `CellFoundation`, `CellData`, `CellAI`, `CellApp`, `CellObservability`; AgentCore resources via L2 construct / CloudFormation / CLI step isolated in `CellAI` |
| CI/CD | **GitHub Actions** with OIDC → AWS (no long-lived keys); PR: lint/type/unit/integration/security scans/eval-smoke; main: build+scan+push, deploy dev cell, run E2E; manual promote to `demo` |
| Security scans | `gitleaks`, `semgrep`, `trivy` (images+IaC), `pip-audit`, `npm audit`, SBOM (`syft`), `cdk-nag` |
| Region | `us-east-1` primary |

## 2. Repo layout (monorepo: `pnpm` workspaces + `uv` workspace)
```
verimed/
  AGENTS.md  Makefile  docker-compose.yml  .github/workflows/
  docs/                      # the six spec files + adr/ + BLOCKERS.md + VERSIONS.md
  apps/web/                  # clinician workspace + tenant admin (cell)
  apps/msp-console/          # MSP console (hub)
  packages/ui/  packages/api-client/  packages/config/
  services/api/              # cell API (FastAPI)
  services/control-api/      # hub API
  services/workers/          # ingestion, kb-ingest, ledger-anchor, metering
  services/cks/              # Clinical Knowledge Service (hub)
  services/tools/            # AgentCore Gateway tool Lambdas (fhir, kb, queue, ledger, asr_slice)
  services/simulator/        # Synthea runner, planner, dialogue gen, TTS, mutator, labeler
  agents/audit_orchestrator/ agents/challenger/ agents/shared/{schemas,prompts,model_client}
  eval/{datasets,harness,rubrics}/
  infra/cdk/  infra/docker/
  scripts/
```

## 3. Local dev contract
`make bootstrap` installs toolchains, pre-commit hooks, and starts compose. `make dev` runs web+api+workers with hot reload against compose services and a real AWS dev profile for AI services. A seeded **dev tenant** is created by running the real simulator (never fixtures).
