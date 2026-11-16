# 003 — HealthScribe transcript evidence

Decision: go for HealthScribe as the scribe adapter. Use Transcribe enrichment where numeric verification needs multiple hypotheses.
The live Polly-generated clip produced 27 pronunciation items. All 27 had timestamps and confidence, zero had multiple alternatives, and the clinical document included five evidence links.
The API returned regional HTTPS S3 paths. The inspector validates the dedicated bucket and job prefix before fetching via the authenticated S3 CLI.
Fallback: mark claims unverified when either enrichment or grounding evidence is insufficient.
Evidence: [sanitized live metrics](../spikes/s3-healthscribe.json) and the [AWS output structure](https://docs.aws.amazon.com/transcribe/latest/dg/starting-health-scribe-job.html).
