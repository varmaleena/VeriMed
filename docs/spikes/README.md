# Spike evidence

Store sanitized measurements here. Exclude access tokens, generated clinical content, and account identifiers.

| Spike | Evidence and status                                                                                                                                                                                      |
| ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| S1    | [ADR 001](../adr/001-agentcore-runtime.md). [Live result](s1-agentcore.json). The anonymous request returned 401 and the authenticated Strands call invoked the Gateway MCP tool.                        |
| S2    | [ADR 002](../adr/002-litellm-strands.md). [Live results](s2-litellm.json). Structured output passed through Nova 2 Lite and the Bedrock Guardrail blocked its sentinel. The temporary stack was deleted. |
| S3    | [Live metrics](s3-healthscribe.json). All 27 words had timestamps and confidence, zero had multiple alternatives, and five evidence links were returned. The temporary stack was deleted.                |
| S4    | [ADR 004](../adr/004-fhir-backend.md). [Live HealthLake result](s4-healthlake.json). HealthLake imported all 76,809 resources for the 50-patient cohort. HAPI timing still needs Docker Compose.         |
| S5    | [Catalog](s5-us-east-1.json), [aliases](s5-alias-candidates.json), and [availability](s5-availability.json). Six candidates were selected. Four agreement statuses require follow-up before invocation.  |
