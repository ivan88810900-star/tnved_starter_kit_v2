"""Original-source replay, plan ambiguity and report provenance controls."""
from dataclasses import asdict
import hashlib
import json

import pytest

from app.services.ett_amendment_inventory import parse_amendment_inventory
from app.services.ett_discovery_audit import (
    ETTDiscoveryAuditError, audit_legal_discovery, build_notes_census, canonical_json_bytes,
)
from scripts import audit_ett_discovery as cli
from tests.ett_index_fixtures import synthetic_index_html
from tests.test_ett_legal_search import CATEGORY, row, page
from tests.test_ett_portal_search_capture import body, run, url


def encoded(value):
    return json.dumps(value, ensure_ascii=False, default=str).encode()


def matched_row(document="1", number="66", adopted="19.04.2022", category=None, **kwargs):
    return row(number=number, document=document, adopted=adopted,
               category=category or CATEGORY.replace("2026", "2022"), **kwargs)


def notes_census():
    quote = "Решением Коллегии Евразийской экономической комиссии от 19 апреля 2022 г. № 66"
    return {"source_document_sha256": "b" * 64, "legal_dates_verified": False,
            "legal_inventory_complete": False, "act_reference_count": 1,
            "unique_act_identities_requiring_primary_body_review": 1,
            "act_identities": [{"issuing_body": "Коллегии", "adopted_on": "2022-04-19", "number": "66",
                                "primary_act_body_verified": False, "effective_date_verified": False,
                                "needs_primary_body_review": True,
                                "references": [{"footnote_id": "1C", "reason": "repeal_statement",
                                                "logical_text_quote": quote,
                                                "logical_text_quote_sha256": hashlib.sha256(quote.encode()).hexdigest(),
                                                "logical_text_span": [4, 4 + len(quote)],
                                                "source_rows": [{"page": 1, "row": "p0001:r00003", "raw_text_sha256": "c" * 64}]}]}]}


def make_inputs(tmp_path, *, pages=None, notes=None):
    """Original inputs and private retained store, reusable by capture tests."""
    index = synthetic_index_html()
    inventory = encoded(asdict(parse_amendment_inventory(index)))
    note_raw = encoded(notes if notes is not None else notes_census())
    capture, store, _ = run(tmp_path, pages or {url(1): body(rows=matched_row())})
    pagination = encoded(capture)
    for raw in (index, inventory, note_raw, pagination):
        store.put(raw)
    return index, inventory, note_raw, pagination, store


def audit_fixture(tmp_path, **kwargs):
    *originals, store = make_inputs(tmp_path, **kwargs)
    return audit_legal_discovery(*originals, store.read), store


def test_exact_identity_plan_retains_both_reference_families_and_original_row_evidence(tmp_path):
    report, _ = audit_fixture(tmp_path)
    assert report["matched_amendment_count"] == report["matched_notes_identity_count"] == report["capture_target_count"] == 1
    target = report["capture_plan"][0]
    assert target["identity"] == {"issuing_body": "collegium", "adoption_date": "2022-04-19", "number": "66"}
    assert target["page_url"] == target["observations"][0]["document_link"]["url"]
    assert len(target["amendment_references"]) == len(target["note_references"]) == 1
    assert target["observations"][0]["evidence"]["locator"].startswith("html:search-row:1:")
    assert report["capture_plan_sha256"] == hashlib.sha256(canonical_json_bytes(report["capture_plan"])).hexdigest()
    assert report["notes_original_pdf_replayed"] is False
    assert report["legal_inventory_complete"] is report["adoption_dates_verified"] is report["effective_dates_verified"] is False
    assert len(report["amendments_not_observed_as_unambiguous_identity"]) == 2
    assert report["founding_act_match"]["status"] == "not_observed_as_strict_identity"


