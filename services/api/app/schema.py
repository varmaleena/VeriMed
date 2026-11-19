"""Canonical Phase 1 cell tables. No runtime records or result fixtures."""

from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.sql.schema import SchemaItem
from sqlalchemy.types import UserDefinedType

metadata = MetaData(
    schema="public",
    naming_convention={
        "pk": "pk_%(table_name)s",
        "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "ix": "ix_%(table_name)s_%(column_0_name)s",
    },
)


class Vector(UserDefinedType[list[float]]):
    cache_ok = True

    def get_col_spec(self, **kw: Any) -> str:
        return "vector(1024)"


def ref(target: str, name: str, *, nullable: bool = False) -> Column[Any]:
    return Column(name, UUID, nullable=nullable)


def fk(target: str, name: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["tenant_id", name], [target + ".tenant_id", target + ".id"]
    )


def enum(column: str, values: str) -> CheckConstraint:
    return CheckConstraint(
        column + " IN (" + ",".join("'" + v + "'" for v in values.split()) + ")"
    )


def entity(name: str, *columns: SchemaItem) -> Table:
    return Table(
        name,
        metadata,
        Column("tenant_id", UUID, primary_key=True),
        Column("id", UUID, primary_key=True, server_default=text("gen_random_uuid()")),
        Column(
            "created_at",
            DateTime(timezone=True),
            nullable=False,
            server_default=text("now()"),
        ),
        *columns,
    )


# Existing migration-owned tables are reference targets, not recreated by the new revision.
patients = Table(
    "patients",
    metadata,
    Column("tenant_id", UUID, primary_key=True),
    Column("id", UUID, primary_key=True),
)
encounters = Table(
    "encounters",
    metadata,
    Column("tenant_id", UUID, primary_key=True),
    Column("id", UUID, primary_key=True),
)
EXISTING = {"patients", "encounters"}

