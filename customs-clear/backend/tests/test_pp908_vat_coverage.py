"""Тесты покрытия льготной ставки НДС 10% по ПП РФ №908.

Проверяем:
- аудит покрытия (scripts.audit_pp908_vat10_coverage) даёт высокий процент;
- смешанные заголовки исключены из целевых перечней (нет over-claim);
- запись vat_preferences для продуктов переработки зерна (1108/1109) → 10%,
  а смешанные/непродовольственные заголовки (1107/9404/9619) остаются 22%.
"""
from __future__ import annotations

import sys
from pathlib import Path

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
    def test_audit_high_coverage(self) -> None:
        result = audit_mod.audit()
        assert result["status"] == "OK"
        s = result["summary"]
        # hs_rates уже кодирует перечни ПП908 на корректной грануляции.
        assert s["coverage_pct"] >= 95.0, f"Низкое покрытие ПП908: {s}"


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
