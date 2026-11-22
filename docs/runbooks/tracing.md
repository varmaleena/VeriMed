# Dev-cell trace verification

Use the authorized dev profile, current locked Python workspace and deployed CellIdentity,
CellWorklist and CellObservability stacks. No active HealthLake window is required.

```powershell
uv run --all-packages python services/api/trace_probe.py --profile default --region us-east-1
```

The probe creates a temporary example.invalid identity without sending an invitation,
authenticates through real Cognito SRP, checks Gateway/API authorization and queries actual
span delivery. It removes that identity in a finally block and records cleanup verification.
The output in docs/tracing-verification.json contains operational metadata only.
If cleanup fails, .phase1-api/trace-probe-cleanup.json identifies the resource to remove;
verify its pool and generated trace-probe email before deletion, then rerun verification.
Never print credentials, tokens, clinical response bodies or signed CloudFormation callbacks.

Build deployable Linux wheels with scripts/Build-ApiBundle.ps1. Deploy tracing with
scripts/Deploy-CellTracing.ps1 using the resulting bundle path. The scripts guard dev tags,
retain existing identity bindings and preserve the expired FHIR-window signal.
The trace CMK adds approximately $1/month before request and log charges; this is an estimate,
not a billing measurement. The unsuccessful stack's unused CMK is pending deletion.
Hosted web tracing and Sentry remote delivery are separate acceptance checks.
