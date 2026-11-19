# ADR 014 — Conservative public-reference CKS lookup and separate hub

- Date: 2026-11-19. Status: accepted for the Phase 1 reference client.
- CKS belongs in a separate, PHI-free hub account; tenant cells connect through PrivateLink.
- Only the standalone dev-cell account is currently configured; hub deployment remains blocked.
- Do not create Organizations, change billing ownership, or reuse a clinical account as the hub implicitly.
- Use real RxNorm exact/normalized lookup, RxClass memberships, and openFDA label sections.
- Only a unique exact RxNorm result automatically selects an RxCUI; normalized/ambiguous candidates require review.
- The live metformin query returned one normalized candidate, whose preferred-name exact lookup returned two concepts.
- This changes the Phase 1 example acceptance: returning candidates is valid; selecting one without review is not.
- Preserve RxClass relationship sources and member concepts; blank relationships require review.
- Preserve label versions, source hashes, retrieval times, missing sections, and truncated coverage.
- Reference text and class membership do not constitute a clinical safety verdict or interaction check.
- Bound requests, retries, response sizes, and per-client request rates; errors yield UNVERIFIED.
- Drug-only validation is not de-identification; callers must remove identifiers before this boundary.
- Hub authentication, PrivateLink, shared rate limiting, Valkey caching, and reference mirroring remain pending.
- Sources: [RxNorm search](https://lhncbc.nlm.nih.gov/RxNav/APIs/api-RxNorm.findRxcuiByString.html), [RxClass](https://lhncbc.nlm.nih.gov/RxNav/APIs/api-RxClass.getClassByRxNormDrugId.html).
- Sources: [openFDA labels](https://open.fda.gov/apis/drug/label/how-to-use-the-endpoint/), [API limits](https://open.fda.gov/apis/authentication/).
