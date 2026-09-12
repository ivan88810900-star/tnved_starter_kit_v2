#!/usr/bin/env python3
"""Build an immutable, exact full-catalog SQLite snapshot for local staging.

The build is deliberately isolated from the configured application database:
Alembic, the PDF importer and the pinned ETT importer only receive a fresh
temporary SQLite path.  The final file is published only after the same strict
validator used by the staging container accepts it.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from typing import Any, Iterator


BACKEND_ROOT = Path(__file__).resolve().parents[1]
CUSTOMS_CLEAR_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ntm_catalog_baseline import (  # noqa: E402
    DEFAULT_BASELINE_PATH,
    DEFAULT_ETT_PATH,
    DEFAULT_PDF_SOURCE_DIR,
    active_ett_fingerprint,
    compare_source_baseline,
    duty_rate_content_sha256,
    load_catalog_baseline,
    parser_fingerprint,
    pdf_source_manifest,
)


PREPARE_DATABASE_SCRIPT = CUSTOMS_CLEAR_ROOT / "staging" / "prepare_database.py"
ALEMBIC_CONFIG_PATH = BACKEND_ROOT / "alembic.ini"
ALEMBIC_SCRIPT_PATH = BACKEND_ROOT / "alembic"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_lines(lines: list[str]) -> str:
    digest = hashlib.sha256()
    for line in lines:
        digest.update(line.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _file_state(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"measurable_local_file": False}
    try:
        stat = path.stat()
    except FileNotFoundError:
        return {
            "measurable_local_file": True,
            "filename": path.name,
            "exists": False,
        }
    return {
        "measurable_local_file": True,
        "filename": path.name,
        "exists": True,
        "size_bytes": stat.st_size,
        "sha256": _sha256_file(path),
    }


def _configured_database_state() -> dict[str, Any]:
    value = (os.getenv("DATABASE_URL") or "").strip()
    scheme = value.partition(":")[0].lower() if value else "unset"
    path: Path | None = None
    if value.startswith("sqlite:///"):
        raw_path = value[len("sqlite:///") :].split("?", 1)[0]
        if raw_path and raw_path != ":memory:":
            path = Path(raw_path).expanduser().resolve()
    return {"scheme": scheme, **_file_state(path)}


def _active_rate_rows(
    payload: dict[str, Any],
    *,
    expected_unique_codes: int,
    expected_code_set_sha256: str,
    expected_duty_rate_sha256: str,
) -> list[dict[str, Any]]:
    """Return a clean one-row-per-code ETT set or fail closed."""
    raw_rows = payload.get("rates")
    if not isinstance(raw_rows, list):
        raise RuntimeError("pinned ETT bundle has no rates array")
    rows = [
        row
        for row in raw_rows
        if isinstance(row, dict)
        and (code := str(row.get("hs_code") or "").strip()).isdigit()
        and len(code) == 10
    ]
    invalid_rows = len(raw_rows) - len(rows)
    unique_codes = sorted({str(row["hs_code"]).strip() for row in rows})
    duplicate_rows = len(rows) - len(unique_codes)
    if invalid_rows or duplicate_rows:
        raise RuntimeError(
            "pinned ETT is not publishable: "
            f"invalid_code_rows={invalid_rows}, duplicate_rows={duplicate_rows}"
        )
    actual_digest = _sha256_lines(unique_codes)
    if len(unique_codes) != expected_unique_codes:
        raise RuntimeError(
            "pinned ETT active-code count mismatch: "
            f"expected {expected_unique_codes}, got {len(unique_codes)}"
        )
    if actual_digest != expected_code_set_sha256:
        raise RuntimeError("pinned ETT active-code fingerprint mismatch")
    actual_duty_digest = duty_rate_content_sha256(
        (row.get("hs_code"), row.get("duty_rate")) for row in rows
    )
    if actual_duty_digest != expected_duty_rate_sha256:
        raise RuntimeError("pinned ETT duty-rate fingerprint mismatch")
    return sorted(rows, key=lambda row: str(row["hs_code"]).strip())


@contextmanager
def _isolated_build_environment(database: Path) -> Iterator[None]:
    """Point every application DB import at the new temporary database only."""
    overrides = {
        "DATABASE_URL": f"sqlite:///{database}",
        "CUSTOMSCLEAR_READ_ONLY": "0",
        "SCHEDULER_ENABLED": "0",
        "REGULATORY_SYNC_SCHEDULER_ENABLED": "0",
        "CUSTOMSCLEAR_ALLOW_LEGACY_AUTOMATION": "0",
        "TAMDOC_SYNC_ENABLED": "0",
        "AUDIT_LOG_ENABLED": "0",
        "TNVED_SEMANTIC_INGEST_ENABLED": "0",
        "TNVED_SEMANTIC_SEARCH_ENABLED": "0",
        "GEMINI_API_KEY": "",
        "GOOGLE_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
        "OPENAI_API_KEY": "",
    }
    previous = {name: os.environ.get(name) for name in overrides}
    os.environ.update(overrides)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _upgrade_fresh_schema() -> None:
    from alembic import command
    from alembic.config import Config

    config = Config(str(ALEMBIC_CONFIG_PATH))
    # Resolve this explicitly so the builder works from any current directory.
    config.set_main_option("script_location", str(ALEMBIC_SCRIPT_PATH))
    command.upgrade(config, "head")


def _import_catalog(database: Path, pdf_dir: Path) -> None:
    from scripts.import_pdf import run_import

    run_import(data_dir=pdf_dir, db_path=database)


def _import_active_ett(
    database: Path,
    ett_path: Path,
    baseline: dict[str, Any],
) -> dict[str, Any]:
    payload = json.loads(ett_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("pinned ETT bundle must be a JSON object")
    expected = baseline["active_ett"]
    rows = _active_rate_rows(
        payload,
        expected_unique_codes=int(expected["unique_codes"]),
        expected_code_set_sha256=str(expected["code_set_sha256"]),
        expected_duty_rate_sha256=str(expected["active_duty_rate_sha256"]),
    )
    active_payload = dict(payload)
    active_payload["rates"] = rows

    from app.services.normative_bundle import import_normative_bundle_dict

    result = import_normative_bundle_dict(
        active_payload,
        filename=ett_path.name,
        source_code="EEC_ETT_STAGING_BUILD",
        source_name="Pinned EEC ETT staging build",
    )
    imported = int((result.get("imported") or {}).get("rates") or 0)
    if imported != len(rows):
        raise RuntimeError(
            f"ETT importer accepted {imported} rows, expected {len(rows)}"
        )

    with sqlite3.connect(database) as connection:
        count = int(connection.execute("SELECT COUNT(*) FROM hs_rates").fetchone()[0])
        invalid = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM hs_rates
                WHERE length(trim(coalesce(hs_code, ''))) != 10
                   OR trim(coalesce(hs_code, '')) GLOB '*[^0-9]*'
                """
            ).fetchone()[0]
        )
    if count != int(expected["unique_codes"]) or invalid:
        raise RuntimeError(
            "fresh staging hs_rates is not the exact active ETT code set: "
            f"rows={count}, invalid={invalid}"
        )
    return {
        "active_ett_codes": count,
        "raw_valid_rows": len(rows),
        "duplicate_rows": 0,
        "invalid_code_rows": 0,
        "active_duty_rate_sha256": expected["active_duty_rate_sha256"],
    }


