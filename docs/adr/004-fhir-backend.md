# 004 — FHIR backend

Decision: retain HAPI as the provisional default until its timing is measured. HealthLake passed the live AWS import.
Fallback and provisional local default: HAPI FHIR with PostgreSQL.
Prepare both inputs from the same checksum-verified Synthea v4.0.0 run with `spikes/s4_prepare_synthea.py`.
Start a fresh HAPI service from Compose and use `spikes/s4_hapi_import.py` to load the prepared transaction bundles.
For the AWS leg, deploy `FhirSpike` with `-c fhirSpike=true`, pass its outputs to `spikes/s4_healthlake_import.py`, then empty the dedicated S3 bucket and destroy the stack.
Measure store readiness and import completion separately and report successful patient counts and cost.
The HealthLake job completed in 3,831 seconds for the 50-patient cohort. It imported 76,809 FHIR resources and rejected zero. The sandbox deployment took 208 seconds. The benchmark had a $1 cost estimate.
Evidence: [live HealthLake metrics](../spikes/s4-healthlake.json). Docker and the local HAPI endpoint are unavailable on the test host.

The interrupted HAPI H2 database was recovered on November 18 and contained 23 patients. Its completion time remains unmeasured. This is partial import evidence and does not satisfy the PostgreSQL benchmark. [Recovery counts](../spikes/s4-hapi-recovery.json)

AWS HealthLake's optional Synthea preload can support smoke tests of live FHIR queries in a separate synthetic-only AWS datastore created through CDK. Use our generated cohort for the HAPI comparison and the live simulator for the hackathon demo so encounter audio, notes, and audit evidence share the same source. [AWS HealthLake Synthea preload](https://docs.aws.amazon.com/healthlake/latest/devguide/reference-healthlake-preloaded-data-types.html)
