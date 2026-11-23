# ADR 025: Managed HTTPS for the dev web application

Date: 2026-11-22
Status: Accepted for synthetic-data dev; deployment verification pending.

The owner selected an AWS-managed hostname rather than supplying a domain.
Use CloudFront's HTTPS hostname, WAF, and a native Lambda Web Function origin.
Current AWS documentation supports Next.js standalone directly on Node.js 24.
Use IamAuth and CloudFront OAC scoped to this distribution; deny direct anonymous origin access.
Disable clinical-page caching and sampled WAF requests; never log cookies, paths or bodies.
Load Auth.js material using the execution role and Secrets Manager/Cognito, never bundle it.
Bound endpoint environments, concurrency and request rate; scale to zero without an ALB floor.
This changes the dev ECS web compute choice, not tenancy, human authorization or data storage.
The regional managed runtime reaches AWS HTTPS endpoints without a customer NAT gateway.
It does not implement the specification's private-only cell egress; that remains a production gate.
Keep the existing API authorization and fail-closed FHIR-expiry behavior.
Use staged IaC updates to register the generated hostname as a Cognito callback.
Go only after real login, CSRF, origin-denial, HTTPS and distributed-trace checks pass.
Fallback: specified private ECS hosting with a tenant-owned certificate/domain and explicit OAuth egress.
Source: https://docs.aws.amazon.com/lambda/latest/dg/web-functions-runtimes.html
Source: https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-restricting-access-to-lambda-web.html
