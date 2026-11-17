# Phase 0 blockers

- **AWS accounts and notifications.** The owner authorized `default` for the dev cell. CDK bootstrap and `CellFoundation` are deployed in `us-east-1`. The separate hub and management accounts, budget alert recipient, and GitHub repository/environment identifiers for OIDC trust remain unspecified. The default CDK bootstrap uses the AWS managed AdministratorAccess execution policy.
- **Remaining spike checks.** AgentCore and HealthLake passed their live AWS runs. HAPI started from the verified WAR on Windows, but the corrected import could not run because the JVM exhausted native memory. Run the prepared 50-patient cohort with its practitioner and hospital bundles on a Docker Compose host with sufficient memory and a fresh PostgreSQL database. Four of the six selected Bedrock aliases reported unavailable agreements despite regional availability and entitlement. Runtime invocation checks remain pending for those four.
- **Hosted CI.** Both the spec source and writable workspace started without Git metadata. Local Git is initialized. Hosted checks require the VeriMed GitHub remote.
- **Local end-to-end validation.** GNU Make and a running Docker Engine with Compose v2 are required for clean-clone bootstrap and service health checks.

The latest native HAPI retry reached transaction processing with the corrected cohort. The process stopped before writing the final patient-count and timing report. Run the benchmark on a separate host with Docker Compose and a fresh database to obtain a complete result.
