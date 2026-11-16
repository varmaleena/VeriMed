# 001 — AgentCore Runtime and Gateway

Decision: no-go for adoption based on Phase 0 evidence until the live JWT and MCP checks pass.
Deploy an ARM64 Strands Runtime, an MCP Gateway with a Lambda target, and a Cognito pool through CDK.
Use Cognito access tokens for inbound authorization and require the expected application client.
Verify a tool call through the agent and denial for a missing or invalid token.
Fallback: defer AgentCore integration or host Strands on ECS with authenticated tools if explicitly approved.
Evidence: no deployment. See BLOCKERS.md.
