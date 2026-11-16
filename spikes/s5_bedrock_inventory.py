"""Discover regional Bedrock candidates without invoking models."""

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


def aws(profile: str, region: str, command: str) -> Any:
    result = subprocess.run(
        [
            "aws",
            "--profile",
            profile,
            "--region",
            region,
            "--no-cli-pager",
            "--output",
            "json",
            "bedrock",
            command,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print("Estimated model inference spend: $0 (catalog listing only).")
    models = aws(args.profile, args.region, "list-foundation-models")
    profiles = aws(args.profile, args.region, "list-inference-profiles")
    # Keep identifiers from the public catalog; omit application profile account information.
    report = {
        "region": args.region,
        "foundation_models": models["modelSummaries"],
        "system_profiles": [
            {
                key: profile[key]
                for key in ("inferenceProfileId", "inferenceProfileName", "status")
            }
            for profile in profiles["inferenceProfileSummaries"]
            if profile["type"] == "SYSTEM_DEFINED"
        ],
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
