"""Real Aurora schema and rollback-only isolation/constraint checks; no clinical fixtures persist."""

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import boto3  # type: ignore[import-untyped]
from app.database import begin_transaction
from app.schema import NEW_TABLES
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]


def main() -> None:
    client = boto3.client(
        "rds-data",
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        config=Config(connect_timeout=5, read_timeout=60, retries={"max_attempts": 1}),
    )
    connection = {
        "resourceArn": os.environ["DATABASE_CLUSTER_ARN"],
        "secretArn": os.environ["DATABASE_SECRET_ARN"],
        "database": "verimed",
    }

    def execute(sql: str, tx: str | None = None, **values: str) -> Any:
        return client.execute_statement(
            **connection,
            **({"transactionId": tx} if tx else {}),
            sql=sql,
            parameters=[
                {"name": name, "value": {"stringValue": value}}
                for name, value in values.items()
            ],
            formatRecordsAs="JSON",
        )

    def rows(sql: str, tx: str | None = None, **values: str) -> list[dict[str, Any]]:
        return list(json.loads(execute(sql, tx, **values)["formattedRecords"]))

    catalog = rows("""SELECT c.relname AS name,c.relrowsecurity AS rls,c.relforcerowsecurity AS forced,
EXISTS(SELECT 1 FROM pg_attribute a WHERE a.attrelid=c.oid AND a.attname='tenant_id' AND a.attnotnull) AS tenant_not_null
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public' AND c.relkind='r' ORDER BY c.relname""")
    expected = {table.name for table in NEW_TABLES} | {
        "patients",
        "encounters",
        "ledger_events",
        "ledger_heads",
    }
    actual = {table["name"] for table in catalog}
    if actual != expected or not all(
        t["rls"] and t["forced"] and t["tenant_not_null"] for t in catalog
    ):
        raise RuntimeError("Public clinical tables are missing forced tenant isolation")
    constraints = rows("""SELECT pg_get_constraintdef(c.oid) AS definition FROM pg_constraint c
JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname='public' AND c.contype='f'""")
    if not all(
        c["definition"].startswith("FOREIGN KEY (tenant_id,") for c in constraints
    ):
        raise RuntimeError("A clinical foreign key is not tenant-composite")
    role = rows(
        "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname='verimed_api'"
    )[0]
    if role["rolsuper"] or role["rolbypassrls"]:
        raise RuntimeError("Runtime reader has unsafe database privileges")
    head = rows("SELECT version_num FROM platform_meta.alembic_version")[0][
        "version_num"
    ]
    if head != "003_platform":
        raise RuntimeError("Unexpected platform revision")

    checks: list[str] = []

    def seeded(tx: str) -> dict[str, str]:
        ids = {
            name: str(uuid4())
            for name in (
                "a",
                "b",
                "pa",
                "pb",
                "ua",
                "ub",
                "ea",
                "eb",
                "na",
                "nb",
                "audit",
            )
        }
        body = "Integration " + uuid4().hex
        ids["body"] = body
        ids["policy"] = "integration-" + uuid4().hex
        for suffix in ("a", "b"):
            tenant = ids[suffix]
            execute(
                "SELECT set_config('app.tenant_id', :tenant, true)", tx, tenant=tenant
            )
            execute(
                "INSERT INTO users(tenant_id,id,cognito_sub) VALUES (CAST(:t AS uuid),CAST(:id AS uuid),:sub)",
                tx,
                t=tenant,
                id=ids["u" + suffix],
                sub="integration-" + uuid4().hex,
            )
            execute(
                "INSERT INTO patients(tenant_id,id,fhir_patient_id,display_token,source) VALUES (CAST(:t AS uuid),CAST(:id AS uuid),:fhir,:token,'integration_only')",
                tx,
                t=tenant,
                id=ids["p" + suffix],
                fhir=uuid4().hex,
                token="INTEGRATION-" + uuid4().hex[:12],
            )
            execute(
                "INSERT INTO encounters(tenant_id,id,patient_id,scribe_adapter,status,started_at,source) VALUES (CAST(:t AS uuid),CAST(:id AS uuid),CAST(:patient AS uuid),'healthscribe','INGESTING',now(),'integration_only')",
                tx,
                t=tenant,
                id=ids["e" + suffix],
                patient=ids["p" + suffix],
            )
            execute(
                "INSERT INTO note_versions(tenant_id,id,encounter_id,version,kind,body_text,sha256) VALUES (CAST(:t AS uuid),CAST(:id AS uuid),CAST(:enc AS uuid),1,'ai_draft',:body,:hash)",
                tx,
                t=tenant,
                id=ids["n" + suffix],
                enc=ids["e" + suffix],
                body=body,
                hash=hashlib.sha256(body.encode()).hexdigest(),
            )
        execute(
            "SELECT set_config('app.tenant_id', :tenant, true)", tx, tenant=ids["a"]
        )
        execute(
            "INSERT INTO policy_packs(tenant_id,version,yaml,json_schema_version) VALUES (CAST(:t AS uuid),:version,'{}','1')",
            tx,
            t=ids["a"],
            version=ids["policy"],
        )
        execute(
            "INSERT INTO audits(tenant_id,id,encounter_id,note_version_id,policy_version) VALUES (CAST(:t AS uuid),CAST(:id AS uuid),CAST(:enc AS uuid),CAST(:note AS uuid),:policy)",
            tx,
            t=ids["a"],
            id=ids["audit"],
            enc=ids["ea"],
            note=ids["na"],
            policy=ids["policy"],
        )
        # These permission grants exist only inside this rollback-only transaction.
        execute(
            "GRANT INSERT,UPDATE ON users,patients,encounters,note_versions,claims TO verimed_api",
            tx,
        )
        execute("SET LOCAL ROLE verimed_api", tx)
        return ids

    for case in (
        "read_isolation",
        "write_isolation",
        "cross_tenant_fk",
        "claim_span",
        "note_immutable",
        "note_hash",
    ):
        tx = begin_transaction(client, connection)
        finish = {
            "resourceArn": connection["resourceArn"],
            "secretArn": connection["secretArn"],
            "transactionId": tx,
        }
        try:
            ids = seeded(tx)
            if case == "read_isolation":
                for table in catalog:
                    count = rows(
                        "SELECT count(*) AS count FROM public."
                        + table["name"]
                        + " WHERE tenant_id=CAST(:tenant AS uuid)",
                        tx,
                        tenant=ids["b"],
                    )[0]["count"]
                    if count:
                        raise RuntimeError("Cross-tenant clinical read was possible")
                if rows("SELECT count(*) AS count FROM patients", tx)[0]["count"] != 1:
                    raise RuntimeError("Own-tenant patient row was not visible")
                checks.append(case)
                continue
            expected_message = ""
            try:
                if case == "write_isolation":
                    expected_message = "row-level security"
                    execute(
                        "INSERT INTO users(tenant_id,cognito_sub) VALUES (CAST(:t AS uuid),:sub)",
                        tx,
                        t=ids["b"],
                        sub=uuid4().hex,
                    )
                elif case == "cross_tenant_fk":
                    expected_message = "foreign key constraint"
                    execute(
                        "INSERT INTO encounters(tenant_id,patient_id,scribe_adapter,status,started_at,source) VALUES (CAST(:t AS uuid),CAST(:p AS uuid),'healthscribe','INGESTING',now(),'integration_only')",
                        tx,
                        t=ids["a"],
                        p=ids["pb"],
                    )
                elif case == "claim_span":
                    expected_message = "claim span does not match"
                    execute(
                        "INSERT INTO claims(tenant_id,audit_id,note_version_id,type,section,char_start,char_end,text) VALUES (CAST(:t AS uuid),CAST(:audit AS uuid),CAST(:note AS uuid),'history','S',0,5,'wrong')",
                        tx,
                        t=ids["a"],
                        audit=ids["audit"],
                        note=ids["na"],
                    )
                elif case == "note_immutable":
                    expected_message = "append-only"
                    execute(
                        "UPDATE note_versions SET body_text=body_text WHERE id=CAST(:note AS uuid)",
                        tx,
                        note=ids["na"],
                    )
                else:
                    expected_message = "check constraint"
                    execute(
                        "INSERT INTO note_versions(tenant_id,encounter_id,version,kind,body_text,sha256) VALUES (CAST(:t AS uuid),CAST(:enc AS uuid),2,'ai_draft','integration_only',:hash)",
                        tx,
                        t=ids["a"],
                        enc=ids["ea"],
                        hash="0" * 64,
                    )
            except ClientError as error:
                if expected_message not in error.response["Error"]["Message"].lower():
                    raise RuntimeError(
                        "Unexpected database rejection during " + case
                    ) from None
                checks.append(case)
            else:
                raise RuntimeError(
                    "Database accepted an unsafe operation during " + case
                )
        finally:
            client.rollback_transaction(**finish)
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "revision": head,
        "clinical_table_count": len(catalog),
        "tenant_composite_foreign_keys": len(constraints),
        "forced_rls_all_tables": True,
        "runtime_superuser_or_bypassrls": False,
        "rollback_only_checks": checks,
        "diagnostic_rows_committed": False,
        "status": "PASSED",
    }
    Path("docs/platform-schema-verification.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
    client.close()


if __name__ == "__main__":
    main()
