# Phase 0 blockers

- **AWS identity.** The only configured profile is `default`. STS resolves it to a principal named `clinical-trials-rag-dev`. Confirm the profile and intended VeriMed hub, cell, and management account IDs or configure a dedicated VeriMed dev profile. Provide the budget alert recipient and GitHub repository/environment identifiers for OIDC trust. Do not share access keys.
- **AWS execution.** AgentCore/Cognito deployment, Bedrock inference and Guardrails, HealthScribe/Polly, HealthLake, and organization setup need an authorized VeriMed account. No resources were created. Service enablement, permissions, and quota checks remain pending.
- **Hosted CI.** Both the spec source and writable workspace started without Git metadata. Local Git is initialized. Hosted checks require the VeriMed GitHub remote.
- **Local end-to-end validation.** GNU Make and a running Docker Engine with Compose v2 are required for clean-clone bootstrap and service health checks.
