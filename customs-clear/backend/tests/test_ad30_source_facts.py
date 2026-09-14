"""Source-record identity boundaries; no legal applicability approval."""
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import shutil

import pytest

from app.services.ad30_source_facts import (
    AD30SourceFactsError, DOSSIER_SHA256, load_ad30_source_facts, validate_ad30_source_facts,
)

ROOT = Path(__file__).resolve().parents[3]
DOSSIER_PATH = "customs-clear/backend/app/data/official_sources/ad30_source_facts_v1.json"
RECORDS = (
    "docs/ai-workflow/evidence/eec-ad30-decision12-capture-review-20260912.json",
    "docs/ai-workflow/evidence/eec-ad30-decision4-notice-review-20260912.json",
    "docs/ai-workflow/evidence/eec-ad30-source-discovery-20260912.json",
)


def copy_inputs(tmp_path):
    for name in (DOSSIER_PATH, *RECORDS):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    return tmp_path


def test_exact_source_values_and_distinct_integrity_flags():
    bundle = load_ad30_source_facts()
    assert bundle.dossier_sha256 == DOSSIER_SHA256
    assert len(bundle.facts) == 24
    assert [(r.row_id, r.rate_percent_literal) for r in bundle.rate_rows] == [
        ("foshan_vinmay", "14,62"), ("guangdong_sumwin", "17,28"), ("other_producers", "17,28")]
    assert bundle.rate_rows[0].producer_name == "Foshan Vinmay Stainless Steel Co., Ltd."
    assert bundle.rate_rows[2].producer_name == "прочие"
    assert bundle.rate_rows[2].producer_address is None
    assert bundle.source_record_integrity_verified
    assert not any((bundle.original_artifacts_verified, bundle.source_text_verified,
                    bundle.legal_review_verified, bundle.can_promote, bundle.production_ready,
                    bundle.active_rates_written, bundle.durable_legal_retention_attested))
    facts = {f.fact_id: f for f in bundle.facts}
    assert json.loads(facts["d12.codes"].value_json) == [
        "7306 40 200 9", "7306 40 800 1", "7306 40 800 8", "7306 61 100 9"]
    assert facts["d12.product"].observation_kind == "recorded_visual_summary"
    assert facts["d12.wall"].page == 1
    assert facts["d12.rectangle_dimensions"].page == 2
    assert facts["d12.foshan_vinmay_row"].page == 3
    for doc in ("d12", "d4", "d121"):
        fact = facts[doc + ".card_metadata"]
        assert fact.observation_kind == "quarantined_portal_metadata_observation"
        assert json.loads(fact.value_json)["capture_status"] == "quarantined_content_rejected"


def test_frozen_rows_and_facts_without_mutable_mappings():
    bundle = load_ad30_source_facts()
    with pytest.raises(FrozenInstanceError):
        bundle.rate_rows[0].rate_percent_literal = "0"
    with pytest.raises(FrozenInstanceError):
        bundle.facts[0].value_json = "null"
    checked = validate_ad30_source_facts(bundle)
    assert checked == bundle
    assert checked is not bundle
    assert checked.rate_rows[0] is not bundle.rate_rows[0]


@pytest.mark.parametrize("field,value", [
    ("row_id", "other_producers"), ("producer_name", "Foshan Vinmay"),
    ("producer_address", None), ("rate_percent_literal", "0"),
    ("rate_percent_literal", "14.62"), ("evidence_ids", ("d4.extension",)),
])
def test_copied_dossier_hash_does_not_authorize_changed_rows(field, value):
    bundle = load_ad30_source_facts()
    altered = replace(bundle.rate_rows[0], **{field: value})
    with pytest.raises(AD30SourceFactsError):
        validate_ad30_source_facts(replace(bundle, rate_rows=(altered, *bundle.rate_rows[1:])))


