"""Run negative isolation checks against the real dev services with rollback-only rows."""

import os
from uuid import uuid4

import boto3  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]


def main() -> None:
    client = boto3.client("rds-data")
    config = {
        "resourceArn": os.environ["DATABASE_CLUSTER_ARN"],
        "secretArn": os.environ["DATABASE_SECRET_ARN"],
        "database": "verimed",
    }
    tenant_a, tenant_b = str(uuid4()), str(uuid4())
    transaction = client.begin_transaction(**config)["transactionId"]
    try:
        for tenant in (tenant_a, tenant_b):
            client.execute_statement(
                **config,
                transactionId=transaction,
                sql="INSERT INTO patients (tenant_id, fhir_patient_id, display_token, source) VALUES (CAST(:tenant AS uuid), :id, :token, 'isolation_test')",
                parameters=[
                    {"name": "tenant", "value": {"stringValue": tenant}},
                    {"name": "id", "value": {"stringValue": str(uuid4())}},
                    {"name": "token", "value": {"stringValue": "TEST-" + uuid4().hex}},
                ],
            )
        client.execute_statement(
            **config, transactionId=transaction, sql="SET LOCAL ROLE verimed_api"
        )
        client.execute_statement(
            **config,
            transactionId=transaction,
            sql="SELECT set_config('app.tenant_id', :tenant, true)",
            parameters=[{"name": "tenant", "value": {"stringValue": tenant_a}}],
        )
        result = client.execute_statement(
            **config,
            transactionId=transaction,
            sql="SELECT count(*) FROM patients WHERE tenant_id = CAST(:tenant AS uuid)",
            parameters=[{"name": "tenant", "value": {"stringValue": tenant_b}}],
        )
        if result["records"][0][0]["longValue"] != 0:
            raise RuntimeError("Tenant A could read tenant B")
        result = client.execute_statement(
            **config, transactionId=transaction, sql="SELECT count(*) FROM patients"
        )
        if result["records"][0][0]["longValue"] != 1:
            raise RuntimeError("RLS did not isolate the transaction to tenant A")
    finally:
        client.rollback_transaction(
            resourceArn=config["resourceArn"],
            secretArn=config["secretArn"],
            transactionId=transaction,
        )
    print("Live PostgreSQL negative tenant isolation passed. Test rows rolled back.")
    readonly = dict(config, secretArn=os.environ["DATABASE_RUNTIME_SECRET_ARN"])
    transaction = client.begin_transaction(**readonly)["transactionId"]
    try:
        try:
            client.execute_statement(
                **readonly, transactionId=transaction, sql="DELETE FROM patients"
            )
        except ClientError as error:
            if (
                error.response["Error"]["Code"] != "DatabaseErrorException"
                or "permission denied" not in error.response["Error"]["Message"]
            ):
                raise
        else:
            raise RuntimeError("The API database login was able to write")
    finally:
        client.rollback_transaction(
            resourceArn=readonly["resourceArn"],
            secretArn=readonly["secretArn"],
            transactionId=transaction,
        )
    print("Live API database write denial passed.")


if __name__ == "__main__":
    main()
