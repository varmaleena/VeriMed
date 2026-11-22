# Phase 0 blockers

- **Synthea Java dependency security gate (November 22).** The first hosted ARM image build and real generation smoke test succeeded, but Trivy reported 87 HIGH/CRITICAL findings in the upstream v4.0.0 fat JAR. Its Alpine OS and Python packages had zero findings in that run. The gate remains enforced. The upstream master build still declares old FHIR dependencies, so replacing the release with an unpinned master artifact is not a fix. A maintained source build with compatible upgraded dependencies, a zero-HIGH/CRITICAL scan, and real FHIR generation/import regression checks is required before this image can pass acceptance. The earlier ECR scan covered OS packages only and did not establish Java safety.

- **AWS accounts and notifications.** The owner authorized `default` for the dev cell. CDK bootstrap and `CellFoundation` are deployed in `us-east-1`. The separate hub and management accounts, budget alert recipient, and GitHub repository/environment identifiers for OIDC trust remain unspecified. The default CDK bootstrap uses the AWS managed AdministratorAccess execution policy.
- **Remaining spike checks.** AgentCore and HealthLake passed their live AWS runs. HAPI started from the verified WAR on Windows, but the corrected import could not run because the JVM exhausted native memory. Run the prepared 50-patient cohort with its practitioner and hospital bundles on a Docker Compose host with sufficient memory and a fresh PostgreSQL database. Four of the six selected Bedrock aliases reported unavailable agreements despite regional availability and entitlement. Runtime invocation checks remain pending for those four.
- **Hosted CI.** The owner supplied https://github.com/varmaleena/VeriMed on November 22. The repository is reachable and initially had no branches. First push and hosted checks are being established; green CI is not yet claimed.
- **Local end-to-end validation.** GNU Make and a running Docker Engine with Compose v2 are required for clean-clone bootstrap and service health checks.

On November 18, the interrupted native HAPI database was reopened and queried successfully. It contained 23 of the required 50 patients. The server was stopped after the count query. The partial run has no valid completion time. Evidence is saved in docs/spikes/s4-hapi-recovery.json. Run the complete benchmark on a host with Docker Compose, sufficient memory, and a fresh PostgreSQL database.

## Phase 1 operations follow-up

- **Reserved Lambda concurrency.** On November 18, `get-account-settings` in the authorized dev account reported total and unreserved concurrency of 10 in us-east-1. AWS requires 100 executions to remain unreserved when allocating a function reservation. The ledger worker uses the explicit dev-only `ledgerUseUnreserved=true` CDK context. To reserve its intended single execution, obtain a regional quota with at least 101 total executions and enough remaining unreserved capacity; then redeploy without that context. No quota increase was requested automatically.
- **Alarm notifications.** The ledger worker has CloudWatch alarms for execution errors, queued failures and a missing 36-hour heartbeat. Connecting paging/email requires the owner's notification destination and corresponding IaC subscription; alarm state alone is not a paging integration.

## CKS hub account — 2026-11-19

The configured default profile is account 160885292760 (dev cell), and no other profile is recorded.
Organizations describe-organization returned AWSOrganizationsNotInUseException.
Enterprise target: separate management, hub, and tenant-cell accounts, with no PHI in hub storage.
Needed before deployment: an owner-provisioned hub account/profile and CDK deployment role/bootstrap,
or management-account credentials plus a unique owner-supplied hub account contact for authorized account provisioning.
The existing Cognito invitation address is not authorization to use that address as an AWS account contact.
No organization/account/billing changes were made. Hub PrivateLink, authenticated service hosting,
Valkey cache, reference mirror, and deployed cross-account acceptance remain unfinished.
A registered openFDA API key stored in Secrets Manager and a shared quota limiter are needed for sustained service use;
the bounded public-reference smoke probe used the documented no-key allowance.

## CKS cache integration — 2026-11-19

Valkey cache implementation and unit tests are present. Real-server integration cannot run locally:
Docker is unavailable and wsl --list --quiet reports WSL is not installed. Needed: a local Valkey
server (Compose/WSL) or an isolated authorized TLS development cache endpoint reachable by this host.
The GitHub workflow includes a real Valkey service integration check, but no remote/hosted run is configured.
Do not treat cache integration, hub caching deployment, or Phase 1 PrivateLink acceptance as passed.

## CKS private service deployment — 2026-11-19

The private API boundary, authorization tests, OpenAPI and CDK ingress construct are implemented locally.
Deployment still requires the separate hub account/profile, Linux runtime bundle, cell interface-endpoint IDs
and IAM role bindings, and restricted gateway-only Lambda invocation.
The final hub runtime must reach private Valkey/reference storage and public providers without NAT gateways;
that integrated egress/cache topology has not been built or validated. The reusable ingress construct is not
a deployed HubCKS stack. Cross-account SigV4/PrivateLink tests and hosted CI remain unverified.

## CKS runtime update — 2026-11-19

The no-NAT topology and Linux packaging are now implemented and synthesis-tested in HubCKS.
The previous runtime/network design blocker is resolved in code, not verified by deployment.
A hub profile/account and real cell role/endpoint bindings are still required; none were inferred from
the owner's architectural preference. No account/organization was created. Serverless engine-major support
must be confirmed during actual deployment. PrivateLink calls, real Valkey access, reference mirroring,
shared rate limiting, credential rotation and configured alert delivery remain acceptance gates.

## Phase 1 FHIR runner packaging — 2026-11-20

Real local Synthea generation and the 50-patient HealthLake import/read-back passed.
The original Docker/WSL packaging blocker is resolved using the IaC-managed ARM CodeBuild project.
The private hosted task now passes real 1- and 50-patient runs; hosted GitHub CI remains unavailable.
The datastore was deleted at the end of its 2026-11-20T13:04:54Z window and was not recreated.
The deployed transfer stack is independent and retains its KMS key/buckets; input/output lifecycle is seven days.

## Sentry delivery (2026-11-20)

API categorical reporting and an actual SDK-envelope privacy test are implemented. No Sentry project/DSN is configured. Provide the project DSN through deployment configuration and verify a scrubbed remote smoke event. Browser reporting and web-to-API tracing remain unverified. API-to-database tracing passed on November 22. No Sentry remote-delivery claim is made.

## Synthea task progress and FHIR expiry — 2026-11-20

CellSynthea is deployed with an on-demand ARM builder and private Fargate workflow. The first Debian
image had 15 HIGH ECR findings; it was not activated as a task and was deleted. The replacement Alpine
image passed real generation and ECR basic OS scanning with zero findings. Actual 1- and 50-patient
Fargate executions succeeded, including KMS/version/checksum/cohort-count verification. The 50-patient
run produced 65,666 resources in 105.22 seconds. Evidence: docs/synthea-task-verification.json.
The new cohort has not been imported into a new HealthLake datastore; the previous 50-patient import
remains separately verified. HealthLake reported DELETED after the approved test-window teardown.
The approved plan remains to recreate it for recording; recording timing has not been supplied.
Hosted CI, broader Trivy dependency scanning, hub account access and deployed web observability
remain acceptance gates; a successful task does not complete Phase 1.
