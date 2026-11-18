# ADR 010 — Versioned ledger hashing and KMS signatures

Status: accepted for Phase 1 cryptographic primitives, November 18, 2026.
Hash each event as SHA-256(previous 32-byte hash || canonical event bytes).
The genesis hash is 32 zero bytes; a complete tenant chain begins at sequence 1.
Version 1 encodes sorted JSON keys, compact separators, ASCII escapes, and UTC microsecond timestamps.
Payload numbers must be integers or decimal strings; floating-point values are rejected.
The signed event includes its version, tenant, sequence, encounter reference, event type, time, and payload.
Use ECC_NIST_P256 with ECDSA_SHA_256 and MessageType=DIGEST in KMS Sign and Verify.
Pin the immutable key ARN independently of the entry; never trust a stored entry's key identifier alone.
Require a separately trusted head to detect tail deletion; hashes alone cannot establish completeness.
An empty chain returns EMPTY. Provider or parsing errors return UNVERIFIED, never VERIFIED.
Retain signing keys on stack deletion so future historical verification remains possible.
AWS does not support automatic rotation for asymmetric keys; version keys and preserve old verification keys.
The initial stack grants no signing rights to the read-only application runtime.
Transactional append-only persistence, concurrent append locking, Object Lock anchors, key-version registries, and sign-off remain later slices.
The live self-test signs ephemeral non-clinical diagnostics and writes no product records.

Sources: [KMS Sign](https://docs.aws.amazon.com/kms/latest/APIReference/API_Sign.html), [KMS Verify](https://docs.aws.amazon.com/kms/latest/APIReference/API_Verify.html), [CDK KMS key constraints](https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.aws_kms.CfnKey.html).
