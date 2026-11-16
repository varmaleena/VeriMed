# Spike evidence

Store sanitized measurements here. Exclude access tokens, generated clinical content, and account identifiers.

| Spike | Evidence and status                                                                                                                                                                                      |
| ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| S1    | [ADR 001](../adr/001-agentcore-runtime.md). Runtime and Gateway spike pending.                                                                                                                           |
| S2    | [ADR 002](../adr/002-litellm-strands.md). [Live results](s2-litellm.json). Structured output passed through Nova 2 Lite and the Bedrock Guardrail blocked its sentinel. The temporary stack was deleted. |
| S3    | [Live metrics](s3-healthscribe.json). All 27 words had timestamps and confidence, zero had multiple alternatives, and five evidence links were returned. The temporary stack was deleted.                |
| S4    | [ADR 004](../adr/004-fhir-backend.md). Local HAPI timing script exists. Synthea generation, HealthLake leg, and comparison remain open.                                                                  |
| S5    | [Catalog](s5-us-east-1.json), [aliases](s5-alias-candidates.json), and [availability](s5-availability.json). Six candidates were selected. Four agreement statuses require follow-up before invocation.  |