def _build_fts_index(database: Path, expected_rows: int) -> dict[str, Any]:
    """Materialize the product search index while the source is writable."""
    from app.services import tnved_fts

    tnved_fts._fts_ready = None
    if not tnved_fts.ensure_fts_index(rebuild=True):
        raise RuntimeError("SQLite FTS5 is required for a full staging snapshot")

    from app.db import engine

    engine.dispose()
    with sqlite3.connect(database) as connection:
        fts_rows = int(connection.execute("SELECT COUNT(*) FROM tnved_fts").fetchone()[0])
        trigger_names = sorted(
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' "
                "AND name IN ('tnved_fts_ai', 'tnved_fts_ad', 'tnved_fts_au')"
            )
        )
        # A real MATCH query proves this is a populated FTS5 table, not a
        # same-named ordinary table.
        connection.execute(
            "SELECT rowid FROM tnved_fts WHERE tnved_fts MATCH ? LIMIT 1",
            ("оборудован*",),
        ).fetchone()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("PRAGMA journal_mode=DELETE")
    expected_triggers = ["tnved_fts_ad", "tnved_fts_ai", "tnved_fts_au"]
    if fts_rows != expected_rows or trigger_names != expected_triggers:
        raise RuntimeError(
            "staging FTS index is incomplete: "
            f"rows={fts_rows}, triggers={trigger_names}"
        )
    return {
        "table": "tnved_fts",
        "rows": fts_rows,
        "triggers": trigger_names,
        "required_search_strategy": "hybrid_fts",
    }


