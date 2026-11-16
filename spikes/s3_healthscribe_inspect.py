"""Measure HealthScribe output structure without retaining transcript or note text."""

import argparse
import json
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit


def mappings(value: object) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from mappings(item)
    elif isinstance(value, list):
        for item in value:
            yield from mappings(item)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--job", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    aws = ["aws", "--profile", args.profile, "--region", "us-east-1", "--no-cli-pager"]
    for _ in range(60):
        job = json.loads(
            subprocess.check_output(
                [
                    *aws,
                    "transcribe",
                    "get-medical-scribe-job",
                    "--medical-scribe-job-name",
                    args.job,
                    "--output",
                    "json",
                ]
            )
        )["MedicalScribeJob"]
        if job["MedicalScribeJobStatus"] == "COMPLETED":
            break
        if job["MedicalScribeJobStatus"] == "FAILED":
            raise RuntimeError(
                f"HealthScribe job failed: {job.get('FailureReason', 'unknown')}"
            )
        time.sleep(10)
    else:
        raise TimeoutError("HealthScribe job did not finish within ten minutes")

    def read_output(name: str) -> Any:
        uri = urlsplit(job["MedicalScribeOutput"][name])
        if uri.scheme == "s3" and uri.netloc == args.bucket:
            key = uri.path.lstrip("/")
        elif uri.scheme == "https" and uri.netloc == "s3.us-east-1.amazonaws.com":
            bucket, _, key = uri.path.lstrip("/").partition("/")
            if bucket != args.bucket:
                raise ValueError(
                    "HealthScribe output points outside the dedicated S3 bucket"
                )
        else:
            raise ValueError(
                "HealthScribe output points outside the dedicated S3 bucket"
            )
        key = unquote(key)
        if not key.startswith(f"{args.job}/"):
            raise ValueError(
                "HealthScribe output points outside the dedicated job prefix"
            )
        return json.loads(
            subprocess.check_output(
                [
                    *aws,
                    "s3",
                    "cp",
                    f"s3://{args.bucket}/{key}",
                    "-",
                    "--only-show-errors",
                ]
            )
        )

    transcript = read_output("TranscriptFileUri")
    clinical = read_output("ClinicalDocumentUri")
    words = [
        item for item in mappings(transcript) if item.get("Type") == "PRONUNCIATION"
    ]
    stats = {
        "words": len(words),
        "words_with_timestamps": sum(
            "BeginAudioTime" in word and "EndAudioTime" in word for word in words
        ),
        "words_with_confidence": sum(
            any("Confidence" in a for a in word.get("Alternatives", []))
            for word in words
        ),
        "words_with_multiple_alternatives": sum(
            len(word.get("Alternatives", [])) > 1 for word in words
        ),
        "evidence_links": sum(
            len(item.get("EvidenceLinks", [])) for item in mappings(clinical)
        ),
    }
    args.output.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
