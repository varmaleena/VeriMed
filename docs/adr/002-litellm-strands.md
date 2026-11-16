# 002 — LiteLLM and Strands

Decision: no-go for LiteLLM until structured output and Guardrails both pass end to end.
Check a schema-valid response and a prompt that triggers an independently observable Guardrail action.
Fallback: Strands BedrockModel with per-tenant tagged application inference profiles.
Evidence: no live inference. See BLOCKERS.md.
