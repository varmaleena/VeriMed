"""Private runtime wiring: Secrets Manager cache credentials and IAM reference worker."""

import asyncio
import json
import re
from urllib.parse import quote

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]

from .bridge import RemoteKnowledgeClient
from .cache import ValkeyStore


def remote_client(function_arn: str) -> RemoteKnowledgeClient:
    if not re.fullmatch(
        r"arn:aws:lambda:[a-z0-9-]+:[0-9]{12}:function:[A-Za-z0-9_-]+", function_arn
    ):
        raise ValueError("A configured reference worker ARN is required")
    return RemoteKnowledgeClient(
        boto3.client(
            "lambda",
            config=Config(
                connect_timeout=2,
                read_timeout=18,
                retries={"max_attempts": 0},
            ),
        ),
        function_arn,
    )


async def secret_store(secret_arn: str, host: str) -> ValkeyStore:
    if not re.fullmatch(r"[a-zA-Z0-9.-]+", host):
        raise ValueError("A configured cache hostname is required")
    client = boto3.client(
        "secretsmanager",
        config=Config(
            connect_timeout=2,
            read_timeout=3,
            retries={"max_attempts": 1},
        ),
    )
    try:
        response = await asyncio.to_thread(client.get_secret_value, SecretId=secret_arn)
        secret = json.loads(response["SecretString"])
        username, password = secret["username"], secret["password"]
        if (
            not isinstance(username, str)
            or not isinstance(password, str)
            or not username
            or len(password) < 16
        ):
            raise ValueError("Invalid cache credential configuration")
        return ValkeyStore(
            "valkeys://"
            + quote(username, safe="")
            + ":"
            + quote(password, safe="")
            + "@"
            + host
            + ":6379/0"
        )
    finally:
        client.close()
