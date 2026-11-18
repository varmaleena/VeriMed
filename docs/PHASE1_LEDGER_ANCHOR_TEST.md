# Phase 1 ledger anchor test

The anchor foundation signs a daily Merkle checkpoint and stores it as a retained S3 object version. Verification pins the bucket, key, version ID and body digest, then checks KMS signatures, encryption and seven-year COMPLIANCE retention. This slice is on-demand. Automatic daily scheduling, an authoritative checkpoint inventory and freshness policy, and the Ledger UI remain pending.

From PowerShell in `F:\AWS MSP`, run the unit tests:

```powershell
.\.venv\Scripts\python.exe -m pytest services/api/tests/test_ledger_anchors.py -q
```

Run the real Aurora/KMS/S3 self-test:

```powershell
.\scripts\Test-LedgerAnchors.ps1 -AwsProfile default -Region us-east-1
```

The existing ledger storage migration must be applied. The dev profile needs the reader/writer secrets, Data API access, signing/encryption key access, S3 object read/write/retention permissions, and permissions to attempt the negative deletion/retention checks. The script discovers resource identifiers from CloudFormation and does not print secrets.

Each run commits four real `system.ledger_probe` diagnostics under a fresh test tenant and retains one small signed checkpoint covering the first three events. It creates no clinical records. Seven-year COMPLIANCE retention is irreversible for the protected version, including for the account root user; rerunning the test creates another retained diagnostic checkpoint. The fourth event tests that a valid but older anchor does not silently verify newer events.

Expected checks:

- A fresh database read verifies against the signed daily Merkle root in the pinned S3 version.
- Retrying the same checkpoint returns its existing reference.
- The object is SSE-KMS encrypted with the configured cell key and retained in COMPLIANCE mode.
- S3 rejects deleting the protected version, shortening its retention, hiding it with a delete marker, or uploading without the required conditional header.
- A different tenant cannot use the reference.
- Truncating the chain and its database head still fails against the independent retained checkpoint.
- Appending after the checkpoint returns UNVERIFIED until a newer checkpoint covers the tail.

Outcomes/counts are saved in `docs/ledger-anchor-verification.json`. The exact version receipt is stored locally in ignored `.phase1-api/anchor-test-receipt.json`, with no signatures or event payloads in logs. In production, trusted receipts/checkpoint inventory must be held independently of the mutable database and selected with an explicit freshness policy. A caller choosing an obsolete receipt cannot prove it is the latest checkpoint.

The retained `CellLedger` bucket blocks public access, requires TLS and conditional writes, and denies delete markers. Object Lock protects individual versions; verification never falls back to an unpinned current version. Missing S3/KMS access, a lost encryption key, malformed data or insufficient retention returns UNVERIFIED. Retaining a bucket does not itself protect KMS keys from a privileged administrator, so key lifecycle controls remain an operations requirement. No signing or S3 write permissions were granted to the web API.

Retention validation uses seven calendar years with a one-second tolerance for S3 timestamp precision. The live service returned a whole-second LastModified and a millisecond retain-until timestamp; unit tests reject a two-second shortfall and a 365-days-per-year approximation that omits leap days.

S3 access logs use a separate private SSE-S3 destination as required by AWS's server-access-logging constraints. Anchor content remains encrypted with the customer-managed CMK. [AWS logging documentation](https://docs.aws.amazon.com/AmazonS3/latest/userguide/troubleshooting-server-access-logging.html).

The additional encryption key costs approximately $1/month, prorated, plus KMS/S3 request and storage charges. Keys must remain available for retained data; deleting the stack retains these resources. Tiny diagnostic objects have minimal byte-storage cost, while the CMK is the main standing charge. Automatic key rotation can add future key-version charges. [KMS pricing](https://aws.amazon.com/kms/pricing/).
