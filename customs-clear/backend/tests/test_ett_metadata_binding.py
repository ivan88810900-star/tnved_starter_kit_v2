"""Original source replay is independent of a self-consistent candidate schema.

The full portal HTML is a retained original. The containing manifest and linked
PDF body are deliberately synthetic: successful byte/field binding cannot prove
that the PDF body identifies this act or that the proposed rates/dates are legal.
"""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json

import pytest

from app.services import ett_metadata_binding as binding
from app.services import ett_evidence_binding as native
from app.services.ett_artifacts import ArtifactIntegrityError, LocalArtifactStore
from app.services.ett_legal_attachments import parse_legal_attachments
from app.services.ett_legal_metadata import parse_legal_metadata
from app.services.ett_manifest import canonical_manifest_bytes, manifest_sha256, validate_manifest
from tests.test_ett_evidence_binding import source_fixture
from tests.test_ett_legal_portal_live import CASES, FIXTURES


def sha(raw):
    return hashlib.sha256(raw if isinstance(raw, bytes) else raw.encode()).hexdigest()


def make_reference(raw, field="publication_date"):
    case = CASES[0]
    metadata = parse_legal_metadata(raw, case["url"])
    row = metadata["rows"][metadata["fields"][field]["observation_rows"][0] - 1]
    anchors = parse_legal_attachments(raw, case["url"])
    anchor = next(asdict(ref) for ref in anchors.documents if ref.text.startswith("Решение"))
    literal = lambda value: {key: value[key] for key in ("locator", "raw_text", "raw_text_sha256")}
    return {
        "kind": "legal_portal_metadata_v1", "artifact_id": "portal-66", "artifact_sha256": sha(raw),
        "field": field, **literal(row["row_evidence"]), "label": literal(row["labels"][0]),
        "value": literal(row["values"][0]),
        "parser": binding.supported_metadata_parser_identity().model_dump(mode="json"),
        "expected_identity": {"issuing_body": "collegium", "adoption_date": "2022-04-19", "number": "66"},
        "pdf_binding": {"artifact_id": "act-66", "artifact_sha256": "0" * 64,
                        **{key: anchor[key] for key in ("url", "href", "raw_href", "text", "locator")},
                        "text_sha256": sha(anchor["text"])},
    }


@pytest.fixture
def mixed(source_fixture, tmp_path):
    data, bodies = deepcopy(source_fixture)
    raw = (FIXTURES / (CASES[0]["stem"] + ".html")).read_bytes()
    # This is an intentionally synthetic PDF, not a counterfeit original fixture.
    pdf = bodies["tariff_notes"]
    for artifact_id, body, url, media in (
        ("portal-66", raw, CASES[0]["url"], "text/html"),
        ("act-66", pdf, CASES[0]["pdf"], "application/pdf"),
    ):
        data["artifacts"].append({"artifact_id": artifact_id, "role": "amendment", "url": url,
                                  "sha256": sha(body), "size_bytes": len(body), "media_type": media,
                                  "retrieved_at": "2026-01-01T00:00:00Z"})
        bodies[artifact_id] = body
    for collection in ("codes", "rate_rules"):
        reference = make_reference(raw)
        reference["pdf_binding"]["artifact_sha256"] = sha(pdf)
        data[collection][0]["effective_evidence"].append(reference)
    root = tmp_path / "objects"
    store = LocalArtifactStore(root)
    for body in bodies.values():
        store.put(body)
    validate_manifest(data)
    return data, LocalArtifactStore(root, create=False), raw


def references(data):
    return [data[collection][0]["effective_evidence"][-1] for collection in ("codes", "rate_rules")]


def replace_html(data, store, raw):
    digest = LocalArtifactStore(store._root).put(raw)
    artifact = next(a for a in data["artifacts"] if a["artifact_id"] == "portal-66")
    artifact.update(sha256=digest, size_bytes=len(raw))
    for reference in references(data):
        reference["artifact_sha256"] = digest


def metadata_report(mixed):
    data, store, _ = mixed
    return binding.verify_manifest_source_metadata(data, store)


