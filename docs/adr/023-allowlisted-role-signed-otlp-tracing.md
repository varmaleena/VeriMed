# ADR 023: Allowlisted, role-signed OTLP tracing

Date: 2026-11-20
Status: Accepted; deployed evidence is recorded separately.

The current API runs on Lambda and has no ADOT collector sidecar.
Use the supported CloudWatch OTLP HTTP endpoint with SigV4 and refreshed IAM credentials.
Enable Transaction Search through CloudFormation, with one-percent indexing.
X-Ray creates its reserved aws/spans group using our CMK; IaC sets thirty-day retention.
Sample five percent of roots and preserve valid W3C parent sampling decisions.
Use manual spans; do not automatically instrument HTTP bodies, SQL or model calls.
Reconstruct all exported spans from fixed names and operational numeric attributes.
Drop events, links, status descriptions, untrusted resource attributes and vendor trace state.
Never forward baggage. Export failures emit fixed logs/metrics and cannot replace API responses.
Disable redirects and environment proxies; require TLS and the exact regional AWS destination.
Flush with a bounded wait before Lambda freezes; record delivery evidence independently.
This is a collector-less deviation for the existing Lambda API; ECS collector work remains separate.
Source: https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-OTLPEndpoint.html
Source: https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Transaction-Search-Cloudformation.html
