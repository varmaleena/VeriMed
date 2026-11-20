# Phase 1 real FHIR import verification

HIPAA-aligned design, synthetic data only.

The reusable loader submitted 50 real Synthea-generated patients to the existing dev HealthLake store.
The managed import completed with 77,470 resources accepted, zero rejected, and all 50 patients verified
by signed FHIR reads. The actual metadata-only report is fhir-import-verification.json.
This cohort includes provider support resources, so its count differs from the earlier Phase 0 import.

CellFhirImport deployed an encrypted, versioned transfer bucket, access-log destination, retained CMK,
and a HealthLake service role bound to the exact datastore. It does not create a datastore.
Inputs/outputs expire after seven days. The existing HealthLake test-window schedule was not extended:
it ends November 20 at 18:34:54 IST (13:04:54 UTC).
The transfer key remains retained and costs about $1/month until separately retired.

The loader validates the dev account/tenant tags, fixed AWS endpoint, cohort identities and checksum,
requires versioned encrypted input, submits idempotently with strict validation, and fails closed when
provider counts or patient read-back do not match. Raw clinical content, identifiers, credentials,
and source-path-bearing generator output are not logged. OTel spans and import count metrics are emitted.
Private state/config/NDJSON files stay under ignored .phase1-fhir; do not commit them.

Generate a fresh cohort using the verified upstream JAR:

    .venv/Scripts/python.exe services/simulator/run_synthea.py --jar .phase0-synthea/synthea-with-dependencies.jar --output .phase1-fhir/new-cohort --population 50

The upstream artifact is Synthea v4.0.0, SHA-256
ed43c20ad40ba5c3bc724503a5af032715fe3c491620b766148e7c2361e6ecc1.
Use a new output directory. Generation creates real FHIR bundles, normalized NDJSON and a seed/date receipt.
A real one-patient generation was run successfully with the new runner, including seed/date options.
The Java workload is bounded to 1 GiB heap and 30 minutes; requested population is 1–50.
A failed preparation never publishes the final NDJSON path.

Submit/check with explicit deployed configuration and private state:

    .venv/Scripts/python.exe services/simulator/run_fhir_loader.py submit --profile default --source PATH_TO_NDJSON --config PATH_TO_CONFIG --state .phase1-fhir/import-state.json
    .venv/Scripts/python.exe services/simulator/run_fhir_loader.py check --profile default --state .phase1-fhir/import-state.json

The config schema is packages/api-client/fhir-import-job.schema.json. It requires actual tenant,
datastore, transfer bucket/role/key and approved expiry values. No guessed account bindings are supplied.
submit exits after starting a managed job; it does not claim completion. check returns 2 while incomplete
and 0 only after successful resource acceptance and patient read-back.
The hosted Synthea container task is not deployed; the local runner and real managed import did run.

Validation: 163 Python tests passed (13 simulator/loader tests), all 14 CDK tests passed,
Ruff/strict mypy and targeted infrastructure ESLint passed. Hosted CI is still unverified.
Test temporary files use per-run workspace scratch directories to avoid the host's Windows temp ACL issue.
Estimated incremental import/storage spend was $0.05, not an observed billing charge; the already-approved
datastore hourly window is unchanged.
