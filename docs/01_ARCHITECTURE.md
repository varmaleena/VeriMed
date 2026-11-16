# 01 — Product & Architecture

## 1. Product definition
**VeriMed** is a vendor-neutral verification layer that sits between any ambient AI scribe and the EHR sign-off button. It decomposes an AI-drafted clinical note into atomic, typed claims and verifies each against three independent evidence sources:

| Evidence source | What it catches |
|---|---|
| **Audio/ASR** (diarized transcript, word timestamps, confidence, alternatives, optional dual-ASR consensus on the clip) | dose/number flips (50 vs 500 mg), negation errors, speaker mis-attribution, hallucinated findings, silent omissions |
| **FHIR chart** (AllergyIntolerance, MedicationStatement/Request, Condition, Observation) | allergy contradictions, med-reconciliation gaps, contradicted history |
| **Deterministic drug knowledge** (RxNorm normalization, RxClass classes, DailyMed/openFDA label sections) | allergen-class prescribing, dose outside labeled range, label contraindications, duplicate therapy |

Output: severity-ranked flags (RED / AMBER / INFO) with one-click audio playback and cited evidence; a hard **sign-off block** on unresolved RED; non-clinical gaps routed to Pharmacist/Coder queues; a hash-chained, KMS-signed audit ledger and FHIR `Provenance` for every sign-off.

**Positioning vs. scribes.** AWS HealthScribe (and other scribes) provide evidence links from note sentences to transcript lines — that is the scribe attesting to itself. VeriMed is the **independent second opinion**: different models, deterministic rules, FHIR + label grounding, and a governance ledger. VeriMed ingests notes from any scribe via adapters (HealthScribe adapter and a Bedrock-LLM scribe adapter ship in v1 to prove vendor neutrality).

**Business model (MSP).** An AWS MSP operates VeriMed as a managed service for hospital tenants: per-clinician seat or per-audited-encounter pricing, with tenant onboarding automated by IaC and fleet operations in an MSP Console. Track 2 fit: *Launch New Managed AI Offerings (Recurring Revenue)*.

## 2. Personas
| Persona | Needs | Primary screens |
|---|---|---|
| Attending physician | Review 2–3 high-risk flags, not 600 words; sign safely | Worklist, Workspace |
| Clinical pharmacist | Medication/allergy/dose issues routed to them | Pharmacy Queue |
| Medical coder | Documentation gaps affecting claims | Coding Queue |
| Compliance auditor / CMIO | Prove oversight; see override rates; verify ledger | Analytics, Ledger |
| Tenant admin | Users, policy thresholds, knowledge docs | Admin |
| MSP SRE / FinOps / Admin | Provision tenants, fleet health, spend, model budgets | MSP Console (hub) |

## 3. Scope
**In v1:** note audit (text+audio+FHIR), flag review/resolve, sign-off with ledger, two role queues, tenant policy packs, analytics, eval lab, MSP console with automated tenant provisioning and metering, two scribe adapters, simulator-driven live data.
**Out of v1:** diagnosis or treatment recommendations, direct EHR write beyond FHIR `DocumentReference`/`Provenance`, real PHI, billing integrations, mobile apps. Stretch: SMART-on-FHIR launch, JIT break-glass access, AgentCore Memory personalization.

## 4. Principles
1. LLMs propose, rules verify, humans decide.
2. Evidence-first: no flag without a pointer (audio span, FHIR resource, label section, or rule id).
3. Fail closed → AMBER "manual verification required".
4. Independence: verifier models differ from the scribe; Red flags can be cross-checked by a challenger on a different model family.
5. Structural tenant isolation (account-per-tenant cells).
6. Everything reproducible: prompts, model IDs, policy versions, and data hashes are recorded per audit.
7. Operability first-class: traces, metrics, evals, runbooks ship with features.

## 5. Topology
**Accounts (AWS Organizations; minimum viable set marked ★):**

| Account | Purpose |
|---|---|
| ★ `verimed-mgmt` | Organizations, SCPs, billing, Identity Center |
| ★ `verimed-hub` | MSP Control Plane: MSP Console, control API, tenant registry, provisioning pipelines, metering store, Quick fleet dashboards, Clinical Knowledge Service (CKS), ECR, CDK assets |
| ★ `verimed-cell-a`, ★ `verimed-cell-b` | Tenant Cells (two hospitals) — the full runtime and all PHI-class data |
| `verimed-logarchive`, `verimed-security` | Org CloudTrail, Config, GuardDuty/Security Hub aggregation (stretch; at minimum enable org CloudTrail) |