users = entity(
    "users",
    Column("cognito_sub", String(128), nullable=False),
    Column("email", String(320)),
    Column("department", String(128)),
    Column("status", String(16), nullable=False, server_default="ACTIVE"),
    UniqueConstraint("tenant_id", "cognito_sub"),
    enum("status", "INVITED ACTIVE SUSPENDED"),
)
memberships = entity(
    "memberships",
    ref("users", "user_id"),
    fk("users", "user_id"),
    Column("role", String(32), nullable=False),
    Column("department", String(128)),
    Column("status", String(16), nullable=False, server_default="ACTIVE"),
    UniqueConstraint("tenant_id", "user_id", "role"),
    enum("role", "PHYSICIAN PHARMACIST CODER AUDITOR TENANT_ADMIN"),
    enum("status", "ACTIVE SUSPENDED"),
)
audio_assets = entity(
    "audio_assets",
    ref("encounters", "encounter_id"),
    fk("encounters", "encounter_id"),
    Column("s3_key", Text, nullable=False),
    Column("s3_version_id", Text),
    Column("duration_ms", BigInteger, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("sample_rate", Integer, nullable=False),
    CheckConstraint("duration_ms > 0 AND sample_rate > 0"),
    CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'"),
    UniqueConstraint("tenant_id", "encounter_id", "id"),
)
transcripts = entity(
    "transcripts",
    ref("encounters", "encounter_id"),
    fk("encounters", "encounter_id"),
    ref("audio_assets", "audio_asset_id"),
    ForeignKeyConstraint(
        ["tenant_id", "encounter_id", "audio_asset_id"],
        ["audio_assets.tenant_id", "audio_assets.encounter_id", "audio_assets.id"],
    ),
    Column("engine", String(24), nullable=False),
    Column("provider_job_id", Text, nullable=False),
    Column("raw_s3_key", Text, nullable=False),
    Column("raw_s3_version_id", Text),
    Column("sha256", String(64), nullable=False),
    Column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    enum("engine", "healthscribe transcribe"),
    CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'"),
    UniqueConstraint("tenant_id", "engine", "provider_job_id"),
)
transcript_turns = entity(
    "transcript_turns",
    ref("transcripts", "transcript_id"),
    fk("transcripts", "transcript_id"),
    Column("turn_index", Integer, nullable=False),
    Column("speaker_role", String(16), nullable=False),
    Column("start_ms", BigInteger, nullable=False),
    Column("end_ms", BigInteger, nullable=False),
    Column("text", Text, nullable=False),
    enum("speaker_role", "CLINICIAN PATIENT OTHER UNKNOWN"),
    CheckConstraint("start_ms >= 0 AND end_ms > start_ms AND turn_index >= 0"),
    UniqueConstraint("tenant_id", "transcript_id", "turn_index"),
    UniqueConstraint("tenant_id", "transcript_id", "id"),
)
transcript_words = entity(
    "transcript_words",
    ref("transcripts", "transcript_id"),
    fk("transcripts", "transcript_id"),
    ref("transcript_turns", "turn_id", nullable=True),
    ForeignKeyConstraint(
        ["tenant_id", "transcript_id", "turn_id"],
        [
            "transcript_turns.tenant_id",
            "transcript_turns.transcript_id",
            "transcript_turns.id",
        ],
    ),
    Column("word_index", Integer, nullable=False),
    Column("text", Text, nullable=False),
    Column("start_ms", BigInteger, nullable=False),
    Column("end_ms", BigInteger, nullable=False),
    Column("confidence", Float),
    Column("alternatives", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    CheckConstraint("start_ms >= 0 AND end_ms > start_ms AND word_index >= 0"),
    CheckConstraint("confidence IS NULL OR confidence BETWEEN 0 AND 1"),
    UniqueConstraint("tenant_id", "transcript_id", "word_index"),
)
note_versions = entity(
    "note_versions",
    ref("encounters", "encounter_id"),
    fk("encounters", "encounter_id"),
    Column("version", Integer, nullable=False),
    Column("kind", String(16), nullable=False),
    Column("body_text", Text, nullable=False),
    Column("sections", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("sha256", String(64), nullable=False),
    ref("users", "author_id", nullable=True),
    fk("users", "author_id"),
    enum("kind", "ai_draft human_edit final"),
    CheckConstraint("version > 0 AND length(body_text) > 0"),
    CheckConstraint("sha256 = encode(digest(body_text, 'sha256'), 'hex')"),
    CheckConstraint("kind = 'ai_draft' OR author_id IS NOT NULL"),
    UniqueConstraint("tenant_id", "encounter_id", "version"),
    UniqueConstraint("tenant_id", "encounter_id", "id"),
)
policy_packs = entity(
    "policy_packs",
    Column("version", String(80), nullable=False),
    Column("yaml", Text, nullable=False),
    Column("json_schema_version", String(32), nullable=False),
    Column("active", Boolean, nullable=False, server_default=text("false")),
    ref("users", "created_by", nullable=True),
    fk("users", "created_by"),
    UniqueConstraint("tenant_id", "version"),
)
Index(
    "policy_packs_one_active",
    policy_packs.c.tenant_id,
    unique=True,
    postgresql_where=policy_packs.c.active,
)
audits = entity(
    "audits",
    ref("encounters", "encounter_id"),
    fk("encounters", "encounter_id"),
    ref("note_versions", "note_version_id"),
    ForeignKeyConstraint(
        ["tenant_id", "encounter_id", "note_version_id"],
        ["note_versions.tenant_id", "note_versions.encounter_id", "note_versions.id"],
    ),
    Column("status", String(16), nullable=False, server_default="QUEUED"),
    Column("policy_version", String(80), nullable=False),
    ForeignKeyConstraint(
        ["tenant_id", "policy_version"],
        ["policy_packs.tenant_id", "policy_packs.version"],
    ),
    Column("prompt_hashes", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("model_ids", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("cost_usd", Numeric(18, 8)),
    Column("latency_ms", BigInteger),
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
    Column("failure_reason", String(160)),
    enum("status", "QUEUED RUNNING COMPLETE FAILED"),
    CheckConstraint("cost_usd IS NULL OR cost_usd >= 0"),
    CheckConstraint("latency_ms IS NULL OR latency_ms >= 0"),
    CheckConstraint(
        "finished_at IS NULL OR (started_at IS NOT NULL AND finished_at >= started_at)"
    ),
    UniqueConstraint("tenant_id", "id", "note_version_id"),
)
claims = entity(
    "claims",
    ref("audits", "audit_id"),
    ref("note_versions", "note_version_id"),
    fk("note_versions", "note_version_id"),
    ForeignKeyConstraint(
        ["tenant_id", "audit_id", "note_version_id"],
        ["audits.tenant_id", "audits.id", "audits.note_version_id"],
    ),
    Column("type", String(24), nullable=False),
    Column("section", String(1), nullable=False),
    Column("char_start", Integer, nullable=False),
    Column("char_end", Integer, nullable=False),
    Column("text", Text, nullable=False),
    Column("negated", Boolean, nullable=False, server_default=text("false")),
    Column("structured", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("status", String(16), nullable=False, server_default="UNVERIFIED"),
    enum(
        "type", "medication allergy vital symptom exam diagnosis plan history followup"
    ),
    enum("section", "S O A P"),
    enum("status", "SUPPORTED CONTRADICTED UNSUPPORTED UNVERIFIED"),
    CheckConstraint(
        "char_start >= 0 AND char_end > char_start AND char_end - char_start = char_length(text)"
    ),
    UniqueConstraint("tenant_id", "audit_id", "id"),
)
evidence_links = entity(
    "evidence_links",
    ref("claims", "claim_id"),
    fk("claims", "claim_id"),
    Column("kind", String(24), nullable=False),
    Column("ref", Text, nullable=False),
    Column("start_ms", BigInteger),
    Column("end_ms", BigInteger),
    Column("excerpt_hash", String(64), nullable=False),
    Column("score", Float),
    enum("kind", "audio_span transcript_turn fhir_resource label_section rule"),
    CheckConstraint("excerpt_hash ~ '^[0-9a-f]{64}$'"),
    CheckConstraint(
        "(start_ms IS NULL AND end_ms IS NULL) OR (start_ms IS NOT NULL AND end_ms IS NOT NULL AND start_ms >= 0 AND end_ms > start_ms)"
    ),
    CheckConstraint("score IS NULL OR score BETWEEN 0 AND 1"),
)
flags = entity(
    "flags",
    ref("audits", "audit_id"),
    fk("audits", "audit_id"),
    ref("claims", "claim_id", nullable=True),
    ForeignKeyConstraint(
        ["tenant_id", "audit_id", "claim_id"],
        ["claims.tenant_id", "claims.audit_id", "claims.id"],
    ),
    Column("class", String(64), nullable=False),
    Column("severity", String(8), nullable=False, server_default="AMBER"),
    Column("status", String(16), nullable=False, server_default="OPEN"),
    Column("title", Text, nullable=False),
    Column("explanation", Text, nullable=False),
    Column("suggested_fix", Text),
    Column("confidence", Float),
    Column("deterministic", Boolean, nullable=False, server_default=text("false")),
    Column("challenger_verdict", JSONB),
    enum("severity", "RED AMBER INFO"),
    enum("status", "OPEN ACCEPTED_FIX EDITED DISMISSED ROUTED"),
    CheckConstraint("confidence IS NULL OR confidence BETWEEN 0 AND 1"),
)
flag_resolutions = entity(
    "flag_resolutions",
    ref("flags", "flag_id"),
    fk("flags", "flag_id"),
    ref("users", "user_id"),
    fk("users", "user_id"),
    Column("action", String(16), nullable=False),
    Column("reason", Text, nullable=False),
    Column("stepup_verified", Boolean, nullable=False, server_default=text("false")),
    Column("resolved_at", DateTime(timezone=True), nullable=False),
    enum("action", "ACCEPTED_FIX EDITED DISMISSED ROUTED"),
    CheckConstraint("length(trim(reason)) > 0"),
)
review_tasks = entity(
    "review_tasks",
    ref("flags", "flag_id"),
    fk("flags", "flag_id"),
    Column("queue", String(16), nullable=False),
    ref("users", "assignee", nullable=True),
    fk("users", "assignee"),
    Column("due_at", DateTime(timezone=True), nullable=False),
    Column("status", String(16), nullable=False, server_default="OPEN"),
    Column("resolution_note", Text),
    enum("queue", "PHARMACY CODING"),
    enum("status", "OPEN ASSIGNED RESOLVED"),
)
kb_documents = entity(
    "kb_documents",
    Column("source", Text, nullable=False),
    Column("set_id", Text),
    Column("title", Text, nullable=False),
    Column("version", String(80), nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'"),
    UniqueConstraint("tenant_id", "source", "version"),
)
kb_chunks = entity(
    "kb_chunks",
    ref("kb_documents", "document_id"),
    fk("kb_documents", "document_id"),
    Column("chunk_index", Integer, nullable=False),
    Column("section_code", String(80)),
    Column("text", Text, nullable=False),
    Column(
        "tsv",
        TSVECTOR,
        Computed("to_tsvector('english', coalesce(text, ''))", persisted=True),
    ),
    Column("embedding", Vector),
    Column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    UniqueConstraint("tenant_id", "document_id", "chunk_index"),
    CheckConstraint("chunk_index >= 0"),
)
Index("kb_chunks_tsv", kb_chunks.c.tsv, postgresql_using="gin")
Index(
    "kb_chunks_embedding",
    kb_chunks.c.embedding,
    postgresql_using="hnsw",
    postgresql_ops={"embedding": "vector_cosine_ops"},
)
ledger_anchors = entity(
    "ledger_anchors",
    Column("day", Date, nullable=False),
    Column("merkle_root", String(64), nullable=False),
    Column("s3_key", Text, nullable=False),
    Column("s3_version_id", Text, nullable=False),
    Column("object_lock_until", DateTime(timezone=True), nullable=False),
    CheckConstraint("merkle_root ~ '^[0-9a-f]{64}$'"),
    UniqueConstraint("tenant_id", "day"),
)
eval_datasets = entity(
    "eval_datasets",
    Column("name", String(80), nullable=False),
    Column("version", String(80), nullable=False),
    Column("source", String(32), nullable=False),
    Column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    UniqueConstraint("tenant_id", "name", "version"),
)
eval_cases = entity(
    "eval_cases",
    ref("eval_datasets", "dataset_id"),
    fk("eval_datasets", "dataset_id"),
    ref("encounters", "encounter_id"),
    fk("encounters", "encounter_id"),
    Column("ground_truth", JSONB, nullable=False),
    Column("tags", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
)
eval_runs = entity(
    "eval_runs",
    ref("eval_datasets", "dataset_id"),
    fk("eval_datasets", "dataset_id"),
    Column("git_sha", String(64), nullable=False),
    Column("model_ids", JSONB, nullable=False),
    Column("metrics", JSONB),
    Column("status", String(16), nullable=False, server_default="RUNNING"),
    Column("finished_at", DateTime(timezone=True)),
    enum("status", "RUNNING COMPLETE FAILED"),
)
eval_results = entity(
    "eval_results",
    ref("eval_runs", "run_id"),
    fk("eval_runs", "run_id"),
    ref("eval_cases", "case_id"),
    fk("eval_cases", "case_id"),
    Column("metrics", JSONB, nullable=False),
    Column("predictions", JSONB, nullable=False),
    UniqueConstraint("tenant_id", "run_id", "case_id"),
)
usage_events = entity(
    "usage_events",
    Column("type", String(64), nullable=False),
    Column("quantity", Numeric(20, 8), nullable=False),
    Column("cost_usd", Numeric(18, 8)),
    Column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("event_key", String(160), nullable=False),
    CheckConstraint("quantity >= 0 AND (cost_usd IS NULL OR cost_usd >= 0)"),
    UniqueConstraint("tenant_id", "event_key"),
)
NEW_TABLES = [table for table in metadata.sorted_tables if table.name not in EXISTING]
