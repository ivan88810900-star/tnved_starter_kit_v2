"""Independent A5 attacks on the isolated AD30 review, never legal approval."""
from dataclasses import replace
from datetime import date
from decimal import Decimal, localcontext
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from app.services.ad30_source_facts import AD30SourceFactsError, load_ad30_source_facts
from app.services.ad30_applicability import assess_ad30_candidate
from app.services.ad30_duty_preview import preview_ad30_duty

ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "customs-clear/backend"
SCRIPT = BACKEND / "scripts/preview_ad30_candidate.py"
RECORD_DIR = ROOT / "docs/ai-workflow/evidence"
DOSSIER = "customs-clear/backend/app/data/official_sources/ad30_source_facts_v1.json"


def product(**changes):
    facts = dict(direction="import", destination="RU", origin_country="CN",
                 commodity_code="7306402009", tubular_product=True, welded=True,
                 corrosion_resistant_steel=True, cross_section="round",
                 wall_thickness_mm="0.4", outer_diameter_mm="6")
    return {**facts, **changes}


def preview(**changes):
    inputs = dict(as_of=date(2026, 9, 14), facts=product(), source_row_id="foshan_vinmay",
                  customs_value="1000000", currency="RUB")
    return preview_ad30_duty(**{**inputs, **changes})


def test_normalized_origin_is_not_a_literal_pdf_transcription():
    # Independently read preserved Decision 12 page 2. The PDF prints the
    # inflected phrase "происходящих из Китайской Народной Республики".
    fact = next(f for f in load_ad30_source_facts().facts if f.fact_id == "d12.origin")
    assert json.loads(fact.value_json) == "Китайская Народная Республика"
    assert fact.observation_kind in {"recorded_origin_label", "recorded_visual_summary"}
    assert fact.page == 2 and fact.locator == "clause 1"


def test_each_pdf_and_quarantined_card_binding_matches_retained_record_metadata():
    records = {
        "d12": json.loads((RECORD_DIR / "eec-ad30-decision12-capture-review-20260912.json").read_text()),
        "d4": json.loads((RECORD_DIR / "eec-ad30-decision4-notice-review-20260912.json").read_text()),
        "d121": json.loads((RECORD_DIR / "eec-ad30-source-discovery-20260912.json").read_text()),
    }
    pdf12 = next(s for s in records["d12"]["capture"]["sources"] if s["capture_status"] == "original_retained")
    pdf4 = records["d4"]["documents"][0]
    pdf121 = records["d121"]["retained_original_reused"]
    pdf_metadata = {
        "d12": (pdf12["body_sha256"], pdf12["response"]["url"], 3),
        "d4": (pdf4["body_sha256"], pdf4["official_url"], pdf4["page_count"]),
        "d121": (pdf121["sha256"], pdf121["url"], pdf121["page_count"]),
    }
    cards = {str(c["document_number"]): c for c in records["d12"]["retained_card_metadata_observations"]["cards"]}
    for fact in load_ad30_source_facts().facts:
        prefix = fact.fact_id.split(".")[0]
        assert hashlib.sha256((ROOT / fact.evidence_path).read_bytes()).hexdigest() == fact.evidence_file_sha256
        if fact.fact_id.endswith("card_metadata"):
            card = cards[prefix[1:]]
            assert (fact.body_sha256, fact.source_url) == (card["body_sha256"], card["url"])
            assert card["capture_status"] == "quarantined_content_rejected"
            assert fact.page is None
            assert fact.observation_kind == "quarantined_portal_metadata_observation"
        else:
            body, url, page_count = pdf_metadata[prefix]
            assert (fact.body_sha256, fact.source_url) == (body, url)
            assert fact.page is None or 1 <= fact.page <= page_count
            assert fact.locator


@pytest.mark.parametrize("row,expected", [("foshan_vinmay", "146200"),
    ("guangdong_sumwin", "172800"), ("other_producers", "172800")])
