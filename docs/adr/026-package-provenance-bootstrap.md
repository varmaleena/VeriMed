# ADR 026: Explicit package supply-chain policy

Date: 2026-11-23
Status: Accepted; owner approved the single Auth.js exception.

Enable pnpm's seven-day minimum release age, blocked exotic transitive sources and no-downgrade trust policy.
Resolve eligible stable dependencies rather than exempting recently published dependency trees.
Use AWS SDK clients 3.1169.0, published November 13, instead of the newly released 3.1175.0.
Retain the specification's Auth.js v5 integration and exact 5.0.0-beta.32 pin.
That prerelease has no npm provenance and triggers the no-downgrade rule.
The official nextauthjs/next-auth tag resolves to e293b3746616660f0844347a68d09eac54b95c6f.
Its package manifest confirms the exact prerelease version; registry integrity remains locked.
Automatic review rejected both broad age exceptions and the initial provenance exception.
No broad age exception was applied. The owner subsequently approved the exact Auth.js version.
Exclude only next-auth@5.0.0-beta.32 from the provenance rule; all age checks remain enforced.
This records the missing attestation, not a claim of independently reproduced package contents.
Frozen installation passed after fresh resolution under these settings.
Pin GitHub Actions to verified commit hashes, retaining release tags as comments.
Source: https://pnpm.io/settings/dependency-resolution
Source: https://github.com/nextauthjs/next-auth/tree/e293b3746616660f0844347a68d09eac54b95c6f/packages/next-auth
