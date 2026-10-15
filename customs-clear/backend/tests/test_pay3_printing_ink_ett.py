"""PAY-3: Decision No. 43 printing-ink nomenclature and duty amendment."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.core import HsRate
from app.services.import_duty_ingestion import (
    _PRINTING_INK_ACT_URL,
    _PRINTING_INK_CHAPTER_URL,
    _PRINTING_INK_CODES,
    _apply_duty_rows,
    _validate_bundle_for_ingest,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
AMENDMENT_PATH = (
    BACKEND_ROOT
    / "data/raw_normative/eec_ett_printing_ink_amendment_2026.json"
)


def _printing_ink_rows() -> tuple[list[dict], dict]:
    _payload, parser_result, _revision, rows, blockers = _validate_bundle_for_ingest(
        "data/raw_normative/eec_ett_normative_bundle.json"
    )
    assert parser_result["status"] == "parsed"
    assert blockers == []
    return (
        [
            row
            for row in rows
            if str(row.get("hs_code") or "").replace(" ", "") in _PRINTING_INK_CODES
        ],
        parser_result,
    )


def test_amendment_is_exact_dated_and_bound_to_official_sources() -> None:
    payload = json.loads(AMENDMENT_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["revision"] == "ett:2026-07-01"
    assert payload["effective_from"] == "2026-07-01"
    assert payload["source_act_url"] == _PRINTING_INK_ACT_URL
    assert payload["source_chapter_url"] == _PRINTING_INK_CHAPTER_URL

    rows = payload["rates"]
    assert len(rows) == 8
    assert {row["hs_code"] for row in rows} == _PRINTING_INK_CODES
    assert {
        row["hs_code"] for row in rows if row.get("valid_to") == "2026-06-30"
    } == {"3215110000", "3215190000"}
    assert {
        row["hs_code"]: row["duty_rate"]
        for row in rows
        if row["hs_code"] not in {"3215110000", "3215190000"}
    } == {
        "3215110001": "5%",
        "3215110002": "5%",
        "3215110009": "5%",
        "3215190001": "0%",
        "3215190002": "0%",
        "3215190009": "0%",
    }
    assert all(
        row["valid_from"] == "2026-07-01"
        for row in rows
        if row["hs_code"] not in {"3215110000", "3215190000"}
    )


def test_full_bundle_replaces_duplicate_legacy_rows_with_one_dated_contour() -> None:
    rows, parser_result = _printing_ink_rows()
    assert len(rows) == 8
    assert {row["hs_code"] for row in rows} == _PRINTING_INK_CODES
    assert len([row for row in rows if row["hs_code"] == "3215110000"]) == 1
    assert len([row for row in rows if row["hs_code"] == "3215190000"]) == 1

    metadata = parser_result["amendments"]
    assert len(metadata) == 1
    assert metadata[0]["revision"] == "ett:2026-07-01"
    assert metadata[0]["record_count"] == 8
    assert len(metadata[0]["checksum_sha256"]) == 64
    assert metadata[0]["source_act_url"] == _PRINTING_INK_ACT_URL
    assert metadata[0]["source_chapter_url"] == _PRINTING_INK_CHAPTER_URL


def test_apply_expires_old_codes_and_inserts_six_current_leaves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=[HsRate.__table__])
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    monkeypatch.setattr("app.services.import_duty_ingestion.SessionLocal", factory)

    with factory() as db:
        db.add_all(
            [
                HsRate(
                    hs_code="3215110000",
                    hs_prefix="3215110000",
                    duty_rate="5%",
                    source_revision="ett:2026-06-18",
                    source_url="https://eec.eaeunion.org/comission/department/catr/ett/",
                ),
                HsRate(
                    hs_code="3215190000",
                    hs_prefix="3215190000",
                    duty_rate="0%",
                    source_revision="ett:2026-06-18",
                    source_url="https://eec.eaeunion.org/comission/department/catr/ett/",
                ),
            ]
        )
        db.commit()

    rows, _parser_result = _printing_ink_rows()
    counts = _apply_duty_rows(rows)
    assert counts.total_in_source == 8
    assert counts.update == 2
    assert counts.insert == 6
    assert counts.blocked == 0

    with factory() as db:
        observed = {row.hs_code: row for row in db.query(HsRate).all()}
    assert set(observed) == _PRINTING_INK_CODES
    assert observed["3215110000"].valid_to == "2026-06-30"
    assert observed["3215190000"].valid_to == "2026-06-30"
    assert observed["3215110001"].valid_from == "2026-07-01"
    assert observed["3215110001"].duty_rate == "5%"
    assert observed["3215190009"].valid_from == "2026-07-01"
    assert observed["3215190009"].duty_rate == "0%"
    assert all(row.hs_prefix == row.hs_code for row in observed.values())
    engine.dispose()


def test_tampered_amendment_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.services.import_duty_ingestion as ingestion

    base_rel = "data/raw_normative/eec_ett_normative_bundle.json"
    amendment_rel = "data/raw_normative/eec_ett_printing_ink_amendment_2026.json"
    base_path = tmp_path / base_rel
    amendment_path = tmp_path / amendment_rel
    base_path.parent.mkdir(parents=True)
    base_path.write_text(
        json.dumps(
            {
                "format": "eec_ett_v1",
                "revision": "ett:2026-06-18",
                "effective_from": "2026-01-01",
                "official_ett_url": "https://eec.eaeunion.org/comission/department/catr/ett/",
                "rates": [
                    {
                        "hs_code": "3215110000",
                        "duty_rate": "5%",
                        "source_revision": "ett:2026-06-18",
                        "source_url": "https://eec.eaeunion.org/comission/department/catr/ett/",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    amendment = json.loads(AMENDMENT_PATH.read_text(encoding="utf-8"))
    amendment["rates"][2]["duty_rate"] = "4%"
    amendment_path.write_text(json.dumps(amendment), encoding="utf-8")
    monkeypatch.setattr(ingestion, "_BACKEND_ROOT", tmp_path)

    _payload, parser_result, _revision, rows, blockers = _validate_bundle_for_ingest(
        base_rel
    )
    assert parser_result["status"] == "parsed"
    assert rows
    assert blockers == ["printing_ink_amendment_scope_or_rate_mismatch"]
