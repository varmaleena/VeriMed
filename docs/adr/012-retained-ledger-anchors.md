# ADR 012 — Version-pinned retained ledger anchors

Status: accepted for the Phase 1 anchor foundation, November 18, 2026.
Store signed daily Merkle manifests in a versioned S3 bucket with seven-year COMPLIANCE retention.
Retain the bucket and its rotating encryption CMK when the stack is removed.
A manifest includes tenant, UTC day, checkpoint head, daily event count, and Merkle root; no clinical payloads.
Verify the complete ledger chain before creating a manifest; sign a domain-separated SHA-256 manifest digest using KMS.
Merkle leaves hash 0x00 || event hash; nodes hash 0x01 || left || right, duplicating an odd final node.
A day's root covers that UTC day's events within the declared checkpoint prefix; later appends are not covered.
Pin bucket, object key, S3 version ID and body digest in the independently held receipt.
Validate KMS signatures, encryption-key ARN, COMPLIANCE mode, retention length, and Merkle contents when reading.
Require conditional writes and deny delete-marker creation in bucket policy; never verify an unpinned latest version.
Retries reuse an existing valid version of the same signed checkpoint; they do not create replacement versions.
A valid older prefix with newer events returns UNVERIFIED until a newer checkpoint covers those events.
S3/KMS failures and malformed references fail closed without logging bodies, signatures or tenant identifiers.
The access-log destination uses SSE-S3 as required by current S3 logging documentation, deviating from blanket CMK logging guidance.
This foundation is on-demand; the scheduled daily worker, checkpoint inventory/freshness policy, and Ledger UI remain pending.
Protected diagnostic anchors cannot be removed before retention expires; preserve encryption/signing keys and version receipts.
Sources: [Object Lock](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html), [conditional-write policy](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes-enforce.html), [S3 logging encryption](https://docs.aws.amazon.com/AmazonS3/latest/userguide/troubleshooting-server-access-logging.html).
