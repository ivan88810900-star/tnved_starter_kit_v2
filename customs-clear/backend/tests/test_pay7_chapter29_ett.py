"""PAY-7: exact chapter 29 rates from the current official EEC ETT PDF."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.import_duty_ingestion import _validate_bundle_for_ingest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
CORRECTION_PATH = (
    BACKEND_ROOT / "data/raw_normative/eec_ett_chapter29_correction_2026.json"
)
CHAPTER_29_URL = (
    "https://eec.eaeunion.org/comission/department/catr/ett/"
    "ru.2022/ru.29_2022_11.07.2026.pdf"
)
EXPECTED_RATES = {
    "2901100001": "3%",
    "2902200000": "3%",
    "2902300000": "3%",
    "2902410000": "3%",
    "2921410000": "5%",
}


def test_chapter29_verified_contour_is_unique_and_exact() -> None:
    payload = json.loads(CORRECTION_PATH.read_text(encoding="utf-8"))
    rows = payload["rates"]

    assert payload["schema_version"] == 1
    assert payload["revision"] == "ett:2026-07-11"
    assert payload["snapshot_date"] == "2026-07-11"
    assert payload["source_chapter_url"] == CHAPTER_29_URL
    assert len(rows) == len(EXPECTED_RATES)
    assert {row["hs_code"]: row["duty_rate"] for row in rows} == EXPECTED_RATES
    assert all(row["source_revision"] == "ett:2026-07-11" for row in rows)
    assert all(row["source_url"] == CHAPTER_29_URL for row in rows)


def test_chapter29_correction_reduces_quarantine_without_opening_ingest() -> None:
    _payload, parser_result, _revision, rows, blockers = _validate_bundle_for_ingest(
        "data/raw_normative/eec_ett_normative_bundle.json"
    )

    assert parser_result["status"] == "parsed"
    assert parser_result["duplicate_hs_code_count"] == 16
    assert not (set(EXPECTED_RATES) & set(parser_result["duplicate_hs_codes"]))
    assert len(blockers) == 1
    assert blockers[0].startswith("duplicate_hs_code_rows: 16 code(s)")
    observed = {
        row["hs_code"]: row["duty_rate"]
        for row in rows
        if row["hs_code"] in EXPECTED_RATES
    }
    assert observed == EXPECTED_RATES
    assert all(row.get("valid_from") == "2026-01-01" for row in rows if row["hs_code"] in EXPECTED_RATES)

    correction = parser_result["corrections"]
    assert len(correction) == 1
    assert correction[0]["revision"] == "ett:2026-07-11"
    assert correction[0]["record_count"] == 5
    assert correction[0]["source_chapter_url"] == CHAPTER_29_URL
    assert len(correction[0]["checksum_sha256"]) == 64


@pytest.mark.parametrize(
    ("field", "value", "expected_blocker"),
    [
        ("duty_rate", "4%", "chapter29_correction_scope_or_rate_mismatch"),
        ("source_revision", "ett:2099-01-01", "chapter29_correction_provenance_mismatch: 2901100001"),
    ],
)
def test_tampered_chapter29_correction_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
    expected_blocker: str,
) -> None:
    import app.services.import_duty_ingestion as ingestion

    base_rel = "data/raw_normative/eec_ett_normative_bundle.json"
    correction_rel = "data/raw_normative/eec_ett_chapter29_correction_2026.json"
    base_path = tmp_path / base_rel
    correction_path = tmp_path / correction_rel
    base_path.parent.mkdir(parents=True)
    base_path.write_text(
        json.dumps(
            {
                "format": "eec_ett_v1",
                "revision": "ett:2026-06-18",
                "effective_from": "2026-01-01",
                "official_ett_url": "https://eec.eaeunion.org/comission/department/catr/ett/",
                "rates": [{"hs_code": "8471300000", "duty_rate": "5%"}],
            }
        ),
        encoding="utf-8",
    )
    correction = json.loads(CORRECTION_PATH.read_text(encoding="utf-8"))
    correction["rates"][0][field] = value
    correction_path.write_text(json.dumps(correction), encoding="utf-8")
    monkeypatch.setattr(ingestion, "_BACKEND_ROOT", tmp_path)

    _payload, parser_result, _revision, rows, blockers = _validate_bundle_for_ingest(base_rel)
    assert parser_result["status"] == "parsed"
    assert rows
    assert blockers == [expected_blocker]
