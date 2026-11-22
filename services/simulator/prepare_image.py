"""Prepare only locked requirements and a checksum-verified public Synthea JAR."""

import argparse
import hashlib
import shutil
import subprocess
import urllib.request
from pathlib import Path
from uuid import uuid4

from simulator.synthea import SYNTHEA_SHA256

URL = "https://github.com/synthetichealth/synthea/releases/download/v4.0.0/synthea-with-dependencies.jar"


def prepare(jar: Path | None) -> None:
    root = Path(__file__).resolve().parents[2]
    destination = root / ".build-synthea"
    destination.mkdir(exist_ok=True)
    artifact = destination / "synthea.jar"
    if jar:
        with jar.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != SYNTHEA_SHA256:
                raise ValueError("Unverified Synthea artifact")
        shutil.copyfile(jar, artifact)
    elif not artifact.exists():
        with (
            # Fixed upstream HTTPS release URL; the downloaded bytes must match SYNTHEA_SHA256 below.
            # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            urllib.request.urlopen(URL, timeout=120) as response,
            artifact.open("xb") as output,
        ):
            shutil.copyfileobj(response, output)
    with artifact.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != SYNTHEA_SHA256:
            raise ValueError("Synthea checksum mismatch; replace the build artifact")
    subprocess.run(
        [
            "uv",
            "export",
            "--locked",
            "--package",
            "verimed-simulator",
            "--no-dev",
            "--no-emit-workspace",
            "--format",
            "requirements.txt",
            "--no-header",
            "--no-annotate",
            "--output-file",
            str(destination / "requirements.txt"),
        ],
        cwd=root,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    context = root / ".phase1-fhir" / ("image-source-" + uuid4().hex)
    runtime = context / "services/simulator/simulator"
    runtime.mkdir(parents=True)
    for source in (root / "services/simulator/simulator").glob("*.py"):
        shutil.copyfile(source, runtime / source.name)
    container = context / "services/simulator/container"
    container.mkdir(parents=True)
    for name in ("Dockerfile", "Dockerfile.dockerignore"):
        shutil.copyfile(root / "services/simulator/container" / name, container / name)
    inputs = context / ".build-synthea"
    inputs.mkdir()
    for name in ("synthea.jar", "requirements.txt"):
        shutil.copyfile(destination / name, inputs / name)
    print("Prepared checksum-verified, allowlisted image context: " + str(context))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar", type=Path)
    prepare(parser.parse_args().jar)