def test_observed_founding_act_is_captured_separately_without_inflating_amendments(tmp_path):
    founding = matched_row(number="80", adopted="14.09.2021", label="Решение Совета ЕЭК № 80",
                           category=CATEGORY.replace("Коллегия", "Совет").replace("2026", "2021"))
    report, _ = audit_fixture(tmp_path, pages={url(1): body(rows=founding)})
    assert report["founding_act_match"]["status"] == "observed_unambiguous_identity"
    assert report["named_amendment_count"] == 3
    assert report["matched_amendment_count"] == report["matched_notes_identity_count"] == 0
    assert report["capture_target_count"] == 1
    target = report["capture_plan"][0]
    assert len(target["founding_references"]) == 1
    assert target["amendment_references"] == target["note_references"] == []
    assert target["identity"] == {"issuing_body": "council", "adoption_date": "2021-09-14", "number": "80"}


def test_repeated_same_identity_and_url_across_distinct_pages_deduplicates_with_all_observations(tmp_path):
    pages = {url(1): body(rows=matched_row(), links=[(2, "2")]),
             url(2): body(rows=matched_row() + row(document="2"))}
    report, _ = audit_fixture(tmp_path, pages=pages)
    assert report["capture_target_count"] == 1
    assert len(report["capture_plan"][0]["observations"]) == 2
    assert report["row_count"] == 3


@pytest.mark.parametrize("same_url", [False, True])
def test_identity_url_conflicts_are_excluded_from_capture_plan(tmp_path, same_url):
    second = matched_row(document="1" if same_url else "2", number="67" if same_url else "66")
    pages = {url(1): body(rows=matched_row(), links=[(2, "2")]), url(2): body(rows=second + row(document="3"))}
    report, _ = audit_fixture(tmp_path, pages=pages)
    assert report["capture_plan"] == []
    assert len(report["ambiguities"]) == 1
    assert report["matched_amendment_count"] == 0


def test_typo_label_retained_as_unresolved_diagnostic_never_repaired(tmp_path):
    report, _ = audit_fixture(tmp_path, pages={url(1): body(rows=matched_row(label="Решение Коллеги ЕЭК № 66"))})
    assert report["capture_target_count"] == 0
    assert report["row_diagnostics"][0]["status"] == "unresolved_decision_identity"
    assert "Коллеги" in report["row_diagnostics"][0]["evidence"]["text"]
    assert report["document_absence_verified"] is False


@pytest.mark.parametrize("changes", [{"label": "Решение Совета ЕЭК № 66"}, {"category": "Международные договоры"}])
def test_same_url_with_any_non_strict_source_identity_is_quarantined(tmp_path, changes):
    pages = {url(1): body(rows=matched_row(), links=[(2, "2")]),
             url(2): body(rows=matched_row(**changes) + row(document="2"))}
    report, _ = audit_fixture(tmp_path, pages=pages)
    assert report["capture_plan"] == []
    conflict = report["ambiguities"][0]
    assert "observed_url_has_non_strict_identity" in conflict["reasons"]
    assert conflict["observations"][0]["document_link"]["url"] == conflict["conflicting_observations"][0]["document_link"]["url"]


@pytest.mark.parametrize("field,value", [("number", "67"), ("issuing_body", "council"), ("adoption_date", "2022-04-20")])
def test_modified_index_report_cannot_authorize_a_new_target(tmp_path, field, value):
    index, inventory, notes, pagination, store = make_inputs(tmp_path)
    parsed = json.loads(inventory)
    parsed["amendments"][0][field] = value
    with pytest.raises(ETTDiscoveryAuditError, match="index inventory"):
        audit_legal_discovery(index, encoded(parsed), notes, pagination, store.read)


@pytest.mark.parametrize("mutation", ["hash", "parent", "rows", "total", "effective", "next", "incomplete"])
def test_invalid_capture_provenance_or_claims_fail_before_plan(tmp_path, mutation):
    values = make_inputs(tmp_path, pages={url(1): body(rows=matched_row(), links=[(2, "2")]), url(2): body(rows=row(document="2"))})
    index, inventory, notes, pagination, store = values
    report = json.loads(pagination)
    if mutation == "hash": report["results"][0]["sha256"] = "f" * 64
    if mutation == "parent": report["results"][1]["followed_from"]["link"]["locator"] = "invented"
    if mutation == "rows": report["results"][0]["accepted_raw_rows"] += 1
    if mutation == "total": report["captured_bytes"] -= 1
    if mutation == "effective": report["effective_dates_verified"] = True
    if mutation == "next": report["results"][1]["requested_url"] = url(3)
    if mutation == "incomplete": report["observed_chain_exhausted"] = False
    with pytest.raises(ETTDiscoveryAuditError):
        audit_legal_discovery(index, inventory, notes, encoded(report), store.read)


