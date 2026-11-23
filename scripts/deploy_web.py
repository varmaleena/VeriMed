"""Deploy a verified Linux web bundle into the existing tagged dev cell through CDK."""

import argparse
import base64
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import boto3  # type: ignore[import-untyped]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--profile", default="default")
    parser.add_argument("--public-origin", default="https://bootstrap.invalid")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    bundle = args.bundle.resolve()
    manifest = json.loads(bundle.with_name("manifest.json").read_text(encoding="utf-8"))
    with bundle.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if (
        manifest.get("sha256") != digest
        or manifest.get("platform") != "linux"
        or manifest.get("environment_files_included") is not False
    ):
        raise ValueError(
            "A checksum-verified Linux bundle without environment files is required"
        )
    session = boto3.Session(profile_name=args.profile, region_name="us-east-1")
    account = session.client("sts").get_caller_identity()["Account"]
    cf = session.client("cloudformation")

    def outputs(name: str, guarded: bool = True) -> dict[str, str]:
        stack: dict[str, Any] = cf.describe_stacks(StackName=name)["Stacks"][0]
        tags = {item["Key"]: item["Value"] for item in stack.get("Tags", [])}
        if guarded and any(
            tags.get(key) != value
            for key, value in {
                "Project": "verimed",
                "Env": "dev",
                "Tenant": "a",
            }.items()
        ):
            raise ValueError("Existing stack does not match the authorized dev cell")
        return {item["OutputKey"]: item["OutputValue"] for item in stack["Outputs"]}

    assets, api, identity = (
        outputs("CellWebAssets"),
        outputs("CellWorklist"),
        outputs("CellIdentity", False),
    )
    versioning = session.client("s3").get_bucket_versioning(Bucket=assets["CodeBucket"])
    if versioning.get("Status") != "Enabled":
        raise ValueError("Deployment bucket must be versioned")
    key = f"revisions/{digest}.zip"
    with bundle.open("rb") as stream:
        uploaded = session.client("s3").put_object(
            Bucket=assets["CodeBucket"],
            Key=key,
            Body=stream,
            ServerSideEncryption="aws:kms",
            SSEKMSKeyId=assets["KeyArn"],
            ChecksumSHA256=base64.b64encode(bytes.fromhex(digest)).decode(),
        )
    version = uploaded.get("VersionId")
    if not version:
        raise RuntimeError("No immutable code-object version returned")
    env = dict(os.environ)
    env.update(
        {
            "VERIMED_CELL_ACCOUNT": account,
            "AWS_REGION": "us-east-1",
            "AWS_PROFILE": args.profile,
            "VERIMED_WEB_CODE_BUCKET": assets["CodeBucket"],
            "VERIMED_WEB_CODE_KEY": key,
            "VERIMED_WEB_CODE_VERSION": version,
            "VERIMED_WEB_KEY_ARN": assets["KeyArn"],
            "WEB_AUTH_SECRET_ARN": assets["AuthSecretArn"],
            "COGNITO_USER_POOL_ID": identity["UserPoolId"],
            "AUTH_COGNITO_ID": identity["ClientId"],
            "AUTH_COGNITO_ISSUER": identity["Issuer"],
            "CELL_API_URL": api["ApiUrl"],
            "VERIMED_WEB_ORIGIN": args.public_origin,
        }
    )
    subprocess.run(
        [
            "node",
            "infra/cdk/node_modules/aws-cdk/bin/cdk",
            "deploy",
            "CellWeb",
            "--app",
            "node infra/cdk/dist/app.js",
            "-c",
            "cellWeb=true",
            "-c",
            "env=dev",
            "-c",
            "cell=a",
            "--profile",
            args.profile,
            "--require-approval",
            "never",
            "--output",
            "infra/cdk/cdk.out/web",
        ],
        cwd=root,
        env=env,
        check=True,
    )
    result = outputs("CellWeb")
    report = {
        "status": "DEPLOYED_NOT_YET_VERIFIED",
        "sha256": digest,
        "url": result["WebUrl"],
        "origin_domain": result["OriginDomain"],
        "auth_origin_configured": args.public_origin == result["WebUrl"],
    }
    (root / "docs/web-deployment.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report))


if __name__ == "__main__":
    main()
