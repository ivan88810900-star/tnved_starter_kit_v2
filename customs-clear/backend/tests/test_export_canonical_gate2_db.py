"""Compact Gate-2 database exporter tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile

from scripts.export_canonical_gate2_db import GATE2_TABLES, export_gate2_database


def _create_source(path: Path) -> None:
    with sqlite3.connect(path) as db:
        db.executescript(
            """
            CREATE TABLE tnved_sections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                roman_number VARCHAR(16),
                title TEXT,
                notes TEXT
            );
            CREATE TABLE tnved_chapters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                section_id INTEGER REFERENCES tnved_sections(id),
                code VARCHAR(16) NOT NULL,
                title TEXT,
                notes TEXT
            );
            CREATE TABLE tnved_commodities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chapter_id INTEGER REFERENCES tnved_chapters(id),
                code VARCHAR(32) NOT NULL,
                description TEXT,
                unit VARCHAR(64),
                import_duty TEXT,
                supp_unit VARCHAR(16),
                weight_coeff FLOAT
            );
            CREATE TABLE hs_rates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hs_code VARCHAR(10),
                hs_prefix VARCHAR(10),
                duty_rate VARCHAR(2048) NOT NULL DEFAULT '0',
                vat_import_rate FLOAT
            );
            CREATE TABLE private_operational_data (
                id INTEGER PRIMARY KEY,
                secret TEXT
            );
            CREATE INDEX ix_tnved_chapters_code ON tnved_chapters(code);
            CREATE UNIQUE INDEX uq_tnved_commodities_code ON tnved_commodities(code);
            CREATE INDEX ix_hs_rates_hs_code ON hs_rates(hs_code);

            INSERT INTO tnved_sections VALUES (1, 'MMD', 'Audit section', 'section notes');
            INSERT INTO tnved_chapters VALUES (1, 1, '98', 'Audit chapter', 'chapter notes');
            INSERT INTO tnved_commodities VALUES
                (1, 1, '9898', 'Audit heading', '', '', '', 0),
                (2, 1, '9898110001', '– audit leaf', '', '1%', '', 0),
                (3, 1, '9898130000', '– – audit synthetic L6', '', '', '', 0);
            INSERT INTO hs_rates VALUES
                (1, '9898110001', '9898', '1', 22),
                (2, '9898130000', '9898', '2', 22);
            INSERT INTO private_operational_data VALUES (1, 'must not be exported');
            """
        )


class Gate2DatabaseExporterTests(unittest.TestCase):
    def test_export_is_minimal_archived_and_passes_parity_without_false_green(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "full customs.db"
            output = root / "canonical-gate2.db"
            archive = root / "canonical-gate2.zip"
            audit_report = root / "gate2-report.json"
            _create_source(source)
            source_mtime = source.stat().st_mtime_ns

            report = export_gate2_database(
                source,
                output,
                archive_path=archive,
                batch_size=2,
            )

            self.assertEqual(report.table_rows["tnved_commodities"], 3)
            self.assertEqual(report.table_rows["hs_rates"], 1)
            self.assertEqual(len(report.output_sha256), 64)
            self.assertTrue(output.is_file())
            self.assertTrue(archive.is_file())
            self.assertEqual(source.stat().st_mtime_ns, source_mtime, "source must be read-only")

            with sqlite3.connect(output) as db:
                user_tables = {
                    row[0]
                    for row in db.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    )
                }
                self.assertEqual(user_tables, set(GATE2_TABLES))
                commodity_count = db.execute("SELECT count(*) FROM tnved_commodities").fetchone()
                self.assertEqual(commodity_count, (3,))
                rate_columns = {
                    row[1] for row in db.execute("PRAGMA table_info(hs_rates)")
                }
                self.assertEqual(rate_columns, {"id", "hs_code"})
                rate_codes = db.execute("SELECT hs_code FROM hs_rates").fetchall()
                self.assertEqual(rate_codes, [("9898130000",)])
                private = db.execute(
                    "SELECT count(*) FROM sqlite_master WHERE name='private_operational_data'"
                ).fetchone()
                self.assertEqual(private, (0,))

            with zipfile.ZipFile(archive) as bundle:
                self.assertEqual(bundle.namelist(), [output.name])

            env = os.environ.copy()
            env["DATABASE_URL"] = f"sqlite:///{output}"
            result = subprocess.run(
                [sys.executable, "scripts/audit_canonical_children.py", "--json"],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 4, msg=result.stderr or result.stdout)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"], msg=payload)
            self.assertFalse(payload["gate2_ok"], msg=payload)
            self.assertEqual(payload["commodity_count"], 3)
            self.assertEqual(payload["mismatches"], 0)

            cli_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/export_canonical_gate2_db.py",
                    "--source",
                    str(source),
                    "--output",
                    str(root / "cli-gate2.db"),
                    "--audit-report",
                    str(audit_report),
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(cli_result.returncode, 4, msg=cli_result.stderr)
            cli_payload = json.loads(cli_result.stdout)
            self.assertEqual(cli_payload["audit_exit_code"], 4)
            portable = json.loads(audit_report.read_text(encoding="utf-8"))
            self.assertEqual(portable["format"], "canonical-gate2-report-v1")
            self.assertEqual(portable["export"]["table_rows"]["tnved_commodities"], 3)
            self.assertEqual(len(portable["export"]["output_sha256"]), 64)
            self.assertEqual(portable["audit_exit_code"], 4)
            self.assertTrue(portable["audit"]["ok"])
            self.assertFalse(portable["audit"]["gate2_ok"])

    def test_export_refuses_destructive_destinations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.db"
            output = Path(tmp) / "output.db"
            _create_source(source)
            output.write_bytes(b"existing")

            with self.assertRaises(FileExistsError):
                export_gate2_database(source, output)
            with self.assertRaises(ValueError):
                export_gate2_database(source, source)


if __name__ == "__main__":
    unittest.main()