```
                 MSP operators ──► MSP Console (Next.js) ─► control-api (FastAPI)
                                                                │
 ┌──────────────── HUB ACCOUNT ─────────────────────────────────┼─────────────────────┐
 │ Aurora PG (control schema: tenants, cells, metering, plans)  │                     │
 │ CKS (Clinical Knowledge Service: RxNorm/RxClass/openFDA/DailyMed index, PHI-free)  │
 │ Provisioning (GitHub OIDC → sts:AssumeRole → cdk deploy cell stacks)               │
 │ EventBridge bus ◄── de-identified usage/quality events from cells ─► S3/Athena ─► Quick
 └───────────────▲───────────────────────────────────────────────┬────────────────────┘
        PrivateLink (drug names/codes only)                      │ sts:AssumeRole (ExternalId)
 ┌──────────────┴──────────── CELL ACCOUNT (one per hospital) ───▼───────────────────┐
 │ CloudFront+WAF ► Next.js web (ECS) ► api (FastAPI, ECS) ─► Aurora PG+pgvector (RLS) │
 │                                   │            │ └─► Valkey (cache, SSE streams)    │
 │                                   │            └─► SQS ► workers (ECS) / Step Functions│
 │   S3 (audio, notes, artifacts; KMS CMK)   S3 Object Lock bucket (audit ledger)      │
 │   FHIR store (HealthLake | HAPI)   Cognito pool (tenant users)   AVP policy store  │
 │   Model Gateway (LiteLLM) ► Bedrock (+Guardrails)   HealthScribe/Transcribe/Polly  │
 │   AgentCore: Runtime(audit-orchestrator, challenger[A2A]) · Gateway(MCP tools) ·   │
 │              Identity · Memory · Observability                                      │
 └──────────────────────────────────────────────────────────────────────────────────────┘
```
Network: private subnets, VPC endpoints (S3, Bedrock runtime, ECR, Logs, STS, Secrets Manager, SQS, KMS, Step Functions) to avoid NAT cost; cells have **no general internet egress** — external drug-knowledge access is centralized in the hub's CKS. Region: `us-east-1` (HealthScribe availability; confirm at build time).

**Hub vs. cell data rule:** the hub never stores PHI. Cells emit only de-identified metering/quality events (counts, severities, latencies, costs, tenant id). MSP staff have no standing access to cell PHI.

## 6. Component catalog
| Component | Where | Responsibility |
|---|---|---|
| `apps/web` | cell | Clinician workspace, queues, analytics, ledger explorer, tenant admin, eval lab (BFF pattern) |
| `apps/msp-console` | hub | Fleet, onboarding wizard, usage/cost, policy packs, model budgets |
| `services/api` | cell | REST + SSE; authz via Verified Permissions; owns DB; starts ingestion/audit jobs; signs ledger entries |
| `services/workers` | cell | SQS consumers: scribe ingestion, ASR post-processing, KB ingest (parse/chunk/embed), ledger anchoring, metering emit |
| Step Functions `ingest_encounter` | cell | Durable audio→HealthScribe/Transcribe→normalize→draft pipeline with EventBridge task-token callbacks |
| `agents/audit_orchestrator` | cell (AgentCore Runtime) | Strands Graph running the verification swarm |
| `agents/challenger` | cell (AgentCore Runtime, **A2A**) | Independent re-verification of RED flags on a different model family |
| Tool Lambdas (`services/tools`) | cell | MCP tools behind AgentCore Gateway: FHIR, KB search, queue, ledger, ASR-slice |
| Model Gateway | cell | LiteLLM proxy: routing, per-tenant budgets/rate limits, fallbacks, usage logging |
| `services/cks` | hub | PHI-free Clinical Knowledge Service: drug normalization, classes, label sections, dose ranges, cross-reactivity |
| `services/simulator` | hub-deployable job, runs into a cell | Live data generator + labeled eval-set builder |
| `services/control-api` | hub | Tenant lifecycle, provisioning orchestration, metering ingest |

