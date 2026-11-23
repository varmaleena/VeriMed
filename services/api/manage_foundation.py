"""Guard standard foundation commands against wrong-account or wrong-tenant mutation."""

import argparse
import os
import subprocess
from pathlib import Path

import boto3  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["deploy", "destroy"])
    parser.add_argument("--env", required=True, choices=["dev", "demo", "prod"])
    parser.add_argument("--cell", required=True)
    args = parser.parse_args()
    if args.cell not in {"a", "b"}:
        raise ValueError("Use an explicitly named tenant cell a or b")
    expected = os.environ.get("VERIMED_CELL_ACCOUNT")
    if not expected or not expected.isdigit() or len(expected) != 12:
        raise ValueError("Set VERIMED_CELL_ACCOUNT to the intended tenant account")
    session = boto3.Session(region_name=os.environ.get("AWS_REGION", "us-east-1"))
    if session.client("sts").get_caller_identity()["Account"] != expected:
        raise ValueError("AWS credentials do not match VERIMED_CELL_ACCOUNT")
    if expected == os.environ.get("VERIMED_HUB_ACCOUNT"):
        raise ValueError("Hub and cell accounts must be different")
    try:
        stack = session.client("cloudformation").describe_stacks(
            StackName="CellFoundation"
        )["Stacks"][0]
    except ClientError as error:
        if error.response["Error"][
            "Code"
        ] != "ValidationError" or "does not exist" not in error.response["Error"].get(
            "Message", ""
        ):
            raise
        if args.action == "destroy":
            raise ValueError("No matching tenant foundation exists") from None
    else:
        tags = {item["Key"]: item["Value"] for item in stack.get("Tags", [])}
        if any(
            tags.get(k) != v
            for k, v in {
                "Project": "verimed",
                "Env": args.env,
                "Tenant": args.cell,
            }.items()
        ):
            raise ValueError(
                "Refusing to mutate a foundation belonging to another tenant or environment"
            )
    root = Path(__file__).resolve().parents[2]
    command = [
        "pnpm",
        "--filter",
        "@verimed/cdk",
        "exec",
        "cdk",
        args.action,
        "CellFoundation",
        "-c",
        "env=" + args.env,
        "-c",
        "cell=" + args.cell,
    ]
    if args.action == "destroy":
        command.append("--force")
    subprocess.run(command, cwd=root, check=True)


if __name__ == "__main__":
    main()
