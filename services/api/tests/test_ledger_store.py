import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.ledger import DigestSigner, SignedEntry
from app.ledger_store import LedgerStore


class UnavailableSigner:
    key_id = "unit-key"

    def sign(self, digest: bytes) -> bytes:
        raise TimeoutError("unit signing outage")

    def verify(self, digest: bytes, signature: bytes) -> bool:
        return True


class Database:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.commits = 0
        self.rollbacks = 0
        self.existing: SignedEntry | None = None

    def begin_transaction(self, **kwargs: Any) -> dict[str, str]:
        return {"transactionId": "unit-tx"}

    def execute_statement(self, **kwargs: Any) -> dict[str, Any]:
        self.statements.append(kwargs["sql"])
        rows = []
        if self.existing and "WHERE id =" in kwargs["sql"]:
            rows = [{"entry": self.existing.model_dump_json()}]
        return {"formattedRecords": json.dumps(rows)}

    def commit_transaction(self, **kwargs: Any) -> None:
        assert "database" not in kwargs
        self.commits += 1

    def rollback_transaction(self, **kwargs: Any) -> None:
        assert "database" not in kwargs
        self.rollbacks += 1


def store(db: Database, signer: DigestSigner | None = None) -> LedgerStore:
    return LedgerStore(
        db,
        {
            "resourceArn": "unit-cluster",
            "secretArn": "unit-secret",
            "database": "verimed",
        },
        signer or UnavailableSigner(),
        writer=True,
    )


def test_signing_failure_rolls_back_without_inserting_or_committing() -> None:
    db = Database()
    with pytest.raises(TimeoutError):
        store(db).append(uuid4(), uuid4(), "unit.probe", {"purpose": "unit-only"})
    assert db.rollbacks == 1 and db.commits == 0
    assert not any("INSERT INTO public.ledger_events" in sql for sql in db.statements)
    assert db.statements[0] == "SET LOCAL ROLE verimed_ledger_append"
    lock = next(
        i for i, sql in enumerate(db.statements) if "pg_advisory_xact_lock" in sql
    )
    head = next(i for i, sql in enumerate(db.statements) if "SELECT seq, hash" in sql)
    assert lock < head


def test_idempotent_retry_returns_original_entry_and_conflict_rolls_back() -> None:
    from datetime import UTC, datetime

    from app.ledger import GENESIS, Head, LedgerEvent, sign_event
    from app.ledger_store import IdempotencyConflict

    class Signer(UnavailableSigner):
        def sign(self, digest: bytes) -> bytes:
            return b"unit-signature"

    signer = Signer()
    tenant = uuid4()
    event = LedgerEvent(
        tenant_id=tenant,
        seq=1,
        created_at=datetime.now(UTC),
        type="unit.probe",
        payload={"value": 1},
    )
    db = Database()
    db.existing = sign_event(event, Head(seq=0, hash=GENESIS), signer)
    assert (
        store(db, signer).append(tenant, uuid4(), "unit.probe", {"value": 1})
        == db.existing
    )
    assert not any("INSERT INTO" in sql for sql in db.statements)
    assert db.commits == 1
    with pytest.raises(IdempotencyConflict):
        store(db, signer).append(tenant, uuid4(), "unit.probe", {"value": 2})
    assert db.rollbacks == 1


def test_read_uses_repeatable_read_and_transaction_local_tenant() -> None:
    db = Database()
    reader = LedgerStore(
        db,
        {"resourceArn": "unit-cluster", "secretArn": "unit-reader"},
        UnavailableSigner(),
    )
    entries, head = reader.read(UUID(int=1))
    assert entries == [] and head.seq == 0
    assert (
        db.statements[0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
    )
    assert db.statements[1] == "SET LOCAL ROLE verimed_api"
    assert any(
        "set_config('app.tenant_id', :tenant, true)" in sql for sql in db.statements
    )
    assert db.commits == 1


def test_invalid_read_bound_never_reaches_database() -> None:
    db = Database()
    with pytest.raises(ValueError, match="read bound"):
        store(db).read(uuid4(), max_events=10001)
    assert not db.statements


def test_uncertain_commit_keeps_original_failure_and_never_retries_write() -> None:
    class CommitUnavailable(Database):
        def commit_transaction(self, **kwargs: Any) -> None:
            self.commits += 1
            raise TimeoutError("commit response unavailable")

        def rollback_transaction(self, **kwargs: Any) -> None:
            self.rollbacks += 1
            raise RuntimeError("transaction already finished")

    db = CommitUnavailable()
    with (
        pytest.raises(TimeoutError, match="commit response unavailable"),
        store(db).transaction(uuid4()),
    ):
        pass
    assert db.commits == 1 and db.rollbacks == 1


def test_oversized_event_is_rejected_before_database_access() -> None:
    db = Database()
    with pytest.raises(ValueError, match="16 KiB"):
        store(db).append(uuid4(), uuid4(), "unit.probe", {"text": "x" * 16384})
    assert not db.statements
