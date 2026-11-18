# Phase 1 ledger primitives test

This slice supplies the hash-chain/signature library and a retained cell KMS signing key. It does not expose a ledger endpoint, write clinical ledger records, or enable note sign-off. Phase 1 remains in progress.

From PowerShell in `F:\AWS MSP`, run the local tamper tests:

```powershell
.\.venv\Scripts\python.exe -m pytest services/api/tests/test_ledger.py -q
```

Run the deployed KMS self-test with the authorized dev profile:

```powershell
$env:AWS_PROFILE = 'default'
$env:AWS_REGION = 'us-east-1'
$env:PYTHONPATH = 'services/api'
$env:TENANT_ID = 'fe54cd8b-3dac-43d3-9a30-1f588cb60d35'
$env:LEDGER_SIGNING_KEY_ARN = aws cloudformation describe-stacks --stack-name CellLedger --query "Stacks[0].Outputs[?OutputKey=='SigningKeyArn'].OutputValue | [0]" --output text
.\.venv\Scripts\python.exe services/api/tests/live_ledger.py
```

Expect `real_kms_chain: VERIFIED`, with `BROKEN` for altered payload, invalid signature, wrong tenant and a truncated chain. The self-test creates fresh diagnostic events in memory, calls real KMS, and saves only verification outcomes/counts in `docs/ledger-verification.json`. Unit tests also cover reordered/missing records, verifier outages, mutable key aliases, timestamp normalization and integer-only payloads. Logs and spans contain no event payload, signature or clinical identifiers.

A trusted head must be supplied from outside the chain being checked. The test retains that head in memory before tampering. Durable independent anchors and transactional append-only DB persistence remain required before this becomes a production ledger. A future encounter verifier must check the full tenant chain before selecting an encounter's events. Key rotation will require a trusted key-version registry; the current primitive pins one key ARN.

The `CellLedger` CDK stack creates an ECC_NIST_P256 SIGN_VERIFY key with Project/Tenant/Env tags. It retains the key on removal and grants no KMS signing access to the Worklist runtime. Do not delete a signing key after clinical records depend on it.

Cost: one customer-managed key adds $1/month prorated hourly. AWS's ECC-256 example lists $0.15 per 10,000 signing requests; asymmetric requests are excluded from the free tier. This small self-test's requests should cost under $0.01, excluding any supporting logging charges. [AWS KMS pricing](https://aws.amazon.com/kms/pricing/).
