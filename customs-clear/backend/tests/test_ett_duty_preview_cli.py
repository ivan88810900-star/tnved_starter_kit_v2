"""Actual CLI/SQLite/original-quote boundary for provisional candidate money."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models.ett import ETTArtifact, ETTCodeVersion, ETTFootnote, ETTRateRule, ETTSnapshot
from app.services.ett_artifacts import LocalArtifactStore
from app.services.ett_manifest import validate_manifest
from app.services.ett_repository import stage_candidate
from tests.ett_fixtures import artifact_bytes
from tests.test_ett_evidence_binding import source_fixture


@pytest.fixture
def staged_preview(source_fixture, tmp_path):
    original, bodies = source_fixture

    def stage(*, percent="5", conditions=(), fabricated_quote=False, specific=False):
        data = deepcopy(original)
        data["rate_rules"][0]["conditions"] = list(conditions)
        data["rate_rules"][0]["duty"] = (
            {"kind": "specific", "specific_amount": "2.5", "currency": "EUR",
             "unit": "kg", "unit_quantity": "100"}
            if specific else {"kind": "ad_valorem", "ad_valorem_percent": percent}
        )
        if fabricated_quote:
            reference = data["rate_rules"][0]["evidence"][0]
            reference["raw_text"] = "Fabricated but rehashed source rate"
            reference["raw_text_sha256"] = hashlib.sha256(reference["raw_text"].encode()).hexdigest()
        store = LocalArtifactStore(tmp_path / "objects")
        for artifact in data["artifacts"]:
            store.put(bodies.get(artifact["artifact_id"], artifact_bytes(artifact["artifact_id"])))
        database = tmp_path / "candidate-only.db"
        engine = create_engine("sqlite:///" + str(database))
        tables = [model.__table__ for model in
                  (ETTSnapshot, ETTArtifact, ETTCodeVersion, ETTFootnote, ETTRateRule)]
        Base.metadata.create_all(engine, tables=tables)
        try:
            with Session(engine) as session:
                digest = stage_candidate(session, store, validate_manifest(data))["manifest_sha256"]
        finally:
            engine.dispose()
        return database, store, digest

    return stage


def run_preview(tmp_path, staged, inputs, *, as_of="2026-09-08", facts=None,
                input_file=None):
    database, store, digest = staged
    if input_file is None:
        input_file = tmp_path / "calculation.json"
        input_file.write_text(json.dumps(inputs), encoding="utf-8")
    arguments = [sys.executable, "scripts/ett_candidates.py", "preview-duty", digest,
                 "--code", "0101210000", "--as-of", as_of, "--destination", "RU",
                 "--database", str(database), "--store-root", str(store._root),
                 "--calculation-inputs", str(input_file)]
    if facts is not None:
        facts_file = tmp_path / "facts.json"
        facts_file.write_text(json.dumps(facts), encoding="utf-8")
        arguments.extend(["--facts", str(facts_file)])
    before_db = database.read_bytes()
    before_store = {p.name: p.read_bytes() for p in store._root.iterdir()}
    unrelated_database = tmp_path / "must-not-exist-application.db"
    result = subprocess.run(
        arguments, cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "DATABASE_URL": "sqlite:///" + str(unrelated_database),
             "PYTHONPATH": os.pathsep.join(str(Path(p).resolve()) for p in sys.path if p)},
        capture_output=True, text=True, timeout=30,
    )
    assert database.read_bytes() == before_db
    assert {p.name: p.read_bytes() for p in store._root.iterdir()} == before_store
    assert not unrelated_database.exists()
    return result.returncode, json.loads(result.stdout)


@pytest.mark.parametrize("percent, expected", [("5", "6.17"), ("0", "0")])
def test_money_is_exact_and_quote_verified_but_never_legal_or_final(staged_preview, tmp_path, percent, expected):
    code, result = run_preview(tmp_path, staged_preview(percent=percent),
                              {"currency": "RUB", "customs_value": "123.40"})
    assert code == 0
    assert result["status"] == "calculated"
    assert result["calculation"]["amount"] == expected
    assert result["source_quote_verification"]["source_evidence_verified"] is True
    assert result["source_quote_verification"]["duty_interpretation_verified"] is False
    assert result["calculation"]["source_evidence_verified"] is False
    assert result["calculation"]["rounding_applied"] is False
    for flag in ("legal_approval", "final_payable", "production_ready", "can_promote", "active_rates_written"):
        assert result[flag] is False


def test_specific_amount_uses_explicit_dated_currency_factor(staged_preview, tmp_path):
    source_text = "Synthetic declared factor: one EUR = 100 RUB; not official evidence"
    inputs = {"currency": "RUB", "quantity": "10", "quantity_unit": "kg",
              "exchange_rate": {"from_currency": "EUR", "to_currency": "RUB",
                  "as_of": "2026-09-08", "multiplier": "100",
                  "source_url": "https://example.test/synthetic-factor",
                  "source_artifact_sha256": "a" * 64, "source_locator": "synthetic-row:1",
                  "source_text": source_text,
                  "source_text_sha256": hashlib.sha256(source_text.encode()).hexdigest()}}
    code, result = run_preview(tmp_path, staged_preview(specific=True), inputs)
    assert code == 0
    assert result["calculation"]["amount"] == "25"
    assert result["calculation"]["exchange_rate"]["as_of"] == "2026-09-08"
    assert result["calculation"]["source_evidence_verified"] is False


def test_missing_money_does_not_become_zero_even_for_zero_rate(staged_preview, tmp_path):
    code, result = run_preview(tmp_path, staged_preview(percent="0"), {"currency": "RUB"})
    assert code == 3
    assert result["status"] == "needs_clarification"
    assert result["calculation"]["amount"] is None
    assert result["calculation"]["missing_facts"] == ["customs_value"]


@pytest.mark.parametrize("case", ["outside_coverage", "missing_product_fact", "rehash_fabricated_quote"])
def test_uncertain_or_unverified_rule_never_reaches_money(staged_preview, tmp_path, case):
    staged = staged_preview(
        conditions=([{"field": "purpose", "op": "eq", "value": "synthetic-research"}]
                    if case == "missing_product_fact" else []),
        fabricated_quote=case == "rehash_fabricated_quote",
    )
    code, result = run_preview(tmp_path, staged, {"currency": "RUB", "customs_value": "100"},
                              as_of="2027-01-01" if case == "outside_coverage" else "2026-09-08")
    assert code == 3
    assert result["calculation"] is None
    if case == "missing_product_fact":
        assert result["status"] == "needs_clarification"
        assert result["resolution"]["missing_facts"] == ["purpose"]
    else:
        assert result["status"] == "unavailable"
    if case == "rehash_fabricated_quote":
        assert result["reason"] == "candidate_source_quotes_unverified"
        assert result["source_quote_verification"]["source_evidence_verified"] is False
    else:
        assert result["source_quote_verification"] is None


@pytest.mark.parametrize("raw", [
    '{"currency":"RUB","currency":"EUR"}',
    '{"currency":"RUB","customs_value":10.5}',
    '{"currency":"RUB","customs_value":"100","legal_approval":true}',
    '{"currency":"RUB","customs_value":NaN}',
    "[]",
])
def test_invalid_calculation_input_has_sanitized_failure(staged_preview, tmp_path, raw):
    path = tmp_path / "invalid-calculation.json"
    path.write_text(raw, encoding="utf-8")
    code, result = run_preview(tmp_path, staged_preview(), None, input_file=path)
    assert code == 2
    assert result["status"] == "ERROR"
    assert "calculation" not in result
    assert str(tmp_path) not in json.dumps(result)


def test_named_pipe_input_fails_without_blocking(staged_preview, tmp_path):
    path = tmp_path / "calculation-pipe"
    os.mkfifo(path)
    code, result = run_preview(tmp_path, staged_preview(), None, input_file=path)
    assert code == 2
    assert result["status"] == "ERROR"


def test_calculation_input_size_limit_is_enforced(staged_preview, tmp_path):
    path = tmp_path / "oversized-calculation.json"
    path.write_bytes(b" " * (1024 * 1024 + 1))
    code, result = run_preview(tmp_path, staged_preview(), None, input_file=path)
    assert code == 2
    assert result["status"] == "ERROR"
