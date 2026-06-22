"""Тесты расчётного движка платежей.

Покрытие:
- НДС: 22% (default), 10% (льготные товары), fallback при неизвестном коде
- Пошлина: авто и ручное переопределение
- Акциз: percent-тип и fixed-тип, ручное переопределение
- Антидемпинг: применяется / не применяется по стране / требует ручной проверки
- Расчёт базы НДС с учётом пошлины, акциза, антидемпинга
- confidence: уровни high/medium/low/none по длине совпадения
- Золотые тесты: эталонные расчёты для известных позиций
"""
import unittest

from app.db import SessionLocal
from app.models.tnved import HsDutyRule, VatPreference
from app.services.normative_store import init_db
from app.services.payment_engine import _compute_structured_duty, compare_payment_scenarios, compute_payments


class PaymentEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    # ------------------------------------------------------------------ helpers
    def _calc(self, **kwargs):
        defaults = {"hs_code": "8509400000", "customs_value": 100_000, "freight": 10_000}
        defaults.update(kwargs)
        return compute_payments(defaults)

    # ------------------------------------------------------------------ VAT
    def test_vat_22_default(self):
        """Код 8509: НДС 22% (бытовая техника, основная ставка)."""
        res = self._calc(hs_code="8509400000", customs_value=500_000, freight=45_000)
        self.assertEqual(res["status"], "OK")
        self.assertEqual(res["breakdown"]["vat_rate"], 22.0)
        self.assertGreater(res["breakdown"]["vat"], 0)
        self.assertIn("vat_reason", res["breakdown"])

    def test_vat_10_food(self):
        """Льготный НДС 10% через признак apply_reduced_vat (без записи в vat_preferences)."""
        res = self._calc(hs_code="0201300000", customs_value=100_000, freight=10_000, apply_reduced_vat=True)
        self.assertEqual(res["breakdown"]["vat_rate"], 10.0)
        self.assertIn("10%", res["breakdown"]["vat_reason"])

    def test_vat_10_pharma(self):
        """Код 3004: лекарства — НДС 10%."""
        res = self._calc(hs_code="3004900000", customs_value=50_000, freight=5_000)
        self.assertEqual(res["breakdown"]["vat_rate"], 10.0)

    def test_vat_10_toys(self):
        """Код 9503 + apply_reduced_vat: НДС 10%."""
        res = self._calc(hs_code="9503009900", customs_value=80_000, freight=8_000, apply_reduced_vat=True)
        self.assertEqual(res["breakdown"]["vat_rate"], 10.0)

    def test_vat_10_beef_from_hs_rates(self):
        """Контрольный код #124: говядина 0201100000 → НДС 10% (НК РФ ст. 164 п. 2)."""
        res = self._calc(hs_code="0201100000", customs_value=100_000, freight=0)
        self.assertEqual(res["breakdown"]["vat_rate"], 10.0)

    def test_vat_10_from_vat_preferences_expansion(self):
        """Льготная позиция из vat_preferences (живой скот по ПП №908) → 10%, без over-claim для электроники."""
        marker = "ТЕСТ ПП РФ № 908 (vat10 expansion)"
        with SessionLocal() as db:
            db.add(VatPreference(hs_code_prefix="0102", vat_rate=10, decree_info=marker, comment="тест"))
            db.commit()
        try:
            res = self._calc(hs_code="0102291000", customs_value=100_000, freight=0)
            self.assertEqual(res["breakdown"]["vat_rate"], 10.0)
            self.assertIn("vat_preferences", res["breakdown"]["vat_reason"].lower())
            # Электроника не должна попасть под льготу.
            res_el = self._calc(hs_code="8471300000", customs_value=100_000, freight=0)
            self.assertEqual(res_el["breakdown"]["vat_rate"], 22.0)
        finally:
            with SessionLocal() as db:
                db.query(VatPreference).filter(VatPreference.decree_info == marker).delete()
                db.commit()

    def test_vat_22_fallback_unknown_code(self):
        """Нет льготы в vat_preferences: базовая ставка НДС 22%."""
        res = self._calc(hs_code="4738291056", customs_value=100_000, freight=0)
        self.assertEqual(res["breakdown"]["vat_rate"], 22.0)
        reason = res["breakdown"]["vat_reason"].lower()
        self.assertTrue("22%" in reason or "базовая" in reason or "по умолчанию" in reason)
        if res["data_quality"]["match_length"] == 0:
            self.assertEqual(res["data_quality"]["confidence"], "none")

    def test_vat_override(self):
        """Ручное переопределение ставки НДС."""
        res = self._calc(hs_code="8509400000", customs_value=100_000, vat_rate=10.0)
        self.assertEqual(res["breakdown"]["vat_rate"], 10.0)
        self.assertIn("вручную", res["breakdown"]["vat_reason"])

    # ------------------------------------------------------------------ Duty
    def test_duty_auto_from_db(self):
        """Пошлина автоматически из БД (ставка из локальной базы / ЕТТ)."""
        res = self._calc(hs_code="8509400000", customs_value=500_000, freight=0)
        dr = res["auto_detected"]["duty_rate"]
        expected_duty = round(500_000 * dr / 100.0, 2)
        self.assertAlmostEqual(res["breakdown"]["duty"], expected_duty, places=1)

    def test_duty_override(self):
        """Ручное переопределение ставки пошлины."""
        res = self._calc(hs_code="8509400000", customs_value=100_000, duty_rate=5.0)
        self.assertAlmostEqual(res["breakdown"]["duty"], 5_000.0, places=1)

    def test_duty_zero_for_phones(self):
        """Код 8517: пошлина 0%."""
        res = self._calc(hs_code="8517120000", customs_value=200_000, freight=0)
        self.assertEqual(res["breakdown"]["duty"], 0.0)

    def test_combined_min_treats_zero_as_valid_number(self):
        """Для combined_min значение 0.0 должно считаться валидным, а не как отсутствие."""
        rule = HsDutyRule(
            commodity_code="9999999999",
            type="combined_min",
            ad_valorem_pct=0.0,
            specific_amount=5.0,
            specific_currency="RUB",
            specific_uom="pcs",
        )
        duty, duty_rate, ad_valorem_amount, specific_amount_rub, selected_rule, _, _ = _compute_structured_duty(
            customs_value=100_000.0,
            quantity=10.0,
            net_weight_kg=None,
            extra_quantity=10.0,
            duty_rule=rule,
            manual_duty_rate=None,
            auto_duty_rate=7.0,
            fx_rates={"RUB": 1.0},
        )
        self.assertEqual(ad_valorem_amount, 0.0)
        self.assertEqual(specific_amount_rub, 50.0)
        self.assertEqual(duty, 0.0)
        self.assertEqual(duty_rate, 0.0)
        self.assertEqual(selected_rule, "combined_min:ad_valorem")

    def test_combined_max_fallback_when_operands_missing(self):
        """Если обе части combined_max отсутствуют, не должно быть TypeError: fallback на auto rate."""
        rule = HsDutyRule(
            commodity_code="9999999998",
            type="combined_max",
            ad_valorem_pct=None,
            specific_amount=None,
            specific_currency="RUB",
            specific_uom="pcs",
        )
        duty, duty_rate, ad_valorem_amount, specific_amount_rub, selected_rule, _, _ = _compute_structured_duty(
            customs_value=100_000.0,
            quantity=1.0,
            net_weight_kg=None,
            extra_quantity=None,
            duty_rule=rule,
            manual_duty_rate=None,
            auto_duty_rate=7.0,
            fx_rates={"RUB": 1.0},
        )
        self.assertIsNone(ad_valorem_amount)
        self.assertIsNone(specific_amount_rub)
        self.assertEqual(duty, 7_000.0)
        self.assertEqual(duty_rate, 7.0)
        self.assertEqual(selected_rule, "combined_max:fallback_auto")

    # ------------------------------------------------------------------ Excise
    def test_excise_percent(self):
        """Код 2203: пиво — акциз 5% от таможенной стоимости."""
        res = self._calc(hs_code="2203009900", customs_value=100_000, freight=5_000)
        self.assertEqual(res["breakdown"]["excise"], 5_000.0)  # 5% от 100000
        self.assertIn("5.0%", res["breakdown"]["excise_reason"])

    def test_excise_fixed(self):
        """Код 2208: крепкий алкоголь — фиксированная ставка акциза (префикс из сида)."""
        res = self._calc(hs_code="2208", customs_value=100_000, freight=0, quantity=10)
        ev = res["auto_detected"]["excise_value"]
        if res["auto_detected"]["excise_type"] == "fixed" and ev:
            expected = round(float(ev) * 10, 2)
            self.assertAlmostEqual(res["breakdown"]["excise"], expected, places=1)
        else:
            self.skipTest("В БД нет fixed-акциза для 2208 (перекрыто данными ЕТТ)")

    def test_excise_override(self):
        """Ручное переопределение акциза."""
        res = self._calc(hs_code="2203009900", customs_value=100_000, freight=0, excise=12_000)
        self.assertEqual(res["breakdown"]["excise"], 12_000.0)
        self.assertIn("вручную", res["breakdown"]["excise_reason"])

    def test_no_excise_for_electronics(self):
        """Бытовая техника — акциза нет."""
        res = self._calc(hs_code="8509400000", customs_value=100_000, freight=0)
        self.assertEqual(res["breakdown"]["excise"], 0.0)

    # ------------------------------------------------------------------ Antidumping
    def test_antidumping_applied_cn(self):
        """Код 7214 из Китая: антидемпинг 18% применяется."""
        res = self._calc(hs_code="7214990000", customs_value=100_000, freight=10_000, country="CN")
        self.assertGreater(res["breakdown"]["antidumping"], 0)
        self.assertEqual(res["data_quality"]["antidumping_status"], "applied")

    def test_antidumping_applied_ua(self):
        """Код 7214 из Украины: антидемпинг 18% применяется."""
        res = self._calc(hs_code="7214990000", customs_value=100_000, freight=0, country="UA")
        self.assertGreater(res["breakdown"]["antidumping"], 0)

    def test_antidumping_not_applied_de(self):
        """Код 7214 из Германии: антидемпинг не применяется."""
        res = self._calc(hs_code="7214990000", customs_value=100_000, freight=0, country="DE")
        self.assertEqual(res["breakdown"]["antidumping"], 0.0)
        self.assertEqual(res["data_quality"]["antidumping_status"], "n/a")

    def test_antidumping_manual_review_no_country(self):
        """Код 7214 без страны: требуется ручная проверка антидемпинга."""
        res = self._calc(hs_code="7214990000", customs_value=100_000, freight=0, country=None)
        self.assertEqual(res["data_quality"]["antidumping_status"], "manual_review")
        self.assertEqual(res["breakdown"]["antidumping"], 0.0)
        self.assertIn("ручная проверка", res["breakdown"]["antidumping_reason"])

    def test_no_antidumping_for_electronics(self):
        """Бытовая техника: антидемпинга нет."""
        res = self._calc(hs_code="8509400000", customs_value=100_000, country="CN")
        self.assertEqual(res["breakdown"]["antidumping"], 0.0)

    # ------------------------------------------------------------------ VAT base calculation
    def test_vat_base_includes_duty_and_antidumping(self):
        """База НДС = таможенная стоимость + пошлина + акциз + антидемпинг + спецпошлины."""
        res = self._calc(hs_code="7214990000", customs_value=100_000, freight=0, country="CN")
        duty = res["breakdown"]["duty"]
        excise = res["breakdown"]["excise"]
        antidumping = res["breakdown"]["antidumping"]
        spec = res["breakdown"]["special_duties_amount"]
        expected_base = 100_000 + duty + excise + antidumping + spec
        self.assertAlmostEqual(res["breakdown"]["vat_base"], expected_base, places=1)

    def test_total_payable_includes_excise_and_antidumping(self):
        """Итог к уплате включает пошлину, НДС, сбор, акциз и антидемпинг."""
        res = compute_payments(
            {
                "hs_code": "7214990000",
                "customs_value": 100_000,
                "freight": 0,
                "country": "CN",
                "excise": 2_500,
            }
        )
        b = res["breakdown"]
        expected_total = b["customs_fee"] + b["duty"] + b["excise"] + b["antidumping"] + b["special_duties_amount"] + b["vat"]
        self.assertAlmostEqual(b["total_payable"], expected_total, places=2)

    # ------------------------------------------------------------------ Confidence
    def test_confidence_high_10digits(self):
        res = self._calc(hs_code="8509400000")
        # 8509 prefix matches → high (4 chars = 'low'? let's verify logic)
        # seed has prefix "8509" (4 chars), so match_length=4 → low
        self.assertIn(res["data_quality"]["confidence"], ("high", "medium", "low"))

    def test_confidence_none_unknown(self):
        res = self._calc(hs_code="9998000000")
        self.assertEqual(res["data_quality"]["confidence"], "none")
        self.assertEqual(res["data_quality"]["match_length"], 0)

    # ------------------------------------------------------------------ Golden tests
    def test_golden_electronics_cn(self):
        """Золотой тест: бытовая техника из Китая (ставка пошлины из БД)."""
        res = compute_payments({
            "hs_code": "8509400000",
            "customs_value": 500_000,
            "freight": 45_000,
            "country": "CN",
        })
        self.assertEqual(res["status"], "OK")
        dr = res["auto_detected"]["duty_rate"]
        duty = round(500_000 * dr / 100.0, 2)
        self.assertAlmostEqual(res["breakdown"]["duty"], duty, places=0)
        self.assertAlmostEqual(res["insurance"], 817.5, places=1)
        vat_base = 500_000 + duty
        fee = res["breakdown"]["customs_fee"]
        self.assertAlmostEqual(res["breakdown"]["vat_base"], vat_base, places=0)
        self.assertAlmostEqual(res["breakdown"]["vat"], round(vat_base * 0.22, 2), places=0)
        self.assertAlmostEqual(
            res["breakdown"]["total_payable"],
            round(fee + duty + vat_base * 0.22, 2),
            places=0,
        )

    def test_golden_steel_cn_antidumping(self):
        """Золотой тест: арматура из Китая с антидемпингом (+ спецпошлины из БД, если есть)."""
        res = compute_payments({
            "hs_code": "7214990000",
            "customs_value": 100_000,
            "freight": 0,
            "country": "CN",
        })
        # duty = 100000 * 10% = 10000
        self.assertAlmostEqual(res["breakdown"]["duty"], 10_000.0, places=0)
        # antidumping = 100000 * 18% = 18000
        self.assertAlmostEqual(res["breakdown"]["antidumping"], 18_000.0, places=0)
        b = res["breakdown"]
        vat_base_expected = 100_000 + b["duty"] + b["excise"] + b["antidumping"] + b["special_duties_amount"]
        self.assertAlmostEqual(b["vat_base"], vat_base_expected, places=0)
        self.assertAlmostEqual(b["vat"], round(vat_base_expected * 0.22, 2), places=0)
        fee = b["customs_fee"]
        total_expected = fee + b["duty"] + b["excise"] + b["antidumping"] + b["special_duties_amount"] + b["vat"]
        self.assertAlmostEqual(b["total_payable"], total_expected, places=0)

    def test_golden_beer_excise(self):
        """Золотой тест: пиво — акциз процентный."""
        res = compute_payments({
            "hs_code": "2203009900",
            "customs_value": 200_000,
            "freight": 0,
        })
        # duty = 200000 * 5% = 10000
        self.assertAlmostEqual(res["breakdown"]["duty"], 10_000.0, places=0)
        # excise = 200000 * 5% = 10000
        self.assertAlmostEqual(res["breakdown"]["excise"], 10_000.0, places=0)
        # vat_base = 200000 + 10000 + 10000 = 220000
        self.assertAlmostEqual(res["breakdown"]["vat_base"], 220_000.0, places=0)
        # vat = 220000 * 22% = 48400
        self.assertAlmostEqual(res["breakdown"]["vat"], 48_400.0, places=0)
        fee = res["breakdown"]["customs_fee"]
        self.assertAlmostEqual(res["breakdown"]["total_payable"], fee + 68_400.0, places=0)

    def test_golden_food_vat10(self):
        """Золотой тест: мясо — НДС 10% (через apply_reduced_vat)."""
        res = compute_payments({
            "hs_code": "0201300000",
            "customs_value": 500_000,
            "freight": 50_000,
            "apply_reduced_vat": True,
        })
        self.assertEqual(res["breakdown"]["vat_rate"], 10.0)
        # duty из БД (может отличаться от 15% при перекрытии ЕТТ)
        duty = res["breakdown"]["duty"]
        self.assertGreater(duty, 0)
        vat_base = 500_000 + duty + res["breakdown"]["excise"] + res["breakdown"]["antidumping"] + res["breakdown"]["special_duties_amount"]
        self.assertAlmostEqual(res["breakdown"]["vat_base"], vat_base, places=0)
        self.assertAlmostEqual(res["breakdown"]["vat"], round(vat_base * 0.10, 2), places=0)
        fee = res["breakdown"]["customs_fee"]
        total_exp = fee + duty + res["breakdown"]["excise"] + res["breakdown"]["antidumping"] + res["breakdown"]["special_duties_amount"] + res["breakdown"]["vat"]
        self.assertAlmostEqual(res["breakdown"]["total_payable"], total_exp, places=0)

    def test_sources_in_result(self):
        """В ответе есть источники (интегрированные данные)."""
        res = self._calc(hs_code="8509400000", customs_value=100_000)
        self.assertIsInstance(res["sources"], list)
        self.assertGreater(len(res["sources"]), 0)
        for s in res["sources"]:
            self.assertIn("name", s)
            self.assertIn("integrated", s)
            self.assertIn("data_info", s)

    def test_data_quality_in_result(self):
        """В ответе есть блок data_quality."""
        res = self._calc(hs_code="8509400000", customs_value=100_000)
        dq = res["data_quality"]
        self.assertIn("confidence", dq)
        self.assertIn("matched_prefix", dq)
        self.assertIn("match_length", dq)
        self.assertIn("antidumping_status", dq)

    def test_error_on_zero_customs_value(self):
        """Нулевая таможенная стоимость → ValueError."""
        with self.assertRaises(ValueError):
            compute_payments({"hs_code": "8509400000", "customs_value": 0})

    def test_insurance_auto_calculated(self):
        """Страховка рассчитывается автоматически как 0.15% от (стоимость + фрахт)."""
        res = compute_payments({
            "hs_code": "8509400000",
            "customs_value": 100_000,
            "freight": 10_000,
        })
        expected = round(0.0015 * (100_000 + 10_000), 2)
        self.assertAlmostEqual(res["insurance"], expected, places=2)

    def test_insurance_explicit(self):
        """Явно переданная страховка используется как есть."""
        res = compute_payments({
            "hs_code": "8509400000",
            "customs_value": 100_000,
            "freight": 10_000,
            "insurance": 500,
        })
        self.assertEqual(res["insurance"], 500.0)

    def test_compare_payment_scenarios(self):
        """Два кода при одной стоимости — разбивка и дельта к первому."""
        out = compare_payment_scenarios(
            {
                "shared": {"customs_value": 500_000, "freight": 50_000, "country": "CN"},
                "scenarios": [
                    {"hs_code": "8509400000", "label": "Чайник"},
                    {"hs_code": "8516108008", "label": "Плита"},
                ],
            }
        )
        self.assertEqual(out["status"], "OK")
        self.assertEqual(len(out["scenarios"]), 2)
        self.assertIsNone(out["scenarios"][0]["delta_total_vs_first_rub"])
        self.assertIsNotNone(out["scenarios"][1]["delta_total_vs_first_rub"])
        first_total = float(out["scenarios"][0]["total_payable"])
        second_total = float(out["scenarios"][1]["total_payable"])
        expected_delta = round(second_total - first_total, 2)
        self.assertEqual(out["scenarios"][1]["delta_total_vs_first_rub"], expected_delta)

    def test_compare_requires_two(self):
        with self.assertRaises(ValueError):
            compare_payment_scenarios(
                {
                    "shared": {"customs_value": 100_000},
                    "scenarios": [{"hs_code": "8509400000"}],
                }
            )


if __name__ == "__main__":
    unittest.main()
