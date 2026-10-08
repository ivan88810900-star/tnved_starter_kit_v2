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
        assert "8715001000" in audit_mod.PP908_EXACT_CODES
        assert set(audit_mod.PP908_LIVE_ANIMAL_AUTO_CODES) < set(audit_mod.PP908_EXACT_CODES)
        assert "8715" in audit_mod.PP908_MIXED_HEADINGS
        assert "8715" not in audit_mod.PP908_CHILD_HEADINGS

    def test_live_animal_mapping_is_complete_and_fail_closed(self) -> None:
        mapping = audit_mod.PP908_LIVE_ANIMAL_MAPPING
        auto = set(mapping["auto_vat10_codes"])
        excluded = set(mapping["excluded_breeding_codes"])
        characteristic = set(mapping["product_characteristic_required_codes"])
        assert len(auto) == 5
        assert len(excluded) == 10
        assert len(characteristic) == 30
        assert not (auto & excluded or auto & characteristic or excluded & characteristic)
        assert all(len(code) == 10 and code.isdigit() for code in auto | excluded | characteristic)
        assert {code[:4] for code in auto | excluded | characteristic} == {"0102", "0103", "0104", "0105"}
        assert mapping["classification_source"]["group_01_snapshot_sha256"] == (
            "7942d2176d8c728dde35f55cc4871ba230fdef721b30d5c191fd444cd55537c9"
        )

    def test_live_animal_mapping_partitions_committed_ett_leaves(self) -> None:
        bundle = json.loads(
            (_BACKEND / "data" / "raw_normative" / "eec_ett_normative_bundle.json").read_text(encoding="utf-8")
        )
        committed = {
            str(row["hs_code"])
            for row in bundle["rates"]
            if str(row.get("hs_code", "")).startswith(("0102", "0103", "0104", "0105"))
        }
        mapping = audit_mod.PP908_LIVE_ANIMAL_MAPPING
        partition = (
            set(mapping["auto_vat10_codes"])
            | set(mapping["excluded_breeding_codes"])
            | set(mapping["product_characteristic_required_codes"])
        )
        assert committed == partition

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
        assert result["manual_review_reasons"] == ["product_characteristic_required"]
        assert s["headings_checked"] == s["headings_total"] == 119
        assert s["covered_10pct"] == 119
        assert s["gaps"] == 0
        assert s["no_sample_code"] == 0
        assert s["coverage_pct"] == 100.0
        assert s["exact_codes_checked"] == 6
        assert s["animal_mapping_auto_codes"] == 5
        assert s["animal_mapping_excluded_codes"] == 10
        assert s["product_characteristic_required"] == 30
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
        assert result["manual_review_reasons"] == ["sample_code_missing", "product_characteristic_required"]
        assert result["summary"]["no_sample_code"] == 1

    def test_non_ten_percent_gap_requires_manual_review(self) -> None:
        result = self._run(gap_heading=audit_mod.PP908_FOOD_HEADINGS[0])
        assert result["status"] == "MANUAL_REVIEW_REQUIRED"
        assert result["manual_review_reasons"] == ["vat_rate_gap", "product_characteristic_required"]
        assert result["summary"]["gaps"] == 1

    def test_complete_fixture_still_requires_unresolved_source_map(self) -> None:
        result = self._run()
        assert result["status"] == "MANUAL_REVIEW_REQUIRED"
        assert result["manual_review_reasons"] == ["product_characteristic_required"]
        assert result["summary"]["headings_checked"] == 119
        assert result["summary"]["covered_10pct"] == 119

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
        assert payload["manual_review_reasons"] == ["sample_code_missing", "product_characteristic_required"]

    def test_animal_mapping_seed_matches_auto_codes_only(self) -> None:
        payload = json.loads(
            (_BACKEND / "data" / "vat_preferences_pp908_expansion.json").read_text(encoding="utf-8")
        )
        animal_seed = {
            str(item["hs_code_prefix"])
            for item in payload["items"]
            if str(item.get("hs_code_prefix", "")).startswith(("0102", "0103", "0104", "0105"))
        }
        assert animal_seed == set(audit_mod.PP908_LIVE_ANIMAL_AUTO_CODES)


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
    def test_mapped_nonbreeding_codes_get_10_and_ambiguous_poultry_stays_closed(self) -> None:
        marker = "ТЕСТ ПП РФ № 908 (animal source map)"
        with SessionLocal() as db:
            db.add_all(
                [
                    VatPreference(
                        hs_code_prefix="0102292100",
                        vat_rate=10,
                        decree_info=marker,
                        comment="mapped slaughter cattle",
                    ),
                ]
            )
            db.commit()
        try:
            with SessionLocal() as db:
                cattle, cattle_len = pick_vat_preference_row("0102292100", db)
                breeding, _ = pick_vat_preference_row("0102211000", db)
                generic_cattle, _ = pick_vat_preference_row("0102290500", db)
                generic_chicks, _ = pick_vat_preference_row("0105119100", db)
                ambiguous_turkeys, _ = pick_vat_preference_row("0105120000", db)
            assert cattle is not None and cattle.vat_rate == 10 and cattle_len == 10
            assert breeding is None
            assert generic_cattle is None
            assert generic_chicks is None
            assert ambiguous_turkeys is None
        finally:
            with SessionLocal() as db:
                db.query(VatPreference).filter(VatPreference.decree_info == marker).delete()
                db.commit()

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
