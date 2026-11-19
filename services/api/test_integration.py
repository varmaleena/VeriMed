"""Run rollback-only integration checks against an explicitly tagged dev cell."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

import boto3  # type: ignore[import-untyped]
from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default="dev")
    parser.add_argument("--cell", default="a")
    args = parser.parse_args()
    if args.env != "dev":
        print("Integration diagnostics require ENV=dev.")
        return 1
    try:
        stack = boto3.client(
            "cloudformation", region_name=os.environ.get("AWS_REGION", "us-east-1")
        ).describe_stacks(StackName="CellWorklist")["Stacks"][0]
    except (BotoCoreError, ClientError):
        print(
            "Integration checks require AWS credentials and a deployed dev CellWorklist stack."
        )
        return 1
    tags = {tag["Key"]: tag["Value"] for tag in stack.get("Tags", [])}
    if tags.get("Env") != "dev" or tags.get("Tenant") != args.cell:
        print("Refusing diagnostics: stack tags do not match the requested dev cell.")
        return 1
    outputs = {value["OutputKey"]: value["OutputValue"] for value in stack["Outputs"]}
    required = {
        "DATABASE_CLUSTER_ARN": "ClusterArn",
        "DATABASE_SECRET_ARN": "SecretArn",
    }
    if any(key not in outputs for key in required.values()):
        print("Integration checks require deployed database outputs.")
        return 1
    api_root = Path(__file__).resolve().parent
    env = dict(os.environ)
    env.update({name: outputs[key] for name, key in required.items()})
    env["PYTHONPATH"] = str(api_root)
    return subprocess.run(
        [sys.executable, str(api_root / "tests/live_platform_schema.py")],
        env=env,
        cwd=api_root.parents[1],
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