@pytest.mark.parametrize("mutation", ["quote_hash", "body", "span", "duplicate", "date", "reference_count"])
def test_notes_reference_inconsistency_fails_closed(tmp_path, mutation):
    notes = notes_census()
    act = notes["act_identities"][0]
    ref = act["references"][0]
    if mutation == "quote_hash": ref["logical_text_quote_sha256"] = "d" * 64
    if mutation == "body": act["issuing_body"] = "Совета"
    if mutation == "span": ref["logical_text_span"][1] += 1
    if mutation == "duplicate": notes["act_identities"].append(act); notes["unique_act_identities_requiring_primary_body_review"] += 1
    if mutation == "date": act["adopted_on"] = "2022-04-20"
    if mutation == "reference_count": notes["act_reference_count"] += 1
    with pytest.raises(ETTDiscoveryAuditError):
        audit_fixture(tmp_path, notes=notes)


def test_duplicate_json_keys_are_rejected(tmp_path):
    index, inventory, notes, pagination, store = make_inputs(tmp_path)
    with pytest.raises(ETTDiscoveryAuditError, match="duplicate JSON"):
        audit_legal_discovery(index, inventory, notes, pagination.replace(b'{', b'{"schema_version":1,', 1), store.read)


def test_source_reader_cannot_return_substituted_html(tmp_path):
    *originals, store = make_inputs(tmp_path)
    with pytest.raises(ETTDiscoveryAuditError, match="original bytes"):
        audit_legal_discovery(*originals, lambda digest: store.read(digest) + b" ")


def test_fresh_notes_replayed_from_pdf_can_add_an_index_unlisted_identity(tmp_path):
    from app.services.ett_notes import extract_tariff_notes
    from tests.test_ett_notes import _pdf
    pdf = _pdf([["1С) В соответствии с Решением Коллегии Евразийской",
                 "экономической комиссии от 19 апреля 2022 г. № 67."]])
    extraction = extract_tariff_notes(pdf, artifact_id="synthetic-notes")
    index, inventory, _, pagination, store = make_inputs(tmp_path, pages={url(1): body(rows=matched_row(number="67"))})
    store.put(pdf)
    result = audit_legal_discovery(index, inventory, encoded(extraction), pagination, store.read)
    assert result["notes_original_pdf_replayed"] is True
    assert result["matched_amendment_count"] == 0
    assert result["matched_notes_identity_count"] == result["capture_target_count"] == 1
    assert result["capture_plan"][0]["amendment_references"] == []
    assert result["capture_plan"][0]["note_references"][0]["references"][0]["reason"] == "act_citation"
    assert result["effective_dates_verified"] is False
    extraction["notes"][0]["logical_text"] += " invented"
    with pytest.raises(ETTDiscoveryAuditError, match="does not replay"):
        audit_legal_discovery(index, inventory, encoded(extraction), pagination, store.read)


def test_legacy_report_alone_cannot_add_an_index_unlisted_capture_target(tmp_path):
    notes = notes_census()
    act = notes["act_identities"][0]
    act["number"] = "67"
    ref = act["references"][0]
    ref["logical_text_quote"] = ref["logical_text_quote"].replace("66", "67")
    ref["logical_text_quote_sha256"] = hashlib.sha256(ref["logical_text_quote"].encode()).hexdigest()
    report, _ = audit_fixture(tmp_path, notes=notes, pages={url(1): body(rows=matched_row(number="67"))})
    assert report["capture_plan"] == []
    assert any(r["status"] == "notes_only_identity_requires_original_pdf_replay" for r in report["row_diagnostics"])


def supplementary_report(store, *, rows=None):
    from scripts.probe_ett_portal_search import probe_portal_search
    from tests.test_ett_portal_search_capture import source
    # The real runner's default three queries supply actual validated metadata;
    # source HTML must echo each independent query exactly.
    def fetch(q):
        from urllib.parse import urlencode
        requested = "https://docs.eaeunion.org/documents/search/?" + urlencode({"q": q})
        return source(page(rows if rows is not None else matched_row(), query=q, pagination=False), requested)
    return encoded(probe_portal_search(store, fetch=fetch))


