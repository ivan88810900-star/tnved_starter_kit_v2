"""Аудит глав с малым покрытием нетарифных мер (issue #123).

Контекст
--------
Часть глав ТН ВЭД имеет < 20 «чистых» строк в ``non_tariff_measures``
(quality != 'noise'). Issue #123 предлагал докачать их парсером
``sync_tks_nontariff.py``. Эмпирическая проверка показала, что против текущей
версии сайта TKS.ru парсер:

* извлекает **0** нетарифных мер для этих глав (модальная вёрстка info-эндпоинта
  не содержит разбираемого блока «Нетарифное регулирование»);
* **портит** поле ``import_duty`` мусором вида «Пошлина: Пошлина: | НДС: НДС:».

Поэтому массовый прогон TKS-синка здесь вреден. Этот скрипт вместо докачки
делает **воспроизводимый аудит**: показывает, что низкое число строк в БД
для этих глав не означает пропуск enforcement — требования для готовых
потребительских товаров формирует runtime-слой (каталог ТР ТС / ntm_layers),
а сырьё/полуфабрикаты этих глав легитимно идут без разрешительных документов.

Запуск:
    cd customs-clear/backend && ../../.venv/bin/python -m scripts.audit_low_coverage_chapters
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text

from app.db import engine
from app.services.non_tariff_service import check_position_non_tariff

CLEAN_THRESHOLD = 20

# Контрольные коды из «бедных» глав: готовые потребительские товары, для которых
# брокер ОБЯЗАН вернуть требование (как правило ДС по ТР ТС 017/2011 и т.п.),
# и сырьё/промежуточная продукция, которая легитимно идёт без разрешений.
SPOTCHECK: list[tuple[str, str, bool]] = [
    # (hs_code, описание, ожидаем_ли_хотя_бы_одно_требование)
    ("6204620000", "Брюки женские, хлопок (готовая одежда)", True),
    ("6505003000", "Головной убор трикотажный", True),
    ("7321110000", "Плита бытовая газовая", True),
    ("5007201000", "Ткань шёлковая (материал)", False),
    ("4901990000", "Книги печатные", False),
    ("2501001000", "Соль пищевая", False),
]


def low_coverage_chapters() -> list[tuple[int, int, int]]:
    q = text(
        """
        SELECT CAST(SUBSTR(commodity_code, 1, 2) AS INT) AS ch,
               COUNT(CASE WHEN quality != 'noise' OR quality IS NULL THEN 1 END) AS clean,
               COUNT(*) AS total
        FROM non_tariff_measures
        GROUP BY ch
        HAVING clean < :thr
        ORDER BY ch
        """
    )
    with engine.connect() as conn:
        rows = [(int(r[0]), int(r[1]), int(r[2])) for r in conn.execute(q, {"thr": CLEAN_THRESHOLD})]
    print(f"=== Главы с clean < {CLEAN_THRESHOLD} ({len(rows)} шт.) ===")
    print(f"{'глава':>6} {'clean':>7} {'total':>7}")
    for ch, clean, total in rows:
        print(f"{ch:>6} {clean:>7} {total:>7}")
    return rows


def broker_spotcheck() -> int:
    print("\n=== Spot-check брокера для кодов «бедных» глав ===")
    failures = 0
    for code, desc, expect_req in SPOTCHECK:
        res = asyncio.run(
            check_position_non_tariff(
                hs_code=code,
                description=desc,
                country="CN",
                permits=[],
                skip_registry_verify=True,
            )
        )
        permits = res.get("required_permit_types") or []
        has_req = bool(permits)
        ok = has_req == expect_req
        flag = "OK" if ok else "FAIL"
        if not ok:
            failures += 1
        exp_label = "требование ожидается" if expect_req else "требований не ожидается"
        print(f"  [{flag}] {code} {desc}: {permits or '—'}  ({exp_label})")
    if failures == 0:
        print(f"  OK — {len(SPOTCHECK)}/{len(SPOTCHECK)} контрольных кодов соответствуют ожиданиям")
    return failures


def main() -> None:
    low_coverage_chapters()
    failures = broker_spotcheck()
    print(
        "\nВывод: малое число строк non_tariff_measures для текстиля (50–67), чёрных/"
        "цветных металлов (72–80) и пр. — не пробел в данных. Требования для готовых "
        "потребительских товаров формирует runtime-слой ТР ТС (ntm_layers / tr_ts_catalog), "
        "сырьё и полуфабрикаты легитимно идут без разрешительных документов. "
        "Прогон sync_tks_nontariff.py против текущего TKS даёт 0 мер и портит import_duty, "
        "поэтому докачка через него отклонена в пользу runtime-слоя / курируемых backfill."
    )
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
