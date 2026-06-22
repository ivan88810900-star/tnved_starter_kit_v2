"""Тесты структурного парсера TKS (актуальная вёрстка modal AJAX).

Проверяем, что:
- из ``table.product-info__table`` корректно извлекаются пошлина/НДС;
- нетарифные меры эмитируются ТОЛЬКО для положительных флагов (да/есть),
  а значение «нет» больше не порождает ложных мер (регрессия noise-бага).
"""
from __future__ import annotations

import sys
from pathlib import Path

from bs4 import BeautifulSoup

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND / "scripts"))

import sync_tks_nontariff as tks  # noqa: E402

_FIXTURE_LAPTOP = Path(__file__).parent / "fixtures_tks_8471300000.html"

# Синтетическая модалка с положительными флагами (требуется лицензия + сертификация).
_HTML_POSITIVE = """
<div class="modal__dialog base_code_info">
  <h5 class="modal__title">9301000000</h5>
  <section class="product-info">
    <table class="product-info__table">
      <tr><td>Пошлина:</td><td>10 %</td><td></td></tr>
      <tr><td>Антидемп. пошлина:</td><td>нет</td><td></td></tr>
      <tr><td>Акциз:</td><td>нет</td><td></td></tr>
      <tr><td>НДС:</td><td>22 % (базовая)</td><td></td></tr>
      <tr><td>Лицензирование:</td><td>да</td><td></td></tr>
      <tr><td>Квотирование:</td><td>нет</td><td></td></tr>
      <tr><td>Сертификация:</td><td>есть</td><td></td></tr>
      <tr><td>Разреш. прочие:</td><td>нет</td><td></td></tr>
    </table>
  </section>
</div>
"""


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


class TestTksTableParsing:
    def test_table_parsed_to_dict(self) -> None:
        soup = _soup(_HTML_POSITIVE)
        table = tks.parse_product_info_table(soup)
        assert table.get("пошлина") == "10 %"
        assert table.get("ндс", "").startswith("22")
        assert table.get("лицензирование") == "да"
        assert table.get("сертификация") == "есть"

    def test_import_text_from_table(self) -> None:
        soup = _soup(_HTML_POSITIVE)
        table = tks.parse_product_info_table(soup)
        txt = tks._format_import_from_table(table)
        assert "Пошлина: 10 %" in txt
        assert "НДС: 22" in txt

    def test_positive_flags_emit_measures(self) -> None:
        soup = _soup(_HTML_POSITIVE)
        table = tks.parse_product_info_table(soup)
        specs = tks.parse_nontariff_from_table(table)
        types = {s["measure_type"] for s in specs}
        assert "license" in types, "Лицензирование: да → license"
        assert "certificate" in types, "Сертификация: есть → certificate"

    def test_negative_flags_emit_nothing(self) -> None:
        soup = _soup(_HTML_POSITIVE)
        table = tks.parse_product_info_table(soup)
        specs = tks.parse_nontariff_from_table(table)
        types = {s["measure_type"] for s in specs}
        # Квотирование: нет, Разреш. прочие: нет → не должны эмитироваться
        assert "other" not in types


class TestTksRealFixtureLaptop:
    """Реальная модалка TKS для ноутбука 8471300000: все нетарифные флаги = нет."""

    def test_fixture_present(self) -> None:
        assert _FIXTURE_LAPTOP.exists()

    def test_laptop_import_duty_extracted(self) -> None:
        soup = _soup(_FIXTURE_LAPTOP.read_text(encoding="utf-8"))
        table = tks.parse_product_info_table(soup)
        txt = tks._format_import_from_table(table)
        assert "Пошлина: нет" in txt
        assert "НДС: 22" in txt

    def test_laptop_no_false_nontariff_measures(self) -> None:
        # Регрессия: раньше для ноутбука эмитировались ложные certificate/sgr/license.
        soup = _soup(_FIXTURE_LAPTOP.read_text(encoding="utf-8"))
        table = tks.parse_product_info_table(soup)
        specs = tks.parse_nontariff_from_table(table)
        assert specs == [], f"Ноутбук не должен порождать нетарифных мер из TKS, получено: {specs}"
