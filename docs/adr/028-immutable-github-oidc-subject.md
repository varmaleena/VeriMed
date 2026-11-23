# ADR 028: Immutable GitHub OIDC subjects

Date: 2026-11-23
Status: Accepted; deployed trust, workflow verification recorded separately.

The owner supplied varmaleena/VeriMed for hosted CI and keyless AWS deployment.
New GitHub repositories use immutable owner/repository identifiers in OIDC subjects after July 15, 2026.
The initial legacy subject correctly denied the new-format token; do not relax it to a wildcard.
Resolve canonical repository name and immutable IDs from the actual repository API.
Use repo:OWNER@OWNER-ID/REPO@REPO-ID:environment:dev and audience sts.amazonaws.com.
Create the IAM provider and role using CDK; retain no static AWS keys in GitHub.
Restrict the GitHub dev environment's deployment branch policy to main.
Allow only the configured bootstrap roles and read-only bootstrap/foundation metadata.
The existing dev bootstrap's CloudFormation execution role remains broad; production narrowing is still required.
Persist foundation exports used by optional deployed stacks even when those consumers are not synthesized.
A workflow that authenticates but attempts to remove an in-use export must fail safely and roll back.
Verify an actual GitHub deployment before marking federation acceptance complete.
Source: https://docs.github.com/en/actions/reference/security/oidc
Source: https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-iam-oidcprovider.html
