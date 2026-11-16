"""Submit one Polly-generated synthetic conversation to a provisioned HealthScribe sandbox."""

import argparse
import json
import subprocess
import tempfile
import uuid
import wave
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("profile", "account", "bucket", "role-arn", "key-arn"):
        parser.add_argument(f"--{option}", required=True)
    args = parser.parse_args()
    aws = ["aws", "--profile", args.profile, "--region", "us-east-1", "--no-cli-pager"]
    identity = subprocess.check_output(
        [*aws, "sts", "get-caller-identity", "--query", "Account", "--output", "text"],
        text=True,
    ).strip()
    if identity != args.account:
        parser.error("the selected profile does not resolve to the expected account")
    job = f"verimed-s3-{uuid.uuid4().hex}"
    media_uri = f"s3://{args.bucket}/{job}.wav"
    print(
        "Estimated speech processing spend: under $0.10, plus sandbox storage requests."
    )
    dialogue = (
        ("Joanna", "What brought you in for your visit today?"),
        ("Matthew", "My ankle felt sore after walking yesterday."),
        ("Joanna", "Did you notice any swelling?"),
        ("Matthew", "No, I did not notice any swelling."),
    )
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        clip = root / "conversation.wav"
        with wave.open(str(clip), "wb") as audio:
            audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            for voice, line in dialogue:
                pcm = root / "turn.pcm"
                subprocess.run(
                    [
                        *aws,
                        "polly",
                        "synthesize-speech",
                        "--engine",
                        "neural",
                        "--text",
                        line,
                        "--voice-id",
                        voice,
                        "--output-format",
                        "pcm",
                        "--sample-rate",
                        "16000",
                        str(pcm),
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                )
                audio.writeframes(pcm.read_bytes() + bytes(8000))
        subprocess.run(
            [
                *aws,
                "s3",
                "cp",
                str(clip),
                media_uri,
                "--sse",
                "aws:kms",
                "--sse-kms-key-id",
                args.key_arn,
                "--only-show-errors",
            ],
            check=True,
        )
    command = [
        *aws,
        "transcribe",
        "start-medical-scribe-job",
        "--medical-scribe-job-name",
        job,
        "--media",
        f"MediaFileUri={media_uri}",
        "--output-bucket-name",
        args.bucket,
        "--data-access-role-arn",
        args.role_arn,
        "--output-encryption-kms-key-id",
        args.key_arn,
        "--settings",
        "ShowSpeakerLabels=true,MaxSpeakerLabels=2",
    ]
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
    print(json.dumps({"job": job, "region": "us-east-1"}))


if __name__ == "__main__":
    main()
