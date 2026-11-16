# 002 — LiteLLM and Strands

Decision: go for LiteLLM based on the live Bedrock Nova 2 Lite spike. Production rollout still requires per-tenant budgets and workload identity.
The Strands client returned the expected schema-valid integer through a localhost LiteLLM proxy backed by Bedrock Converse.
An independent chat completion request hit the Bedrock word filter. The proxy returned HTTP 400 with the configured block message.
Use separate client and proxy environments because the Strands LiteLLM extra excludes the current proxy version.
Fallback: Strands BedrockModel with per-tenant tagged application inference profiles.
Evidence: [live results](../spikes/s2-litellm.json). The temporary Guardrail stack was deleted.
