# 004 — FHIR backend

Decision: no-go on selecting HealthLake as the measured default until both 50-patient imports are timed.
Fallback and provisional local default: HAPI FHIR with PostgreSQL.
Measure store readiness and import completion separately and report successful patient counts and cost.
Evidence: no benchmark. See BLOCKERS.md.
