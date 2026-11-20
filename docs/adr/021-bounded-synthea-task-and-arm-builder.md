# ADR 021: Bounded Synthea task and ARM image build

Date: 2026-11-20
Status: Accepted; live validation is recorded separately.

Run Synthea as an on-demand ARM64 Fargate task, not a persistent service.
Use the cell's existing isolated VPC, ECR/Logs endpoints and S3 gateway route.
The task has no public IP, inbound access, NAT or unrestricted internet egress.
Pin Python/Java base image digests and verify the Synthea v4 JAR checksum.
Use a non-root user, read-only root and one writable ephemeral work volume.
Bound population to 1–50; bound generation to 30 minutes and the process to 35.
Publish encrypted immutable input, cohort metadata, then a final ready receipt.
The task does not extend or recreate HealthLake; managed import stays a separate step.
Use an optional IaC-managed ARM CodeBuild builder because local Docker is unavailable.
The builder accepts an allowlisted source asset, has no clinical-data read permissions,
and pushes only after real one-patient generation succeeds with networking disabled.
Launch permissions target the exact deployed task revision; workflow logs exclude payloads.
Source: https://docs.aws.amazon.com/step-functions/latest/dg/connect-ecs.html
Source: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/bind-mounts.html