@pytest.mark.parametrize("field,value", [
    ("value_json", '"new rule"'), ("page", 2), ("body_sha256", "0" * 64),
    ("source_url", "https://example.com/document.pdf"), ("json_pointer", "/unrelated"),
    ("observation_kind", "native_verified"), ("evidence_file_sha256", "0" * 64),
])
def test_changed_fact_metadata_is_rejected(field, value):
    bundle = load_ad30_source_facts()
    altered = replace(bundle.facts[0], **{field: value})
    with pytest.raises(AD30SourceFactsError):
        validate_ad30_source_facts(replace(bundle, facts=(altered, *bundle.facts[1:])))


@pytest.mark.parametrize("field", ["original_artifacts_verified", "source_text_verified",
    "legal_review_verified", "can_promote", "production_ready", "active_rates_written",
    "durable_legal_retention_attested"])
def test_no_caller_approval_or_integrity_grant(field):
    with pytest.raises(AD30SourceFactsError):
        validate_ad30_source_facts(replace(load_ad30_source_facts(), **{field: True}))


@pytest.mark.parametrize("change", [
    lambda b: replace(b, facts=b.facts[:-1]),
    lambda b: replace(b, facts=tuple(reversed(b.facts))),
    lambda b: replace(b, rate_rows=(b.rate_rows[0], b.rate_rows[0], b.rate_rows[2])),
    lambda b: replace(b, rate_rows=list(b.rate_rows)),
    lambda b: replace(b, source_record_integrity_verified=1),
    lambda b: replace(b, facts=(replace(b.facts[0], page=True), *b.facts[1:])),
    lambda b: {"dossier_sha256": b.dossier_sha256, "facts": b.facts},
])
def test_missing_reordered_duplicate_or_coerced_values_rejected(change):
    with pytest.raises(AD30SourceFactsError):
        validate_ad30_source_facts(change(load_ad30_source_facts()))


@pytest.mark.parametrize("name", RECORDS)
def test_each_source_record_byte_drift_fails_even_same_json(tmp_path, name):
    copy_inputs(tmp_path)
    path = tmp_path / name
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(AD30SourceFactsError, match="record_hash_mismatch"):
        load_ad30_source_facts(tmp_path)


def test_missing_record_fails_without_fallback(tmp_path):
    copy_inputs(tmp_path)
    (tmp_path / RECORDS[1]).unlink()
    with pytest.raises(AD30SourceFactsError):
        load_ad30_source_facts(tmp_path)


@pytest.mark.parametrize("alter", [
    lambda d: d["rate_rows"][0].update(rate_percent_literal="0"),
    lambda d: d.update(can_promote=True),
    lambda d: d["evidence_records"][0].update(path="../../other.json"),
    lambda d: d["facts"][0].update(value_json='"forged"'),
])
def test_replaced_dossier_cannot_choose_own_pins(tmp_path, alter):
    copy_inputs(tmp_path)
    path = tmp_path / DOSSIER_PATH
    data = json.loads(path.read_text())
    alter(data)
    path.write_text(json.dumps(data))
    with pytest.raises(AD30SourceFactsError, match="identity_mismatch"):
        load_ad30_source_facts(tmp_path)


@pytest.mark.parametrize("raw", [b'{"schema_version":1,"schema_version":1}',
    b'{"x":NaN}', b'{"x":Infinity}', b'[' * 2000, b'x' * (256 * 1024 + 1)])
def test_malformed_or_oversized_dossier_rejected(tmp_path, raw):
    copy_inputs(tmp_path)
    (tmp_path / DOSSIER_PATH).write_bytes(raw)
    with pytest.raises(AD30SourceFactsError):
        load_ad30_source_facts(tmp_path)


def test_source_record_symlink_rejected(tmp_path):
    copy_inputs(tmp_path)
    path = tmp_path / RECORDS[0]
    path.unlink()
    path.symlink_to(ROOT / RECORDS[0])
    with pytest.raises(AD30SourceFactsError):
        load_ad30_source_facts(tmp_path)


def test_source_record_fifo_rejected_without_reading(tmp_path):
    import os
    copy_inputs(tmp_path)
    path = tmp_path / RECORDS[0]
    path.unlink()
    os.mkfifo(path)
    with pytest.raises(AD30SourceFactsError, match="regular_file"):
        load_ad30_source_facts(tmp_path)