def test_original_metadata_binds_but_contradictory_synthetic_pdf_body_and_dates_are_not_approved(mixed):
    data, store, _ = mixed
    before = {p.name: p.read_bytes() for p in store._root.iterdir()}
    report = binding.verify_manifest_source_evidence(data, store)
    assert report["source_evidence_verified"] is True
    assert report["references_total"] == report["references_verified"] == 7
    assert report["references_failed"] == 0
    assert report["manifest_sha256"] == manifest_sha256(data)
    assert report["pdf_rows"]["references_verified"] == 5
    metadata = report["portal_metadata"]
    assert metadata["references_verified"] == 2
    assert metadata["html_artifacts_parsed"] == metadata["linked_pdf_artifacts_verified"] == 1
    assert metadata["verified_occurrences"][0]["short_title_status"] == "strict_identity_agrees"
    assert data["codes"][0]["valid_from"] == "2026-01-01"
    assert "2030-01-01" in data["codes"][0]["effective_evidence"][0]["raw_text"]
    for component in (report, metadata):
        for flag in binding._unverified_flags():
            assert component[flag] is False
    assert {p.name: p.read_bytes() for p in store._root.iterdir()} == before
    assert binding.verify_manifest_source_evidence(canonical_manifest_bytes(data), store) == report


def test_native_only_interface_explicitly_rejects_typed_html_without_crashing_or_attesting_it(mixed):
    data, store, _ = mixed
    report = native.verify_manifest_source_rows(data, store)
    assert report["rows_verified"] is False
    assert report["references_total"] == 7
    assert report["references_verified"] == 5
    assert report["references_failed"] == 2
    assert {issue["reason"] for issue in report["issues"]} == {"non_pdf_evidence_unsupported"}
    assert all("page" not in issue and issue["kind"] == "legal_portal_metadata_v1" for issue in report["issues"])


def test_pdf_only_coordinator_preserves_the_complete_native_report(mixed):
    data, store, _ = mixed
    for collection in ("codes", "rate_rules"):
        data[collection][0]["effective_evidence"].pop()
    expected = native.verify_manifest_source_rows(data, store)
    result = binding.verify_manifest_source_evidence(data, store)
    assert result["pdf_rows"] == expected
    assert result["portal_metadata"]["references_total"] == 0
    assert result["source_evidence_verified"] is True


@pytest.mark.parametrize("field", ["publication_date", "entry_into_force_date_metadata", "comment"])
def test_each_allowed_field_replays_exactly_without_deriving_dates(mixed, field):
    data, store, raw = mixed
    for collection in ("codes", "rate_rules"):
        old = data[collection][0]["effective_evidence"][-1]
        new = make_reference(raw, field)
        new["pdf_binding"]["artifact_sha256"] = old["pdf_binding"]["artifact_sha256"]
        data[collection][0]["effective_evidence"][-1] = new
    report = metadata_report(mixed)
    assert report["metadata_verified"] is True
    assert report["effective_dates_verified"] is False
    assert "observed_iso_date" not in json.dumps(report)


def test_fabricated_fully_rehashed_value_passes_schema_but_fails_original_replay(mixed):
    data, _, _ = mixed
    reference = references(data)[0]
    old = reference["value"]["raw_text"]
    reference["value"].update(raw_text="01.01.2000", raw_text_sha256=sha("01.01.2000"))
    reference["raw_text"] = reference["raw_text"].replace(old, "01.01.2000")
    reference["raw_text_sha256"] = sha(reference["raw_text"])
    validate_manifest(data)
    report = metadata_report(mixed)
    assert report["metadata_verified"] is False
    assert report["references_verified"] == report["references_failed"] == 1
    assert report["issues"][0]["reason"] == "metadata_text_mismatch"
    assert "01.01.2000" not in json.dumps(report)


@pytest.mark.parametrize("part", ["row", "label", "value", "anchor"])
def test_valid_but_wrong_source_locator_is_not_rescued_by_searching_for_equal_text(mixed, part):
    data, _, _ = mixed
    reference = references(data)[0]
    target = reference if part == "row" else reference["pdf_binding" if part == "anchor" else part]
    head, column = target["locator"].rsplit(":", 1)
    target["locator"] = head + ":" + str(int(column) + 1)
    validate_manifest(data)
    report = metadata_report(mixed)
    assert report["references_failed"] == 1
    assert report["issues"][0]["reason"] == ("primary_anchor_locator_mismatch" if part == "anchor" else "metadata_locator_mismatch")


