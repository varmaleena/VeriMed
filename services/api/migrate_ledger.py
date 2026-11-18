"""Apply the ledger schema transactionally; never prints database credentials."""

import json
import os
from pathlib import Path

import boto3  # type: ignore[import-untyped]
from app.database import begin_transaction


def main() -> None:
    client = boto3.client("rds-data")
    config = {
        "resourceArn": os.environ["DATABASE_CLUSTER_ARN"],
        "secretArn": os.environ["DATABASE_SECRET_ARN"],
        "database": "verimed",
    }
    transaction = begin_transaction(client, config)
    finish = {
        "resourceArn": config["resourceArn"],
        "secretArn": config["secretArn"],
        "transactionId": transaction,
    }
    try:
        client.execute_statement(
            **config,
            transactionId=transaction,
            sql="SELECT pg_advisory_xact_lock(44801753)",
        )
        source = (Path(__file__).parent / "migrations/002_ledger.sql").read_text()
        for statement in source.split("-- statement-break"):
            if statement.strip():
                client.execute_statement(
                    **config, transactionId=transaction, sql=statement
                )
        credential = json.loads(
            boto3.client("secretsmanager").get_secret_value(
                SecretId=os.environ["DATABASE_LEDGER_SECRET_ARN"]
            )["SecretString"]
        )
        if (
            credential["username"] != "verimed_ledger_writer"
            or not credential["password"].isalnum()
        ):
            raise ValueError("Unexpected ledger writer credential configuration")
        client.execute_statement(
            **config,
            transactionId=transaction,
            sql="DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='verimed_ledger_writer') THEN CREATE ROLE verimed_ledger_writer LOGIN NOSUPERUSER NOBYPASSRLS; END IF; END $$",
        )
        client.execute_statement(
            **config,
            transactionId=transaction,
            sql="ALTER ROLE verimed_ledger_writer PASSWORD '"
            + credential["password"]
            + "'",
        )
        client.execute_statement(
            **config,
            transactionId=transaction,
            sql="GRANT verimed_ledger_append TO verimed_ledger_writer",
        )
        client.commit_transaction(**finish)
    except Exception:
        client.rollback_transaction(**finish)
        raise
    print("Ledger schema applied.")


if __name__ == "__main__":
    main()
