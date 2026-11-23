"""Prepare ignored local-only Compose credentials and verify real service readiness."""

import argparse
import http.client
import secrets
import time
from pathlib import Path


def prepare() -> None:
    path = Path(".env")
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    required = {
        "LOCAL_POSTGRES_PASSWORD": secrets.token_hex(32),
        "LOCAL_MINIO_USER": "local" + secrets.token_hex(8),
        "LOCAL_MINIO_PASSWORD": secrets.token_hex(32),
    }
    lines = content.splitlines()
    for name, value in required.items():
        matches = [
            index for index, line in enumerate(lines) if line.startswith(name + "=")
        ]
        if len(matches) > 1:
            raise ValueError(
                "Duplicate local configuration keys; fix .env before bootstrap"
            )
        if not matches:
            lines.append(name + "=" + value)
        elif not lines[matches[0]].split("=", 1)[1].strip():
            lines[matches[0]] = name + "=" + value
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        "Local Compose configuration prepared in ignored .env; values are not printed."
    )


def readiness() -> None:
    deadline = time.monotonic() + 240
    pending = {(8080, "/fhir/metadata"), (9000, "/minio/health/live")}
    while pending and time.monotonic() < deadline:
        for port, path in list(pending):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            try:
                connection.request("GET", path)
                response = connection.getresponse()
                if response.status == 200:
                    pending.remove((port, path))
            except (OSError, http.client.HTTPException):
                pass
            finally:
                connection.close()
        if pending:
            time.sleep(3)
    if pending:
        raise RuntimeError(
            "Local service readiness failed; inspect Docker health and resource limits"
        )
    print("Real local FHIR and object-storage readiness checks passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-services", action="store_true")
    if parser.parse_args().check_services:
        readiness()
    else:
        prepare()