## 7. Key flows
**F1 Tenant provisioning.** MSP admin completes wizard → control-api creates tenant record → triggers pipeline: create/assume cell account role → deploy `CellFoundation`, `CellData`, `CellAI`, `CellApp` stacks → seed Cognito pool + first admin → register Gateway tools → run smoke audit (simulator-generated encounter) → mark tenant `ACTIVE` → fleet dashboard shows green. Target: one command / one wizard, repeatable.

**F2 Encounter ingestion.** Source = (a) simulator-generated audio, (b) uploaded audio+note, or (c) `POST /v1/encounters/import` (FHIR `DocumentReference` + `Binary` audio from any scribe). Step Functions: store audio (S3) → run scribe adapter (HealthScribe job *or* Transcribe + LLM scribe) → normalize into `transcript_words`, `transcript_turns`, `draft_note` (v1) with the scribe's own evidence links kept as metadata → run dual-ASR enrichment (Transcribe with drug custom vocabulary → word alternatives/confidence) → index → status `READY_FOR_AUDIT`.

**F3 Audit.** UI "Run VeriMed Audit" → `POST /v1/audits` → SQS → worker invokes `audit-orchestrator` (streaming) → events pushed to Valkey stream `audit:{id}` → UI consumes SSE (resumable via `Last-Event-ID`) → flags persisted as they are produced → ledger events appended → audit `COMPLETE`.
Pipeline stages: (1) de-identify + segment note → (2) claim extraction (typed, span-anchored) → (3) in parallel: grounding/NLI verification, numeric audio verification, FHIR reconciliation, drug-safety rules, omission audit → (4) adjudication (dedupe, severity per policy pack, abstain→AMBER) → (5) challenger cross-check on RED (A2A) → (6) routing to queues → (7) persist + ledger.

**F4 Review & sign-off.** Clinician navigates flags (keyboard-first), plays audio evidence, accepts suggested correction / edits note / dismisses with reason (dismissing RED requires reason + step-up MFA) → note vN+1 stored → **Approve & Sign** enabled only when no unresolved RED → API writes FHIR `DocumentReference` (+ `Provenance` linking AI draft → human edits → audit) → ledger entry with receipt (SHA-256 chain hash, KMS signature, model/prompt/policy versions) → receipt shown to user.

**F5 Queues.** INFO/AMBER pharmacy and documentation items create `review_tasks` for roles; assignment, SLA timers, resolution notes, all ledgered.

**F6 Metering & fleet.** Cells emit de-identified events to the hub bus: `audit.completed`, `flag.raised/resolved`, `signoff.completed`, `llm.usage`, `asr.minutes`. Hub aggregates for billing preview, SLO tracking, and Quick dashboards.

## 8. Architecture Decision Records (summary)
| # | Decision | Rationale | Rejected alternative |
|---|---|---|---|
| A1 | Account-per-tenant **cells** + pooled hub | Strongest PHI isolation story; reproducible via IaC (judging "Design") | Pooled multi-tenant DB only |
| A2 | Strands Graph on **AgentCore Runtime** | Required AWS AI service depth; session isolation; native observability | Self-hosted LangGraph on ECS |
| A3 | **MCP via AgentCore Gateway** for tools; **A2A** for challenger | Open protocols, JWT authz, per-tenant throttling | Bespoke REST tool-calling |
| A4 | **Deterministic-first** verification | Reliability, explainability, lower cost, safer than pure LLM | LLM-only NLI |
| A5 | **Aurora PostgreSQL + pgvector** (one store for relational + vectors) | Fewer moving parts; RLS; scale-to-zero friendly | OpenSearch Serverless (high floor cost) |
| A6 | **Step Functions** for ingestion; **SQS + Valkey streams** for interactive audits | Durable long jobs vs. resumable low-latency streaming | Step Functions for everything |
| A7 | **LiteLLM Model Gateway** in every cell | Per-tenant budgets, fallbacks, usage metering, provider abstraction | Direct Bedrock calls everywhere (fallback if spike fails, see Phase 0) |
| A8 | **FHIR store abstraction** (`HealthLake` default, `HAPI` fallback) | Controls cost/risk; same tools, same tests | Hard dependency on HealthLake |
| A9 | **CKS in hub, PHI-free** | Cells need no internet egress; shared cache/index of public drug data | Per-cell internet egress to NLM/FDA |
| A10 | Hash-chained ledger + KMS signature + S3 Object Lock anchors | Tamper evidence without deprecated QLDB | QLDB (end-of-support) |
| A11 | BFF in Next.js (OIDC code+PKCE, httpOnly session) | No tokens in browser | SPA with tokens in localStorage |

