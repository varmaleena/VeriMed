# 001 — AgentCore Runtime and Gateway

Decision: go for AgentCore Runtime with Strands, Cognito JWT authorization and the Gateway MCP Lambda target.
The temporary `AgentCoreSpike` stack deploys a Python 3.12 ARM64 code asset from the CDK bootstrap bucket, an MCP Gateway Lambda target, and a Cognito machine client.
Stage the ARM64 wheels and `spikes/s1_agentcore_runtime.py` as `main.py` in `VERIMED_AGENTCORE_BUNDLE`. Select the model through `MODEL_CHALLENGER_ID` and populate `VERIMED_SPIKE_MODEL_ARNS` from the selected inference profile and its destination models.
Synthesize or deploy with `-c agentCoreSpike=true`. The Runtime and Gateway validate the same Cognito client ID. The Runtime explicitly forwards the validated Authorization header to the Gateway.
Retrieve the temporary client secret from Cognito in memory, request its client-credentials token, and set `VERIMED_SPIKE_COGNITO_TOKEN` for `spikes/s1_agentcore_probe.py`. The probe checks anonymous denial and confirms the greeting from an actual Strands tool result.
Fallback: defer AgentCore integration or host Strands on ECS with authenticated tools if explicitly approved.
Evidence: [live probe](../spikes/s1-agentcore.json) recorded HTTP 401 for the anonymous request and verified a Gateway tool response from the authenticated Strands call.
