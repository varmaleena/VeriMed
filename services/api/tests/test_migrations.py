"""Migration doubles are limited to this unit module; live tests use Aurora."""

import json
from typing import Any

import pytest
from app.migration_source import REVISIONS, checksum
from app.migrations import MigrationFailure, apply


class Database:
    def __init__(self, *, fail: bool = False, corrupt: bool = False) -> None:
        self.calls: list[str] = []
        self.rolled_back = False
        self.committed = False
        self.fail = fail
        self.corrupt = corrupt

    def begin_transaction(self, **kwargs: Any) -> dict[str, str]:
        return {"transactionId": "unit"}

    def execute_statement(self, **kwargs: Any) -> dict[str, str]:
        sql = kwargs["sql"]
        self.calls.append(sql)
        if sql == "SELECT version_num FROM platform_meta.alembic_version":
            return {"formattedRecords": json.dumps([{"version_num": REVISIONS[-1]}])}
        if sql == "SELECT revision,sha256 FROM platform_meta.applied_revisions":
            return {
                "formattedRecords": json.dumps(
                    [
                        {
                            "revision": revision,
                            "sha256": "0" * 64 if self.corrupt else checksum(revision),
                        }
                        for revision in REVISIONS
                    ]
                )
            }
        if self.fail:
            raise RuntimeError("unit-sensitive-provider-detail")
        return {"formattedRecords": "[]"}

    def commit_transaction(self, **kwargs: Any) -> None:
        self.committed = True

    def rollback_transaction(self, **kwargs: Any) -> None:
        self.rolled_back = True


CONNECTION = {
    "resourceArn": "unit-cluster",
    "secretArn": "unit-secret",
    "database": "verimed",
}


def test_current_checksum_verified_schema_does_not_reapply_revisions() -> None:
    client = Database()
    assert apply(client, CONNECTION) == []
    assert client.committed and not client.rolled_back
    assert not any("CREATE TABLE public." in sql for sql in client.calls)


def test_corrupt_history_rolls_back_without_applying_or_leaking_details() -> None:
    client = Database(corrupt=True)
    with pytest.raises(MigrationFailure) as caught:
        apply(client, CONNECTION)
    assert client.rolled_back and not client.committed
    assert not any("CREATE TABLE public." in sql for sql in client.calls)
    assert "unit-sensitive-provider-detail" not in str(caught.value)


def test_provider_failure_rolls_back_and_redacts_exception() -> None:
    client = Database(fail=True)
    with pytest.raises(MigrationFailure) as caught:
        apply(client, CONNECTION)
    assert client.rolled_back and not client.committed
    assert "unit-sensitive-provider-detail" not in str(caught.value)


def test_first_install_applies_revisions_in_one_transaction() -> None:
    class EmptyDatabase(Database):
        def execute_statement(self, **kwargs: Any) -> dict[str, str]:
            self.calls.append(kwargs["sql"])
            return {"formattedRecords": "[]"}

    client = EmptyDatabase()
    assert apply(client, CONNECTION) == list(REVISIONS)
    assert client.committed and not client.rolled_back
    assert (
        sum(
            sql.startswith("INSERT INTO platform_meta.applied_revisions")
            for sql in client.calls
        )
        == 3
    )


def test_mid_revision_error_rolls_back_entire_install() -> None:
    class FailingDatabase(Database):
        def execute_statement(self, **kwargs: Any) -> dict[str, str]:
            self.calls.append(kwargs["sql"])
            if kwargs["sql"].startswith("CREATE TABLE public.claims"):
                raise RuntimeError("unit-sensitive-claim-body")
            return {"formattedRecords": "[]"}

    client = FailingDatabase()
    with pytest.raises(MigrationFailure) as caught:
        apply(client, CONNECTION)
    assert client.rolled_back and not client.committed
    assert "unit-sensitive-claim-body" not in str(caught.value)
