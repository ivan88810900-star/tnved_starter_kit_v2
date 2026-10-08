"""Тесты покрытия льготной ставки НДС 10% по ПП РФ №908.

Проверяем:
- аудит покрытия проверяет только целые льготные заголовки и точные коды;
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
from app.services.vat_preferential_reference import match_preferential_vat_group
from app.api.tnved_catalog import _get_vat_preferences_rows

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

    def test_exact_codes_do_not_restore_broad_heading_claims(self) -> None:
        assert audit_mod.PP908_EXACT_CODES == ("8715001000",)
        assert "8715" in audit_mod.PP908_MIXED_HEADINGS
        assert "8715" not in audit_mod.PP908_CHILD_HEADINGS

    def test_unresolved_animal_headings_remain_visible(self) -> None:
        assert set(audit_mod.PP908_SOURCE_MAPPING_REQUIRED) == {"0102", "0103", "0104", "0105"}

    def test_committed_preferences_have_no_unsafe_whole_heading_vat10(self) -> None:
        unsafe = {"0102", "0103", "0104", "0105", "8715"}
        prefixes: set[str] = set()
        for name in ("vat_preferences_164p2_expansion.json", "vat_preferences_pp908_expansion.json"):
            payload = json.loads((_BACKEND / "data" / name).read_text(encoding="utf-8"))
            prefixes.update(str(item["hs_code_prefix"]) for item in payload["items"])
        assert prefixes.isdisjoint(unsafe)
        assert "8715001000" in prefixes


class TestPp908AuditCoverage:
    def test_audit_reports_narrowed_scope_and_unresolved_source_map(self) -> None:
        result = audit_mod.audit()
        s = result["summary"]
        assert result["status"] == "MANUAL_REVIEW_REQUIRED"
        assert result["manual_review_reasons"] == ["source_mapping_required"]
        assert s["headings_checked"] == s["headings_total"] == 114
        assert s["covered_10pct"] == 114
        assert s["gaps"] == 0
        assert s["no_sample_code"] == 0
        assert s["coverage_pct"] == 100.0
        assert s["exact_codes_checked"] == 1
        assert s["source_mappings_required"] == 4
        assert result["gaps"] == []


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
        assert result["manual_review_reasons"] == ["sample_code_missing", "source_mapping_required"]
        assert result["summary"]["no_sample_code"] == 1

    def test_non_ten_percent_gap_requires_manual_review(self) -> None:
        result = self._run(gap_heading=audit_mod.PP908_FOOD_HEADINGS[0])
        assert result["status"] == "MANUAL_REVIEW_REQUIRED"
        assert result["manual_review_reasons"] == ["vat_rate_gap", "source_mapping_required"]
        assert result["summary"]["gaps"] == 1

    def test_complete_fixture_still_requires_unresolved_source_map(self) -> None:
        result = self._run()
        assert result["status"] == "MANUAL_REVIEW_REQUIRED"
        assert result["manual_review_reasons"] == ["source_mapping_required"]
        assert result["summary"]["headings_checked"] == 114
        assert result["summary"]["covered_10pct"] == 114

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
        assert payload["manual_review_reasons"] == ["sample_code_missing", "source_mapping_required"]


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


class TestPp908NarrowVatPreferences:
    def test_stale_broad_preferences_are_rejected_but_exact_code_is_allowed(self) -> None:
        marker = "ТЕСТ ПП РФ № 908 (narrow scope)"
        with SessionLocal() as db:
            db.add_all(
                [
                    VatPreference(hs_code_prefix="0102", vat_rate=10, decree_info=marker, comment="unsafe broad"),
                    VatPreference(hs_code_prefix="8715", vat_rate=10, decree_info=marker, comment="unsafe broad"),
                    VatPreference(
                        hs_code_prefix="8715001000",
                        vat_rate=10,
                        decree_info=marker,
                        comment="exact carriage code",
                    ),
                ]
            )
            db.commit()
        try:
            with SessionLocal() as db:
                breeding, _ = pick_vat_preference_row("0102211000", db)
                carriage, match_len = pick_vat_preference_row("8715001000", db)
                carriage_parts, _ = pick_vat_preference_row("8715009000", db)
            assert breeding is None
            assert carriage is not None and carriage.vat_rate == 10 and match_len == 10
            assert carriage_parts is None
        finally:
            with SessionLocal() as db:
                db.query(VatPreference).filter(VatPreference.decree_info == marker).delete()
                db.commit()

    def test_catalog_and_ai_reference_share_narrow_scope(self) -> None:
        marker = "ТЕСТ ПП РФ № 908 (alternate read paths)"
        with SessionLocal() as db:
            db.add_all(
                [
                    VatPreference(hs_code_prefix="0102", vat_rate=10, decree_info=marker, comment="unsafe broad"),
                    VatPreference(hs_code_prefix="8715", vat_rate=10, decree_info=marker, comment="unsafe broad"),
                    VatPreference(
                        hs_code_prefix="8715001000",
                        vat_rate=10,
                        decree_info=marker,
                        comment="exact carriage code",
                    ),
                ]
            )
            db.commit()
        try:
            with SessionLocal() as db:
                breeding_rows = _get_vat_preferences_rows(db, "0102211000")
                carriage_rows = _get_vat_preferences_rows(db, "8715001000")
                sibling_rows = _get_vat_preferences_rows(db, "8715009000")
            assert breeding_rows == []
            assert carriage_rows
            assert {row.hs_code_prefix for row in carriage_rows} == {"8715001000"}
            assert sibling_rows == []
            exact_group = match_preferential_vat_group("8715001000")
            assert exact_group is not None and exact_group["prefix"] == "8715001000"
            assert match_preferential_vat_group("8715009000") is None
        finally:
            with SessionLocal() as db:
                db.query(VatPreference).filter(VatPreference.decree_info == marker).delete()
                db.commit()
