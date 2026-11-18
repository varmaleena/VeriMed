# 006 — Begin Phase 1 with an authentication slice

The owner requested moving to the next phase after reviewing the remaining Phase 0 blocker.
Phase 0 stays incomplete with the HAPI PostgreSQL benchmark and hosted CI still open.
Build Phase 1 incrementally with a test handoff after each working slice.
The first slice is Cognito authorization-code sign-in, mandatory TOTP, and a protected clinician shell.
No patient data is shown until the real cell API is connected.
Auth.js v5 is explicitly specified but remains a prerelease in the registry.
Pin 5.0.0-beta.32 and verify the integration before deployment.
Use PKCE, state and nonce checks, a server-side encrypted session, and short token-bound access.
The first slice is complete only after a human tests TOTP setup, sign-in, expiry and sign-out.