def test_equivalent_html_entity_href_cannot_replace_the_original_lexical_href(mixed):
    data, _, _ = mixed
    references(data)[0]["pdf_binding"]["raw_href"] = references(data)[0]["pdf_binding"]["raw_href"].replace("_", "&#95;", 1)
    validate_manifest(data)
    report = metadata_report(mixed)
    assert report["references_failed"] == 1
    assert report["issues"][0]["reason"] == "primary_anchor_projection_mismatch"


def test_rehashed_raw_whitespace_cannot_replace_the_exact_dom_text(mixed):
    data, _, _ = mixed
    reference = references(data)[0]
    reference["raw_text"] = reference["raw_text"].replace("\n", " ", 1)
    reference["raw_text_sha256"] = sha(reference["raw_text"])
    validate_manifest(data)
    assert metadata_report(mixed)["issues"][0]["reason"] == "metadata_text_mismatch"


def test_wrong_supported_parser_hash_cannot_approve_valid_source_text(mixed):
    data, _, _ = mixed
    references(data)[0]["parser"]["sha256"] = "a" * 64
    report = metadata_report(mixed)
    assert report["references_failed"] == 1
    assert report["issues"][0]["reason"] == "metadata_parser_identity_mismatch"


def test_parser_drift_invalidates_previously_matching_occurrences(mixed, monkeypatch):
    initial = binding.supported_metadata_parser_identity()
    changed = initial.model_copy(update={"sha256": "b" * 64})
    values = iter([initial, changed])
    monkeypatch.setattr(binding, "supported_metadata_parser_identity", lambda: next(values))
    report = metadata_report(mixed)
    assert report["references_verified"] == 0
    assert report["references_failed"] == 2
    assert report["parser_unchanged_during_replay"] is False
    assert {i["reason"] for i in report["issues"]} == {"metadata_parser_changed_during_replay"}


@pytest.mark.parametrize("mode", ["forged_pdf_row", "unsupported_legacy_html", "missing_native_artifact"])
def test_successful_metadata_cannot_hide_a_real_native_failure_even_when_issues_are_truncated(mixed, monkeypatch, mode):
    data, store, _ = mixed
    if mode == "forged_pdf_row":
        ref = data["codes"][0]["evidence"][0]
        ref.update(raw_text="forged native row", raw_text_sha256=sha("forged native row"))
    elif mode == "unsupported_legacy_html":
        next(a for a in data["artifacts"] if a["artifact_id"] == "tariff_notes")["media_type"] = "text/html"
    else:
        artifact = next(a for a in data["artifacts"] if a["artifact_id"] == "chapter-01")
        actual = LocalArtifactStore.read
        def read(self, digest):
            if digest == artifact["sha256"]:
                raise ArtifactIntegrityError("private storage path")
            return actual(self, digest)
        monkeypatch.setattr(LocalArtifactStore, "read", read)
    monkeypatch.setattr(native, "MAX_ISSUES", 0)
    report = binding.verify_manifest_source_evidence(data, store)
    assert report["portal_metadata"]["metadata_verified"] is True
    assert report["pdf_rows"]["references_failed"] > 0
    assert report["pdf_rows"]["issues"] == []
    assert report["pdf_rows"]["issues_truncated"] is True
    assert report["source_evidence_verified"] is False
    assert report["references_failed"] > 0


@pytest.mark.parametrize("target", ["portal-66", "act-66"])
@pytest.mark.parametrize("mode", ["missing", "wrong_body"])
def test_both_original_sources_are_independently_verified_and_private_errors_sanitized(mixed, monkeypatch, target, mode):
    data, store, _ = mixed
    digest = next(a["sha256"] for a in data["artifacts"] if a["artifact_id"] == target)
    actual = LocalArtifactStore.read
    def read(self, requested):
        if requested == digest:
            if mode == "missing":
                raise OSError("private secret file")
            return b"private fake replacement"
        return actual(self, requested)
    monkeypatch.setattr(LocalArtifactStore, "read", read)
    report = metadata_report(mixed)
    assert report["metadata_verified"] is False
    assert report["references_failed"] == 2
    assert "private" not in json.dumps(report)
    assert {i["reason"] for i in report["issues"]} == {
        "artifact_unavailable_or_corrupt" if mode == "missing" else "artifact_integrity_mismatch"}


