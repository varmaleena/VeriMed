# 005 — Bedrock aliases

Decision: go for the six candidate aliases at the catalog level. Runtime use remains gated on invocation and compatibility checks.
The authorized dev profile returned 126 foundation model entries and 103 system profiles for us-east-1.
All six candidates reported regional availability, account authorization, and entitlement. Nova and Titan also reported an available agreement. The API reported `NOT_AVAILABLE` for the other four agreements, so those candidates require an invocation check before use.
Use US inference profiles for generative workloads and separate families for reasoning, challenge, and judging.
The selection remains deployment configuration. Product source must read aliases from its environment.
Fallback: leave any unavailable alias unset and block its consumers until a compatible replacement passes a live check.
Evidence: [catalog](../spikes/s5-us-east-1.json), [alias candidates](../spikes/s5-alias-candidates.json), and [availability checks](../spikes/s5-availability.json).
