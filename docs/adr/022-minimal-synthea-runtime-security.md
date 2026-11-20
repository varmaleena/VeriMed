# ADR 022: Reduce Synthea runtime OS dependencies

Date: 2026-11-20
Status: Accepted; replacement scan evidence is recorded separately.

The first real ARM build generated a Synthea patient successfully.
Its ECR scan reported 15 HIGH findings in the Debian-based runtime.
Several involved glibc, Kerberos, PAM, util-linux, SQLite and zlib.
Debian lists CVE-2026-84243 as unfixed, so routine upgrades alone are insufficient.
Do not deploy this first image merely because its generation smoke test passed.
Use verified official Alpine Python 3.12 and Temurin Java 21 JRE image digests.
Apply the distribution's current security updates and install only required runtime libraries.
Require hash-verified binary Python wheels; do not compile unpinned build dependencies.
Use coreutils for the same hard timeout contract and retain the non-root/read-only controls.
Rebuild and rerun real generation; do not infer musl compatibility from compilation alone.
Hold Fargate activation until the replacement image completes its security scan.
Do not suppress CVEs or report an unsupported/incomplete scan as clean.
Source: https://security-tracker.debian.org/tracker/CVE-2026-84243
Source: https://security-tracker.debian.org/tracker/CVE-2026-85091
