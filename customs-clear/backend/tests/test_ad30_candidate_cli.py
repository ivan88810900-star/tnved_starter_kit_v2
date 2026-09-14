"""Real offline CLI process: strict inputs, explicit review and no DB writes."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.test_ad30_duty_preview import candidate_facts


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/preview_ad30_candidate.py"


def scenario(**changes):
    value = {"as_of": "2026-09-14", "facts": candidate_facts(), "currency": "RUB",
             "customs_value": "0.01", "source_row_id": "foshan_vinmay"}
    value.update(changes)
    return value


def run_cli(tmp_path, *, data=None, raw=None, filename=None):
    arguments = [sys.executable, str(SCRIPT)]
    if filename is not None:
        arguments += ["--input", str(filename)]
    database = tmp_path / "application-must-not-exist.db"
    before = sorted(path.name for path in tmp_path.iterdir())
    process = subprocess.run(arguments, input=raw if raw is not None else json.dumps(scenario() if data is None else data),
                             cwd=tmp_path, text=True, capture_output=True, timeout=20,
                             env={**os.environ, "DATABASE_URL": "sqlite:///" + str(database)})
    assert sorted(path.name for path in tmp_path.iterdir()) == before
    assert not database.exists()
    assert process.stderr == ""
    output = json.loads(process.stdout)
    assert output["legal_applicability"] == "unavailable"
    assert output["review_required"] is True
    for key in ("legal_approval", "final_payable", "can_promote", "active_rates_written", "db_mutated"):
        assert output[key] is False
    return process.returncode, output


def test_stdin_cli_exposes_exact_trace_without_starting_application(tmp_path):
    code, output = run_cli(tmp_path)
    assert code == 0
    assert output["status"] == "calculated"
    assert output["amount"] == "0.001462"
    assert output["calculation"]["amount"] == output["amount"]
    assert output["calculation"]["trace"][0]["operands"] == ["0.01", "14.62", "100"]
    assert output["rounding_applied"] is False
    assert output["producer_identity_verified"] is False


def test_regular_file_is_read_without_any_write_or_output_artifact(tmp_path):
    path = tmp_path / "scenario.json"
    raw = json.dumps(scenario(source_row_id="other_producers"))
    path.write_text(raw)
    code, output = run_cli(tmp_path, filename=path)
    assert code == 0 and output["amount"] == "0.001728"
    assert path.read_text() == raw


@pytest.mark.parametrize("row_id,row_index", [("foshan_vinmay", 0), ("guangdong_sumwin", 1), ("other_producers", 2)])
@pytest.mark.parametrize("customs_value", ["1000", None])
def test_selected_row_and_percent_unit_have_complete_standalone_source_evidence(tmp_path, row_id, row_index, customs_value):
    code, output = run_cli(tmp_path, data=scenario(source_row_id=row_id, customs_value=customs_value))
    assert code == (0 if customs_value is not None else 3)
    selected = output["selected_source_row"]
    evidence = selected["source_evidence"]
    assert [item["fact_id"] for item in evidence] == [f"d12.{row_id}_row", "d12.rate_unit"]
    root = Path(__file__).resolve().parents[3]
    for item in evidence:
        assert item["body_sha256"] == "1d6936be2b492b2976e03b3558c55c36062a89dc612ffe54f7e54af49a372c4b"
        assert item["source_url"] == "https://docs.eaeunion.org/upload/iblock/08a/wp70m6eckvicuanvf0sfo4sxqaro4aax/err_12022021_12_doc.pdf"
        assert item["page"] == 3
        assert item["locator"] and item["observation_kind"]
        assert item["evidence_path"] == "docs/ai-workflow/evidence/eec-ad30-decision12-capture-review-20260912.json"
        raw = (root / item["evidence_path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == item["evidence_file_sha256"]
        pointed = json.loads(raw)
        for token in item["json_pointer"].split("/")[1:]:
            pointed = pointed[int(token)] if isinstance(pointed, list) else pointed[token]
        assert json.loads(item["value_json"]) == pointed
    assert evidence[0]["json_pointer"] == f"/document_observations/annex/producer_rows/{row_index}"
    assert json.loads(evidence[0]["value_json"])["rate_text_printed"] == selected["rate_percent_literal"]
    assert json.loads(evidence[1]["value_json"]) == "процентов от таможенной стоимости"
    assert output["original_artifacts_verified"] is False
    assert output["source_text_verified"] is False


@pytest.mark.parametrize("changes", [{"source_row_id": None}, {"customs_value": None}, {"facts": {}}, {"facts": candidate_facts(welded=False)}])
def test_valid_incomplete_or_excluded_scenario_uses_review_exit_without_zero(tmp_path, changes):
    code, output = run_cli(tmp_path, data=scenario(**changes))
    assert code == 3
    assert output["amount"] is None and output["calculation"] is None


@pytest.mark.parametrize("raw", [
    '{"as_of":"2026-09-14","as_of":"2021-01-01"}',
    '{"facts":{"welded":true,"welded":false}}',
    '{"customs_value":NaN}', '{"customs_value":Infinity}',
    '{"customs_value":1.5}', '{"customs_value":1e309}',
    '{"customs_value":' + '9' * 100 + '}',
    '[]', 'null', 'true', '{}', '{bad json}',
    '[' * 2000 + '0' + ']' * 2000, ' ' * (64 * 1024 + 1),
])
def test_bad_duplicate_nonfinite_float_oversized_and_deep_input_is_rejected(tmp_path, raw):
    code, output = run_cli(tmp_path, raw=raw)
    assert code == 2 and output["status"] == "invalid_input"
    assert output["amount"] is None


@pytest.mark.parametrize("changes", [
    {"as_of": None}, {"as_of": "2026-9-14"}, {"as_of": "2026-09-14T00:00:00"},
    {"as_of": "2026-02-30"}, {"as_of": 20260914},
    {"legal_approval": True}, {"assessment": {"candidate_scope": "matches_source_candidate"}},
    {"source_facts": {}}, {"source_row_id": "unknown"}, {"source_row_id": True},
    {"facts": []}, {"currency": "CNY"}, {"customs_value": True},
])
def test_dates_forged_grants_and_unsupported_fields_cannot_enter_preview(tmp_path, changes):
    code, output = run_cli(tmp_path, data=scenario(**changes))
    assert code == 2 and output["amount"] is None


@pytest.mark.parametrize("kind", ["symlink", "fifo", "directory", "oversize", "invalid_utf8"])
def test_nonregular_and_oversize_input_never_blocks_or_gets_modified(tmp_path, kind):
    path = tmp_path / "input.json"
    if kind == "symlink":
        path.symlink_to(SCRIPT)
    elif kind == "fifo":
        os.mkfifo(path)
    elif kind == "directory":
        path.mkdir()
    elif kind == "oversize":
        path.write_bytes(b" " * (64 * 1024 + 1))
    else:
        path.write_bytes(b"\xff")
    code, output = run_cli(tmp_path, filename=path)
    assert code == 2 and output["amount"] is None
