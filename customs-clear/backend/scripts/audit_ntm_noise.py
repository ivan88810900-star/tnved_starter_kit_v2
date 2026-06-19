"""Аудит noise-разметки нетарифных мер (issue #110).

Воспроизводимый отчёт: распределение noise по типам мер + валидация
контрольных кодов классификатора. Помогает периодически проверять, что высокая
доля noise остаётся обоснованной (исправление массового over-assignment краулера
TKS), а не следствием ложноположительных срабатываний.

Запуск:
    cd customs-clear/backend && ../../.venv/bin/python -m scripts.audit_ntm_noise
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal
from app.models.tnved import NonTariffMeasure
from app.services.ntm_noise_classifier import is_measure_noise

# Контрольные коды: какие типы мер должны остаться (keep) и какие — noise.
CONTROL_CODES: list[tuple[str, str, set[str], set[str]]] = [
    ("8517120000", "Смартфон", {"certificate", "tr_ts"}, {"sgr", "vet_control", "phyto_control"}),
    ("8471300000", "Ноутбук", {"certificate", "tr_ts"}, {"sgr", "vet_control", "phyto_control"}),
    ("0808108000", "Яблоки", {"phyto_control"}, {"sgr", "vet_control"}),
    ("0201100000", "Говядина", {"vet_control", "certificate"}, {"phyto_control", "sgr"}),
    ("6403990000", "Обувь", {"certificate", "tr_ts"}, {"vet_control", "phyto_control", "sgr"}),
    ("9503007500", "Игрушка", {"certificate", "tr_ts"}, {"vet_control", "phyto_control", "sgr"}),
    ("3304990000", "Косметика", {"certificate", "tr_ts"}, {"vet_control", "phyto_control", "sgr"}),
    ("9401300000", "Кресло", {"certificate", "tr_ts"}, {"vet_control", "phyto_control", "sgr"}),
    ("3004909200", "Лекарство", {"license", "certificate"}, {"vet_control", "phyto_control", "sgr"}),
    ("2106909200", "БАД", {"sgr", "certificate", "tr_ts"}, {"vet_control", "phyto_control"}),
    ("2204210000", "Вино", {"license", "certificate", "tr_ts"}, {"vet_control", "phyto_control"}),
    ("8703230000", "Автомобиль", {"certificate", "tr_ts"}, {"vet_control", "phyto_control", "sgr"}),
]


def distribution() -> None:
    print("=== Noise distribution by measure_type ===")
    print(f"{'measure_type':<18} {'total':>7} {'noise':>7} {'noise%':>7}")
    with SessionLocal() as db:
        rows = db.query(NonTariffMeasure.measure_type, NonTariffMeasure.quality).all()
    by_type: dict[str, list[int]] = {}
    for mtype, quality in rows:
        t = (mtype or "?").strip().lower()
        bucket = by_type.setdefault(t, [0, 0])
        bucket[0] += 1
        if (quality or "").strip().lower() == "noise":
            bucket[1] += 1
    total = noise = 0
    for t, (cnt, n) in sorted(by_type.items(), key=lambda x: -x[1][1]):
        pct = 100.0 * n / cnt if cnt else 0.0
        print(f"{t:<18} {cnt:>7} {n:>7} {pct:>6.1f}%")
        total += cnt
        noise += n
    overall = 100.0 * noise / total if total else 0.0
    print(f"{'TOTAL':<18} {total:>7} {noise:>7} {overall:>6.1f}%")


def validate_control_codes() -> int:
    print("\n=== Control-code validation (precision) ===")
    failures = 0
    for code, desc, keep_types, noise_types in CONTROL_CODES:
        for mt in keep_types:
            if is_measure_noise(code, mt):
                print(f"  FAIL {code} {desc}: {mt} should be KEPT but marked noise")
                failures += 1
        for mt in noise_types:
            if not is_measure_noise(code, mt):
                print(f"  FAIL {code} {desc}: {mt} should be NOISE but kept")
                failures += 1
    if failures == 0:
        print(f"  OK — {len(CONTROL_CODES)}/{len(CONTROL_CODES)} control codes pass")
    return failures


def main() -> None:
    distribution()
    failures = validate_control_codes()
    print(
        "\nВывод: высокая доля noise по license/sgr ожидаема — краулер TKS массово "
        "присваивал меры почти всем кодам; классификатор оставляет только меры в "
        "официальном регуляторном scope (Решения ЕЭК №317/318/299/30, каталог ТР ТС)."
    )
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
