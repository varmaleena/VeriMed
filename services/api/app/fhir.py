"""Read synthetic patient demographics from the cell's signed FHIR endpoint."""

import base64
import hashlib
import json
import os
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

import boto3  # type: ignore[import-untyped]
from botocore.auth import SigV4Auth  # type: ignore[import-untyped]
from botocore.awsrequest import AWSRequest  # type: ignore[import-untyped]
from pydantic import BaseModel


class PatientSummary(BaseModel):
    id: str
    display_token: str
    birth_year: int | None
    sex: str | None


class PatientPage(BaseModel):
    items: list[PatientSummary]
    total: int | None
    next_cursor: str | None
    source: str = "HealthLake Synthea preload"
    expires_at: str


def read_patients(cursor: str | None = None) -> PatientPage:
    base = os.environ["FHIR_ENDPOINT"].rstrip("/") + "/"
    expected = urlsplit(base + "Patient")
    if cursor:
        url = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        parsed = urlsplit(url)
        if (parsed.scheme, parsed.netloc, parsed.path) != (
            expected.scheme,
            expected.netloc,
            expected.path,
        ):
            raise ValueError(
                "The FHIR cursor does not belong to this cell's Patient endpoint"
            )
    else:
        url = base + "Patient?" + urlencode({"_count": 20})
    # HealthLake pagination links can contain reserved characters in page tokens.
    # Encode once before signing so the HTTP request and SigV4 canonical query agree.
    parsed = urlsplit(url)
    url = urlunsplit(
        parsed._replace(
            query=urlencode(
                parse_qsl(parsed.query, keep_blank_values=True), quote_via=quote
            )
        )
    )
    session = boto3.Session()
    credentials = session.get_credentials()
    if credentials is None:
        raise RuntimeError("FHIR workload credentials are unavailable")
    request = AWSRequest(
        method="GET", url=url, headers={"Accept": "application/fhir+json"}
    )
    SigV4Auth(
        credentials.get_frozen_credentials(),
        "healthlake",
        os.environ.get("AWS_REGION", "us-east-1"),
    ).add_auth(request)
    with urlopen(
        Request(url, headers=dict(request.headers.items())), timeout=20
    ) as response:
        bundle: dict[str, Any] = json.load(response)
    if bundle.get("resourceType") != "Bundle":
        raise ValueError("The FHIR server did not return a search bundle")
    items = []
    for entry in bundle.get("entry", []):
        patient = entry["resource"]
        if patient.get("resourceType") != "Patient":
            continue
        identifier = patient["id"]
        digest = (
            hashlib.sha256(f"{os.environ['TENANT_ID']}:{identifier}".encode())
            .hexdigest()[:10]
            .upper()
        )
        birth_date = patient.get("birthDate", "")
        birth_year = (
            int(birth_date[:4])
            if len(birth_date) >= 4 and birth_date[:4].isdigit()
            else None
        )
        items.append(
            PatientSummary(
                id=identifier,
                display_token=f"PT-{digest}",
                birth_year=birth_year,
                sex=patient.get("gender"),
            )
        )
    next_cursor = None
    for link in bundle.get("link", []):
        if link.get("relation") == "next":
            next_cursor = (
                base64.urlsafe_b64encode(link["url"].encode()).decode().rstrip("=")
            )
    return PatientPage(
        items=items,
        total=bundle.get("total"),
        next_cursor=next_cursor,
        expires_at=os.environ["FHIR_EXPIRES_AT"],
    )
