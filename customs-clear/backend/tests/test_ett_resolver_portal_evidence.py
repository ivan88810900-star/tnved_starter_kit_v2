"""Typed resolver and HTTP payloads preserve distinct native/portal evidence.

The candidate container/rate is synthetic; portal literals come from the small
retained138 fixture. These tests do not establish source binding or legal effect.
"""
from copy import deepcopy
from datetime import date
from decimal import Decimal
import json

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient
from pydantic import TypeAdapter
import pytest

from app.api import ett_candidates as api
from app.services.ett_manifest import (
    ETTEvidence, ETTLegalPortalMetadataEvidence, manifest_sha256, validate_manifest,
)
from app.services.ett_resolver import ETTResolution, resolve_rate
from tests.test_ett_manifest_portal_evidence import manifest_with_portal, portal_reference


@pytest.fixture
def mixed_manifest():
    data = manifest_with_portal()
    for collection in ("codes", "rate_rules"):
        evidence = data[collection][0]["effective_evidence"]
        evidence.append(portal_reference("entry_into_force_date_metadata"))
        # Duplicate source occurrences should retain one copy of each distinct
        # projection, without treating different fields as an identical source.
        evidence.extend(deepcopy(evidence))
    return validate_manifest(data)


def expected_effective(manifest):
    unique = {item.model_dump_json(): item.model_dump(mode="json")
              for item in manifest.rate_rules[0].effective_evidence}
    return [unique[key] for key in sorted(unique)]


def test_typed_dataclass_roundtrip_accepts_native_and_portal_sources_without_inventing_pdf_coordinates(mixed_manifest):
    result = resolve_rate(mixed_manifest, "0101210000", date(2026, 9, 8), "RU")
    wire = jsonable_encoder(result, custom_encoder={Decimal: str})
    restored = TypeAdapter(ETTResolution).validate_json(json.dumps(wire))
    assert restored == result
    assert len(restored.effective_evidence) == 3
    assert sum(type(item) is ETTEvidence for item in restored.effective_evidence) == 1
    assert sum(type(item) is ETTLegalPortalMetadataEvidence for item in restored.effective_evidence) == 2
    assert all(type(item) is ETTEvidence for item in restored.evidence)
    assert wire["effective_evidence"] == expected_effective(mixed_manifest)
    for item in wire["effective_evidence"]:
        if "kind" in item:
            assert "page" not in item and "row" not in item
            assert item["kind"] == "legal_portal_metadata_v1"
            assert item["value"]["raw_text_sha256"]
            assert item["pdf_binding"]["locator"].startswith("html:a:")
        else:
            assert item["page"] == 1 and "row" in item
    assert restored.mode == "candidate_preview"


def test_real_preview_route_serializes_both_evidence_types_and_keeps_typed_wire_contract(mixed_manifest, monkeypatch):
    app = FastAPI()
    app.include_router(api.router, prefix="/ett")
    app.dependency_overrides[api.require_authenticated_user] = lambda: {"role": "admin"}
    marker = object()
    app.dependency_overrides[api.candidate_db] = lambda: marker
    digest = manifest_sha256(mixed_manifest)
    loads = []

    def load(db, requested):
        assert db is marker and requested == digest
        loads.append(requested)
        return mixed_manifest

    monkeypatch.setattr(api, "_load", load)
    with TestClient(app) as client:
        response = client.post(f"/ett/{digest}/preview", json={
            "code": "0101210000", "as_of": "2026-09-08", "destination": "RU", "facts": {},
        })
    assert response.status_code == 200, response.text
    assert loads == [digest]
    wire = response.json()
    assert wire["status"] == "resolved"
    assert wire["mode"] == "candidate_preview"
    assert wire["duty"]["ad_valorem_percent"] == "5"
    assert wire["effective_evidence"] == expected_effective(mixed_manifest)
    typed = TypeAdapter(ETTResolution).validate_python(wire)
    assert typed.manifest_sha256 == digest
    assert len(typed.effective_evidence) == 3
    assert {item.field for item in typed.effective_evidence if isinstance(item, ETTLegalPortalMetadataEvidence)} == {
        "publication_date", "entry_into_force_date_metadata"}


def test_native_only_resolution_keeps_the_original_wire_shape(mixed_manifest):
    data = mixed_manifest.model_dump(mode="json")
    for collection in ("codes", "rate_rules"):
        data[collection][0]["effective_evidence"] = [
            item for item in data[collection][0]["effective_evidence"] if "kind" not in item]
    manifest = validate_manifest(data)
    result = resolve_rate(manifest, "0101210000", date(2026, 9, 8), "RU")
    wire = jsonable_encoder(result, custom_encoder={Decimal: str})
    assert len(wire["effective_evidence"]) == 1
    assert set(wire["effective_evidence"][0]) == {
        "artifact_id", "artifact_sha256", "page", "row", "raw_text", "raw_text_sha256"}
    assert all(type(item) is ETTEvidence for item in TypeAdapter(ETTResolution).validate_python(wire).effective_evidence)
