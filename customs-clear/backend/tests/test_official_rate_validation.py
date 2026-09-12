"""Malformed official-bundle source cells cannot acquire invented rates."""

from decimal import Decimal
import hashlib
import importlib
import json

import pytest

from app.services import excise_ingestion, vat_ingestion
from app.services.official_rate_validation import explicit_nonnegative_rate, load_official_rate_json, rate_value_diagnostic


@pytest.mark.parametrize("value,expected", [
    (0, 0.0), (0.0, 0.0), ("0", 0.0), ("0,0", 0.0),
    (Decimal("0"), 0.0), (10, 10.0), (22.0, 22.0),
    ("2,75", 2.75), (" 2.75 ", 2.75), (Decimal("2.75"), 2.75),
    ("2800", 2800.0), (1e-300, 1e-300),
])
def test_existing_explicit_finite_values_and_true_zero_are_preserved(value, expected):
    assert explicit_nonnegative_rate(value) == expected


@pytest.mark.parametrize("value", [
    None, "", " ", "not-a-rate", "1e2", "2/3", "10%", "NaN", "Infinity",
    True, False, [], {}, -1, "-0.1", float("nan"), float("inf"), float("-inf"),
    Decimal("NaN"), Decimal("Infinity"), Decimal("1e400"), Decimal("1e-400"),
    "1" * 129, 10 ** 1000, Decimal("1" * 65), Decimal("1e1000000"),
])
def test_invalid_source_cells_have_no_numeric_fallback(value):
    with pytest.raises(ValueError):
        explicit_nonnegative_rate(value)


@pytest.mark.parametrize("domain,module,field,extract,validate", [
    ("vat", vat_ingestion, "vat_import_rate", vat_ingestion._extract_vat_rows, vat_ingestion._validate_official_vat_bundle_payload),
    ("excise", excise_ingestion, "excise_value", excise_ingestion._extract_excise_rows, excise_ingestion._validate_official_excise_bundle_payload),
])
@pytest.mark.parametrize("value", [None, "", "not-a-rate", "NaN", float("inf"), True, -1, {}, Decimal("1e-400")])
def test_official_extractors_and_parser_readiness_reject_the_same_bad_cell(domain, module, field, extract, validate, value):
    payload = _payload(domain, field, value)
    original = dict(payload["rates"][0])
    _, rows, blockers = extract(payload)
    assert rows == [] and len(blockers) == 1
    assert f"invalid_{domain}_rate" in blockers[0]
    assert "row=1" in blockers[0] and "0101210000" in blockers[0]
    assert f"raw={rate_value_diagnostic(value)}" in blockers[0]
    parsed = validate(payload, rel_path="unused.json", checksum="a" * 64)
    assert parsed["status"] == "parser_failed"
    assert parsed["reason"] == f"invalid_{domain}_rate_value"
    assert parsed["rate_diagnostics"] == blockers
    assert parsed["invalid_rate_count"] == 1
    assert parsed["checksum_sha256"] == "a" * 64
    assert payload["rates"][0] == original


def _payload(domain, field, value):
    return {
        "format": "customs_clear_normative_bundle",
        "revision": f"{domain}:2026-09-08",
        "source_url": "https://www.nalog.gov.ru/rn77/about_fts/docs/12345678",
        "rates": [{"hs_code": "0101210000", field: value,
                   **({"vat_rule": "standard"} if domain == "vat" else {"excise_type": "fixed"})}],
    }


@pytest.mark.parametrize("domain,module,field,extract", [
    ("vat", vat_ingestion, "vat_import_rate", vat_ingestion._extract_vat_rows),
    ("excise", excise_ingestion, "excise_value", excise_ingestion._extract_excise_rows),
])
def test_explicit_null_and_true_zero_are_not_silently_ignored_without_other_signal(domain, module, field, extract):
    payload = _payload(domain, field, None)
    payload["rates"] = [{"hs_code": "0101210000", field: None}]
    _, rows, blockers = extract(payload)
    assert not rows and blockers
    payload["rates"][0][field] = 0
    if domain == "excise":
        # A zero scalar alone does not say whether this is a zero-rated excise
        # or a non-excisable product. The existing "none" form is explicit.
        _, rows, blockers = extract(payload)
        assert not rows and "missing_excise_type" in blockers[0]
        payload["rates"][0]["excise_type"] = "none"
    _, rows, blockers = extract(payload)
    assert not blockers and len(rows) == 1 and rows[0][field] == 0