def _verify_pinned_inputs(
    *,
    baseline_path: Path,
    pdf_dir: Path,
    ett_path: Path,
) -> dict[str, Any]:
    baseline = load_catalog_baseline(baseline_path)
    inspection = inspect_staging_inputs(
        baseline_path=baseline_path,
        pdf_dir=pdf_dir,
        ett_path=ett_path,
    )
    failed = sorted(
        name for name, matches in inspection["source_fingerprints"].items()
        if not matches
    )
    if failed:
        raise RuntimeError("pinned staging input drift: " + ", ".join(failed))
    if not inspection["positive_snapshot_allowed"]:
        raise RuntimeError(
            "pinned ETT is quarantined; positive staging snapshot blocked: "
            + "; ".join(inspection["blockers"])
        )
    return baseline


def inspect_staging_inputs(
    *,
    baseline_path: Path = DEFAULT_BASELINE_PATH,
    pdf_dir: Path = DEFAULT_PDF_SOURCE_DIR,
    ett_path: Path = DEFAULT_ETT_PATH,
) -> dict[str, Any]:
    """Return a non-mutating, machine-readable release-readiness decision."""
    baseline = load_catalog_baseline(baseline_path)
    active_ett = active_ett_fingerprint(ett_path)
    comparison = compare_source_baseline(
        baseline,
        pdf_source=pdf_source_manifest(pdf_dir),
        active_ett=active_ett,
        parser=parser_fingerprint(),
    )
    release_gate = baseline.get("staging_release_gate") or {}
    blockers: list[str] = []
    if not (
        baseline.get("schema_version") == "1"
        and baseline.get("validation_mode") == "quarantine_only"
    ):
        blockers.append("unsupported staging baseline contract")
    else:
        blockers.append(
            "baseline schema v1 is quarantine-only; positive validation "
            "requires a separate approved schema-v2 decision"
        )
    if not all(comparison.values()):
        blockers.append("tracked source fingerprints drifted from baseline")
    if int(active_ett.get("invalid_code_rows") or 0):
        blockers.append(
            f"invalid ETT code rows={active_ett['invalid_code_rows']}"
        )
    if int(active_ett.get("duplicate_rows") or 0):
        blockers.append(
            "duplicate ETT rows="
            f"{active_ett['duplicate_rows']} across "
            f"{active_ett['duplicate_code_count']} codes"
        )
    if int(active_ett.get("material_conflict_code_count") or 0):
        blockers.append(
            "materially conflicting duty-rate code groups="
            f"{active_ett['material_conflict_code_count']}"
        )
    if not bool(active_ett.get("structurally_publishable")):
        blockers.append("ETT structure is not one valid row per exact code")
    if not bool(release_gate.get("current_official_ett_verified")):
        blockers.append("current official EEC ETT artifact/revision is not verified")
    if not bool(release_gate.get("temporal_footnotes_verified")):
        blockers.append("temporary/as-of tariff footnotes are not verified")
    if not bool(release_gate.get("positive_snapshot_allowed")):
        blockers.append("manual positive-snapshot release gate is closed")
    return {
        "format": "customsclear-staging-input-readiness-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_id": baseline["dataset_id"],
        "baseline_contract": {
            "schema_version": baseline.get("schema_version"),
            "validation_mode": baseline.get("validation_mode"),
            "positive_validation_implemented": False,
        },
        "source_fingerprints": comparison,
        "ett": active_ett,
        "release_gate": release_gate,
        "blockers": blockers,
        "positive_snapshot_allowed": not blockers,
    }


