# 009 — HealthLake synthetic patient testing window

The owner authorized AWS's Synthea preload for patient-view testing.
The full Billing screenshot reports an estimated $360.58 remaining, correcting the plan-only API figure.
The owner approved a two-day HealthLake window and later recreation for recording.
Use a separate CellFhirDemo stack with FHIR R4, customer-managed KMS encryption and NLP disabled.
Provision the built-in SYNTHEA preload through CloudFormation.
Use Cognito and Verified Permissions to protect the API's ListPatients action.
The API signs HealthLake searches with its workload IAM identity and exposes only tokenized patient demographics.
Validate pagination URLs against this cell's Patient endpoint before signing a request.
EventBridge Scheduler deletes only CellFhirDemo at the approved expiry.
The API returns a closed-window response after expiry.
This preload supports patient UI tests. Simulator encounters still use the production ingestion pipeline.
The HAPI PostgreSQL comparison remains an open Phase 0 acceptance item.
