from typing import Any
from uuid import uuid4

import pytest
from app import main
from fastapi.testclient import TestClient


def test_anonymous_request_is_denied_before_database_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_client(service: str) -> Any:
        pytest.fail("anonymous access reached AWS")

    monkeypatch.setattr(main, "aws_client", unexpected_client)
    with TestClient(main.app) as client:
        response = client.get("/encounters")
    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"


def test_denied_role_cannot_reach_database(monkeypatch: pytest.MonkeyPatch) -> None:
    user = main.Principal(sub="test", tenant_id=uuid4(), roles=["UNKNOWN"])

    class Denied:
        def is_authorized(self, **kwargs: Any) -> dict[str, Any]:
            return {"decision": "DENY"}

    monkeypatch.setenv("POLICY_STORE_ID", "test-store")
    monkeypatch.setattr(main, "aws_client", lambda service: Denied())
    main.app.dependency_overrides[main.principal] = lambda: user
    try:
        with TestClient(main.app) as client:
            response = client.get("/encounters")
        assert response.status_code == 403
    finally:
        main.app.dependency_overrides.clear()


def test_failed_query_rolls_back_tenant_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statements: list[str] = []
    rolled_back: list[str] = []

    class Database:
        def begin_transaction(self, **kwargs: Any) -> dict[str, str]:
            return {"transactionId": "tx"}

        def execute_statement(self, **kwargs: Any) -> dict[str, Any]:
            statements.append(kwargs["sql"])
            if "FROM encounters" in kwargs["sql"]:
                raise RuntimeError("query unavailable")
            return {}

        def rollback_transaction(self, **kwargs: Any) -> None:
            assert "database" not in kwargs
            rolled_back.append(kwargs["transactionId"])

    for name in ("DATABASE_CLUSTER_ARN", "DATABASE_SECRET_ARN"):
        monkeypatch.setenv(name, "test")
    monkeypatch.setattr(main, "aws_client", lambda service: Database())
    with pytest.raises(RuntimeError, match="query unavailable"):
        main.list_encounters(
            main.Principal(sub="test", tenant_id=uuid4(), roles=[]), None, 50
        )
    assert statements[0] == "SET LOCAL ROLE verimed_api"
    assert "set_config('app.tenant_id'" in statements[1]
    assert rolled_back == ["tx"]


def test_read_commits_with_data_api_transaction_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    committed: list[str] = []

    class Database:
        def begin_transaction(self, **kwargs: Any) -> dict[str, str]:
            return {"transactionId": "read-tx"}

        def execute_statement(self, **kwargs: Any) -> dict[str, str]:
            return {"formattedRecords": "[]"}

        def commit_transaction(self, **kwargs: Any) -> None:
            assert set(kwargs) == {"resourceArn", "secretArn", "transactionId"}
            committed.append(kwargs["transactionId"])

    for name in ("DATABASE_CLUSTER_ARN", "DATABASE_SECRET_ARN"):
        monkeypatch.setenv(name, "test")
    monkeypatch.setattr(main, "aws_client", lambda service: Database())
    result = main.list_encounters(
        main.Principal(sub="test", tenant_id=uuid4(), roles=[]), None, 50
    )
    assert result.items == []
    assert result.has_more is False
    assert committed == ["read-tx"]
