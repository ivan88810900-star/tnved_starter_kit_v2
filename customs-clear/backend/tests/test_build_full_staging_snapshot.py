from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.core import HsRate
from app.services import normative_store
from app.services.normative_bundle import _normalize_rate_row
from app.services.ntm_catalog_baseline import (
    DEFAULT_BASELINE_PATH,
    DEFAULT_ETT_PATH,
    canonical_duty_rate,
    duty_rate_content_sha256,
)
from scripts import build_full_staging_snapshot as builder


def _load_prepare_database_module():
    spec = importlib.util.spec_from_file_location(
        "staging_prepare_database_test",
        builder.PREPARE_DATABASE_SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_current_pinned_ett_is_explicitly_quarantined() -> None:
    report = builder.inspect_staging_inputs()

    assert report["positive_snapshot_allowed"] is False
    assert report["source_fingerprints"] == {
        "pdf_source_manifest_match": True,
        "active_ett_snapshot_match": True,
        "catalog_parser_match": True,
    }
    assert report["ett"]["raw_rows"] == 13_319
    assert report["ett"]["unique_codes"] == 13_290
    assert report["ett"]["invalid_code_rows"] == 2
    assert report["ett"]["duplicate_rows"] == 27
    assert report["ett"]["duplicate_code_count"] == 23
    assert report["ett"]["material_conflict_code_count"] == 18
    assert report["ett"]["structurally_publishable"] is False
    assert report["release_gate"]["current_official_ett_verified"] is False
    assert report["release_gate"]["temporal_footnotes_verified"] is False


def test_quarantined_build_creates_neither_output_nor_parent(tmp_path: Path) -> None:
    output = tmp_path / "not-created" / "customs-staging.db"

    with pytest.raises(RuntimeError, match="positive staging snapshot blocked"):
        builder.build_full_staging_snapshot(output)

    assert not output.exists()
    assert not output.parent.exists()


def test_clean_active_ett_requires_exact_code_and_duty_fingerprints() -> None:
    payload = {
        "rates": [
            {"hs_code": "0101210000", "duty_rate": "0"},
            {"hs_code": "0101291000", "duty_rate": "5%"},
        ]
    }
    expected_codes = ["0101210000", "0101291000"]
    expected_duties = duty_rate_content_sha256(
        (row["hs_code"], row["duty_rate"]) for row in payload["rates"]
    )

    rows = builder._active_rate_rows(
        payload,
        expected_unique_codes=2,
        expected_code_set_sha256=builder._sha256_lines(expected_codes),
        expected_duty_rate_sha256=expected_duties,
    )

    assert [row["hs_code"] for row in rows] == expected_codes

    payload["rates"][0]["duty_rate"] = "999%"
    with pytest.raises(RuntimeError, match="duty-rate fingerprint mismatch"):
        builder._active_rate_rows(
            payload,
            expected_unique_codes=2,
            expected_code_set_sha256=builder._sha256_lines(expected_codes),
            expected_duty_rate_sha256=expected_duties,
        )


def test_active_ett_rejects_invalid_and_duplicate_rows() -> None:
    payload = {
        "rates": [
            {"hs_code": "0101210000", "duty_rate": "0"},
            {"hs_code": "0101210000", "duty_rate": "999%"},
            {"hs_code": "BAD", "duty_rate": "0"},
        ]
    }

    with pytest.raises(
        RuntimeError,
        match=r"invalid_code_rows=1, duplicate_rows=1",
    ):
        builder._active_rate_rows(
            payload,
            expected_unique_codes=1,
            expected_code_set_sha256="unused",
            expected_duty_rate_sha256="unused",
        )


def test_full_ett_artifact_fingerprint_detects_value_only_mutation(
    tmp_path: Path,
) -> None:
    payload = json.loads(DEFAULT_ETT_PATH.read_text(encoding="utf-8"))
    payload["rates"][0]["duty_rate"] = "999%"
    mutated = tmp_path / "mutated-ett.json"
    mutated.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(RuntimeError, match="pinned staging input drift"):
        builder._verify_pinned_inputs(
            baseline_path=DEFAULT_BASELINE_PATH,
            pdf_dir=builder.DEFAULT_PDF_SOURCE_DIR,
            ett_path=mutated,
        )


def test_duty_rate_canonicalization_is_conservative() -> None:
    assert canonical_duty_rate(0) == canonical_duty_rate("0.0")
    assert canonical_duty_rate("5%") == canonical_duty_rate("5,0")
    assert canonical_duty_rate("10%, но не менее 0,1 EUR") == (
        "text:10%, но не менее 0,1 eur"
    )


def test_generic_exact_rate_never_covers_unknown_sibling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine("sqlite:///:memory:")
    HsRate.__table__.create(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(normative_store, "SessionLocal", sessions)

    row = _normalize_rate_row(
        {"hs_code": "8471300000", "hs_prefix": "8471", "duty_rate": "5%"}
    )
    assert row is not None
    assert row["hs_prefix"] == "8471300000"
    normative_store.upsert_hs_rate(row)

    exact, exact_length = normative_store.find_rate_for_hs("8471300000")
    sibling, sibling_length = normative_store.find_rate_for_hs("8471900000")
    assert exact is not None and exact_length == 10
    assert sibling is None and sibling_length == 0


def test_prepare_validator_rejects_extra_invalid_duplicate_and_mutated_rates() -> None:
    prepare = _load_prepare_database_module()
    database = sqlite3.connect(":memory:")
    database.execute(
        "CREATE TABLE hs_rates (hs_code TEXT, hs_prefix TEXT, duty_rate TEXT)"
    )
    rows = [
        ("0101210000", "0101210000", "0"),
        ("0101291000", "0101291000", "5%"),
    ]
    database.executemany("INSERT INTO hs_rates VALUES (?, ?, ?)", rows)
    expected = {
        "unique_codes": 2,
        "code_set_sha256": prepare._sha256_lines(sorted(row[0] for row in rows)),
        "active_duty_rate_sha256": duty_rate_content_sha256(
            (row[0], row[2]) for row in rows
        ),
    }
    assert prepare._validate_active_ett_rates(database, expected)["rows"] == 2

    database.execute("UPDATE hs_rates SET duty_rate='999%' WHERE hs_code='0101210000'")
    with pytest.raises(RuntimeError, match="duty-rate content"):
        prepare._validate_active_ett_rates(database, expected)
    database.execute("UPDATE hs_rates SET duty_rate='0' WHERE hs_code='0101210000'")

    database.execute("UPDATE hs_rates SET hs_prefix='0101' WHERE hs_code='0101210000'")
    with pytest.raises(RuntimeError, match="broad hs_prefix"):
        prepare._validate_active_ett_rates(database, expected)
    database.execute(
        "UPDATE hs_rates SET hs_prefix='0101210000' WHERE hs_code='0101210000'"
    )

    database.execute("INSERT INTO hs_rates VALUES ('BAD', 'BAD', '999%')")
    with pytest.raises(RuntimeError, match=r"total=3, invalid=1"):
        prepare._validate_active_ett_rates(database, expected)
    database.execute("DELETE FROM hs_rates WHERE hs_code='BAD'")

    database.execute("INSERT INTO hs_rates VALUES ('0101210000', '0101210000', '999%')")
    with pytest.raises(RuntimeError, match=r"total=3, invalid=0, duplicates=1"):
        prepare._validate_active_ett_rates(database, expected)


def test_prepare_validator_independently_enforces_release_quarantine() -> None:
    prepare = _load_prepare_database_module()
    with sqlite3.connect(":memory:") as database:
        with pytest.raises(RuntimeError, match="schema v1 is quarantine-only"):
            prepare._validate_full_catalog(database)


def test_fts_validator_checks_canonical_schema_triggers_and_every_posting() -> None:
    prepare = _load_prepare_database_module()
    with sqlite3.connect(":memory:") as database:
        database.execute(
            "CREATE TABLE tnved_commodities "
            "(id INTEGER PRIMARY KEY, code TEXT, description TEXT)"
        )
        database.execute(prepare.EXPECTED_FTS_TABLE_SQL)
        for sql in prepare.EXPECTED_FTS_TRIGGER_SQL.values():
            database.execute(sql)
        database.executemany(
            "INSERT INTO tnved_commodities VALUES (?, ?, ?)",
            [
                (1, "8509400000", "Машины электромеханические бытовые"),
                (2, "0101210000", "Лошади чистопородные племенные"),
            ],
        )

        assert prepare._validate_fts(database, 2) == 2


def test_fts_validator_rejects_external_content_count_spoof_and_noop_triggers() -> None:
    prepare = _load_prepare_database_module()
    with sqlite3.connect(":memory:") as database:
        database.execute(
            "CREATE TABLE tnved_commodities "
            "(id INTEGER PRIMARY KEY, code TEXT, description TEXT)"
        )
        database.executemany(
            "INSERT INTO tnved_commodities VALUES (?, ?, ?)",
            [
                (1, "8509400000", "Машины электромеханические бытовые"),
                (2, "0101210000", "Лошади чистопородные племенные"),
            ],
        )
        database.execute(prepare.EXPECTED_FTS_TABLE_SQL)
        database.execute(
            "INSERT INTO tnved_fts(rowid, code, description) VALUES (?, ?, ?)",
            (1, "8509400000", "Машины электромеханические бытовые"),
        )
        for name in prepare.EXPECTED_FTS_TRIGGER_SQL:
            database.execute(
                f"CREATE TRIGGER {name} AFTER INSERT ON tnved_commodities "
                "BEGIN SELECT 1; END"
            )

        # An external-content FTS table reports the content-table row count even
        # though only one row has postings.  No-op same-name triggers must not
        # satisfy the schema gate.
        assert database.execute("SELECT COUNT(*) FROM tnved_fts").fetchone() == (2,)
        with pytest.raises(RuntimeError, match="trigger definition mismatch"):
            prepare._validate_fts(database, 2)

        for name in prepare.EXPECTED_FTS_TRIGGER_SQL:
            database.execute(f"DROP TRIGGER {name}")
        for sql in prepare.EXPECTED_FTS_TRIGGER_SQL.values():
            database.execute(sql)
        with pytest.raises(
            RuntimeError,
            match=r"missing_code_matches=1, missing_description_matches=1",
        ):
            prepare._validate_fts(database, 2)


def test_fts_validator_rejects_first_description_token_only_postings() -> None:
    prepare = _load_prepare_database_module()
    with sqlite3.connect(":memory:") as database:
        database.execute(
            "CREATE TABLE tnved_commodities "
            "(id INTEGER PRIMARY KEY, code TEXT, description TEXT)"
        )
        database.execute(
            "INSERT INTO tnved_commodities VALUES (?, ?, ?)",
            (1, "8509400000", "Машины электромеханические бытовые"),
        )
        database.execute(prepare.EXPECTED_FTS_TABLE_SQL)
        for sql in prepare.EXPECTED_FTS_TRIGGER_SQL.values():
            database.execute(sql)
        # Canonical schema and triggers plus an exact code posting can make
        # count/code-only gates look healthy. The description index is
        # intentionally truncated after its first source token.
        database.execute(
            "INSERT INTO tnved_fts(rowid, code, description) VALUES (?, ?, ?)",
            (1, "8509400000", "Машины"),
        )

        assert database.execute("SELECT COUNT(*) FROM tnved_fts").fetchone() == (1,)
        assert database.execute(
            "SELECT 1 FROM tnved_fts WHERE rowid=1 AND tnved_fts MATCH ?",
            ('code:"8509400000"',),
        ).fetchone() == (1,)
        with pytest.raises(
            RuntimeError,
            match=r"missing_code_matches=0, missing_description_matches=1",
        ):
            prepare._validate_fts(database, 1)


def test_description_token_chunks_are_bounded_and_cover_full_sequence() -> None:
    prepare = _load_prepare_database_module()
    tokens = [f"токен{index}" for index in range(61)]
    chunks = prepare._description_token_chunks(" ".join(tokens))

    assert all(len(chunk) <= prepare.FTS_DESCRIPTION_TOKEN_CHUNK_SIZE for chunk in chunks)
    rebuilt = list(chunks[0])
    for chunk in chunks[1:]:
        assert rebuilt[-1] == chunk[0]
        rebuilt.extend(chunk[1:])
    assert rebuilt == tokens

def test_self_approved_schema_v1_baseline_cannot_open_positive_gate(
    tmp_path: Path,
) -> None:
    prepare = _load_prepare_database_module()
    baseline = json.loads(DEFAULT_BASELINE_PATH.read_text(encoding="utf-8"))
    baseline["active_ett"]["structurally_publishable"] = True
    baseline["staging_release_gate"].update(
        {
            "current_official_ett_verified": True,
            "temporal_footnotes_verified": True,
            "positive_snapshot_allowed": True,
        }
    )
    self_approved = tmp_path / "self-approved-v1.json"
    self_approved.write_text(json.dumps(baseline), encoding="utf-8")

    inspection = builder.inspect_staging_inputs(baseline_path=self_approved)
    assert inspection["positive_snapshot_allowed"] is False
    assert any("schema v1 is quarantine-only" in row for row in inspection["blockers"])
    with sqlite3.connect(":memory:") as database:
        with pytest.raises(RuntimeError, match="schema v1 is quarantine-only"):
            prepare._validate_full_catalog(database, self_approved)


def test_isolated_environment_never_inherits_configured_database(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    production_url = "postgresql://production.example/forbidden"
    monkeypatch.setenv("DATABASE_URL", production_url)
    monkeypatch.setenv("CUSTOMSCLEAR_READ_ONLY", "1")
    temporary_database = tmp_path / "fresh.db"

    with builder._isolated_build_environment(temporary_database):
        assert os.environ["DATABASE_URL"] == f"sqlite:///{temporary_database}"
        assert os.environ["CUSTOMSCLEAR_READ_ONLY"] == "0"
        assert os.environ["SCHEDULER_ENABLED"] == "0"
        assert os.environ["REGULATORY_SYNC_SCHEDULER_ENABLED"] == "0"

    assert os.environ["DATABASE_URL"] == production_url
    assert os.environ["CUSTOMSCLEAR_READ_ONLY"] == "1"


def test_existing_snapshot_is_rejected_before_source_build(tmp_path: Path) -> None:
    output = tmp_path / "existing.db"
    output.write_bytes(b"do not overwrite")

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        builder.build_full_staging_snapshot(output)

    assert output.read_bytes() == b"do not overwrite"


def test_source_builder_requires_machine_readable_worker_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    worker = {
        "active_ett": {"active_ett_codes": 13_290},
        "fts": {"rows": 17_809},
        "isolation": {"configured_database_unchanged": True},
    }

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["python"],
            returncode=0,
            stdout=f"worker log\n{json.dumps(worker)}\n",
            stderr="",
        )

    monkeypatch.setattr(builder.subprocess, "run", fake_run)
    result = builder._run_source_builder(
        tmp_path / "source.db",
        pdf_dir=builder.DEFAULT_PDF_SOURCE_DIR,
        ett_path=DEFAULT_ETT_PATH,
    )

    assert result == worker


def test_source_builder_fails_without_measured_database_isolation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    worker = {
        "active_ett": {"active_ett_codes": 13_290},
        "fts": {"rows": 17_809},
        "isolation": {"configured_database_unchanged": False},
    }

    monkeypatch.setattr(
        builder.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=["python"],
            returncode=0,
            stdout=json.dumps(worker),
            stderr="",
        ),
    )
    with pytest.raises(RuntimeError, match="did not prove"):
        builder._run_source_builder(
            tmp_path / "source.db",
            pdf_dir=builder.DEFAULT_PDF_SOURCE_DIR,
            ett_path=DEFAULT_ETT_PATH,
        )