def _run_snapshot_tool(*args: str) -> str:
    result = subprocess.run(
        [sys.executable, str(PREPARE_DATABASE_SCRIPT), *args],
        cwd=CUSTOMS_CLEAR_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"staging snapshot validation failed: {detail}")
    return result.stdout.strip()


def _run_source_builder(
    database: Path,
    *,
    pdf_dir: Path,
    ett_path: Path,
) -> dict[str, Any]:
    """Build the writable source in a fresh process with no cached app engine."""
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "_build-source",
            str(database),
            "--pdf-dir",
            str(pdf_dir),
            "--ett",
            str(ett_path),
        ],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"isolated staging source build failed: {detail[-8000:]}")
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    try:
        payload = json.loads(lines[-1])
        if not isinstance(payload.get("active_ett"), dict):
            raise TypeError("worker active_ett result is missing")
        if not isinstance(payload.get("fts"), dict):
            raise TypeError("worker FTS result is missing")
        isolation = payload.get("isolation")
        if not isinstance(isolation, dict):
            raise TypeError("worker isolation result is missing")
        if isolation.get("configured_database_unchanged") is not True:
            raise RuntimeError(
                "isolated staging build did not prove the configured database unchanged"
            )
        return payload
    except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("isolated staging source build returned no result") from exc


