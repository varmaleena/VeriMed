# ADR 027: Maintained Synthea dependency rebuild

Date: 2026-11-23
Status: Go for the validated JAR; full runtime image and fifty-patient regressions remain separate gates.

The upstream v4.0.0 fat JAR contained 70 HIGH and 17 CRITICAL Java findings in hosted Trivy.
ECR basic OS scanning had not covered those embedded Java dependencies.
Build immutable upstream commit 0185c09ea9d10a822c6f5f3ef9bdcbcbe960c813 with reviewed dependency pins.
Upgrade FHIR core to 6.9.12, HTTP core to 5.4.3, Jackson to 2.23, and the recorded utility dependencies.
Apply explicit FHIRPath package and SnakeYAML LoaderOptions compatibility changes.
An initial filesystem scan skipped JARs; replace it with image scanning and require populated Java inventory.
The final image-mode report inventoried 132 Java packages with zero HIGH/CRITICAL findings.
Real FHIR generation passed with networking disabled and alive-patient filtering enabled.
Publish only code, checksum and scanner metadata; no generated patient output is released.
Runtime SHA-256: 33b36f37163db67d36fb5ff515027fee666933ddad2a37628708abcec4f8005b.
Historical generation/import evidence continues to identify the older JAR and is not rewritten.
No-go on a future scan or regression failure: block image promotion and investigate; do not suppress vulnerabilities.
Source: https://github.com/varmaleena/VeriMed/releases/tag/synthea-4.0.0-security.1
Source: https://trivy.dev/docs/latest/coverage/language/
