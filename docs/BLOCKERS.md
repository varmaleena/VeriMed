# Phase 0 blockers

- **AWS accounts and notifications.** The owner authorized `default` for the dev cell. CDK bootstrap and `CellFoundation` are deployed in `us-east-1`. The separate hub and management accounts, budget alert recipient, and GitHub repository/environment identifiers for OIDC trust remain unspecified. The default CDK bootstrap uses the AWS managed AdministratorAccess execution policy.
- **Remaining spike checks.** AgentCore and HealthLake passed their live AWS runs. HAPI started from the verified WAR on Windows, but the corrected import could not run because the JVM exhausted native memory. Run the prepared 50-patient cohort with its practitioner and hospital bundles on a Docker Compose host with sufficient memory and a fresh PostgreSQL database. Four of the six selected Bedrock aliases reported unavailable agreements despite regional availability and entitlement. Runtime invocation checks remain pending for those four.
- **Hosted CI.** Both the spec source and writable workspace started without Git metadata. Local Git is initialized. Hosted checks require the VeriMed GitHub remote.
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
