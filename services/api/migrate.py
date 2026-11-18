"""Apply the Worklist schema in one Data API transaction."""

import json
import os
from pathlib import Path

import boto3  # type: ignore[import-untyped]


def main() -> None:
    client = boto3.client("rds-data")
    config = {
        "resourceArn": os.environ["DATABASE_CLUSTER_ARN"],
        "secretArn": os.environ["DATABASE_SECRET_ARN"],
        "database": "verimed",
    }
    # Dollar-quoted DO bodies contain semicolons and must remain intact.
    source = (Path(__file__).parent / "migrations/001_worklist.sql").read_text()
    prefix, body, suffix = source.split("$$")
    statements = [
        item.strip() for item in prefix.rsplit("DO", 1)[0].split(";") if item.strip()
    ]
    statements.append("DO $$" + body + "$$")
    statements.extend(item.strip() for item in suffix.split(";") if item.strip())
    transaction = client.begin_transaction(**config)["transactionId"]
    try:
        client.execute_statement(
            **config,
            transactionId=transaction,
            sql="SELECT pg_advisory_xact_lock(44801753)",
        )
        for statement in statements:
            client.execute_statement(**config, transactionId=transaction, sql=statement)
        credential = json.loads(
            boto3.client("secretsmanager").get_secret_value(
                SecretId=os.environ["DATABASE_RUNTIME_SECRET_ARN"]
            )["SecretString"]
        )
        if (
            credential["username"] != "verimed_reader"
            or not credential["password"].isalnum()
        ):
            raise ValueError("Unexpected read-only database credential configuration")
        client.execute_statement(
            **config,
            transactionId=transaction,
            sql="DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='verimed_reader') THEN CREATE ROLE verimed_reader LOGIN NOSUPERUSER NOBYPASSRLS; END IF; END $$",
        )
        client.execute_statement(
            **config,
            transactionId=transaction,
            sql="ALTER ROLE verimed_reader PASSWORD '" + credential["password"] + "'",
        )
        client.execute_statement(
            **config,
            transactionId=transaction,
            sql="GRANT verimed_api TO verimed_reader",
        )
        client.commit_transaction(
            resourceArn=config["resourceArn"],
            secretArn=config["secretArn"],
            transactionId=transaction,
        )
    except Exception:
        client.rollback_transaction(
            resourceArn=config["resourceArn"],
            secretArn=config["secretArn"],
            transactionId=transaction,
        )
        raise
    print("Worklist schema applied.")


if __name__ == "__main__":
    main()
