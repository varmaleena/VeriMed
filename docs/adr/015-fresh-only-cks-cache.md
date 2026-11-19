# ADR 015 — Fresh-only CKS Valkey cache

- Date: 2026-11-19. Status: accepted for Phase 1 cache implementation.
- Add an optional shared public-reference cache around the validated reference client.
- Use the Valkey project's Python client, pinned to stable 6.2.0 after PyPI verification.
- Cache typed RESOLVED and REVIEW_REQUIRED results with source provenance for at most one hour.
- Never cache NOT_FOUND, UNVERIFIED, invalid inputs, or results without fresh source timestamps.
- Preserve original retrieval times, ambiguity, missing label sections, and partial-coverage flags.
- Reject expired, future-dated, oversized, malformed, wrong-query and digest-mismatched entries.
- Cache read/write failure bypasses cache and uses the real provider; provider failure remains UNVERIFIED.
- Use versioned SHA-256 query keys; do not log query text, credentials, payloads, or exception text.
- SHA-256 detects accidental corruption; it is not cache authentication or encryption.
- Require TLS with certificate and hostname verification; plaintext needs explicit loopback-only opt-in.
- Bound pool size, socket deadlines and operation timeouts; no unbounded cache retries.
- No endpoint or clinical verdict is introduced; service authorization remains required before deployment.
- Shared rate limiting, hub hosting, PrivateLink, and the Postgres mirror remain separate unfinished work.
- Real-Valkey integration is added to CI; local execution is blocked by absent Docker and WSL.
- Sources: [Valkey clients](https://valkey.io/clients/), [async API](https://valkey-py.readthedocs.io/en/latest/examples/asyncio_examples.html), [SET expiry](https://valkey.io/commands/set/).