def test_supplementary_original_search_rows_union_without_duplicate_targets(tmp_path):
    index, inventory, notes, pagination, store = make_inputs(tmp_path)
    supplemental = supplementary_report(store)
    result = audit_legal_discovery(index, inventory, notes, pagination, store.read, supplementary_report_raws=(supplemental,))
    assert result["supplementary_page_count"] == 3
    assert result["capture_target_count"] == 1
    assert len(result["capture_plan"][0]["observations"]) == 4
    assert result["inputs"]["supplementary_probe_report_sha256s"] == [hashlib.sha256(supplemental).hexdigest()]
    data = json.loads(supplemental)
    data["results"][1]["query"] = "unobserved"
    with pytest.raises(ETTDiscoveryAuditError, match="query disagrees"):
        audit_legal_discovery(index, inventory, notes, pagination, store.read, supplementary_report_raws=(encoded(data),))


def test_supplementary_duplicate_reports_and_bad_sha_fail(tmp_path):
    *originals, store = make_inputs(tmp_path)
    supplemental = supplementary_report(store)
    with pytest.raises(ETTDiscoveryAuditError, match="duplicate supplementary"):
        audit_legal_discovery(*originals, store.read, supplementary_report_raws=(supplemental, supplemental))
    data = json.loads(supplemental)
    data["results"][0]["sha256"] = "d" * 64
    with pytest.raises(ETTDiscoveryAuditError):
        audit_legal_discovery(*originals, store.read, supplementary_report_raws=(encoded(data),))


def test_supplementary_actual_identity_can_fill_a_title_query_gap(tmp_path):
    *originals, store = make_inputs(tmp_path)
    supplemental = supplementary_report(store, rows=row(number="102", adopted="11.08.2026"))
    result = audit_legal_discovery(*originals, store.read, supplementary_report_raws=(supplemental,))
    assert result["matched_amendment_count"] == result["capture_target_count"] == 2
    assert {r["identity"]["number"] for r in result["capture_plan"]} == {"66", "102"}
    assert result["legal_inventory_complete"] is False


@pytest.mark.parametrize("bound", ["bytes", "rows"])
def test_supplementary_stops_at_remaining_budget_before_reading_later_objects(tmp_path, monkeypatch, bound):
    from app.services import ett_discovery_audit as audit
    *originals, store = make_inputs(tmp_path)
    supplemental = supplementary_report(store)
    records = json.loads(supplemental)["results"]
    title = json.loads(originals[-1])["results"][0]
    seen = []
    def read(digest):
        seen.append(digest)
        return store.read(digest)
    if bound == "bytes":
        monkeypatch.setattr(audit, "MAX_TOTAL_BYTES", title["size_bytes"] + records[0]["size_bytes"] - 1)
    else:
        monkeypatch.setattr(audit, "MAX_ROWS", 2)
    with pytest.raises(ETTDiscoveryAuditError, match="aggregate discovery"):
        audit_legal_discovery(*originals, read, supplementary_report_raws=(supplemental,))
    assert seen == ([title["sha256"]] if bound == "bytes" else
                    [title["sha256"], records[0]["sha256"], records[1]["sha256"]])


def test_cli_retains_original_report_bytes_and_never_overwrites_output(tmp_path, capsys):
    *originals, store = make_inputs(tmp_path)
    args = []
    for name, raw in zip(("index", "inventory", "notes", "pagination"), originals):
        path = tmp_path / (name + ".json")
        path.write_bytes(raw)
        args.extend(("--" + name, str(path)))
    output = tmp_path / "audit.json"
    args.extend(("--store-root", str(tmp_path / "objects"), "--output", str(output)))
    assert cli.main(args) == 0
    report = json.loads(output.read_bytes())
    assert report["capture_target_count"] == 1
    for raw in originals:
        assert store.read(hashlib.sha256(raw).hexdigest()) == raw
    saved = output.read_bytes()
    assert cli.main(args) == 2
    assert output.read_bytes() == saved
