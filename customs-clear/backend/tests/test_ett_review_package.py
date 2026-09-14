"""Review packages replay source evidence; no fixture represents approved law."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pymupdf
import pytest

from app.services import ett_acquisition as acquisition
from app.services import ett_review_package as subject
from app.services.ett_artifacts import LocalArtifactStore
from app.services.ett_derived_inventory import canonical_inventory_report_bytes, supported_inventory_parser_identity
from app.services.ett_discovery_audit import canonical_json_bytes
from app.services.ett_index import INDEX_URL, parse_index
from app.services.ett_legal_attachments import parse_legal_attachments
from app.services.ett_manifest import canonical_manifest_bytes, manifest_sha256, validate_manifest
from app.services.ett_pdf_evidence import extract_pdf_evidence
from tests.ett_fixtures import synthetic_manifest_data
from tests.ett_index_fixtures import synthetic_index_html
from tests.test_ett_acquisition import fake_fetch
from tests.test_ett_legal_portal_live import CASES, FIXTURES
from tests.test_ett_metadata_binding import make_reference
from tests.test_ett_notes import _pdf


def sha(body):
    return hashlib.sha256(body).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def quote(body, artifact_id, *, chapter=None):
    report = extract_pdf_evidence(body, artifact_id=artifact_id, chapter=chapter)
    page = report["pages"][0]
    if chapter:
        candidate = next(item for p in report["pages"] for item in p["candidates"] if item["code"] == "0101210000")
        page = report["pages"][candidate["page"] - 1]
        row = next(row for row in page["rows"] if row["row"] == candidate["row"])
    else:
        row = page["rows"][0]
    return {"artifact_id": artifact_id, "artifact_sha256": sha(body), "page": page["page"],
            **{key: row[key] for key in ("row", "raw_text", "raw_text_sha256")}}


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    root = tmp_path_factory.mktemp("review-package-source-fixture")
    store = LocalArtifactStore(root / "objects")
    index = synthetic_index_html()
    discovery = parse_index(index)
    corpus = Path(__file__).resolve().parents[3] / "backend/app/services/source_sync/data"
    chapter = next(corpus.glob("ru.01_*.pdf")).read_bytes()
    notes = _pdf([["1C) Синтетическое примечание: с 01.01.2026 по 31.12.2026 включительно."]])
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((70, 70), "Synthetic unreferenced source fixture only")
        other = pdf.tobytes()
    first_chapter_url = next(ref.url for ref in discovery.chapters if ref.chapter == "01")
    transport, _ = fake_fetch()

    def fetch(url, *, expected_media):
        response = transport(url, expected_media=expected_media)
        if expected_media == "application/pdf":
            body = chapter if url == first_chapter_url else notes if url == discovery.tariff_notes.url else other
            response = replace(response, content=body)
        return response

    captured = acquisition.acquire_official(store, _fetch=fetch)
    receipt, discovery = acquisition.load_acquisition(store, captured["receipt_sha256"])
    data = synthetic_manifest_data()
    data["created_at"] = "2026-09-08T14:00:00Z"
    data["artifacts"] = []
    records = {record.requested_url: record for record in receipt.downloads}

    def artifact(record, artifact_id, role, chapter=None):
        return {"artifact_id": artifact_id, "role": role, "url": record.url,
                "sha256": record.sha256, "size_bytes": record.size_bytes,
                "media_type": record.media_type, "retrieved_at": record.retrieved_at.isoformat(),
                **({"chapter": chapter} if chapter else {})}

    data["artifacts"].append(artifact(receipt.index_end, "index", "index"))
    for ref in (*discovery.chapters, discovery.nomenclature_notes, discovery.tariff_notes):
        identity = f"chapter-{ref.chapter}" if ref.chapter else ref.role
        data["artifacts"].append(artifact(records[ref.url], identity, ref.role, ref.chapter))
    inventory = canonical_inventory_report_bytes(index)
    data["derived_amendment_inventory"] = {
        "derivation_kind": "eec_index_amendment_inventory_v1", "source_artifact_id": "index",
        "source_artifact_sha256": sha(index), "report_sha256": store.put(inventory),
        "report_size_bytes": len(inventory),
        "parser": supported_inventory_parser_identity().model_dump(mode="json"),
    }
    native, dates = quote(chapter, "chapter-01", chapter="01"), quote(notes, "tariff_notes")
    for item in (*data["codes"], *data["rate_rules"]):
        item["evidence"] = [deepcopy(native)]
        item["effective_evidence"] = [deepcopy(dates)]
    validate_manifest(data)
    return data, captured["receipt_sha256"], {p.name: p.read_bytes() for p in (root / "objects").iterdir()}


@pytest.fixture
def case(prepared, tmp_path):
    data, receipt, objects = prepared
    store = LocalArtifactStore(tmp_path / "objects")
    for name, body in objects.items():
        assert store.put(body) + ".blob" == name
    return deepcopy(data), store, receipt


def build(case, *, prior=None, **kwargs):
    data, store, receipt = case
    return subject.build_review_package(data, store, acquisition_receipt_sha256=receipt,
                                        prior_manifest=prior, **kwargs)


def add_unbound_portal(case):
    data, store, _ = case
    raw = (FIXTURES / (CASES[0]["stem"] + ".html")).read_bytes()
    pdf = store.read(next(item["sha256"] for item in data["artifacts"] if item["role"] == "tariff_notes"))
    for artifact_id, body, url, media in [
        ("portal-66", raw, CASES[0]["url"], "text/html"),
        ("act-66", pdf, CASES[0]["pdf"], "application/pdf"),
    ]:
        data["artifacts"].append({"artifact_id": artifact_id, "role": "amendment", "url": url,
                                  "sha256": store.put(body), "size_bytes": len(body), "media_type": media,
                                  "retrieved_at": "2026-09-08T13:00:00Z"})
    for item in (*data["codes"], *data["rate_rules"]):
        reference = make_reference(raw)
        reference["pdf_binding"]["artifact_sha256"] = sha(pdf)
        item["effective_evidence"].append(reference)
    return raw, pdf


def add_selected_supplement(case):
    raw, _ = add_unbound_portal(case)
    data, store, _ = case
    discovery = parse_legal_attachments(raw, CASES[0]["url"])
    attachment_sha = store.put(canonical_json_bytes(asdict(discovery)))
    html_artifact = next(a for a in data["artifacts"] if a["artifact_id"] == "portal-66")
    pdf_artifact = next(a for a in data["artifacts"] if a["artifact_id"] == "act-66")

    def download(artifact):
        return {"status": "captured", "requested_url": artifact["url"], "redirect_chain": [],
                **{key: artifact[key] for key in ("url", "sha256", "size_bytes", "media_type", "retrieved_at")}}

    page = download(html_artifact)
    page.update(expected_identity={"issuing_body": "collegium", "adoption_date": "2022-04-19", "number": "66"},
                attachment_discovery_sha256=attachment_sha)
    pdf = download(pdf_artifact)
    pdf["source_references"] = [{"page_sha256": html_artifact["sha256"], "page_url": html_artifact["url"],
                                  "attachment_discovery_sha256": attachment_sha,
                                  "reference_index": next(i for i, ref in enumerate(discovery.documents) if ref.url == pdf_artifact["url"])}]
    report = {"schema_version": 1, "kind": "ett_observed_legal_document_capture", "documents": [page], "pdfs": [pdf],
              "fixture": "Synthetic acquisition associations only; PDF body is not an original act"}
    return report, store.put(canonical(report))


def test_full_core_capture_and_actual_native_quotes_produce_only_a_review_package(case):
    package = build(case, assumptions=("All rates and periods in this fixture are synthetic.",))
    report = package.as_dict()
    assert package.sha256 == sha(package.canonical_bytes)
    assert canonical(report) == package.canonical_bytes
    assert report["assembly_ready"] is True
    assert report["package_ready"] is True
    assert report["source_evidence"]["source_evidence_verified"] is True
    assert report["source_evidence"]["references_total"] == 4
    assert report["semantic_diff"]["after_manifest_sha256"] == manifest_sha256(case[0])
    for field in ("source_complete", "legal_ready", "can_promote", "production_ready"):
        assert report[field] is False
    assert subject.verify_review_package(package, case[1]).canonical_bytes == package.canonical_bytes
    assert subject.verify_review_package(package.canonical_bytes, case[1]).sha256 == package.sha256


def test_prior_input_must_be_an_explicit_decision_even_for_the_first_package(case):
    data, store, receipt = case
    with pytest.raises(TypeError):
        subject.build_review_package(data, store, acquisition_receipt_sha256=receipt)


def test_identical_inputs_are_deterministic_and_exported_nested_values_are_detached(case):
    first, second = build(case), build(case)
    assert first.canonical_bytes == second.canonical_bytes
    assert first.sha256 == second.sha256
    exported = first.as_dict()
    exported["source_evidence"]["source_evidence_verified"] = False
    exported["semantic_diff"]["codes"]["added"].clear()
    assert first.as_dict() == second.as_dict()
    with pytest.raises((AttributeError, TypeError)):
        first.canonical_bytes = b"{}"
    with pytest.raises((AttributeError, TypeError)):
        first.sha256 = "0" * 64


def test_build_and_verification_do_not_write_source_objects(case, monkeypatch):
    _, store, _ = case
    before = {p.name: p.read_bytes() for p in store._root.iterdir()}

    def no_write(*args, **kwargs):
        raise AssertionError("Review package unexpectedly wrote to the source store")

    monkeypatch.setattr(LocalArtifactStore, "put", no_write)
    package = build(case)
    subject.verify_review_package(package, store)
    assert {p.name: p.read_bytes() for p in store._root.iterdir()} == before


@pytest.mark.parametrize("field", ["assembly_ready", "package_ready", "source_complete", "legal_ready", "can_promote", "production_ready"])
def test_rehashed_forged_boolean_cannot_replace_a_fresh_report(case, field):
    report = build(case).as_dict()
    report[field] = not report[field]
    with pytest.raises(subject.ReviewPackageError):
        subject.verify_review_package(canonical(report), case[1])


@pytest.mark.parametrize("part", ["source_evidence", "tariff_notes", "source_bindings", "semantic_diff"])
def test_rehashed_embedded_green_report_is_not_trusted(case, part):
    report = build(case).as_dict()
    report[part] = {"verified": True, "references_failed": 0, "invented_report": True}
    with pytest.raises(subject.ReviewPackageError):
        subject.verify_review_package(canonical(report), case[1])


@pytest.mark.parametrize("mutation", ["newline", "duplicate", "unknown"])
def test_package_json_requires_exact_canonical_unambiguous_bytes(case, mutation):
    package = build(case)
    if mutation == "newline":
        raw = package.canonical_bytes + b"\n"
    elif mutation == "duplicate":
        raw = b'{"production_ready":false,' + package.canonical_bytes[1:]
    else:
        data = package.as_dict()
        data["caller_verified"] = True
        raw = canonical(data)
    with pytest.raises(subject.ReviewPackageError):
        subject.verify_review_package(raw, case[1])


def test_prior_semantic_diff_uses_code_version_keys_and_complete_payloads(case):
    prior = deepcopy(case[0])
    case[0]["codes"][0]["description"] = "Changed synthetic description"
    case[0]["rate_rules"][0]["duty"]["ad_valorem_percent"] = "6"
    report = build(case, prior=prior).as_dict()
    diff = report["semantic_diff"]
    assert diff["before_manifest_sha256"] == manifest_sha256(prior)
    assert diff["after_manifest_sha256"] == manifest_sha256(case[0])
    assert diff["codes"] == {"added": [], "removed": [], "changed": ["0101210000@2026-01-01"]}
    assert diff["rate_rules"] == {"added": [], "removed": [], "changed": ["test-rule-1"]}
    assert diff["artifacts"] == {"added": [], "removed": [], "changed": []}
    assert diff["coverage_changed"] is False
    assert diff["parser_changed"] is False
    assert diff["derived_amendment_inventory_changed"] is False


def test_changed_code_version_start_is_remove_add_and_rate_start_is_change(case):
    prior = deepcopy(case[0])
    case[0]["codes"][0]["valid_from"] = "2026-02-01"
    case[0]["rate_rules"][0]["valid_from"] = "2026-02-01"
    diff = build(case, prior=prior).as_dict()["semantic_diff"]
    assert diff["codes"] == {"added": ["0101210000@2026-02-01"], "removed": ["0101210000@2026-01-01"], "changed": []}
    assert diff["rate_rules"]["changed"] == ["test-rule-1"]


def test_changed_prior_and_changed_candidate_each_change_package_identity(case):
    prior = deepcopy(case[0])
    original = build(case, prior=prior)
    prior["codes"][0]["description"] = "Different historical proposal"
    changed_prior = build(case, prior=prior)
    assert changed_prior.sha256 != original.sha256
    assert changed_prior.as_dict()["semantic_diff"]["before_manifest_sha256"] != original.as_dict()["semantic_diff"]["before_manifest_sha256"]
    case[0]["codes"][0]["description"] = "Different next proposal"
    assert build(case, prior=prior).sha256 != changed_prior.sha256


def test_decimal_spelling_cannot_change_diff_or_package_of_canonical_manifests(case):
    prior = deepcopy(case[0])
    prior["rate_rules"][0]["duty"]["ad_valorem_percent"] = "5.000"
    case[0]["rate_rules"][0]["duty"]["ad_valorem_percent"] = "5.00"
    spelled = build(case, prior=prior)
    prior["rate_rules"][0]["duty"]["ad_valorem_percent"] = "5"
    case[0]["rate_rules"][0]["duty"]["ad_valorem_percent"] = "5"
    normalized = build(case, prior=prior)
    assert spelled.canonical_bytes == normalized.canonical_bytes
    assert spelled.as_dict()["semantic_diff"]["rate_rules"] == {"added": [], "removed": [], "changed": []}
    assert subject.verify_review_package(spelled, case[1]).sha256 == spelled.sha256


def test_valid_but_unbound_typed_portal_sources_stay_explicitly_unready(case):
    add_unbound_portal(case)
    report = build(case).as_dict()
    assert report["source_evidence"]["source_evidence_verified"] is True
    assert report["source_evidence"]["portal_metadata"]["references_verified"] == 2
    assert report["assembly_ready"] is False
    assert report["package_ready"] is False
    assert report["source_complete"] is False


def test_selected_supplement_replays_exact_html_attachment_and_pdf_bytes(case):
    _, digest = add_selected_supplement(case)
    package = build(case, supplemental_capture_report_sha256=digest)
    report = package.as_dict()
    assert report["assembly_ready"] is report["package_ready"] is True
    assert report["source_evidence"]["source_evidence_verified"] is True
    assert report["source_evidence"]["portal_metadata"]["references_verified"] == 2
    assert report["source_complete"] is report["legal_ready"] is False
    page = next(item for item in report["supplemental_sources"]["selected_sources"] if item["artifact_id"] == "portal-66")
    assert page["identity"]["metadata_matches_supplied_capture_identity"] is True
    assert "metadata_matches_discovery_identity" not in page["identity"]
    assert page["identity"]["expected_identity_origin"] == "selected_capture_record_not_replayed_discovery_plan"
    assert subject.verify_review_package(package, case[1]).canonical_bytes == package.canonical_bytes


@pytest.mark.parametrize("mutation", ["page_identity", "pdf_parent", "reference_index", "attachment_report", "pdf_hash"])
def test_rehashed_supplement_cannot_invent_selected_identity_or_attachment_provenance(case, mutation):
    report, _ = add_selected_supplement(case)
    if mutation == "page_identity":
        report["documents"][0]["expected_identity"]["number"] = "999"
    elif mutation == "pdf_parent":
        report["pdfs"][0]["source_references"][0]["page_sha256"] = "0" * 64
    elif mutation == "reference_index":
        report["pdfs"][0]["source_references"][0]["reference_index"] = 99999
    elif mutation == "attachment_report":
        discovery = json.loads(case[1].read(report["documents"][0]["attachment_discovery_sha256"]))
        discovery["document_identity"] = "Invented identity"
        digest = case[1].put(canonical_json_bytes(discovery))
        report["documents"][0]["attachment_discovery_sha256"] = digest
        report["pdfs"][0]["source_references"][0]["attachment_discovery_sha256"] = digest
    else:
        report["pdfs"][0]["sha256"] = "0" * 64
    digest = case[1].put(canonical(report))
    if mutation == "pdf_hash":
        # A well-formed record for different bytes is not the candidate's
        # acquisition association. It stays unbound, with no green package.
        output = build(case, supplemental_capture_report_sha256=digest).as_dict()
        assert output["assembly_ready"] is output["package_ready"] is False
        assert "act-66" in output["supplemental_sources"]["unbound_artifact_ids"]
        return
    with pytest.raises(subject.ReviewPackageError):
        build(case, supplemental_capture_report_sha256=digest)


def test_supplement_download_timestamp_cannot_rebind_a_manifest_observation(case):
    report, _ = add_selected_supplement(case)
    report["documents"][0]["retrieved_at"] = "2026-09-08T13:01:00Z"
    digest = case[1].put(canonical(report))
    output = build(case, supplemental_capture_report_sha256=digest).as_dict()
    assert output["assembly_ready"] is output["package_ready"] is False


def test_a_self_consistent_fabricated_pdf_quote_cannot_make_a_package_ready(case):
    reference = case[0]["rate_rules"][0]["evidence"][0]
    reference["raw_text"] = "A fabricated quote absent from the retained original"
    reference["raw_text_sha256"] = sha(reference["raw_text"].encode())
    report = build(case).as_dict()
    assert report["source_evidence"]["source_evidence_verified"] is False
    assert report["source_evidence"]["references_failed"] == 1
    assert report["assembly_ready"] is report["package_ready"] is False


def test_original_corruption_is_not_a_partial_green_review(case):
    _, store, _ = case
    original = next(a for a in case[0]["artifacts"] if a["role"] == "tariff_notes")
    (store._root / (original["sha256"] + ".blob")).unlink()
    with pytest.raises(subject.ReviewPackageError):
        build(case)


def test_replay_detects_original_missing_after_package_assembly(case):
    package = build(case)
    _, store, _ = case
    original = next(a for a in case[0]["artifacts"] if a["role"] == "chapter")
    (store._root / (original["sha256"] + ".blob")).unlink()
    with pytest.raises(subject.ReviewPackageError):
        subject.verify_review_package(package, store)


def test_rehashed_derived_inventory_report_cannot_hide_changed_source_claims(case):
    data, store, _ = case
    descriptor = data["derived_amendment_inventory"]
    report = json.loads(store.read(descriptor["report_sha256"]))
    report["legal_inventory_complete"] = True
    raw = canonical(report)
    descriptor.update(report_sha256=store.put(raw), report_size_bytes=len(raw))
    with pytest.raises(subject.ReviewPackageError):
        build(case)


def test_old_v1_receipt_does_not_satisfy_the_expanded_capture_gate(case):
    data, store, receipt = case
    raw = json.loads(store.read(receipt))
    raw["schema_version"] = 1
    raw.pop("attachment_downloads")
    raw.pop("legal_attachment_inventory_sha256")
    digest = store.put(acquisition.canonical_bytes(raw))
    assert acquisition.load_acquisition(store, digest)[0].schema_version == 1
    with pytest.raises(subject.ReviewPackageError):
        build((data, store, digest))


def test_rehashed_incomplete_download_plan_is_rejected(case):
    data, store, receipt = case
    report = json.loads(store.read(receipt))
    report["downloads"].pop()
    digest = store.put(acquisition.canonical_bytes(report))
    with pytest.raises(subject.ReviewPackageError):
        build((data, store, digest))


def test_rehashed_receipt_cannot_fabricate_another_download_date(case):
    data, store, receipt = case
    report = json.loads(store.read(receipt))
    report["downloads"][0]["retrieved_at"] = "2027-01-01T00:00:00Z"
    digest = store.put(acquisition.canonical_bytes(report))
    with pytest.raises(subject.ReviewPackageError):
        build((data, store, digest))


def test_rehashed_core_capture_cannot_declare_non_pdf_bytes_for_an_unreferenced_chapter(case):
    data, store, receipt = case
    artifact = next(a for a in data["artifacts"] if a.get("chapter") == "02")
    raw = b"This is not PDF data at all."
    artifact.update(sha256=store.put(raw), size_bytes=len(raw))
    report = json.loads(store.read(receipt))
    record = next(r for r in report["downloads"] if r["url"] == artifact["url"])
    record.update(sha256=artifact["sha256"], size_bytes=artifact["size_bytes"])
    altered_receipt = store.put(acquisition.canonical_bytes(report))
    # Hashes and index plan alone are insufficient to replay capture shape.
    acquisition.load_acquisition(store, altered_receipt)
    validate_manifest(data)
    with pytest.raises(subject.ReviewPackageError):
        build((data, store, altered_receipt))


def test_manifest_download_time_must_match_the_observed_capture_record(case):
    first = next(a for a in case[0]["artifacts"] if a.get("chapter") == "02")
    first["retrieved_at"] = "2026-09-08T13:00:00Z"
    report = build(case).as_dict()
    assert report["assembly_ready"] is False
    assert report["package_ready"] is False


def test_valid_manifest_role_swap_is_not_attested_by_equal_source_hashes(case):
    data = case[0]
    second = next(a for a in data["artifacts"] if a.get("chapter") == "02")
    third = next(a for a in data["artifacts"] if a.get("chapter") == "03")
    # These unreferenced fixtures deliberately share the same valid PDF body.
    assert second["sha256"] == third["sha256"]
    second["chapter"], third["chapter"] = third["chapter"], second["chapter"]
    validate_manifest(data)
    report = build(case).as_dict()
    assert report["assembly_ready"] is report["package_ready"] is False


@pytest.mark.parametrize("field,value", [
    ("MAX_SOURCE_OBJECTS", 1), ("MAX_SOURCE_BYTES", 1),
    ("MAX_INPUT_REPORT_BYTES", 1), ("MAX_PACKAGE_BYTES", 1),
])
def test_public_builder_rejects_inputs_above_its_resource_budget(case, monkeypatch, field, value):
    monkeypatch.setattr(subject, field, value)
    with pytest.raises(subject.ReviewPackageError):
        build(case)


def test_public_builder_stops_when_elapsed_budget_is_exhausted(case, monkeypatch):
    ticks = iter((0.0, float(subject.MAX_BUILD_SECONDS + 1)))
    monkeypatch.setattr(subject.time, "monotonic", lambda: next(ticks))
    with pytest.raises(subject.ReviewPackageError, match="time_limit"):
        build(case)


@pytest.mark.parametrize("assumptions", [
    ["List instead of immutable input tuple"], ("",), ("   ",), ("bad\x00text",),
    (True,), ("x" * (subject.MAX_ASSUMPTION_LENGTH + 1),),
    ("many",) * (subject.MAX_ASSUMPTIONS + 1),
])
def test_assumptions_are_bounded_unverified_text_only(case, assumptions):
    with pytest.raises(subject.ReviewPackageError, match="assumptions"):
        build(case, assumptions=assumptions)


def test_duplicate_selected_source_acquisition_is_ambiguous(case):
    report, _ = add_selected_supplement(case)
    report["documents"].append(deepcopy(report["documents"][0]))
    digest = case[1].put(canonical(report))
    with pytest.raises(subject.ReviewPackageError, match="ambiguous"):
        build(case, supplemental_capture_report_sha256=digest)


def test_selected_capture_cannot_claim_a_portal_path_the_capture_tool_rejects(case):
    report, _ = add_selected_supplement(case)
    # No typed reference independently constrains this unreferenced portal.
    # Its acquisition association must still satisfy the original capture gate.
    for row in (*case[0]["codes"], *case[0]["rate_rules"]):
        row["effective_evidence"] = [ref for ref in row["effective_evidence"]
                                     if ref.get("kind") != "legal_portal_metadata_v1"]
    url = "https://docs.eaeunion.org/docs/ru-ru/0100000000000000000000"
    portal = next(a for a in case[0]["artifacts"] if a["artifact_id"] == "portal-66")
    portal["url"] = url
    page = report["documents"][0]
    page["url"] = page["requested_url"] = url
    attachments = parse_legal_attachments(case[1].read(portal["sha256"]), url)
    attachment_sha = case[1].put(canonical_json_bytes(asdict(attachments)))
    page["attachment_discovery_sha256"] = attachment_sha
    for reference in report["pdfs"][0]["source_references"]:
        reference["page_url"] = url
        reference["attachment_discovery_sha256"] = attachment_sha
    validate_manifest(case[0])
    digest = case[1].put(canonical(report))
    with pytest.raises(subject.ReviewPackageError):
        build(case, supplemental_capture_report_sha256=digest)


def test_elapsed_budget_includes_final_package_serialization(case, monkeypatch):
    clock = [0.0]
    original = subject._encode
    monkeypatch.setattr(subject.time, "monotonic", lambda: clock[0])

    def encode_past_deadline(value):
        result = original(value)
        clock[0] = subject.MAX_BUILD_SECONDS + 1.0
        return result

    monkeypatch.setattr(subject, "_encode", encode_past_deadline)
    with pytest.raises(subject.ReviewPackageError, match="time_limit"):
        build(case)


def test_unselected_capture_claims_cannot_become_a_complete_capture_gate(case):
    report, _ = add_selected_supplement(case)
    report.update(discovery_plan_replayed=True, legal_inventory_complete=True,
                  legal_approval_verified=True, primary_act_bodies_verified=True)
    digest = case[1].put(canonical(report))
    result = build(case, supplemental_capture_report_sha256=digest).as_dict()
    assert result["assembly_ready"] is True
    assert result["supplemental_sources"]["discovery_plan_replayed"] is False
    assert result["supplemental_sources"]["whole_capture_report_replayed"] is False
    assert result["supplemental_sources"]["unselected_capture_records_verified"] is False
    assert result["source_complete"] is result["legal_approval_verified"] is False
    assert result["can_promote"] is result["production_ready"] is False


def test_pure_builder_does_not_import_database_or_access_network(case, tmp_path):
    data, store, receipt = case
    manifest_file = tmp_path / "candidate.json"
    manifest_file.write_bytes(canonical_manifest_bytes(data))
    database = tmp_path / "must-not-exist.db"
    script = r'''
import importlib.abc, socket, sys
class RejectDatabaseImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "app.db" or fullname.startswith("app.db.") or fullname == "app.services.ett_repository" or fullname == "sqlalchemy" or fullname.startswith("sqlalchemy."):
            raise AssertionError("Review package imports a database dependency")
sys.meta_path.insert(0, RejectDatabaseImports())
def no_network(*args, **kwargs):
    raise AssertionError("Review package attempted network access")
socket.create_connection = no_network
socket.socket.connect = no_network
from pathlib import Path
from app.services.ett_artifacts import LocalArtifactStore
from app.services.ett_review_package import build_review_package, verify_review_package
store = LocalArtifactStore(Path(sys.argv[2]), create=False)
package = build_review_package(Path(sys.argv[1]).read_bytes(), store, acquisition_receipt_sha256=sys.argv[3], prior_manifest=None)
assert verify_review_package(package, store).sha256 == package.sha256
'''
    before = {p.name: p.read_bytes() for p in store._root.iterdir()}
    result = subprocess.run([sys.executable, "-c", script, str(manifest_file), str(store._root), receipt],
                            cwd=Path(__file__).resolve().parents[1],
                            env={**os.environ, "DATABASE_URL": "sqlite:///" + str(database),
                                 "PYTHONPATH": os.pathsep.join(str(Path(p).resolve()) for p in sys.path if p)},
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert not database.exists()
    assert {p.name: p.read_bytes() for p in store._root.iterdir()} == before
