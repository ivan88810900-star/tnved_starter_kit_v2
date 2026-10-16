"""PAY-8: exact chapter 27 rates from the current official EEC ETT PDF."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.import_duty_ingestion import _validate_bundle_for_ingest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
CORRECTION_PATH = (
    BACKEND_ROOT / "data/raw_normative/eec_ett_chapter27_correction_2026.json"
)
CHAPTER_27_URL = (
    "https://eec.eaeunion.org/comission/department/catr/ett/"
    "ru.2022/ru.27_2022_11.07.2026.pdf"
)
APPLICABILITY_STATUS = "current_snapshot_only_historical_intervals_unverified"
CHAPTER29_APPLICABILITY_BLOCKER = (
    "chapter29_correction_applicability_unverified: current snapshot does not model "
    "Decision 6 aniline 0% interval 2026-02-07..2027-12-31"
)
CHAPTER27_APPLICABILITY_BLOCKER = (
    "chapter27_correction_applicability_unverified: current snapshot has no verified "
    "historical intervals"
)
EXPECTED_RATES = {
    "2707501000": "5%",
    "2707991100": "5%",
    "2707999100": "5%",
    "2710123100": "5%",
    "2710124110": "5%",
    "2710129001": "5%",
    "2710194210": "5%",
    "2710195101": "5%",
    "2710197100": "5%",
    "2710910000": "5%",
    "2712901100": "5%",
    "2712901900": "5%",
    "2713110000": "3%",
    "2713200000": "5%",
    "2715000000": "5%",
}
BASE_RATE_ROWS = [
    (code, rate)
    for code, official_rate in EXPECTED_RATES.items()
    for rate in (
        "0" if code in {"2710124110", "2710194210"} else official_rate,
        "0.0",
    )
]


def _base_payload(*, revision: str = "ett:2026-06-18") -> dict:
    return {
        "format": "eec_ett_v1",
        "revision": revision,
        "effective_from": "2026-01-01",
        "official_ett_url": "https://eec.eaeunion.org/comission/department/catr/ett/",
        "rates": [
            {
                "hs_code": code,
                "duty_rate": rate,
                "source_revision": revision,
                "source_url": "https://eec.eaeunion.org/comission/department/catr/ett/",
            }
            for code, rate in BASE_RATE_ROWS
        ],
    }


def test_chapter27_verified_contour_is_unique_and_exact() -> None:
    payload = json.loads(CORRECTION_PATH.read_text(encoding="utf-8"))
    rows = payload["rates"]

    assert payload["schema_version"] == 1
    assert payload["revision"] == "ett:2026-07-11"
    assert payload["snapshot_date"] == "2026-07-11"
    assert payload["applies_to_base_revision"] == "ett:2026-06-18"
    assert payload["applicability_status"] == APPLICABILITY_STATUS
    assert payload["source_chapter_url"] == CHAPTER_27_URL
    assert len(rows) == len(EXPECTED_RATES)
    assert {row["hs_code"]: row["duty_rate"] for row in rows} == EXPECTED_RATES
    assert all(row["source_revision"] == "ett:2026-07-11" for row in rows)
    assert all(row["source_url"] == CHAPTER_27_URL for row in rows)


def test_chapter27_correction_leaves_only_non_ett_duplicate_quarantined() -> None:
    _payload, parser_result, _revision, rows, blockers = _validate_bundle_for_ingest(
        "data/raw_normative/eec_ett_normative_bundle.json"
    )

    assert parser_result["status"] == "parsed"
    assert parser_result["duplicate_hs_code_count"] == 1
    assert parser_result["duplicate_hs_codes"] == ["8511100001"]
    assert blockers == [
        CHAPTER29_APPLICABILITY_BLOCKER,
        CHAPTER27_APPLICABILITY_BLOCKER,
        "duplicate_hs_code_rows: 1 code(s); first=8511100001",
    ]
    observed = {
        row["hs_code"]: row["duty_rate"]
        for row in rows
        if row["hs_code"] in EXPECTED_RATES
    }
    assert observed == EXPECTED_RATES
    verified = [row for row in rows if row["hs_code"] in EXPECTED_RATES]
    assert all(row.get("valid_from") == "2026-01-01" for row in verified)
    assert all(row.get("valid_to") is None for row in verified)

    corrections = parser_result["corrections"]
    assert [correction["record_count"] for correction in corrections] == [5, 15]
    assert corrections[1]["revision"] == "ett:2026-07-11"
    assert corrections[1]["applicability_status"] == APPLICABILITY_STATUS
    assert corrections[1]["source_chapter_url"] == CHAPTER_27_URL
    assert len(corrections[1]["checksum_sha256"]) == 64


@pytest.mark.parametrize(
    ("field", "value", "expected_blocker"),
    [
        ("duty_rate", "4%", "chapter27_correction_scope_or_rate_mismatch"),
        ("source_revision", "ett:2099-01-01", "chapter27_correction_provenance_mismatch: 2707501000"),
    ],
)
def test_tampered_chapter27_correction_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
    expected_blocker: str,
) -> None:
    import app.services.import_duty_ingestion as ingestion

    base_rel = "data/raw_normative/eec_ett_normative_bundle.json"
    correction_rel = "data/raw_normative/eec_ett_chapter27_correction_2026.json"
    base_path = tmp_path / base_rel
    correction_path = tmp_path / correction_rel
    base_path.parent.mkdir(parents=True)
    base_path.write_text(json.dumps(_base_payload()), encoding="utf-8")
    correction = json.loads(CORRECTION_PATH.read_text(encoding="utf-8"))
    correction["rates"][0][field] = value
    correction_path.write_text(json.dumps(correction), encoding="utf-8")
    monkeypatch.setattr(ingestion, "_BACKEND_ROOT", tmp_path)

    _payload, parser_result, _revision, rows, blockers = _validate_bundle_for_ingest(base_rel)
    assert parser_result["status"] == "parsed"
    assert rows
    assert blockers[0] == expected_blocker
    assert blockers[1].startswith("duplicate_hs_code_rows: 15 code(s)")


def test_chapter27_correction_rejects_future_base_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.import_duty_ingestion as ingestion

    base_rel = "data/raw_normative/eec_ett_normative_bundle.json"
    correction_rel = "data/raw_normative/eec_ett_chapter27_correction_2026.json"
    base_path = tmp_path / base_rel
    correction_path = tmp_path / correction_rel
    base_path.parent.mkdir(parents=True)
    future = _base_payload(revision="ett:2027-01-01")
    for row in future["rates"]:
        row["duty_rate"] = "7%"
    base_path.write_text(json.dumps(future), encoding="utf-8")
    correction_path.write_text(CORRECTION_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(ingestion, "_BACKEND_ROOT", tmp_path)

    _payload, _parser_result, _revision, rows, blockers = _validate_bundle_for_ingest(base_rel)
    assert blockers[0] == (
        "chapter27_correction_base_revision_mismatch: "
        "expected=ett:2026-06-18; observed=ett:2027-01-01"
    )
    assert blockers[1].startswith("duplicate_hs_code_rows: 15 code(s)")
    assert {row["duty_rate"] for row in rows} == {"7%"}


def test_chapter27_correction_requires_exact_base_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.import_duty_ingestion as ingestion

    base_rel = "data/raw_normative/eec_ett_normative_bundle.json"
    correction_rel = "data/raw_normative/eec_ett_chapter27_correction_2026.json"
    base_path = tmp_path / base_rel
    correction_path = tmp_path / correction_rel
    base_path.parent.mkdir(parents=True)
    base = _base_payload()
    base["rates"] = [row for row in base["rates"] if row["hs_code"] != "2715000000"]
    base_path.write_text(json.dumps(base), encoding="utf-8")
    correction_path.write_text(CORRECTION_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(ingestion, "_BACKEND_ROOT", tmp_path)

    _payload, _parser_result, _revision, _rows, blockers = _validate_bundle_for_ingest(base_rel)
    assert blockers[0] == "chapter27_correction_base_scope_mismatch: 2715000000"
    assert blockers[1].startswith("duplicate_hs_code_rows: 14 code(s)")


def test_chapter27_metadata_uses_its_own_base_revision_constant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.import_duty_ingestion as ingestion

    base_rel = "data/raw_normative/eec_ett_normative_bundle.json"
    correction_rel = "data/raw_normative/eec_ett_chapter27_correction_2026.json"
    base_path = tmp_path / base_rel
    correction_path = tmp_path / correction_rel
    base_path.parent.mkdir(parents=True)
    base_path.write_text(json.dumps(_base_payload()), encoding="utf-8")
    correction_path.write_text(CORRECTION_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(ingestion, "_BACKEND_ROOT", tmp_path)
    monkeypatch.setattr(ingestion, "_CHAPTER27_BASE_REVISION", "ett:2026-06-19")

    _payload, _parser_result, _revision, _rows, blockers = _validate_bundle_for_ingest(base_rel)
    assert blockers[0] == "chapter27_correction_metadata_mismatch"
