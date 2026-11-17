# Phase 0 blockers

- **AWS accounts and notifications.** The owner authorized `default` for the dev cell. CDK bootstrap and `CellFoundation` are deployed in `us-east-1`. The separate hub and management accounts, budget alert recipient, and GitHub repository/environment identifiers for OIDC trust remain unspecified. The default CDK bootstrap uses the AWS managed AdministratorAccess execution policy.
- **Remaining spike checks.** AgentCore and HealthLake passed their live AWS runs. The HAPI leg needs a running Docker Engine with Compose v2 and a fresh database. Four of the six selected Bedrock aliases reported unavailable agreements despite regional availability and entitlement. Runtime invocation checks remain pending for those four.
- **Hosted CI.** Both the spec source and writable workspace started without Git metadata. Local Git is initialized. Hosted checks require the VeriMed GitHub remote.
- **Local end-to-end validation.** GNU Make and a running Docker Engine with Compose v2 are required for clean-clone bootstrap and service health checks.
