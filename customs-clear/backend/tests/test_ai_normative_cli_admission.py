"""Legacy AI CLI entry points cannot initialize or write an application database."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from unittest.mock import Mock

import pytest

from scripts import sync_invoice_codes as invoice
from scripts import sync_missing_codes as missing


@pytest.mark.parametrize("module", [invoice, missing])
def test_apply_cli_blocks_before_file_database_or_provider_access(module, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [module.__name__, "--excel", "/unavailable/no-file.xlsx"])
    probe = Mock(side_effect=AssertionError("Input read before admission guard"))
    monkeypatch.setattr(module, "_codes_from_excel", probe)
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 2 and probe.call_count == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "manual_review_required"
    assert result["db_mutated"] is False
    assert result["active_rates_written"] is False
    assert result["active_measures_written"] is False
    assert result["imported"] == 0


@pytest.mark.parametrize("function,args", [
    (invoice._apply_payload, ("8517130000", {"duty_percent": 7.5, "vat_import_percent": 10,
                                            "approved": True, "non_tariff_items": [{"document_required": "ФСБ"}]})),
    (invoice._ensure_commodity, (None, "8517130000", "AI placeholder")),
    (invoice._gemini_payload, ("8517130000",)),
    (missing._gemini_rate_row, ("8517130000",)),
])
def test_direct_legacy_helpers_cannot_bypass_cli_admission(function, args):
    with pytest.raises(PermissionError, match="ai_normative_review_required"):
        function(*args)


@pytest.mark.parametrize("module", [invoice, missing])
def test_real_cli_does_not_create_database_or_call_provider(module, tmp_path):
    database = tmp_path / "must-not-exist.db"
    env = dict(os.environ, DATABASE_URL="sqlite:///" + str(database), GEMINI_API_KEY="unusable-test-value",
               GOOGLE_API_KEY="", CUSTOMSCLEAR_READ_ONLY="0")
    run = subprocess.run([sys.executable, module.__file__, "--excel", str(tmp_path / "absent.xlsx")],
                         capture_output=True, text=True, env=env, timeout=20)
    assert run.returncode == 2, run.stderr
    assert json.loads(run.stdout)["status"] == "manual_review_required"
    assert not database.exists()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("module", [invoice, missing])
def test_dry_run_requires_no_implicit_database(module, monkeypatch, tmp_path, capsys):
    source = tmp_path / "input.xlsx"
    source.write_bytes(b"Explicit parser input fixture")
    monkeypatch.setattr(module, "_codes_from_excel", lambda _: ["8517130000", "2402200000"])
    monkeypatch.setattr(sys, "argv", [module.__name__, "--dry-run", "--excel", str(source)])
    module.main()
    result = json.loads(capsys.readouterr().out)
    assert result["database_checked"] is False and result["missing_rate_codes"] is None
    assert result["database_sha256"] is None and result["database_size_bytes"] is None
    assert result["invoice_codes"] == ["8517130000", "2402200000"]
    assert result["status"] == "manual_review_required"


@pytest.mark.parametrize("module", [invoice, missing])
def test_explicit_snapshot_lookup_is_read_only_and_distinguishes_missing_codes(module, monkeypatch, tmp_path, capsys):
    source = tmp_path / "input.xlsx"
    source.write_bytes(b"Explicit parser input fixture")
    database = tmp_path / "snapshot.sqlite"
    db = sqlite3.connect(database)
    db.execute("CREATE TABLE hs_rates (hs_code TEXT)")
    db.execute("INSERT INTO hs_rates VALUES (?)", ("8517130000",))
    db.commit()
    db.close()
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    monkeypatch.setattr(module, "_codes_from_excel", lambda _: ["8517130000", "2402200000"])
    monkeypatch.setattr(sys, "argv", [module.__name__, "--dry-run", "--excel", str(source), "--database", str(database)])
    module.main()
    result = json.loads(capsys.readouterr().out)
    assert result["database_checked"] is True and result["missing_rate_codes"] == ["2402200000"]
    assert result["database_sha256"] == before
    assert result["database_size_bytes"] == database.stat().st_size
    assert result["database_read_method"] == "bounded_in_memory_snapshot"
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    assert {p.name for p in tmp_path.iterdir()} == {"input.xlsx", "snapshot.sqlite"}


@pytest.mark.parametrize("lookup", [invoice._missing_hs_rate_codes, missing._missing_in_hs_rates])
def test_missing_snapshot_is_rejected_without_creating_it(lookup, tmp_path):
    database = tmp_path / "absent.sqlite"
    with pytest.raises(ValueError, match="explicit existing"):
        lookup(["8517130000"], database)
    with pytest.raises(ValueError, match="explicit existing"):
        lookup(["8517130000"])
    assert not database.exists()


@pytest.mark.parametrize("script", ["bulk_ai_importer.py", "historical_crawler.py"])
def test_checkpoint_reset_cli_rejects_before_creating_or_opening_database(script, tmp_path):
    database = tmp_path / "must-not-exist.db"
    env = dict(os.environ, DATABASE_URL="sqlite:///" + str(database), GEMINI_API_KEY="unusable-test-value",
               GOOGLE_API_KEY="", CUSTOMSCLEAR_READ_ONLY="0")
    path = Path(invoice.__file__).parent / script
    run = subprocess.run([sys.executable, str(path), "--reset-checkpoints"],
                         capture_output=True, text=True, env=env, timeout=20)
    assert run.returncode == 2, run.stderr
    result = json.loads(run.stdout)
    assert result["status"] == "manual_review_required"
    assert result["db_mutated"] is False and result["checkpoints_deleted"] is False
    assert list(tmp_path.iterdir()) == []


def test_bulk_list_only_does_not_create_source_directory_or_job(monkeypatch, tmp_path, capsys):
    from scripts import bulk_ai_importer as cli
    raw = tmp_path / "absent-raw"
    monkeypatch.setattr(cli, "RAW_NORMATIVE_DIR", raw)
    create = Mock(side_effect=AssertionError("job must not be created"))
    monkeypatch.setattr(cli, "create_import_job", create)
    monkeypatch.setattr(sys, "argv", [cli.__name__, "--list-only"])
    cli.main()
    assert create.call_count == 0 and not raw.exists()
    assert "Найдено файлов: 0" in capsys.readouterr().out


@pytest.mark.parametrize("status,exit_code", [("manual_review_required", 2), ("error", 1)])
def test_bulk_cli_reports_job_state_without_generic_success(status, exit_code, monkeypatch, tmp_path, capsys):
    from scripts import bulk_ai_importer as cli
    from unittest.mock import AsyncMock
    monkeypatch.setattr(cli, "RAW_NORMATIVE_DIR", tmp_path / "raw")
    monkeypatch.setattr(cli, "create_import_job", lambda: 1)
    worker = AsyncMock()
    monkeypatch.setattr(cli, "run_bulk_import", worker)
    monkeypatch.setattr(cli, "get_job_status", lambda _: {"job": {"id": 1, "status": status, "measures_applied": 0},
                                                         "application_status": "manual_review_required"})
    monkeypatch.setenv("GEMINI_API_KEY", "not-a-provider-call")
    monkeypatch.setattr(sys, "argv", [cli.__name__, "--delay", "0"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == exit_code and worker.await_count == 1
    output = capsys.readouterr().out
    assert "Готово" not in output
    assert json.loads(output.splitlines()[-1])["job"]["status"] == status


@pytest.mark.parametrize("status,exit_code", [("manual_review_required", 2), ("error", 1)])
def test_historical_cli_reports_extraction_state_without_claiming_application(status, exit_code, monkeypatch, capsys):
    from scripts import historical_crawler as cli
    from unittest.mock import AsyncMock
    worker = AsyncMock(return_value={"status": status, "measures_applied": 0, "active_rates_written": False})
    monkeypatch.setattr(cli, "run_historical_crawl", worker)
    monkeypatch.setenv("GEMINI_API_KEY", "not-a-provider-call")
    monkeypatch.setattr(sys, "argv", [cli.__name__])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == exit_code and worker.await_count == 1
    result = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert result["status"] == status and result["active_rates_written"] is False


@pytest.mark.parametrize("live_wal", [False, True])
@pytest.mark.parametrize("lookup", [invoice._missing_hs_rate_codes, missing._missing_in_hs_rates])
def test_wal_snapshot_is_refused_without_creating_or_ignoring_sidecars(lookup, live_wal, tmp_path):
    database = tmp_path / "wal-snapshot.sqlite"
    writer = sqlite3.connect(database)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("CREATE TABLE hs_rates (hs_code TEXT)")
    writer.execute("INSERT INTO hs_rates VALUES (?)", ("8517130000",))
    writer.commit()
    if not live_wal:
        writer.close()
        assert {path.name for path in tmp_path.iterdir()} == {database.name}
    before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in tmp_path.iterdir()}
    try:
        with pytest.raises(ValueError, match="WAL or unsupported|journal/sidecar"):
            lookup(["8517130000"], database)
        after = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in tmp_path.iterdir()}
        assert after == before
    finally:
        if live_wal:
            writer.close()


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
@pytest.mark.parametrize("dangling_symlink", [False, True])
def test_rollback_snapshot_with_any_sidecar_is_refused_before_sqlite_open(suffix, dangling_symlink, monkeypatch, tmp_path):
    database = tmp_path / "snapshot.sqlite"
    writer = sqlite3.connect(database)
    writer.execute("CREATE TABLE hs_rates (hs_code TEXT)")
    writer.commit()
    writer.close()
    sidecar = Path(str(database) + suffix)
    if dangling_symlink:
        sidecar.symlink_to(tmp_path / "absent-journal")
    else:
        sidecar.write_bytes(b"Do not ignore pending journal evidence")
    probe = Mock(side_effect=AssertionError("SQLite must not open a live snapshot"))
    monkeypatch.setattr(invoice.sqlite3, "connect", probe)
    with pytest.raises(ValueError, match="journal/sidecar"):
        invoice._missing_hs_rate_codes(["8517130000"], database)
    assert probe.call_count == 0
    if dangling_symlink:
        assert sidecar.is_symlink()
    else:
        assert sidecar.read_bytes() == b"Do not ignore pending journal evidence"


def test_snapshot_identity_change_during_read_is_not_returned_as_a_result(monkeypatch, tmp_path):
    database = tmp_path / "snapshot.sqlite"
    writer = sqlite3.connect(database)
    writer.execute("CREATE TABLE hs_rates (hs_code TEXT)")
    writer.commit()
    writer.close()
    original = invoice._snapshot_identity
    identities = []

    def changed_on_second_validation(path):
        value = original(path)
        identities.append(value)
        return value if len(identities) == 1 else (*value[:-1], value[-1] + 1)

    monkeypatch.setattr(invoice, "_snapshot_identity", changed_on_second_validation)
    probe = Mock(side_effect=AssertionError("Changed source must not reach SQLite"))
    monkeypatch.setattr(invoice.sqlite3, "connect", probe)
    with pytest.raises(ValueError, match="identity changed during bounded"):
        invoice._missing_hs_rate_codes(["8517130000"], database)
    assert probe.call_count == 0


def test_user_snapshot_path_is_never_opened_through_sqlite(monkeypatch, tmp_path):
    database = tmp_path / "snapshot.sqlite"
    writer = sqlite3.connect(database)
    writer.execute("CREATE TABLE hs_rates (hs_code TEXT)")
    writer.commit()
    writer.close()
    real_connect = sqlite3.connect
    calls = []

    def isolated_only(path, *args, **kwargs):
        calls.append(path)
        assert path == ":memory:"
        return real_connect(path, *args, **kwargs)

    monkeypatch.setattr(invoice.sqlite3, "connect", isolated_only)
    assert invoice._missing_hs_rate_codes(["8517130000"], database) == ["8517130000"]
    assert calls == [":memory:"]


def test_symlink_source_is_rejected_without_touching_target(monkeypatch, tmp_path):
    target = tmp_path / "target.sqlite"
    target.write_bytes(b"not opened")
    link = tmp_path / "snapshot.sqlite"
    link.symlink_to(target)
    probe = Mock(side_effect=AssertionError("Symlink source must not reach SQLite"))
    monkeypatch.setattr(invoice.sqlite3, "connect", probe)
    with pytest.raises(ValueError, match="explicit existing"):
        invoice._missing_hs_rate_codes(["8517130000"], link)
    assert probe.call_count == 0 and target.read_bytes() == b"not opened"


def test_oversized_snapshot_is_rejected_before_body_read(monkeypatch, tmp_path):
    database = tmp_path / "large.sqlite"
    with database.open("wb") as out:
        out.truncate(64 * 1024 * 1024 + 1)
    read = Mock(side_effect=AssertionError("Oversized snapshot body must not be read"))
    monkeypatch.setattr(invoice.os, "read", read)
    with pytest.raises(ValueError, match="unsupported_snapshot_size"):
        invoice._missing_hs_rate_codes(["8517130000"], database)
    assert read.call_count == 0


def test_fifo_replacement_cannot_block_snapshot_open(tmp_path):
    code = """