def test_printed_annex_operands_are_hypotheses_with_no_automatic_producer_admission(row, expected):
    # Independent source-page reading: 14,62 / 17,28 / 17,28 percent of value.
    result = preview(source_row_id=row)
    assert result["amount"] == Decimal(expected)
    assert result["row_selection_kind"] == "hypothetical_source_row"
    assert result["selected_source_row"]["row_id"] == row
    assert result["producer_identity_verified"] is False
    assert result["legal_applicability"] == result["temporal_applicability"] == "unavailable"
    assert result["applied"] is result["final_payable"] is result["can_promote"] is False
    assert result["final_payable_amount"] is None


@pytest.mark.parametrize("row", ["foshan_vinmay", "guangdong_sumwin", "other_producers"])
def test_hypothetical_money_row_carries_resolved_rate_and_unit_source_evidence(row):
    selected = preview(source_row_id=row)["selected_source_row"]
    evidence = selected["source_evidence"]
    assert {fact["fact_id"] for fact in evidence} == {f"d12.{row}_row", "d12.rate_unit"}
    for fact in evidence:
        assert fact["body_sha256"] == "1d6936be2b492b2976e03b3558c55c36062a89dc612ffe54f7e54af49a372c4b"
        assert fact["page"] == 3 and fact["locator"].startswith("annex ")
        assert fact["source_url"].endswith("err_12022021_12_doc.pdf")
        raw = (ROOT / fact["evidence_path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == fact["evidence_file_sha256"]
        value = json.loads(raw)
        for part in fact["json_pointer"].split("/")[1:]:
            value = value[int(part)] if isinstance(value, list) else value[part]
        assert json.loads(fact["value_json"]) == value
        assert fact["observation_kind"] == "recorded_visual_transcription"


@pytest.mark.parametrize("mutation", [
    lambda b: replace(b, facts=(replace(b.facts[0], source_url=b.facts[-1].source_url), *b.facts[1:])),
    lambda b: replace(b, rate_rows=(replace(b.rate_rows[0], rate_percent_literal="NaN"), *b.rate_rows[1:])),
    lambda b: replace(b, rate_rows=(replace(b.rate_rows[0], evidence_ids=("d121.effective_clause",)), *b.rate_rows[1:])),
    lambda b: replace(b, source_text_verified=True),
])
def test_forged_dto_is_rejected_by_product_assessment_and_money_boundary(mutation):
    forged = mutation(load_ad30_source_facts())
    for call in (lambda: assess_ad30_candidate(as_of=date(2026, 9, 14), facts=product(), source_facts=forged),
                 lambda: preview(source_facts=forged)):
        with pytest.raises(AD30SourceFactsError):
            call()


@pytest.mark.parametrize("facts", [
    {"commodity_code": "7306402009"}, product(origin_country="ZZ"),
    product(welded=False), product(cross_section="other"),
    product(direction="export"), product(commodity_code="7306402000"),
    product(cross_section="rectangular", perimeter_mm="240", max_side_mm="120"),
    product(destination="DE", wall_thickness_mm=float("nan")),
])
def test_no_arithmetic_or_zero_liability_for_missing_outside_or_invalid_product(facts):
    result = preview(facts=facts)
    assert result["amount"] is result["calculation"] is None
    assert result["final_payable_amount"] is None
    assert result["review_required"] is True
    assert result["legal_applicability"] == "unavailable"


@pytest.mark.parametrize("as_of", [date(1900, 1, 1), date(2021, 3, 13), date(2021, 3, 14),
    date(2026, 3, 14), date(2026, 10, 11), date(2031, 9, 8), date(9999, 12, 31)])
def test_explicit_dates_never_convert_prose_or_portal_dates_into_legal_interval(as_of):
    result = preview(as_of=as_of)
    assert result["as_of"] == as_of.isoformat()
    assert result["temporal_applicability"] == "unavailable"
    assert result["assessment"]["effective_dates_verified"] is False
    assert "effective_dates_unverified" in result["assessment"]["review_blockers"]


def test_subcent_preview_preserves_exact_value_under_hostile_decimal_context():
    with localcontext() as context:
        context.prec = 2
        result = preview(customs_value=Decimal("0.01"))
    assert result["amount"] == Decimal("0.001462")
    assert result["rounding_applied"] is False
