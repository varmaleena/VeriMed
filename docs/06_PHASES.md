# 06 — Phased Build Plan

Today: Mon Nov 16, 2026. Hard deadline: **Fri Dec 11, 12:00 pm PT (≈ 1:30 AM IST Dec 12)**. Internal submit target: **Thu Dec 10**. Credits expire Dec 31 and are only $200 per partner account — see cost envelope in `01`.

**Rule:** finish a phase's acceptance tests before starting the next *on the same track*. Tracks run in parallel.

## Tracks (suggested split for 3 engineers; adapt)
- **T1 Platform/Infra:** P0, P1 (infra), P5, P6 (ops)
- **T2 Data & Agents:** P2, P3, P4 (backend), P6 (eval)
- **T3 Frontend:** P1 (shell), P3/P4 (workspace), P5 (MSP console), P7 (video polish)

## Timeline
| Phase | Dates | Output |
|---|---|---|
| P0 Foundations & spikes | Nov 16–19 | Accounts, CI/CD, repo, spikes decided |
| P1 Cell platform core | Nov 19–24 | Auth, tenancy, DB, API/UI shell, FHIR store, CKS v0 |
| P2 Ingestion & live simulator | Nov 22–28 | Real audio→scribe→draft pipeline with labeled errors |
| P3 Audit engine v1 | Nov 27–Dec 3 | AgentCore swarm, grounding + numeric audio checks, streaming UI |
| P4 Safety, governance, sign-off | Dec 1–6 | Chart/drug/omission checks, adjudication, ledger, queues |
| P5 MSP control plane | Nov 24–Dec 7 (parallel) | Provision 2 cells from console, metering, fleet, Quick |
| P6 Evaluation & hardening | Dec 5–9 | Eval report with real numbers, load/chaos, security scans |
| P7 Submission | Dec 8–10 | HLD, diagram, video, repo shared, dry run, submit |

## Cut line (if time runs short, cut in this order)
1. AgentCore Memory personalization · 2. SMART-on-FHIR · 3. JIT break-glass · 4. Dual-ASR consensus (keep word-confidence/alternatives) · 5. Challenger A2A agent (keep adjudicator) · 6. Docling/Textract (keep SPL + plain-text KB) · 7. Cell B live (keep cell B provisioned in a recorded run). **Never cut:** fail-closed behavior, ledger, eval numbers, two-account video footage, HLD.

---

## Phase 0 — Foundations & spikes (Nov 16–19)
**Goal:** a deployable skeleton and every risky unknown resolved.
**Tasks**
1. AWS Organizations: `mgmt`, `hub`, `cell-a` (cell-b later); budgets/alarms; org CloudTrail; GitHub OIDC roles per account; request promo credits; confirm APN eligibility of all members.
2. Monorepo scaffold per `02` layout, Makefile, pre-commit (ruff, mypy, eslint, prettier, gitleaks), docker-compose (Postgres+pgvector, Valkey, HAPI, MinIO, OTel), devcontainer, `docs/VERSIONS.md`.
3. CI skeleton (lint/type/unit/security scans/cdk synth) and image build to ECR.
4. CDK: `HubFoundation`, `CellFoundation` (VPC, endpoints, KMS, logging) — deploy to dev.
5. **Spikes (time-boxed, write ADRs):**
   - S1 AgentCore Runtime: deploy a Strands "hello" agent (container or code deploy) with Gateway MCP tool + Cognito JWT; capture exact IaC approach.
   - S2 LiteLLM↔Strands via Bedrock with structured output + Guardrails; **go/no-go** (fallback: `BedrockModel` + inference profiles).
   - S3 HealthScribe: run one job on a Polly-generated clip; inspect output JSON (word timestamps, confidence/alternatives presence, evidence links). Decide whether Transcribe dual-ASR is needed for alternatives.
   - S4 FHIR backend: HealthLake vs HAPI — cost/time to load 50 Synthea patients; pick default.
   - S5 Resolve real Bedrock model IDs for the aliases; record regional availability.
**Acceptance:** `make bootstrap && make test` green on a clean clone; CI green; dev cell foundation deployed; ADRs 001–005 committed; spike demos recorded in `docs/spikes/`.
**Codex prompt:**
> Read AGENTS.md and docs/01–06. Execute Phase 0. Scaffold the monorepo exactly per docs/02 §2, create Makefile targets listed in AGENTS.md, docker-compose, pre-commit, GitHub Actions (lint, type, unit, trivy/gitleaks/semgrep, cdk synth), and CDK stacks HubFoundation and CellFoundation. Then implement spikes S1–S5 as minimal scripts under `spikes/`, running them against my AWS dev profile, and write one ADR per spike with a go/no-go decision. Do not build product features yet. Stop and list any blockers in docs/BLOCKERS.md.