@pytest.mark.parametrize("domain,field,extract", [
    ("vat", "vat_import_rate", vat_ingestion._extract_vat_rows),
    ("excise", "excise_value", excise_ingestion._extract_excise_rows),
])
def test_basis_or_rule_without_numeric_source_value_requires_review(domain, field, extract):
    payload = _payload(domain, field, 22)
    del payload["rates"][0][field]
    _, rows, blockers = extract(payload)
    assert rows == [] and "missing_rate_value" in blockers[0]


@pytest.mark.parametrize("domain,field,extract", [
    ("vat", "vat_import_rate", vat_ingestion._extract_vat_rows),
    ("excise", "excise_value", excise_ingestion._extract_excise_rows),
])
def test_mixed_source_rows_preserve_actual_bad_row_locator(domain, field, extract):
    payload = _payload(domain, field, 0)
    payload["rates"].append({**payload["rates"][0], "hs_code": "0101291000", field: "unreadable"})
    _, rows, blockers = extract(payload)
    assert len(rows) == 1 and rows[0][field] == 0
    assert len(blockers) == 1 and "row=2" in blockers[0]
    assert "0101291000" in blockers[0] and "raw='unreadable'" in blockers[0]


@pytest.mark.parametrize("domain,module,field,dry,apply", [
    ("vat", vat_ingestion, "vat_import_rate", vat_ingestion.run_vat_dry_run, vat_ingestion.run_vat_apply),
    ("excise", excise_ingestion, "excise_value", excise_ingestion.run_excise_dry_run, excise_ingestion.run_excise_apply),
])
@pytest.mark.parametrize("literal", ['"unreadable"', "NaN", "Infinity", "1e-400", "1e400", "null"])
def test_actual_bundle_bytes_block_before_db_or_provenance_access(domain, module, field, dry, apply, literal, tmp_path, monkeypatch):
    relative = f"data/raw_normative/eec_{'ett_vat' if domain == 'vat' else 'excise'}.json"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    payload = _payload(domain, field, "PLACEHOLDER")
    payload["rates"].insert(0, {"hs_code": "0101291000", field: 0,
                              **({"excise_type": "none"} if domain == "excise" else {})})
    source = json.dumps(payload).replace('"PLACEHOLDER"', literal).encode()
    path.write_bytes(source)
    monkeypatch.setattr(module, "_BACKEND_ROOT", tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("invalid source reached database/planning/provenance")

    for name in ("SessionLocal", "append_sync_log", "upsert_source_status",
                 f"_plan_{domain}_rows", f"_apply_{domain}_rows"):
        monkeypatch.setattr(module, name, forbidden)
    for operation in (dry, apply):
        result = operation(rel_path=relative)
        assert result["status"] == "parser_failed"
        assert result["db_mutated"] is False
        assert result["parser_result"]["checksum_sha256"] == hashlib.sha256(source).hexdigest()
        if literal in {"NaN", "Infinity"}:
            assert result["parser_result"]["reason"] == "invalid_bundle_json"
            assert "nonfinite_json_number" in result["parser_result"]["error"]
        else:
            assert result["parser_result"]["reason"] == f"invalid_{domain}_rate_value"
            assert result["parser_result"]["invalid_rate_count"] == 1
            assert "row=2" in result["parser_result"]["rate_diagnostics"][0]
    assert path.read_bytes() == source


@pytest.mark.parametrize("domain,module,field,extract", [
    ("vat", vat_ingestion, "vat_import_rate", vat_ingestion._extract_vat_rows),
    ("excise", excise_ingestion, "excise_value", excise_ingestion._extract_excise_rows),
])
def test_source_decimal_literals_still_load_and_extract_known_finite_values(domain, module, field, extract, tmp_path, monkeypatch):
    path = tmp_path / "rates.json"
    path.write_text(json.dumps(_payload(domain, field, 2.75)))
    monkeypatch.setattr(module, "_BACKEND_ROOT", tmp_path)
    payload, parsed = module._load_bundle_payload("rates.json")
    assert parsed["status"] == "parsed"
    assert payload["rates"][0][field] == Decimal("2.75")
    _, rows, blockers = extract(payload)
    assert not blockers and rows[0][field] == 2.75


@pytest.mark.parametrize("domain,module,field", [
    ("vat", vat_ingestion, "vat_import_rate"),
    ("excise", excise_ingestion, "excise_value"),
])
@pytest.mark.parametrize("literal", ["1e999999999999999999999999999999", "1" * 5000])
def test_out_of_range_json_numbers_are_parser_failures_not_unhandled_errors(domain, module, field, literal, tmp_path, monkeypatch):
    path = tmp_path / "rates.json"
    source = json.dumps(_payload(domain, field, "PLACEHOLDER")).replace('"PLACEHOLDER"', literal)
    path.write_text(source)
    monkeypatch.setattr(module, "_BACKEND_ROOT", tmp_path)
    payload, parsed = module._load_bundle_payload("rates.json")
    assert payload is None and parsed["status"] == "parser_failed"
    assert path.read_text() == source


def test_source_diagnostics_are_bounded_and_do_not_expand_containers_or_custom_repr():
    class Unexpected:
        def __repr__(self):
            raise AssertionError("arbitrary repr must not run")

    assert len(rate_value_diagnostic("x" * 10000)) < 180
    assert "exceeds" in rate_value_diagnostic(10 ** 10000)
    assert rate_value_diagnostic({"arbitrary": "content"}) == "<dict>"
    assert rate_value_diagnostic(Unexpected()) == "<Unexpected>"


@pytest.mark.parametrize("kind,value,reason", [
    (None, 5, "missing_excise_type"), ("", 5, "missing_excise_type"),
    (" ", 5, "missing_excise_type"), (True, 5, "invalid_excise_type"),
    ({}, 5, "invalid_excise_type"), ("combined_max", 5, "unsupported_excise_type"),
    ("combined_sum", 5, "unsupported_excise_type"), ("specific", 5, "unsupported_excise_type"),
    ("needs_review", 0, "unsupported_excise_type"), ("unknown", 0, "unsupported_excise_type"),
    ("none", 5, "nonzero_non_excisable_value"), (None, 0, "missing_excise_type"),
])
def test_unrepresented_excise_forms_cannot_normalize_into_zero_or_not_applicable(kind, value, reason):
    payload = _payload("excise", "excise_value", value)
    if kind is None:
        del payload["rates"][0]["excise_type"]
    else:
        payload["rates"][0]["excise_type"] = kind
    _, rows, blockers = excise_ingestion._extract_excise_rows(payload)
    assert rows == [] and len(blockers) == 1
    assert reason in blockers[0]
    assert f"excise_type={rate_value_diagnostic(kind)}" in blockers[0]
    parsed = excise_ingestion._validate_official_excise_bundle_payload(payload, rel_path="unused", checksum="a" * 64)
    assert parsed["status"] == "parser_failed"
    assert parsed["rate_diagnostics"] == blockers


@pytest.mark.parametrize("kind,value,normalized", [
    ("percent", 5, "percent"), ("fixed", 10, "fixed"),
    ("percent", 0, "percent"), ("fixed", 0, "fixed"),
    ("none", 0, "none"), ("NONE", "0", "none"),
    (" PERCENT ", "2,75", "percent"),
])
def test_supported_explicit_excise_forms_preserve_zero_and_normalize_known_spelling(kind, value, normalized):
    payload = _payload("excise", "excise_value", value)
    payload["rates"][0]["excise_type"] = kind
    _, rows, blockers = excise_ingestion._extract_excise_rows(payload)
    assert not blockers and len(rows) == 1
    assert rows[0]["excise_type"] == normalized
    assert rows[0]["excise_value"] == explicit_nonnegative_rate(value)


@pytest.mark.parametrize("kind", [None, "combined_max", "none"])
def test_unsupported_or_contradictory_excise_form_blocks_mixed_bundle_before_plan(kind, tmp_path, monkeypatch):
    relative = "data/raw_normative/eec_excise.json"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    payload = _payload("excise", "excise_value", 5)
    if kind is None:
        del payload["rates"][0]["excise_type"]
    else:
        payload["rates"][0]["excise_type"] = kind
    payload["rates"].insert(0, {"hs_code": "0101291000", "excise_type": "none", "excise_value": 0})
    path.write_text(json.dumps(payload))
    monkeypatch.setattr(excise_ingestion, "_BACKEND_ROOT", tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("unrepresented form reached database/planning/provenance")

    for name in ("SessionLocal", "append_sync_log", "upsert_source_status", "_plan_excise_rows", "_apply_excise_rows"):
        monkeypatch.setattr(excise_ingestion, name, forbidden)
    for operation in (excise_ingestion.run_excise_dry_run, excise_ingestion.run_excise_apply):
        result = operation(rel_path=relative)
        assert result["status"] == "parser_failed" and result["db_mutated"] is False
        assert result["parser_result"]["invalid_rate_count"] == 1
        assert "row=2" in result["parser_result"]["rate_diagnostics"][0]


@pytest.mark.parametrize("source", [
    '{"rate_value":15,"rate_value":0}',
    '{"rate_value":0,"rate_value":0}',
    '{"rows":[{"rate_type":"percent","rate_type":"specific"}]}',
    '{"revision":"seed","revision":"official"}',
    '{"metadata":{"origin_country":"CN","origin_country":"RU"}}',
    r'{"rate_value":15,"\u0072ate_value":0}',
])
def test_duplicate_object_names_are_rejected_even_when_values_match_or_names_are_escaped(source):
    with pytest.raises(ValueError, match="duplicate_json_key"):
        load_official_rate_json(source)


def test_unique_objects_and_decimal_literals_keep_their_exact_values():
    source = b'{"rows":[{"rate_value":0},{"rate_value":1e-400}],"metadata":{"other":1.25}}'
    payload = load_official_rate_json(source)
    assert payload["rows"][0]["rate_value"] == 0
    assert payload["rows"][1]["rate_value"] == Decimal("1e-400")
    assert payload["metadata"]["other"] == Decimal("1.25")


_SOURCE_DOMAINS = ("vat", "excise", "anti_dumping", "special_safeguard", "countervailing")


def _source_bundle(domain):
    if domain in {"vat", "excise"}:
        value_field = "vat_import_rate" if domain == "vat" else "excise_value"
        payload = _payload(domain, value_field, 5)
        rows_key = "rates"
        type_field = "vat_rule" if domain == "vat" else "excise_type"
    else:
        value_field, type_field, rows_key = "rate_value", "rate_type", "measures"
        payload = {
            "revision": domain.replace("_", "-") + ":2026-09-08",
            "official_url": "https://eec.eaeunion.org/comission/department/deptexsec/trade_remedies/",
            "measures": [{"hs_code": "0101210000", "measure_type": domain,
                          "rate_type": "percent", "rate_value": 5,
                          "regulatory_act": "Synthetic test, not legal evidence"}],
        }
    payload[rows_key][0]["origin_country"] = "CN"
    return payload, rows_key, value_field, type_field


@pytest.mark.parametrize("domain", _SOURCE_DOMAINS)
@pytest.mark.parametrize("duplicate", ["rate", "type", "revision", "country", "metadata"])
def test_every_official_loader_rejects_duplicate_source_keys_before_plan(domain, duplicate, tmp_path, monkeypatch):
    module = importlib.import_module("app.services." + domain + "_ingestion")
    payload, rows_key, value_field, type_field = _source_bundle(domain)
    source = json.dumps(payload)
    if duplicate == "rate":
        target = json.dumps(value_field) + ": 5"
        replacement = json.dumps(value_field) + ": 15, " + json.dumps(value_field) + ": 0"
    elif duplicate == "type":
        target = json.dumps(type_field) + ": " + json.dumps(payload[rows_key][0][type_field])
        replacement = target + ", " + json.dumps(type_field) + ': "none"'
    elif duplicate == "revision":
        target = '"revision": ' + json.dumps(payload["revision"])
        replacement = '"revision": "seed", ' + target
    elif duplicate == "country":
        target, replacement = '"origin_country": "CN"', '"origin_country": "CN", "origin_country": "RU"'
    else:
        target, replacement = '"revision":', '"metadata": {"sha": "a", "sha": "b"}, "revision":'
    assert target in source
    source_bytes = source.replace(target, replacement, 1).encode()
    _assert_invalid_source_before_plan(domain, module, source_bytes, "duplicate_json_key", tmp_path, monkeypatch)


@pytest.mark.parametrize("domain", _SOURCE_DOMAINS)
@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_metadata_is_rejected_by_every_official_loader(domain, constant, tmp_path, monkeypatch):
    module = importlib.import_module("app.services." + domain + "_ingestion")
    payload, _, _, _ = _source_bundle(domain)
    source = json.dumps(payload).replace('"revision":', '"metadata": {"observation": ' + constant + '}, "revision":', 1).encode()
    _assert_invalid_source_before_plan(domain, module, source, "nonfinite_json_number", tmp_path, monkeypatch)


def _assert_invalid_source_before_plan(domain, module, source, error, tmp_path, monkeypatch):
    filename = "eec_" + ("ett_vat" if domain == "vat" else domain) + ".json"
    relative = "data/raw_normative/" + filename
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(source)
    monkeypatch.setattr(module, "_BACKEND_ROOT", tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("ambiguous source reached database/planning/provenance")

    for name in ("SessionLocal", "append_sync_log", "upsert_source_status",
                 f"_plan_{domain}_rows", f"_apply_{domain}_rows"):
        monkeypatch.setattr(module, name, forbidden)
    for mode in ("dry_run", "apply"):
        result = getattr(module, f"run_{domain}_{mode}")(rel_path=relative)
        assert result["status"] == "parser_failed" and result["db_mutated"] is False
        assert result["parser_result"]["reason"] == "invalid_bundle_json"
        assert error in result["parser_result"]["error"]
        assert result["parser_result"]["checksum_sha256"] == hashlib.sha256(source).hexdigest()
    assert path.read_bytes() == source