import os
from pathlib import Path
import sqlite3
import sys
from scripts import sync_invoice_codes as invoice

database = Path(sys.argv[1])
with sqlite3.connect(database) as writer:
    writer.execute("CREATE TABLE hs_rates (hs_code TEXT)")
original = invoice._snapshot_identity
replaced = False
def swap_to_fifo(path):
    global replaced
    value = original(path)
    if not replaced:
        replaced = True
        path.unlink()
        os.mkfifo(path)
    return value
invoice._snapshot_identity = swap_to_fifo
try:
    invoice._missing_hs_rate_codes(["8517130000"], database)
except (ValueError, OSError):
    print("rejected_without_blocking")
else:
    raise AssertionError("FIFO replacement accepted")
"""
    database = tmp_path / "replace.sqlite"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(invoice.__file__).resolve().parents[1])
    run = subprocess.run([sys.executable, "-c", code, str(database)], capture_output=True, text=True,
                         timeout=5, env=env)
    assert run.returncode == 0, run.stderr
    assert run.stdout.strip() == "rejected_without_blocking"


def test_mutation_while_source_bytes_are_read_is_rejected(monkeypatch, tmp_path):
    database = tmp_path / "snapshot.sqlite"
    writer = sqlite3.connect(database)
    writer.execute("CREATE TABLE hs_rates (hs_code TEXT)")
    writer.commit()
    writer.close()
    real_read = os.read
    changed = False

    def append_after_header(fd, count):
        nonlocal changed
        result = real_read(fd, count)
        if not changed:
            changed = True
            with database.open("ab") as other_writer:
                other_writer.write(b"changed-by-test")
        return result

    monkeypatch.setattr(invoice.os, "read", append_after_header)
    probe = Mock(side_effect=AssertionError("Mutated source must not reach SQLite"))
    monkeypatch.setattr(invoice.sqlite3, "connect", probe)
    with pytest.raises(ValueError, match="changed during bounded"):
        invoice._missing_hs_rate_codes(["8517130000"], database)
    assert probe.call_count == 0


def test_symlink_replacement_during_read_is_rejected(monkeypatch, tmp_path):
    database = tmp_path / "snapshot.sqlite"
    writer = sqlite3.connect(database)
    writer.execute("CREATE TABLE hs_rates (hs_code TEXT)")
    writer.commit()
    writer.close()
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    moved = tmp_path / "retained-original.sqlite"
    real_read = os.read
    changed = False

    def replace_path_after_header(fd, count):
        nonlocal changed
        result = real_read(fd, count)
        if not changed:
            changed = True
            database.rename(moved)
            database.symlink_to(moved)
        return result

    monkeypatch.setattr(invoice.os, "read", replace_path_after_header)
    probe = Mock(side_effect=AssertionError("Replaced source must not reach SQLite"))
    monkeypatch.setattr(invoice.sqlite3, "connect", probe)
    with pytest.raises((ValueError, OSError)):
        invoice._missing_hs_rate_codes(["8517130000"], database)
    assert probe.call_count == 0
    assert database.is_symlink() and hashlib.sha256(moved.read_bytes()).hexdigest() == before
