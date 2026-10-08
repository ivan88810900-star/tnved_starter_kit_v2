"""Тесты покрытия льготной ставки НДС 10% по ПП РФ №908.

Проверяем:
- аудит покрытия (scripts.audit_pp908_vat10_coverage) даёт высокий процент;
- смешанные заголовки исключены из целевых перечней (нет over-claim);
- запись vat_preferences для продуктов переработки зерна (1108/1109) → 10%,
  а смешанные/непродовольственные заголовки (1107/9404/9619) остаются 22%.
"""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from app.db import SessionLocal
from app.models.tnved import VatPreference
from app.services.compliance_resolver import pick_vat_preference_row
from app.services.normative_store import find_rate_for_hs

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND / "scripts"))

import audit_pp908_vat10_coverage as audit_mod  # noqa: E402


def _effective_vat(code: str) -> int | None:
    rate_row, _ = find_rate_for_hs(code)
    if rate_row is not None and int(rate_row.vat_import_rate) == 10:
        return 10
    with SessionLocal() as db:
        vp, _ = pick_vat_preference_row(code, db)
    if vp is not None and int(vp.vat_rate) == 10:
        return 10
    return int(rate_row.vat_import_rate) if rate_row is not None else None


class TestPp908ListsIntegrity:
    def test_no_overlap_target_and_mixed(self) -> None:
        targets = set(audit_mod.PP908_FOOD_HEADINGS) | set(audit_mod.PP908_CHILD_HEADINGS)
        mixed = set(audit_mod.PP908_MIXED_HEADINGS)
        assert targets.isdisjoint(mixed), "Смешанные заголовки не должны быть в целевых перечнях"

    def test_mixed_headings_documented(self) -> None:
        for heading, reason in audit_mod.PP908_MIXED_HEADINGS.items():
            assert reason.strip(), f"Заголовок {heading} без обоснования исключения"


class TestPp908AuditCoverage:
    def test_audit_reports_known_fixture_gaps(self) -> None:
        result = audit_mod.audit()
        s = result["summary"]
        assert result["status"] == "MANUAL_REVIEW_REQUIRED"
        assert result["manual_review_reasons"] == ["vat_rate_gap"]
        assert s["headings_checked"] == s["headings_total"] == 118
        assert s["covered_10pct"] == 113
        assert s["gaps"] == 5
        assert s["no_sample_code"] == 0
        assert s["coverage_pct"] == 95.8
        assert {gap["heading"] for gap in result["gaps"]} == {
            "0102",
            "0103",
            "0104",
            "0105",
            "8715",
        }
        assert all(gap["vat_rate"] == 22 for gap in result["gaps"])


class TestPp908AuditFailClosed:
    @staticmethod
    def _run(
        *,
        missing_heading: str | None = None,
        gap_heading: str | None = None,
    ) -> dict:
        session = mock.MagicMock()
        session.return_value.__enter__.return_value = object()

        def rep_code(_db: object, heading: str) -> str | None:
            if heading == missing_heading:
                return None
            return heading.ljust(10, "0")

        def effective_vat(_db: object, code: str) -> tuple[int, str]:
            if gap_heading is not None and code.startswith(gap_heading):
                return 22, "hs_rates"
            return 10, "hs_rates"

        with (
            mock.patch.object(audit_mod, "SessionLocal", session),
            mock.patch.object(audit_mod, "_rep_code", side_effect=rep_code),
            mock.patch.object(audit_mod, "_effective_vat", side_effect=effective_vat),
        ):
            return audit_mod.audit()

    def test_missing_sample_code_requires_manual_review(self) -> None:
        result = self._run(missing_heading=audit_mod.PP908_FOOD_HEADINGS[0])
        assert result["status"] == "MANUAL_REVIEW_REQUIRED"
        assert result["manual_review_reasons"] == ["sample_code_missing"]
        assert result["summary"]["no_sample_code"] == 1

    def test_non_ten_percent_gap_requires_manual_review(self) -> None:
        result = self._run(gap_heading=audit_mod.PP908_FOOD_HEADINGS[0])
        assert result["status"] == "MANUAL_REVIEW_REQUIRED"
        assert result["manual_review_reasons"] == ["vat_rate_gap"]
        assert result["summary"]["gaps"] == 1

    def test_complete_fixture_remains_ok(self) -> None:
        result = self._run()
        assert result["status"] == "OK"
        assert result["manual_review_reasons"] == []
        assert result["summary"]["headings_checked"] == 118
        assert result["summary"]["covered_10pct"] == 118

    def test_json_cli_exits_nonzero_for_manual_review(self) -> None:
        result = self._run(missing_heading=audit_mod.PP908_FOOD_HEADINGS[0])
        stdout = io.StringIO()

        with (
            mock.patch.object(audit_mod, "audit", return_value=result),
            mock.patch.object(sys, "argv", ["audit_pp908_vat10_coverage.py", "--json"]),
            redirect_stdout(stdout),
        ):
            try:
                audit_mod.main()
            except SystemExit as exc:
                assert exc.code == 1
            else:
                raise AssertionError("CLI must exit non-zero when manual review is required")

        payload = json.loads(stdout.getvalue())
        assert payload["status"] == "MANUAL_REVIEW_REQUIRED"
        assert payload["manual_review_reasons"] == ["sample_code_missing"]


class TestPp908GrainProductsVat10:
    def test_starch_and_gluten_get_10_from_preferences(self) -> None:
        # Герметично: добавляем 1108/1109 как vat_preferences и проверяем 10%.
        marker = "ТЕСТ ПП РФ № 908 (grain products)"
        with SessionLocal() as db:
            db.add(VatPreference(hs_code_prefix="1108", vat_rate=10, decree_info=marker, comment="крахмал"))
            db.add(VatPreference(hs_code_prefix="1109", vat_rate=10, decree_info=marker, comment="клейковина"))
            db.commit()
        try:
            with SessionLocal() as db:
                vp_starch, _ = pick_vat_preference_row("1108110000", db)
                vp_gluten, _ = pick_vat_preference_row("1109000000", db)
            assert vp_starch is not None and vp_starch.vat_rate == 10
            assert vp_gluten is not None and vp_gluten.vat_rate == 10
        finally:
            with SessionLocal() as db:
                db.query(VatPreference).filter(VatPreference.decree_info == marker).delete()
                db.commit()

    def test_mixed_headings_not_over_claimed(self) -> None:
        # Солод (1107), матрацы (9404), гигиена/подгузники (9619) — НЕ 10%.
        for code in ("1107101100", "9404100000", "9619003000"):
            eff = _effective_vat(code)
            assert eff != 10, f"Заголовок code={code} не должен давать 10% (over-claim)"