## 9. Verified platform facts (checked Nov 16, 2026) — build against these
- **RxNav Drug–Drug Interaction API was discontinued Jan 2, 2024.** RxNorm normalization and RxClass still work (free, ~20 req/s/IP). Therefore VeriMed's v1 safety checks are: allergy-class conflicts, label-derived dose ranges/contraindications, duplicate therapy, and *advisory* label-text interaction mentions (AMBER at most). Do **not** call `rxnav…/interaction`. A curated DDI dataset (e.g., ONC high-priority list) is optional/stretch; licensed DrugBank is out of scope.
- **Claude 3.7 Sonnet is legacy/EOL on Bedrock.** Use current Sonnet-class / Haiku-class / Nova 2 models available in your region via config aliases; discover IDs at deploy time. Prefer a Sonnet-class model as primary reasoner, a Haiku-class/Nova 2 Lite model for cheap extraction, and a *different family* for the challenger/judge.
- **AWS HealthScribe**: HIPAA-eligible; returns diarized turn-by-turn transcript with word-level timestamps, speaker roles, segment classification, extracted medical terms, a draft note, and note-sentence→transcript evidence links; processes audio from S3 in the same region (documented as us-east-1 — confirm); ~$0.001667/sec (~$0.10/min) in us-east-1; free tier 300 min/month for first 2 months. It does not retain audio/text.
- **AgentCore**: GA since Oct 2025; services include Runtime, Memory, Gateway, Identity, Observability, Evaluations, Policy, Browser, Code Interpreter; **MCP** supported (Gateway tool federation) and **A2A** supported in Runtime; VPC connectivity across services; Strands is a first-class framework. Verify regional availability and any HIPAA-eligibility statement before making compliance claims.
- Hackathon rules: judged on four equal criteria (Technological Implementation, Design, Potential Impact, Innovation); repo must show an AWS AI service **called at runtime**; video must show upstream/downstream accounts; HLD + architecture diagram required; each project can win only one prize and top-3 per track cannot take special prizes.

## 10. Cost envelope (credits are only $200/partner account — design for it)
- Scale-to-zero / smallest sizes everywhere: Aurora Serverless v2 (minimum capacity, auto-pause if available), ElastiCache Serverless (Valkey), Fargate tasks desired=1 only for `api` and `web`; workers scale from SQS depth to 0.
- No NAT gateways; VPC endpoints only where needed (interface endpoints cost hourly — prefer gateway endpoints and consolidate).
- Two cells only; destroy cell B outside test windows (`make destroy`).
- HealthScribe at ~$0.10/min: cap eval corpus (e.g., 120 encounters × ~3 min ≈ 360 min) and reuse cached transcripts; use free-tier minutes first.
- AWS Budgets alarms at 50/80/100% per account; tag every resource `Project=verimed`, `Tenant`, `Env`; daily cost report to Slack/email.
- LLM cost: Haiku-class/Nova 2 Lite for extraction; Sonnet-class only for adjudication/explanation; prompt caching on static system prompts; per-audit cost recorded and shown in Analytics.
- Hard rule: HealthLake/HAPI choice is decided in Phase 1 by measured cost; keep `FHIR_BACKEND` switchable.

## 11. Top risks
| Risk | Mitigation |
|---|---|
| Credits exhausted | Cost envelope above; budgets; teardown scripts |
| AgentCore IaC/API immaturity | Thin deployment wrapper (`agentcore` CLI/CFN custom resource) isolated in one stack; spike in Phase 0 |
| LiteLLM↔Strands friction | Phase-0 spike with fallback to Strands `BedrockModel` + application inference profiles |
| Audit latency too high for UX | Stream first deterministic flags < ~6s; full audit target p95 < 30s; progressive UI |
| False positives erode trust | Eval Lab, abstain→AMBER policy, challenger on RED, per-class thresholds in policy packs |
| Synthetic voices ≠ real audio | Optional public corpora (PriMock57, ACI-BENCH — verify licenses) alongside Polly-rendered encounters; disclose limits honestly |
| Scope blow-up | Cut line in `06_PHASES.md` |