## Phase 1 — Cell platform core (Nov 19–24)
**Goal:** a secure, tenant-isolated, observable cell with working UI shell and real data plumbing.
**Tasks**
- `CellData` (Aurora Serverless v2 + pgvector, Valkey, S3 buckets incl. Object Lock, FHIR store per ADR-004), `CellApp` (ECS services web/api, ALB, CloudFront+WAF, Cognito pool + MFA, AVP policy store).
- `services/api`: FastAPI skeleton, auth middleware (JWT → tenant/user/role), RLS (`SET app.tenant_id` per request), Alembic migrations for all tables in `03 §2`, Cedar policies (roles), health endpoints, OTel + structlog + Sentry, problem+json errors, idempotency middleware.
- `apps/web`: Auth.js Cognito login + TOTP, app shell, role-gated nav, theme/density tokens, generated API client, Worklist page reading real (empty) data.
- `services/cks` v0 in hub: RxNorm normalize + RxClass classes + openFDA label fetch with Valkey cache; PrivateLink to cell; tools `cks.normalize_drug`, `cks.drug_classes`.
- Ledger primitives (hash chain, KMS signing) with unit tests.
- Synthea runner task + FHIR loader (50 patients) via real import path.
**Acceptance:** login with MFA works on deployed dev cell; RLS test proves tenant A cannot read tenant B; ledger chain verify test passes; `cks.normalize_drug("metformin 500 mg tablet")` returns RxCUI via PrivateLink from the cell; Worklist renders; CloudWatch shows a distributed trace from web→api→DB; Sentry receives a scrubbed test error.
**Demo:** log in, see FHIR patients from the live store through `/patients`.
**Codex prompt:**
> Execute Phase 1 per docs/06. Implement CellData and CellApp CDK stacks, the FastAPI service with RLS + Cedar authz + OTel, Alembic schema from docs/03 §2, the Next.js shell with Auth.js (Cognito, TOTP), the CKS service in the hub with PrivateLink to cells, the hash-chained ledger with KMS signing, and the Synthea→FHIR loader. Write integration tests including negative tenant-isolation and authz tests. No mock data: patients must come from Synthea through the real loader.

## Phase 2 — Ingestion & live simulator (Nov 22–28)
**Goal:** real encounters flow audio → scribe → transcript → draft note, with ground-truth labels.
**Tasks**
- Scribe adapter interface + `healthscribe` and `transcribe_llm` adapters; Step Functions `ingest_encounter` with EventBridge task-token callbacks; S3 presigned upload; `POST /encounters/import`.
- Normalizers → `transcript_turns/words` (speaker roles, timestamps, confidence/alternatives), `note_versions` v1 (`ai_draft`), preserved scribe evidence links.
- Transcribe enrichment job with drug custom vocabulary (from CKS) to obtain alternatives/confidence where HealthScribe lacks them.
- Simulator: planner, dialogue generator, Polly rendering + noise, mutator operators with `ground_truth_errors`, labeler for organic mode; `POST /simulator/encounters`; Admin "Simulator" page with live progress.
- Workspace (read-only for now): note viewer, transcript panel synced to waveform (wavesurfer), audio dock, patient banner with FHIR allergies.
**Acceptance:** generating 10 encounters via UI yields 10 `READY_FOR_AUDIT` encounters through real HealthScribe/Transcribe; each injected error has a ground-truth row whose span exists in the note text; transcript click-to-seek works; Step Functions failure path retries then marks `FAILED` with reason; cost per encounter recorded.
**Demo:** click "Generate live encounter," watch pipeline stages, open the workspace, play the 500 mg clip.
**Codex prompt:**
> Execute Phase 2. Build the scribe adapter interface and both adapters, the Step Functions ingestion pipeline, normalizers, and the full simulator (Synthea patient → planner → dialogue → Polly audio → real scribe → mutator with ground-truth labels). Expose it through the API and Admin UI. Verify with real AWS services; record per-encounter cost. No pre-baked transcripts or notes anywhere.

