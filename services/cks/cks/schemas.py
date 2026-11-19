"""Strict, source-cited reference lookup contracts; no clinical verdicts."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

Status = Literal["RESOLVED", "REVIEW_REQUIRED", "NOT_FOUND", "UNVERIFIED"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DrugQuery(StrictModel):
    drug_text: str = Field(
        min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9 µμ%().,+/ -]*$"
    )

    @field_validator("drug_text")
    @classmethod
    def drug_only(cls, value: str) -> str:
        import re

        cleaned = " ".join(value.split())
        if re.search(
            r"\b(patient|mrn|dob|ssn|address|phone|email)\b", cleaned, re.IGNORECASE
        ):
            raise ValueError("Only de-identified drug names and strengths are accepted")
        return cleaned


class RxCuiQuery(StrictModel):
    rxcui: str = Field(pattern=r"^[1-9][0-9]{0,11}$")


class LabelQuery(RxCuiQuery):
    sections: list[
        Literal[
            "boxed_warning",
            "contraindications",
            "dosage_and_administration",
            "warnings_and_cautions",
            "warnings",
            "drug_interactions",
            "indications_and_usage",
        ]
    ] = Field(min_length=1, max_length=7)


class Source(StrictModel):
    provider: Literal["RXNORM", "RXCLASS", "OPENFDA"]
    url: str
    retrieved_at: AwareDatetime
    response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DrugConcept(StrictModel):
    rxcui: str = Field(pattern=r"^[1-9][0-9]{0,11}$")
    name: str = Field(min_length=1, max_length=1000)
    term_type: str = Field(min_length=1, max_length=20)


class NormalizationResult(StrictModel):
    status: Status
    reason: str
    rxcui: str | None = None
    candidates: list[DrugConcept] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)


class ClassMembership(StrictModel):
    class_id: str = Field(min_length=1, max_length=100)
    class_name: str = Field(min_length=1, max_length=1000)
    class_type: str = Field(min_length=1, max_length=50)
    relationship: str | None = Field(default=None, min_length=1, max_length=100)
    relationship_source: str = Field(min_length=1, max_length=100)
    member_rxcui: str = Field(pattern=r"^[1-9][0-9]{0,11}$")
    member_term_type: str = Field(min_length=1, max_length=20)


class ClassesResult(StrictModel):
    status: Status
    reason: str
    items: list[ClassMembership] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)


class LabelDocument(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    set_id: str = Field(min_length=1, max_length=100)
    version: str = Field(pattern=r"^[0-9]+$")
    effective_time: str = Field(pattern=r"^[0-9]{8}$")
    sections: dict[str, list[str]]
    missing_sections: list[str] = Field(default_factory=list)


class LabelsResult(StrictModel):
    status: Status
    reason: str
    items: list[LabelDocument] = Field(default_factory=list)
    total: int | None = Field(default=None, ge=0)
    truncated: bool = False
    sources: list[Source] = Field(default_factory=list)


class CksContracts(StrictModel):
    normalize_request: DrugQuery
    normalize_response: NormalizationResult
    classes_request: RxCuiQuery
    classes_response: ClassesResult
    labels_request: LabelQuery
    labels_response: LabelsResult
