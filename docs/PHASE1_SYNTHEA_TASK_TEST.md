# Phase 1 hosted Synthea task

The generator runs as an on-demand ARM64 Fargate task: 1 vCPU, 2 GiB, no public IP,
no NAT, no inbound listener, read-only root and a writable ephemeral `/work` volume.
It generates 1–50 patients using the verified Synthea v4 JAR and publishes encrypted,
versioned NDJSON plus cohort metadata into the existing cell transfer bucket.
`metadata/ready.json` is written last. Partial output is not a completed generation.
The generator does not create a datastore or submit a managed FHIR import.

## Image build

Run `uv run --all-packages python services/simulator/prepare_image.py --jar PATH_TO_VERIFIED_JAR`.
The command exports hash-locked requirements and prepares an allowlisted source directory
under `.phase1-fhir/`. Supply that directory as `VERIMED_SYNTHEA_BUILD_CONTEXT`.
Only Python sources, Docker build files, requirements and the public JAR are included.
No `.env`, AWS credentials, clinical exports, cohort IDs or result JSON enter the build asset.

`CellSynthea` first creates an immutable KMS-encrypted ECR repository and optional ARM
CodeBuild project. Start one bounded build. The builder generates one actual patient with
networking disabled before pushing. Obtain the resulting image digest and redeploy with
`VERIMED_SYNTHEA_IMAGE_DIGEST`; never provide a floating tag or an invented digest.
The builder has no permission to read cell clinical data or secrets.

Required deployment configuration: `VERIMED_CELL_ACCOUNT`, `VERIMED_TRANSFER_BUCKET`,
`VERIMED_TRANSFER_KEY_ARN`, `VERIMED_S3_PREFIX_LIST_ID`, and the optional build context/digest.
Use `-c cellSynthea=true`; the task reuses CellFoundation's endpoint security group and subnets.

## Verification

The internal job schema is `packages/api-client/synthea-generation-job.schema.json`.
Start the workflow with a new UUID `job_id` and integer `population`; use the same UUID
as the execution name to avoid duplicate operator submissions. No retries generate a new cohort
under an already-used ID: conditional S3 writes fail rather than overwrite existing output.
Never include patient content in the execution input.

The guarded Windows entry point is `./scripts/Start-SyntheaTask.ps1 -Population 50 -AwsProfile default`.
It verifies the stack's Project/Env/Tenant tags and starts only a dev-cell workflow;
it never chooses a bucket, role, endpoint or datastore from user-supplied job input.

Unit tests cover population bounds, extra target fields, versioning, immutable encrypted
publication, partial failure and payload-free error telemetry. CDK assertions cover private
execution, bounded resources, IAM boundaries, image immutability and security validation.
The GitHub ARM job builds the real image, runs the same isolated smoke test and scans it.
Hosted CI remains unverified until a GitHub remote is configured.

`docs/synthea-task-verification.json` records actual successful 1- and 50-patient Fargate runs.
The latter produced 65,666 resources in 105.22 seconds. The source version, KMS encryption,
checksum and cohort counts were checked through the real S3 API. This newly generated cohort
was not submitted to HealthLake because its approved window had already ended.
ECR basic OS scanning completed with zero findings; this does not replace broader dependency scanning.