def _snapshot_profile(path: Path) -> dict[str, Any]:
    uri = f"file:{path.resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as database:
        database.execute("PRAGMA query_only=ON")
        counts = {
            table: int(database.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in (
                "tnved_sections",
                "tnved_chapters",
                "tnved_commodities",
                "hs_rates",
            )
        }
        alembic_heads = sorted(
            str(row[0]) for row in database.execute("SELECT version_num FROM alembic_version")
        )
    return {
        "size_bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
        "mode": oct(path.stat().st_mode & 0o777),
        "alembic_heads": alembic_heads,
        "counts": counts,
    }


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    target = path.expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"refusing to overwrite existing report: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary_name, target)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def build_full_staging_snapshot(
    output: Path,
    *,
    pdf_dir: Path = DEFAULT_PDF_SOURCE_DIR,
    ett_path: Path = DEFAULT_ETT_PATH,
) -> dict[str, Any]:
    output = output.expanduser().resolve()
    baseline_path = DEFAULT_BASELINE_PATH.resolve(strict=True)
    pdf_dir = pdf_dir.expanduser().resolve(strict=True)
    ett_path = ett_path.expanduser().resolve(strict=True)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing snapshot: {output}")

    baseline = _verify_pinned_inputs(
        baseline_path=baseline_path,
        pdf_dir=pdf_dir,
        ett_path=ett_path,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".customsclear-staging-build-", dir=output.parent
    ) as temporary_dir:
        source_database = Path(temporary_dir) / "source.db"
        source_build = _run_source_builder(
            source_database,
            pdf_dir=pdf_dir,
            ett_path=ett_path,
        )
        _run_snapshot_tool(str(source_database), str(output))

    # Reopen only through the strict validator after the temporary writable
    # source has been destroyed.
    validator_output = _run_snapshot_tool("--validate-only", str(output))
    profile = _snapshot_profile(output)
    return {
        "format": "customsclear-full-staging-snapshot-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "output": str(output),
        "dataset_id": baseline["dataset_id"],
        "catalog_source_manifest_sha256": baseline["pdf_source"]["manifest_sha256"],
        "catalog_code_set_sha256": baseline["catalog"]["code_set_sha256"],
        "catalog_code_description_sha256": baseline["catalog"][
            "code_description_sha256"
        ],
        "active_ett_revision": baseline["active_ett"]["revision"],
        "active_ett_code_set_sha256": baseline["active_ett"]["code_set_sha256"],
        "active_ett_codes": source_build["active_ett"]["active_ett_codes"],
        "active_ett_resolution": source_build["active_ett"],
        "fts": source_build["fts"],
        "validator": validator_output,
        "snapshot": profile,
        "isolation": source_build["isolation"],
    }


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build an immutable staging SQLite snapshot from the repository-pinned "
            "96-PDF TN VED catalog and active ETT bundle."
        )
    )
    parser.add_argument(
        "output",
        type=Path,
        nargs="?",
        help="new snapshot path; must not exist",
    )
    parser.add_argument("--report", type=Path, help="optional new JSON report path")
    parser.add_argument(
        "--check-inputs",
        action="store_true",
        help="inspect pinned source readiness without creating a database",
    )
    parser.add_argument("--pdf-dir", type=Path, default=DEFAULT_PDF_SOURCE_DIR)
    parser.add_argument("--ett", type=Path, default=DEFAULT_ETT_PATH)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    if args.check_inputs:
        inspection = inspect_staging_inputs(
            baseline_path=DEFAULT_BASELINE_PATH,
            pdf_dir=args.pdf_dir,
            ett_path=args.ett,
        )
        if args.report:
            _write_report(args.report, inspection)
        print(json.dumps(inspection, ensure_ascii=False, indent=2))
        return 0 if inspection["positive_snapshot_allowed"] else 1
    if args.output is None:
        raise SystemExit("snapshot output is required unless --check-inputs is used")
    if args.report:
        report_path = args.report.expanduser().resolve()
        if report_path == args.output.expanduser().resolve():
            raise SystemExit("--report and snapshot output must be different files")
        if report_path.exists():
            raise SystemExit(f"refusing to overwrite existing report: {report_path}")
    report = build_full_staging_snapshot(
        args.output,
        pdf_dir=args.pdf_dir,
        ett_path=args.ett,
    )
    if args.report:
        _write_report(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _source_worker_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("database", type=Path)
    parser.add_argument("--pdf-dir", type=Path, required=True)
    parser.add_argument("--ett", type=Path, required=True)
    args = parser.parse_args(argv)
    database = args.database.expanduser().resolve()
    if database.exists():
        raise SystemExit(f"refusing to reuse staging source database: {database}")
    baseline = _verify_pinned_inputs(
        baseline_path=DEFAULT_BASELINE_PATH,
        pdf_dir=args.pdf_dir,
        ett_path=args.ett,
    )
    configured_before = _configured_database_state()
    with _isolated_build_environment(database):
        _upgrade_fresh_schema()
        _import_catalog(database, args.pdf_dir)
        active_ett = _import_active_ett(database, args.ett, baseline)
        fts = _build_fts_index(
            database,
            int(baseline["catalog"]["rows"]),
        )
    configured_after = _configured_database_state()
    print(json.dumps({
        "active_ett": active_ett,
        "fts": fts,
        "isolation": {
            "configured_database_url_overridden": True,
            "configured_database_before": configured_before,
            "configured_database_after": configured_after,
            "configured_database_unchanged": configured_before == configured_after,
            "temporary_build_database": _file_state(database),
        },
    }))
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "_build-source":
        raise SystemExit(_source_worker_main(sys.argv[2:]))
    raise SystemExit(main())
