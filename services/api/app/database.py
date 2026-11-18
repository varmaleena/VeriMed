"""Bounded retries for an auto-paused Aurora Data API transaction."""

import time
from typing import Any

from botocore.exceptions import ClientError  # type: ignore[import-untyped]


def begin_transaction(client: Any, connection: dict[str, str]) -> str:
    for delay in (2, 4, 8):
        try:
            return str(client.begin_transaction(**connection)["transactionId"])
        except ClientError as error:
            if error.response["Error"]["Code"] != "DatabaseResumingException":
                raise
            time.sleep(delay)
    return str(client.begin_transaction(**connection)["transactionId"])
