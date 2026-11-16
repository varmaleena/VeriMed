# 04 — UI Specification

Two web apps: **Clinician Workspace** (`apps/web`, per cell) and **MSP Console** (`apps/msp-console`, hub). Desktop-first (≥1280 px), tablet read-only fallback. Look and feel: calm, dense, clinical — closer to a modern code-review tool (flags = review comments) than a marketing dashboard.

## 1. Design system (`packages/ui`)
- **Type:** Inter (UI), JetBrains Mono (doses, IDs, hashes, timestamps). Base 14 px, line-height 1.45; note body 15 px.
- **Color tokens (light / dark both required):**
  - Surfaces: `bg` #F7F8FA / #0E1116 · `panel` #FFFFFF / #151A21 · `border` #E3E6EB / #2A313B
  - Text: `fg` #111827 / #E6EAF0 · `muted` #5B6574 / #98A2B3
  - Brand: `primary` #1F5EFF (actions), `primary-fg` #FFFFFF
  - Severity (never color-only — always icon + label + pattern): **RED** #D92D20 `ShieldAlert` solid underline · **AMBER** #DC6803 `AlertTriangle` dashed underline · **INFO** #1570EF `Info` dotted underline · **VERIFIED** #067647 `CheckCircle2` no underline (subtle green gutter tick) · **UNVERIFIED** #667085 `HelpCircle` wavy gray underline
- **Radius** 8 px cards / 6 px inputs; **elevation** only for popovers/modals; **spacing** 4-pt scale; **density** toggle (comfortable/compact).
- **Motion:** ≤150 ms, none for flag state changes beyond a 1-time highlight pulse; respects `prefers-reduced-motion`.
- **Accessibility:** WCAG 2.2 AA, full keyboard operation, visible focus rings, ARIA live region announcing new flags, axe in CI, severity conveyed by text+icon.

## 2. App shell (Clinician Workspace)
Top bar (48 px): logo · tenant name · global search (patient token / encounter id) · notifications · role badge · user menu (theme, density, shortcuts, sign out).
Left nav (collapsible): **Worklist · Pharmacy Queue* · Coding Queue* · Analytics · Ledger · Admin*** (*role-gated). Routes: `/worklist`, `/encounters/[id]`, `/queues/pharmacy`, `/queues/coding`, `/analytics`, `/ledger`, `/admin/{users,policy,knowledge,integrations,eval,simulator}`, `/settings`.

## 3. Screen: Worklist (`/worklist`)
Table (TanStack): Patient token · Age/Sex · Encounter time · Scribe adapter · **Risk** (counts: 🔴 n 🟠 n) · Status chip · Assigned · Time in queue. Filters: status, risk, scribe, date; saved views ("My unsigned", "Has RED"). Row click → Workspace. Top-right: **Import encounter** (upload audio+note) and, in demo/admin mode, **Generate live encounter** (calls simulator; progress toast shows pipeline stages: planning → dialogue → audio → scribe → ready). Empty state explains both options.