## Phase 3 — Audit engine v1 on AgentCore (Nov 27–Dec 3)
**Goal:** end-to-end audit with streaming UI catching dose flips, hallucinations, and negation errors with cited audio evidence.
**Tasks**
- `CellAI` stack: AgentCore Runtime (audit-orchestrator), Gateway (MCP targets + Cognito JWT authorizer), Identity, Observability; tool Lambdas: `kb.search_transcript`, `asr.get_slice`, `policy.get`, `ledger.append`; Model Gateway (LiteLLM) with per-tenant budget and Guardrails.
- `agents`: A0 Prep (tokenizer), A1 ClaimExtractor (span-exact validation), A2 GroundingVerifier (bidirectional NLI with escalation), A3 NumericAudioVerifier (deterministic spoken-number parser + ASR confidence/alternatives; dual-ASR if enabled), A7 Adjudicator (policy v1), persistence + SSE via Valkey streams + SQS worker.
- Workspace: flag rail, note decorations (TipTap), flag cards, evidence panel (transcript/sources/log), audit progress, keyboard shortcuts, clip playback.
- Fail-closed paths (timeouts → `CHECK_FAILED`).
**Acceptance:** on 20 injected encounters, audit completes with flags streamed; ≥ 1 RED `DOSE_MISMATCH_AUDIO` for each `dose_flip` case (report actual recall, don't assert 100 %); span exactness 100 % (invalid spans rejected); forced Bedrock failure yields `CHECK_FAILED` and sign-off remains gated; end-to-end trace visible in AgentCore Observability and CloudWatch; first-flag latency recorded.
**Demo:** run audit live, watch flags stream in, click the RED dose flag, hear the clip.
**Codex prompt:**
> Execute Phase 3. Implement the CellAI stack (AgentCore Runtime, Gateway, Identity, Observability, LiteLLM gateway, Guardrails), the Strands Graph with agents A0, A1, A2, A3, A7 per docs/03 §5, MCP tool Lambdas, SQS→worker→Runtime streaming with Valkey streams, SSE endpoint, and the Workspace UI per docs/04 §4. Write the spoken-number parser with hypothesis property tests. Add fail-closed tests that inject tool timeouts and model errors. Report measured recall/latency in docs/eval-notes.md.

## Phase 4 — Safety, governance, sign-off, queues (Dec 1–6)
**Goal:** the full safety story: allergy conflicts, reconciliation, omissions, adjudication, ledger-backed sign-off.
**Tasks**
- A4 ChartReconciler, A5 DrugSafety (RxNorm/RxClass allergy-class logic, label dose ranges via CKS, contraindications, duplicates), A6 OmissionAuditor (reverse NLI, red-flag symptom list), A8 Challenger (A2A, separate Runtime; stretch), A9 Router; FHIR tool Lambdas; CKS label ingest (DailyMed subset) + dose-range extraction job with source spans; KB (RAG) service for tenant docs (Docling + pgvector hybrid + rerank).
- Flag resolution API + UI (accept/edit/dismiss/route), step-up TOTP, note versioning + diff, sign-off modal, FHIR `DocumentReference` + `Provenance`, ledger receipts, Ledger Explorer with verify, Pharmacy/Coding queues, policy pack admin (+ "simulate on dataset").
- Guardrails contextual-grounding on explanations.
**Acceptance:** a note prescribing an allergen-class drug yields a deterministic RED with FHIR + RxClass evidence; a dropped chest-pain statement yields OMISSION flag; sign-off blocked until RED resolved, succeeds after, produces receipt that `GET /ledger/verify` validates; tampering a ledger row in a test DB is detected; role queues receive routed tasks; RED dismissal requires step-up.
**Demo:** the "Triple Catch": 500-vs-50 mg audio, penicillin allergy block, silent chest-pain omission → resolve → sign → verify ledger.
**Codex prompt:**
> Execute Phase 4. Implement agents A4–A6, A8 (A2A challenger), A9, the FHIR and CKS tool Lambdas, DailyMed ingestion and RAG per docs/03 §7, the resolution/sign-off/ledger/FHIR-provenance flows, queues, policy admin, and the corresponding UI per docs/04. Add negative tests (unauthorized dismiss, sign with open RED, tampered ledger). Keep every check deterministic-first and fail-closed.

## Phase 5 — MSP control plane & multi-cell (Nov 24–Dec 7, parallel track T1/T3)
**Goal:** prove the MSP business model: one-click, repeatable tenant cells and fleet operations.
**Tasks**
- `HubControl` stack, control-api, MSP Console (fleet, onboarding wizard, tenant detail, usage, policy-pack library, model budgets).
- Provisioning pipeline: wizard → run → assume-role → deploy cell stacks → seed Cognito + admin → register tools → golden audit → `ACTIVE`; teardown path.
- Cell→hub EventBridge metering (de-identified), hub rollups, Quick dashboards (fleet + tenant), billing preview.
- Provision **cell-b** end-to-end from the console during development and again for the video.
**Acceptance:** a new tenant cell is provisioned from the wizard with no manual steps in < 45 min (record actual time); fleet shows both cells with live metrics; hub contains no PHI (test scans hub DB schema + sampled data); `make destroy CELL=b` cleans up; model budget change takes effect via gateway.
**Codex prompt:**
> Execute Phase 5. Build HubControl, the control API, MSP Console, and the provisioning pipeline (GitHub OIDC→assume-role→CDK deploy of cell stacks with progress events). Implement de-identified metering from cells to the hub via EventBridge and Quick dashboards. Add a test that proves no PHI-class fields exist in hub storage. Provisioning must be idempotent and resumable.

## Phase 6 — Evaluation, hardening, observability (Dec 5–9)
**Goal:** honest numbers and production-grade operations.
**Tasks:** build `core-injected`, `organic`, `adversarial` datasets via simulator; Eval harness + Eval Lab UI + promptfoo suites; CI gates; tune thresholds in policy pack; k6 load (50 concurrent audits); chaos scripts; canary; alarms; runbooks; security scan fixes; a11y pass; cost report; prompt-injection test pass; update HLD numbers from real runs.
**Acceptance:** eval report (markdown + dashboard) with per-class P/R/F1 and CIs, FP/note, latency, cost/audit; chaos scenarios degrade to AMBER/blocked, never silent pass; no high/critical findings in scans; Playwright E2E green on deployed `demo`; axe clean on core screens.
**Codex prompt:**
> Execute Phase 6. Generate the three eval datasets via the simulator, implement the eval harness, Eval Lab, promptfoo suites, CI gates, k6 load tests, chaos scripts, canary, alarms and runbooks per docs/05. Produce docs/EVAL_REPORT.md with real measured metrics (confidence intervals, failures included). Fix any scan or a11y findings.

## Phase 7 — Submission package (Dec 8–10)
**Deliverables checklist (map to judging criteria)**
- [ ] Public working URL (+ test credentials in the Devpost testing instructions) — **Design / Tech**
- [ ] Private GitHub repo shared with the two judging emails shown on the rules page; README with setup; code visibly **calling AWS AI services at runtime** (Bedrock, AgentCore, Strands, HealthScribe/Transcribe, Quick) — **Tech**
- [ ] Architecture diagram (hub + 2 cells, data flows, trust boundaries) and **HLD doc** (components, NFRs, security, cost model, scaling path, "Path to production" incl. BAA/pen-test/HIPAA-eligibility confirmation) — **Design**
- [ ] ~3-minute YouTube video, public: hook (500 mg audio catch) → Triple Catch → sign-off + ledger verify → **show hub console and both cell accounts (upstream/downstream)** → provisioning a cell → eval numbers → pricing/MSP model. No third-party trademarks/music — **Impact / Innovation**
- [ ] Devpost text: problem, solution, MSP business case (seat/encounter pricing, margin estimate from measured cost/audit), measured results, what's novel (independent multi-modal verification firewall; fail-closed; ledger; cell-based MSP delivery), limitations (synthetic data, advisory dose ranges)
- [ ] Track 2 selected; AWS AI services identified; APN-registered team confirmed; submission dry-run on **Dec 9**; submit **Dec 10**; freeze `main`.
- [ ] Post-submission: keep the public URL up and free of restrictions until the judging period ends (Jan 22, 2027); set budget alarms so it survives credit expiry (Dec 31) — fund it or note the plan.
**Codex prompt:**
> Execute Phase 7. Generate the architecture diagram (Mermaid + exported SVG), draft docs/HLD.md from the implemented system and real eval numbers, write the README quick-start and judge testing instructions (accounts, URLs, scripted demo flow), and produce a demo script with timestamps matching the checklist in docs/06. Do not invent metrics; pull them from docs/EVAL_REPORT.md.

---

## Daily operating rhythm
- 15-min standup: yesterday / today / blockers (write blockers to `docs/BLOCKERS.md`).
- End of each day: deploy `main` to `dev`; run `make eval-smoke`; post a 60-second screen recording of the current flow in the team channel (this becomes raw video footage).
- Every Friday-equivalent checkpoint (Nov 20, Nov 27, Dec 4): cost report vs. credits; decide on cuts per the cut line.