@pytest.mark.parametrize("change", [
    lambda raw: raw.replace("28.04.2022".encode(), "29.04.2022".encode()),
    lambda raw: raw.replace("Коллегия Евразийской".encode(), "Совет Евразийской".encode()),
    lambda raw: raw.replace("19.04.2022".encode(), "20.04.2022".encode()),
    lambda raw: raw.replace("Решение Коллегии ЕЭК № 66".encode(), "Решение Совета ЕЭК № 66".encode()),
    lambda raw: raw.replace("Решение Коллегии №66 от 19 апреля 2022 г".encode(), "Решение Совета №66 от 19 апреля 2022 г".encode()),
    lambda raw: raw.replace('        Документ\n'.encode(), '        Приложения\n'.encode()),
    lambda raw: raw.replace(b'class="DocDetail_Files_Group"', b'class="DocDetail_Files_Group" hidden', 1),
    lambda raw: raw[:-7],
])
def test_new_original_sha_cannot_rescue_changed_metadata_identity_or_attachment_scope(mixed, change):
    data, store, raw = mixed
    updated = change(raw)
    assert updated != raw
    replace_html(data, store, updated)
    validate_manifest(data)
    report = metadata_report(mixed)
    assert report["metadata_verified"] is False
    assert report["references_failed"] == 2


@pytest.mark.parametrize("limit,reason", [
    ("MAX_HTML_ARTIFACTS", "metadata_html_artifact_count_limit"),
    ("MAX_LINKED_PDFS", "linked_pdf_artifact_count_limit"),
    ("MAX_SOURCE_BYTES", "aggregate_source_size_limit"),
    ("MAX_BINDING_SECONDS", "metadata_binding_time_limit"),
])
def test_aggregate_bounds_fail_closed(mixed, monkeypatch, limit, reason):
    monkeypatch.setattr(binding, limit, 0)
    report = metadata_report(mixed)
    assert report["references_failed"] == 2
    assert {i["reason"] for i in report["issues"]} == {reason}


def test_bounded_details_do_not_drop_counts_or_turn_failures_green(mixed, monkeypatch):
    monkeypatch.setattr(binding, "MAX_VERIFIED_DETAILS", 0)
    report = metadata_report(mixed)
    assert report["metadata_verified"] is True
    assert report["references_verified"] == 2
    assert report["verified_occurrences"] == []
    assert report["verified_occurrences_truncated"] is True
    monkeypatch.setattr(binding, "MAX_ISSUES", 0)
    monkeypatch.setattr(binding, "MAX_LINKED_PDFS", 0)
    report = metadata_report(mixed)
    assert report["references_failed"] == 2
    assert report["issues"] == []
    assert report["issues_truncated"] is True
    assert report["metadata_verified"] is False


def test_nested_model_construct_is_revalidated_and_error_has_no_source_text(mixed):
    data, store, _ = mixed
    validated = validate_manifest(data)
    code = validated.codes[0]
    last = code.effective_evidence[-1].model_copy(update={"raw_text": "private unbound source quotation"})
    bad_code = code.model_copy(update={"effective_evidence": (*code.effective_evidence[:-1], last)})
    invalid = validated.model_copy(update={"codes": (bad_code,)})
    with pytest.raises(binding.MetadataBindingError) as caught:
        binding.verify_manifest_source_evidence(invalid, store)
    assert "private" not in str(caught.value)


def test_total_reference_bound_is_enforced_before_partitioning(mixed, monkeypatch):
    data, store, _ = mixed
    monkeypatch.setattr(native, "MAX_REFERENCES", 6)
    with pytest.raises(binding.MetadataBindingError, match="reference count"):
        binding.verify_manifest_source_evidence(data, store)
