"""Typed portal observations remain candidate evidence, never legal approval.

The containing tariff manifest is synthetic. The separately labeled fragments
retain original bytes of one observed portal card; they do not prove tariff
coverage, a publication event, effective dates, or the PDF's interpretation.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.services.ett_manifest import (
    ETTEvidence, ETTLegalPortalMetadataEvidence, canonical_manifest_bytes,
    manifest_sha256, validate_manifest,
)
from app.services.ett_legal_metadata import parse_legal_metadata
from tests.ett_fixtures import synthetic_manifest, synthetic_manifest_data


FIXTURES = Path(__file__).parent / "fixtures/ett_manifest_portal"


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def payload_sha(value):
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def retained_source():
    return json.loads((FIXTURES / "collegium_138.metadata.json").read_bytes())


def portal_reference(field="publication_date"):
    source = retained_source()
    row = source["observed_metadata_rows"][0 if field == "publication_date" else 1]
    literal_keys = ("locator", "raw_text", "raw_text_sha256")
    return {
        "kind": "legal_portal_metadata_v1",
        "artifact_id": "portal-138", "artifact_sha256": source["source_sha256"],
        "field": field,
        **{key: row["row_evidence"][key] for key in literal_keys},
        "label": {key: row["labels"][0][key] for key in literal_keys},
        "value": {key: row["values"][0][key] for key in literal_keys},
        "parser": {"name": "ett_legal_metadata", "version": "1", "sha256": "a" * 64},
        "expected_identity": source["expected_identity"],
        "pdf_binding": {
            "artifact_id": "act-138", "artifact_sha256": source["pdf_sha256"],
            **source["pdf_binding"],
        },
    }


def manifest_with_portal():
    data = synthetic_manifest_data()
    source = retained_source()
    for artifact_id, url, digest, size, media_type in [
        ("portal-138", source["source_url"], source["source_sha256"], source["source_size_bytes"], "text/html"),
        ("act-138", source["pdf_binding"]["url"], source["pdf_sha256"], source["pdf_size_bytes"], "application/pdf"),
    ]:
        data["artifacts"].append({
            "artifact_id": artifact_id, "role": "amendment", "url": url,
            "sha256": digest, "size_bytes": size, "media_type": media_type,
            "retrieved_at": "2026-09-01T00:00:00Z",
        })
    # Existing native clause evidence is retained alongside portal metadata.
    for collection in ("codes", "rate_rules"):
        data[collection][0]["effective_evidence"].append(portal_reference())
    return data


def change_literal(reference, key, text):
    reference[key]["raw_text"] = text
    reference[key]["raw_text_sha256"] = sha(text)


def align_row_projection(reference):
    reference["raw_text"] = reference["label"]["raw_text"] + " " + reference["value"]["raw_text"]
    reference["raw_text_sha256"] = sha(reference["raw_text"])


def test_existing_manifest_and_child_payload_digests_do_not_change():
    # Captured from the old native-only schema before portal models were added.
    manifest = synthetic_manifest()
    assert manifest_sha256(manifest) == "dfc7093f5fe87bd39a3bebee633808f725a725c84e8b009a705d8687e5580af3"
    assert len(canonical_manifest_bytes(manifest)) == 30973
    assert payload_sha(manifest.codes[0].model_dump(mode="json")) == "803a12ce3eb40fa3204f19a8941d8572133052c0dcc7c383f5f21f7ef5f372f6"
    assert payload_sha(manifest.rate_rules[0].model_dump(mode="json")) == "71fbb982bd28f1de0ea9693a5954080c5f837c69527d9c5fbfa74ff5b6483773"
    assert payload_sha(manifest.codes[0].evidence[0].model_dump(mode="json")) == "85dda7a92e704b8b1ced5544d8a6e0b00b07d6d0fd68872e123c73c84224e5b3"
    assert canonical_manifest_bytes(canonical_manifest_bytes(manifest)) == canonical_manifest_bytes(manifest)


def test_native_effective_reference_keeps_its_exact_shape_and_model():
    data = synthetic_manifest_data()
    manifest = validate_manifest(data)
    for collection in ("codes", "rate_rules"):
        native = getattr(manifest, collection)[0].effective_evidence[0]
        assert type(native) is ETTEvidence
        assert native.model_dump(mode="json") == data[collection][0]["effective_evidence"][0]
        assert "kind" not in native.model_dump()


@pytest.mark.parametrize("field", ["publication_date", "entry_into_force_date_metadata"])
def test_retained_138_literals_have_their_own_typed_reference_without_pdf_page(field):
    reference = portal_reference(field)
    model = ETTLegalPortalMetadataEvidence.model_validate(reference)
    assert model.kind == "legal_portal_metadata_v1"
    assert model.raw_text == reference["raw_text"]
    assert model.raw_text_sha256 == sha(model.raw_text)
    assert model.value.raw_text == reference["value"]["raw_text"]
    assert "page" not in model.model_dump()
    assert "row" not in model.model_dump()
    assert model.pdf_binding.text == "Решение Коллегии № 138 от 24 декабря 2025 г"


def test_retained_fragments_bind_exact_source_spans_and_reproduce_date_text():
    source = retained_source()
    assert source["source_sha256"] == "572145df293145270724e11652c193717d09f7568e4d86a9c8eabc986d59f7ee"
    for fragment in source["fragments"].values():
        body = (FIXTURES / fragment["file"]).read_bytes()
        assert hashlib.sha256(body).hexdigest() == fragment["sha256"]
        assert len(body) == fragment["size_bytes"] == fragment["source_byte_span"][1] - fragment["source_byte_span"][0]
    # The wrapper is synthetic and changes locators. Only the fragment's bytes
    # and decoded text are observations from the retained original page.
    body = ('<html><head><title>Fixture</title></head><body>'
            '<div class="Header_Bottom__Title">Правовой портал</div>'
            '<div class="Box_Title">Информация о документе</div>').encode()
    body += (FIXTURES / source["fragments"]["metadata"]["file"]).read_bytes() + b"</body></html>"
    parsed = parse_legal_metadata(body, source["source_url"])
    for field, original in zip(("publication_date", "entry_into_force_date_metadata"), source["observed_metadata_rows"]):
        observed = parsed["fields"][field]
        row = parsed["rows"][observed["observation_rows"][0] - 1]
        assert observed["status"] == "observed"
        assert row["row_evidence"]["raw_text"] == original["row_evidence"]["raw_text"]
    assert parsed["fields"]["publication_date"]["observed_iso_date"] == "2025-12-26"
    assert parsed["fields"]["entry_into_force_date_metadata"]["observed_iso_date"] == "2026-01-25"
    assert parsed["official_publication_event_verified"] is False
    assert parsed["effective_dates_verified"] is False


def test_portal_candidate_roundtrip_preserves_native_and_portal_references():
    data = manifest_with_portal()
    manifest = validate_manifest(data)
    for collection in ("codes", "rate_rules"):
        references = getattr(manifest, collection)[0].effective_evidence
        assert type(references[0]) is ETTEvidence
        assert type(references[1]) is ETTLegalPortalMetadataEvidence
    assert canonical_manifest_bytes(canonical_manifest_bytes(manifest)) == canonical_manifest_bytes(manifest)
    assert validate_manifest(canonical_manifest_bytes(manifest)) == manifest


@pytest.mark.parametrize("collection", ["codes", "rate_rules", "footnotes"])
def test_portal_observation_cannot_establish_ordinary_code_rate_or_footnote_evidence(collection):
    data = manifest_with_portal()
    if collection == "footnotes":
        data[collection] = [{"footnote_id": "test-note", "text": "Synthetic note", "evidence": [portal_reference()],
                             "resolution": "informational", "rule_ids": [], "rationale": "Synthetic test"}]
    else:
        data[collection][0]["evidence"] = [portal_reference()]
    with pytest.raises(ValidationError):
        validate_manifest(data)


@pytest.mark.parametrize("key,value", [
    ("page", 1), ("row", "p0001:r00001"), ("verified", True), ("legal_approval", True),
    ("kind", "native_pdf_row"), ("field", "adoption_date"), ("field", "unknown"),
    ("artifact_id", 138), ("artifact_sha256", "A" * 64), ("raw_text", "forged source row"),
    ("raw_text_sha256", "0" * 64), ("locator", "p0001:r00001"),
    ("locator", "html:metadata-row:0:line:135:column:124"), ("locator", "html:metadata-value:6:line:135:column:124"),
])
def test_wrong_shape_or_forged_top_level_portal_values_fail(key, value):
    reference = portal_reference()
    reference[key] = value
    with pytest.raises(ValidationError):
        ETTLegalPortalMetadataEvidence.model_validate(reference)


@pytest.mark.parametrize("part", ["label", "value"])
@pytest.mark.parametrize("mutation", ["text", "hash", "locator", "extra"])
def test_literal_hash_locator_and_closed_fields_are_checked(part, mutation):
    reference = portal_reference()
    if mutation == "text":
        reference[part]["raw_text"] = "Forged literal with unchanged digest"
    elif mutation == "hash":
        reference[part]["raw_text_sha256"] = "0" * 64
    elif mutation == "locator":
        reference[part]["locator"] = "p0001:r00001"
    else:
        reference[part]["verified"] = True
    with pytest.raises(ValidationError):
        ETTLegalPortalMetadataEvidence.model_validate(reference)


@pytest.mark.parametrize("value", ["31.02.2025", "2025-12-26", "Сегодня", "26.12.2025 00:00", "", "２６.１２.２０２５"])
def test_date_metadata_must_contain_an_exact_valid_calendar_literal(value):
    reference = portal_reference()
    change_literal(reference, "value", value)
    align_row_projection(reference)
    with pytest.raises(ValidationError):
        ETTLegalPortalMetadataEvidence.model_validate(reference)


def test_wrong_label_and_rehashed_row_do_not_change_the_meaning_of_a_field():
    reference = portal_reference()
    change_literal(reference, "label", "Дата принятия документа")
    align_row_projection(reference)
    with pytest.raises(ValidationError):
        ETTLegalPortalMetadataEvidence.model_validate(reference)


def test_independently_rehashed_row_must_still_project_its_label_and_value():
    reference = portal_reference()
    reference["raw_text"] = "Дата опубликования 01.01.2000"
    reference["raw_text_sha256"] = sha(reference["raw_text"])
    with pytest.raises(ValidationError):
        ETTLegalPortalMetadataEvidence.model_validate(reference)


def test_comment_is_textual_metadata_without_an_invented_calendar_date():
    reference = portal_reference()
    reference["field"] = "comment"
    change_literal(reference, "label", "Комментарий")
    change_literal(reference, "value", "Решение вступает в силу по истечении 30 календарных дней со дня опубликования.")
    align_row_projection(reference)
    model = ETTLegalPortalMetadataEvidence.model_validate(reference)
    assert model.value.raw_text.endswith("опубликования.")
    assert "observed_iso_date" not in model.model_dump()
    assert "valid_from" not in model.model_dump()


@pytest.mark.parametrize("part,key,value", [
    ("parser", "name", "arbitrary_parser"), ("parser", "version", "2"), ("parser", "verified", True),
    ("expected_identity", "issuing_body", "council"), ("expected_identity", "issuing_body", "unknown"),
    ("expected_identity", "adoption_date", "2025-12-25"), ("expected_identity", "adoption_date", "24.12.2025"),
    ("expected_identity", "number", "139"), ("expected_identity", "number", 138),
    ("expected_identity", "verified", True),
    ("pdf_binding", "text", "Скачать"), ("pdf_binding", "text_sha256", "0" * 64),
    ("pdf_binding", "locator", "html:metadata-row:6:line:135:column:124"),
    ("pdf_binding", "href", "/upload/iblock/other.pdf"),
    ("pdf_binding", "raw_href", "/upload/iblock/other.pdf"),
    ("pdf_binding", "verified", True),
])
def test_parser_identity_and_pdf_binding_are_not_caller_attestations(part, key, value):
    reference = portal_reference()
    reference[part][key] = value
    if part == "pdf_binding" and key == "text":
        reference[part]["text_sha256"] = sha(value)
    with pytest.raises(ValidationError):
        ETTLegalPortalMetadataEvidence.model_validate(reference)


@pytest.mark.parametrize("text", [
    "Решение Совета № 138 от 24 декабря 2025 г", "Решение Коллегии № 139 от 24 декабря 2025 г",
    "Решение Коллегии № 138 от 25 декабря 2025 г", "Решение Коллеги № 138 от 24 декабря 2025 г",
    "Решение Коллегии № 138 от 24 декабря 2025 г приложение 1", "Рус", "138.pdf",
])
def test_rehashed_anchor_requires_exact_expected_act_identity(text):
    reference = portal_reference()
    reference["pdf_binding"].update(text=text, text_sha256=sha(text))
    with pytest.raises(ValidationError):
        ETTLegalPortalMetadataEvidence.model_validate(reference)


@pytest.mark.parametrize("segment", ["discard/../", "./", "%2e/", "%2e%2e/", "/"])
def test_observed_href_cannot_be_rewritten_by_path_normalization(segment):
    reference = portal_reference()
    binding = reference["pdf_binding"]
    prefix = "/upload/iblock/"
    altered = prefix + segment + binding["href"][len(prefix):]
    binding.update(href=altered, raw_href=altered)
    with pytest.raises(ValidationError):
        ETTLegalPortalMetadataEvidence.model_validate(reference)


@pytest.mark.parametrize("target,key,value", [
    ("portal-138", "media_type", "application/pdf"), ("act-138", "media_type", "text/html"),
    ("portal-138", "sha256", "0" * 64), ("act-138", "sha256", "0" * 64),
    ("portal-138", "url", "https://eec.eaeunion.org/documents/446/10423/"),
    ("portal-138", "url", "https://docs.eaeunion.org/documents/10423/"),
    ("portal-138", "url", "https://docs.eaeunion.org/documents/446/10423/extra/"),
    ("act-138", "url", "https://docs.eaeunion.org/upload/iblock/another.pdf"),
])
def test_manifest_binds_exact_original_html_and_pdf_artifacts(target, key, value):
    data = manifest_with_portal()
    next(a for a in data["artifacts"] if a["artifact_id"] == target)[key] = value
    with pytest.raises(ValidationError):
        validate_manifest(data)


@pytest.mark.parametrize("target", ["portal-138", "act-138"])
def test_both_bound_sources_must_have_the_amendment_role(target):
    data = manifest_with_portal()
    # Preserve singleton cardinality so only the typed source-role check fails.
    next(a for a in data["artifacts"] if a["role"] == "nomenclature_notes")["role"] = "amendment"
    next(a for a in data["artifacts"] if a["artifact_id"] == target)["role"] = "nomenclature_notes"
    with pytest.raises(ValidationError):
        validate_manifest(data)


@pytest.mark.parametrize("target", ["portal-138", "act-138"])
def test_missing_source_artifact_never_leaves_a_valid_dangling_reference(target):
    data = manifest_with_portal()
    data["artifacts"] = [a for a in data["artifacts"] if a["artifact_id"] != target]
    with pytest.raises(ValidationError):
        validate_manifest(data)


def test_nested_portal_models_are_immutable_and_input_aliases_do_not_mutate_manifest():
    data = manifest_with_portal()
    manifest = validate_manifest(data)
    before = canonical_manifest_bytes(manifest)
    reference = manifest.codes[0].effective_evidence[1]
    for target, field, value in [
        (reference, "field", "comment"), (reference.value, "raw_text", "Changed"),
        (reference.pdf_binding, "text", "Changed"), (reference.expected_identity, "number", "999"),
        (reference.parser, "version", "2"),
    ]:
        with pytest.raises(ValidationError, match="frozen"):
            setattr(target, field, value)
    data["codes"][0]["effective_evidence"][1]["value"]["raw_text"] = "Changed caller dictionary"
    assert canonical_manifest_bytes(manifest) == before


def test_model_construct_does_not_bypass_reference_revalidation():
    bad = portal_reference()
    bad["raw_text"] = "Unbound constructed text"
    constructed = ETTLegalPortalMetadataEvidence.model_construct(**bad)
    data = manifest_with_portal()
    data["codes"][0]["effective_evidence"][1] = constructed
    with pytest.raises(ValidationError):
        validate_manifest(data)


def test_schema_consistency_cannot_attest_a_fabricated_but_self_consistent_observation():
    reference = portal_reference()
    change_literal(reference, "value", "01.01.2000")
    align_row_projection(reference)
    # Original-byte replay belongs to the separate binder; schema acceptance
    # cannot claim that this internally consistent text exists in the source.
    model = ETTLegalPortalMetadataEvidence.model_validate(reference)
    assert model.value.raw_text == "01.01.2000"
    assert "verified" not in model.model_dump()
