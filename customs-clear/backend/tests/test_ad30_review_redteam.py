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


def _audited_cli(tmp_path, payload, script=SCRIPT):
    # Run the real CLI in a fresh interpreter. Audit hooks fail the process on
    # attempted network/DB/write activity, including reads of the sentinel DB.
    sentinel = tmp_path / "application-must-not-open.db"
    sentinel.write_bytes(b"A5 isolated sentinel: not a SQLite database")
    harness = r'''
import os, runpy, sys
sys.dont_write_bytecode = True
target = sys.argv[1]
sys.argv = [target]
def audit(event, args):
    if event.startswith(("socket.", "sqlite3.", "subprocess.")):
        raise AssertionError("forbidden offline side effect: " + event)
    if event == "open":
        path, mode, flags = args
        if isinstance(path, (str, bytes)) and os.fsdecode(path).endswith(".db"):
            raise AssertionError("attempted application DB access")
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            raise AssertionError("attempted filesystem mutation")
    if event in {"os.remove", "os.rename", "os.rmdir", "os.mkdir", "os.link", "os.symlink", "os.chmod"}:
        raise AssertionError("attempted filesystem mutation")
sys.addaudithook(audit)
try:
    runpy.run_path(target, run_name="__main__")
finally:
    assert "app.db" not in sys.modules
    assert "app.main" not in sys.modules
'''
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.rglob("*") if p.is_file()}
    process = subprocess.run([sys.executable, "-B", "-c", harness, str(script)],
        input=json.dumps(payload) if not isinstance(payload, str) else payload,
        text=True, capture_output=True, timeout=20, cwd=tmp_path,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "DATABASE_URL": "sqlite:///" + str(sentinel)})
    after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.rglob("*") if p.is_file()}
    assert after == before
    assert process.stderr == ""
    output = json.loads(process.stdout)
    assert output["legal_applicability"] == "unavailable"
    assert output["review_required"] is True
    assert output["legal_approval"] is output["final_payable"] is output["can_promote"] is False
    return process.returncode, output


def _scenario(**changes):
    return {"as_of": "2026-09-14", "facts": product(), "currency": "RUB",
            "customs_value": "0.01", "source_row_id": "foshan_vinmay", **changes}


@pytest.mark.parametrize("changes,exit_code", [
    ({}, 0), ({"source_row_id": "other_producers"}, 0),
    ({"facts": {"commodity_code": "7306402009"}}, 3),
    ({"facts": product(welded=False)}, 3), ({"source_row_id": None}, 3),
    ({"source_row_id": "unknown_producer"}, 2), ({"customs_value": True}, 2),
    ({"as_of": "2026-09-14T00:00:00"}, 2),
    ({"legal_review_verified": True}, 2),
    ({"assessment": {"candidate_scope": "matches_source_candidate"}}, 2),
])
def test_real_cli_cannot_start_application_touch_database_network_or_write(tmp_path, changes, exit_code):
    code, output = _audited_cli(tmp_path, _scenario(**changes))
    assert code == exit_code
    if code == 0:
        assert output["amount"] in {"0.001462", "0.001728"}
        assert len(output["selected_source_row"]["source_evidence"]) == 2
    else:
        assert output["amount"] is None


def _copy_cli_repository(tmp_path):
    relative_paths = [DOSSIER, "customs-clear/backend/scripts/preview_ad30_candidate.py"]
    relative_paths.extend("customs-clear/backend/app/services/" + name + ".py" for name in (
        "ad30_source_facts", "ad30_applicability", "ad30_duty_preview",
        "ett_duty_preview", "ett_manifest", "official_rate_validation"))
    relative_paths.extend(str(p.relative_to(ROOT)) for p in RECORD_DIR.glob("eec-ad30-*.json")
                          if p.name in {"eec-ad30-decision12-capture-review-20260912.json",
                              "eec-ad30-decision4-notice-review-20260912.json",
                              "eec-ad30-source-discovery-20260912.json"})
    for relative in relative_paths:
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    return tmp_path / "customs-clear/backend/scripts/preview_ad30_candidate.py"


@pytest.mark.parametrize("mutation", ["none", "raw_record_whitespace", "own_hash_forgery", "zero_rate", "missing_record"])
def test_real_cli_revalidates_its_actual_repository_bytes_before_arithmetic(tmp_path, mutation):
    script = _copy_cli_repository(tmp_path)
    dossier_path = tmp_path / DOSSIER
    dossier = json.loads(dossier_path.read_text())
    record_path = tmp_path / dossier["evidence_records"][0]["path"]
    if mutation in {"raw_record_whitespace", "own_hash_forgery"}:
        record_path.write_bytes(record_path.read_bytes() + b" ")
        if mutation == "own_hash_forgery":
            dossier["evidence_records"][0]["sha256"] = hashlib.sha256(record_path.read_bytes()).hexdigest()
            dossier_path.write_text(json.dumps(dossier))
    elif mutation == "zero_rate":
        dossier["rate_rows"][0]["rate_percent_literal"] = "0"
        dossier_path.write_text(json.dumps(dossier))
    elif mutation == "missing_record":
        record_path.unlink()
    code, output = _audited_cli(tmp_path, _scenario(), script)
    assert code == (0 if mutation == "none" else 2)
    if mutation != "none":
        assert output["status"] == "invalid_input" and output["amount"] is None
