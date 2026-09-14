"""Real offline CLI process: strict inputs, explicit review and no DB writes."""
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
