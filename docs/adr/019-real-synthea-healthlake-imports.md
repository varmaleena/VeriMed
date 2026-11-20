# ADR 019 — Real Synthea imports in the approved HealthLake dev window

- Date: 2026-11-20. Status: accepted and verified for the synthetic dev cell.
- Use the existing scheduled HealthLake datastore; do not create another hourly datastore.
- Keep the HAPI benchmark/default-production decision open as recorded in ADR 004.
- Generate synthetic cohorts with the checksum-verified Synthea v4.0.0 JAR.
- Capture generator seeds/reference date privately; suppress name-bearing generator console output.
- Normalize actual FHIR references and publish NDJSON atomically, never fabricated clinical records.
- Inspect input size, resource identities, duplicate identities, patient count and SHA-256 before submission.
- Upload once with checksum verification, KMS encryption and a pinned S3 object version.
- Bind HealthLake role trust to the exact datastore and scope data permissions to transfer prefixes.
- Check the caller account, tagged dev tenant, endpoint identity and approved expiry before writes.
- Repeated submissions use an input/config-derived idempotency token and strict provider validation.
- Mark import acceptance only after provider completion, zero rejected resources and patient read-back.
- The real 50-patient cohort imported 77,470 resources, rejected zero, and all 50 patients were read back.
- This is additional runtime-generated Synthea data, distinct from AWS's built-in Synthea preload.
- The approved datastore teardown remains 2026-11-20 13:04:54 UTC; no extension was made.
- Local generation and managed import ran; a hosted Synthea container task remains packaging/deployment work.
- Sources: [import API](https://docs.aws.amazon.com/healthlake/latest/APIReference/API_StartFHIRImportJob.html), [role trust](https://docs.aws.amazon.com/healthlake/latest/devguide/getting-started-setting-up.html), [Synthea release](https://github.com/synthetichealth/synthea/releases/tag/v4.0.0).
