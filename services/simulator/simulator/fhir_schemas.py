"""Strict job contracts; no clinical records or fabricated provider results."""

import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Cohort(StrictModel):
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    resource_count: int = Field(ge=1)
    byte_count: int = Field(ge=1, le=536870912)
    patient_ids: list[Annotated[str, Field(pattern=r"^[A-Za-z0-9.-]{1,64}$")]] = Field(
        min_length=1, max_length=50
    )


class ImportConfig(StrictModel):
    tenant_id: UUID
    tenant_slug: str = Field(pattern=r"^[a-z][a-z0-9-]{0,31}$")
    region: str = Field(pattern=r"^[a-z]{2}-[a-z]+-[0-9]+$")
    datastore_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    datastore_arn: str
    endpoint: str
    bucket: str = Field(pattern=r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
    key_arn: str = Field(
        pattern=r"^arn:aws:kms:[a-z0-9-]+:[0-9]{12}:key/[A-Za-z0-9-]+$"
    )
    role_arn: str = Field(pattern=r"^arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]+$")
    expires_at: AwareDatetime
    estimated_usd: float = Field(gt=0)
    synthetic: Literal[True] = True

    @model_validator(mode="after")
    def authorized_window(self) -> "ImportConfig":
        if not self.synthetic:
            raise ValueError("An active synthetic-data test window is required")
        expected = (
            r"arn:aws:healthlake:"
            + re.escape(self.region)
            + r":[0-9]{12}:datastore/fhir/"
            + self.datastore_id
        )
        if not re.fullmatch(expected, self.datastore_arn):
            raise ValueError("FHIR datastore identity mismatch")
        endpoint = (
            "https://healthlake."
            + self.region
            + ".amazonaws.com/datastore/"
            + self.datastore_id
            + "/r4"
        )
        if self.endpoint.rstrip("/") != endpoint:
            raise ValueError("FHIR endpoint does not match the configured datastore")
        return self


class ImportState(StrictModel):
    config: ImportConfig
    cohort: Cohort
    job_id: str
    source_key: str
    source_version_id: str
    submitted_at: AwareDatetime

    @field_validator("source_version_id")
    @classmethod
    def pinned_version(cls, value: str) -> str:
        if not value or value == "null":
            raise ValueError("A versioned FHIR source is required")
        return value
