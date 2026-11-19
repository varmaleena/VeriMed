# ADR 017 — No-NAT private CKS with IAM reference worker

- Date: 2026-11-19. Status: accepted for the dev HubCKS deployment design.
- Keep tenant cells and the CKS API/cache in isolated subnets with no internet gateway or NAT.
- A separate non-VPC Lambda fetches only fixed-host public NLM/FDA references.
- The API invokes it synchronously through a scoped Lambda interface endpoint and IAM role.
- This replaces a public-subnet Fargate shortcut and completes the dev adapter introduced in ADR 016.
- The worker has no Function URL, inbound API, cache credentials, or clinical-record access.
- Requests validate drug-only fields twice; worker failures and malformed replies remain UNVERIFIED.
- Enforce resolved-response evidence invariants and preserve review/partial-result states.
- Propagate W3C trace context; export payload-free spans and outcome metrics, never request bodies.
- Private Valkey uses a KMS CMK, explicit ACL user, TLS hostname verification and generated credentials.
- Fetch credentials through Secrets Manager at runtime; never place passwords in Lambda environment values.
- Scope runtime egress to cache and AWS endpoint security groups; endpoint policies permit only required calls.
- Build Python 3.12 Linux x86_64 wheels from the hashed uv lockfile and include a module-hash manifest.
- Pin the configured engine major after regional catalog verification; serverless deployment availability remains untested.
- Dev AWS endpoints use one AZ for cost; endpoint redundancy and credential rotation remain production gates.
- Hub credentials, cross-account endpoint/identity policies, reference mirroring, distributed quotas and live acceptance remain pending.
- Sources: [Lambda networking](https://docs.aws.amazon.com/lambda/latest/dg/configuration-vpc-internet.html), [private invocation](https://docs.aws.amazon.com/lambda/latest/dg/configuration-vpc-endpoints.html), [Invoke semantics](https://docs.aws.amazon.com/lambda/latest/api/API_Invoke.html).
- Sources: [cache authentication](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/Clusters.RBAC.html), [Secrets Manager](https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html).