## 4. Screen: Encounter Workspace (`/encounters/[id]`) — the hero screen
```
┌────────────────────────────────────────────────────────────────────────────────────────────┐
│ ◉ VeriMed · Westside Medical        ⌕ Search            🔔2    Dr. A. Rao ▾       ☾  ?   │
├────────────────────────────────────────────────────────────────────────────────────────────┤
│ PATIENT BANNER  PT-7F3A · 58 F    ⚠ ALLERGIES: Penicillin (anaphylaxis) · Sulfa (rash)      │
│ Encounter 14 Nov 10:42 · Scribe: HealthScribe · Draft v1 · Policy v3                        │
│ Audit: ████████░░ 80% · Verifying chart… (A4)        [ Run VeriMed Audit ]  [Approve & Sign]│
│                                                          (disabled: 1 unresolved RED)       │
├───────────┬──────────────────────────────────────────────┬──────────────────────────────────┤
│ FLAGS     │ NOTE  (SOAP) · v1 ▾ · [Diff vs AI draft]     │ EVIDENCE                         │
│ 🔴 1 🟠 3 │                                              │ [Transcript][Chart][Sources][Log]│
│ ───────── │ S: 58F with T2DM presents for follow-up…     │                                  │
│ 🔴 Dose   │ O: BP 128/82, HR 76. Lungs clear.            │ ▶ Doctor 00:02:14                │
│  Metformin│ A: T2DM, uncontrolled…                       │ "…increase the metformin to      │
│  50 mg ≠  │ P: Metformin ̲5̲0̲ ̲m̲g̲ ̲b̲i̲d̲ ← red underline      │   **five hundred** milligrams…" │
│  heard 500│    Start amoxicillin 500 mg ← red (allergy)  │ Confidence: "five hundred" 0.62  │
│ 🔴 Allergy│    Follow up 3 months                        │ Alt: "fifty" 0.31                │
│  Amoxicil.│ (chest pain omitted ← amber gutter marker)   │ Dual-ASR: ✗ disagree             │
│ 🟠 Omitted│                                              │ ─────────────────────────────── │
│  chest pn │                                              │ Label: Metformin §2 Dosage       │
│ 🟠 Reconc.│                                              │ typical start 500 mg BID (cite) │
│ ─────────│                                              │ Chart: AllergyIntolerance/a-91   │
│ ✓ 14 verif│                                              │ Penicillin — anaphylaxis         │
├───────────┴──────────────────────────────────────────────┴──────────────────────────────────┤
│ ▶ ◀◀ ▶▶  0.75× 1× 1.25×   ████▌▌▌██▌▌███▌██▌▌▌█▌▌▌▌██▌████   00:02:14 / 00:11:37  🔴🟠 marks │
└────────────────────────────────────────────────────────────────────────────────────────────┘
```
**Regions**
1. **Patient banner (sticky):** always-visible allergy chips (from FHIR), encounter meta, audit progress, primary actions. **Run VeriMed Audit** → progress bar + live stage chip (stage names from SSE). **Approve & Sign** disabled with tooltip "1 unresolved RED flag" until resolved.
2. **Flag rail (left, 280 px):** severity-grouped list; each card: icon+label, class title, claim excerpt, one-line evidence summary, status. Verified claims collapsed into "✓ n verified" (expandable, shows green ticks list). Sort: severity → note order. Keyboard: `J/K` next/prev, `Enter` focus in note.
3. **Note canvas (center, TipTap):** canonical note text with claim-span decorations (severity underline style per tokens), hover popover (flag title + one-line reason + Play ▶), click selects the flag. Editing allowed (creates `human_edit` versions on blur/save). Gutter markers for omissions (claims that should exist but don't) anchored to the section end. Toggle **Diff vs AI draft**. Verified claims show faint green tick in gutter only.
4. **Evidence panel (right, 360 px) tabs:** **Transcript** (diarized, Doctor/Patient colored, word-level highlight synced to playhead, flagged word ranges outlined; click word → seek) · **Chart** (FHIR summary: allergies, active meds, problems, recent vitals, each with resource id) · **Sources** (label sections/policy chunks cited, with deep link/excerpt) · **Log** (agent trace timeline: stage, duration, model, cost — transparency for compliance).
5. **Audio dock (bottom, 96 px):** wavesurfer waveform with **flag regions** (red/amber bands), speed, loop-clip toggle (auto-plays 3 s before to 3 s after the evidence span), time display. Selecting a flag auto-seeks and offers ▶ "Play evidence clip".

**Flag card (expanded)**
- Header: severity icon + class title + confidence chip (`Deterministic` badge when rule-based; `Challenger confirmed` / `Challenger disagrees` badge).
- "Note says" vs "Evidence says" two-column mini diff (e.g., `50 mg` vs `500 mg` heard) with ▶ clip.
- Explanation (≤2 sentences, cited chips linking to evidence).
- Suggested fix (if any) as a diff preview.
- Actions: **Accept fix** (`A`) · **Edit note** (`E`) · **Dismiss…** (`D`, requires reason from list + free text; RED requires step-up TOTP) · **Route to pharmacist/coder** (`R`).
- Footer: evidence ids, checker name, policy threshold used.

**Sign-off modal:** summary (counts resolved/dismissed by severity, edits made), diff stats vs AI draft, attestation checkbox ("I reviewed the flagged items and the final note"), step-up auth, **Sign**. On success: receipt card (chain hash, signature id, timestamp, model/policy versions, "Verify in ledger" link) + FHIR write status.

**Keyboard map:** `Space` play/pause · `J/K` next/prev flag · `[`/`]` seek ±3 s · `L` loop clip · `A/E/D/R` flag actions · `Ctrl+Enter` run audit · `Ctrl+Shift+S` sign (opens modal) · `?` shortcuts overlay.

**States**
- *Ingesting:* skeleton note + stepper (Audio stored → Scribe running → Transcript ready → Draft ready).
- *Auditing:* flags stream in live (rail items slide in, ARIA live announcement); partial results are usable.
- *Check failed:* amber `CHECK_FAILED` card "Verification of <check> did not complete — manual review required" with retry button; sign-off remains gated per policy.
- *Offline/SSE drop:* banner "Reconnecting…", auto-resume via `Last-Event-ID`.
- *Signed:* note read-only, green "Signed" banner with receipt; "Re-audit" disabled.

## 5. Screen: Pharmacy & Coding Queues
Kanban-style or table (toggle): Open / In review / Resolved. Row: flag class, drug/code, patient token, severity, SLA countdown, assignee. Detail drawer: same evidence panel components (reused), resolution note field, **Resolve / Return to physician**. All actions ledgered.

## 6. Screen: Analytics (`/analytics`)
Top KPIs (native components): audits run, flags per 100 notes, RED catch count, median time-to-sign, dismissal rate by class, challenger-disagreement rate, cost per audit, p95 audit latency. Below: embedded **Amazon Quick** dashboards (department/clinician breakdown, trend lines, flag-class heatmap). Filters: date range, department, scribe adapter. Export CSV.

## 7. Screen: Ledger Explorer (`/ledger`)
Chronological table of ledger events with seq, type, actor, hash (mono, truncated, copy), signature status. **Verify chain** button (calls `/ledger/verify`) → animated pass/fail with first-broken-seq pointer. Encounter filter; "Download receipt (JSON)". Anchor status per day (Object Lock until date).

## 8. Screen: Admin
- **Users & roles:** invite, role assignment, MFA status.
- **Policy pack:** YAML editor with schema validation and **live diff vs. active version**; "Simulate on dataset" runs the eval smoke set against the draft policy and shows precision/recall delta before activation.
- **Knowledge base:** upload PDFs/DOCX → ingest progress → chunk preview → search tester (shows hybrid retrieval scores).
- **Integrations:** scribe adapters (HealthScribe, LLM scribe), FHIR backend status, import endpoint credentials.
- **Eval Lab:** datasets list (injected/organic), run eval, results table per flag class (precision, recall, F1, FP/note), confusion highlights, regressions vs previous run, per-case drill-down to the exact audio clip and flags.
- **Simulator:** generate N encounters with sliders for error rate and error classes; shows live pipeline progress.

## 9. MSP Console (`apps/msp-console`)
- **Fleet (`/fleet`):** tenant cards/table with cell status (Provisioning/Active/Degraded), version, region, last golden-audit result, SLO burn, 24 h audits, RED catches, spend (MTD). Map-free; status heatmap.
- **Onboarding wizard (`/tenants/new`):** 1) tenant details, 2) plan & seats, 3) policy pack choice, 4) model budget, 5) review → **Provision**. Live provisioning timeline (stack by stack, with logs), final smoke-audit result, admin invite link. One run = one new cell.
- **Tenant detail:** health, versions, usage, incidents, policy pack, budget, "Run golden audit", "Roll back release".
- **Usage & billing preview:** per-tenant seats/encounters, LLM cost, ASR minutes, margin estimate; Quick embed.
- **Policy pack library & Model budgets:** versioned packs, diff, rollout; per-tenant LLM budgets and fallbacks from the model gateway.
- **MSP has no PHI views** — only de-identified aggregates; no encounter pages exist in this app.

## 10. Frontend architecture rules
- BFF: all API calls go through Next.js route handlers/server actions that attach the access token from the session; SSE proxied as a streaming response.
- TanStack Query keys per resource; SSE events patch cache (`flag.raised` → insert; `flag.updated` → patch).
- Components are presentational in `packages/ui`; feature code in `apps/*/features/*`.
- Zod-validated forms; optimistic updates only for flag status changes with rollback on failure.
- Error boundaries per panel; failure of Evidence panel must not block note review.
- i18n-ready strings (English only in v1). Copy tone: precise, calm, no hype; never imply diagnosis.
- Storybook (or Ladle) for `packages/ui`; Playwright visual snapshots for the Workspace in light/dark.

## 11. Microcopy examples
- Run button: "Run VeriMed Audit" · busy: "Auditing… 3 of 6 checks complete"
- Gated sign: "Resolve 1 critical flag to sign"
- Fail-closed: "We couldn’t verify this against the audio. Please listen before signing."
- Dismiss RED dialog title: "Dismiss critical flag?" body: "This is recorded in the audit ledger with your reason."
- Footer disclaimer (Workspace): "VeriMed supports clinical documentation review. It does not provide diagnosis or treatment advice. Synthetic data only."
