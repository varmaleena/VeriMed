# ADR 016 — Private IAM CKS service boundary

- Date: 2026-11-19. Status: accepted for the Phase 1 service-boundary slice.
- Keep CKS in the separate PHI-free hub; no public browser or patient-data interface is introduced.
- Implement POST normalize/classes/labels with strict drug-only request and typed response schemas.
- Use AWS_IAM on a private REST API, accessed through explicitly allowed cell interface endpoints.
- Trust identity only from the Lambda proxy event injected by Mangum after gateway authentication.
- Bind each configured IAM role to one tenant, approved endpoints, and permitted operations.
- Reject unsigned/unknown callers, wrong account/stage/API, caller-selected tenant fields, and forbidden operations.
- Never infer identity from HTTP headers, request bodies, or browser access tokens.
- Provide a reusable CDK ingress construct for an existing Lambda-compatible runtime.
- This dev adapter differs from the planned ECS CKS hosting; full runtime/network/cache integration is not deployed.
- Direct Lambda invocation must be restricted to the gateway; broad invocation grants would break the trust boundary.
- Resource policies deny unknown roles/endpoints; methods require SigV4; cell identity policies must also grant invocation.
- Bound bodies and deadlines; redact errors and validation details; record payload-free spans, logs, and metrics.
- CDK uses explicit acknowledgements for backend validation, private-API WAF hardening, and gateway log delivery.
- Separate hub credentials, Linux packaging, private cache connectivity and no-NAT reference egress remain deployment gates.
- Sources: [private APIs](https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-private-apis.html), [IAM access](https://docs.aws.amazon.com/apigateway/latest/developerguide/api-gateway-control-access-using-iam-policies-to-invoke-api.html).
- Sources: [proxy identity](https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-lambda-proxy-integrations.html), [context variables](https://docs.aws.amazon.com/apigateway/latest/developerguide/api-gateway-mapping-template-reference.html).
