from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from sqlalchemy.orm import selectinload

from app.db import SessionLocal
from app.models.tnved import Commodity, NonTariffMeasure


TEST_CODES = [
    "8516710000",  # Электронагревательные приборы для приготовления кофе
    "0901210000",  # Кофе жареный
    "0201100001",  # Мясо крупного рогатого скота
    "6109100000",  # Футболки трикотажные
    "8703231940",  # Автомобили легковые
]

QC_REPORT_PATH = ROOT / "downloads" / "qc_report.txt"
SUSPICIOUS_THRESHOLD = 12
MASS_INHERITANCE_THRESHOLD = 5000


def _digits(raw: str) -> str:
    return "".join(ch for ch in str(raw or "") if ch.isdigit())


def _pad10(raw: str) -> str:
    d = _digits(raw)
    return d.zfill(10)[:10]


def _non_tariff_code_candidates(code10: str) -> list[str]:
    d = _pad10(code10)
    return [d, d[:6] + "0000", d[:4] + "000000"]


def _chapter(code10: str) -> int | None:
    if len(code10) < 2 or not code10[:2].isdigit():
        return None
    return int(code10[:2])


def _is_vet_phyto_unexpected_chapter(code10: str) -> bool:
    """
    Подозрительные группы для vet/phyto:
      50-63 (текстиль), 64 (обувь), 68-76 (камень/стекло/металлы), 84-97 (техника/транспорт/инструменты).
    """
    ch = _chapter(code10)
    if ch is None:
        return False
    return (50 <= ch <= 63) or (ch == 64) or (68 <= ch <= 76) or (84 <= ch <= 97)


def _is_food(code10: str) -> bool:
    ch = _chapter(code10)
    return ch is not None and 1 <= ch <= 24


def _collect_effective_measures(db, code10: str) -> tuple[str | None, str, list[NonTariffMeasure], str]:
    """
    Возвращает:
      - найденный код commodity (или None),
      - название commodity,
      - эффективные нетарифные меры,
      - источник мер: direct | fallback | not_found
    Логика совпадает с preview: если у позиции нет прямых мер, берём fallback (6/4 префикс).
    """
    row = (
        db.query(Commodity)
        .options(selectinload(Commodity.non_tariff_measures))
        .filter(Commodity.code == code10)
        .order_by(Commodity.id.asc())
        .first()
    )
    if not row:
        # fallback, как в preview: первая позиция по 4-значному префиксу
        row = (
            db.query(Commodity)
            .options(selectinload(Commodity.non_tariff_measures))
            .filter(Commodity.code.like(f"{code10[:4]}%"))
            .order_by(Commodity.code.asc())
            .first()
        )
    if not row:
        return None, "", [], "not_found"

    title = (row.description or "").strip()
    direct_rows = list(row.non_tariff_measures or [])
    if direct_rows:
        return (row.code or ""), title, direct_rows, "direct"

    fallback_codes = _non_tariff_code_candidates(code10)[1:]
    fb_rows = (
        db.query(NonTariffMeasure)
        .filter(NonTariffMeasure.commodity_code.in_(fallback_codes))
        .order_by(NonTariffMeasure.id.asc())
        .all()
    )
    return (row.code or ""), title, fb_rows, "fallback"


def _unique_measures(rows: list[NonTariffMeasure]) -> list[dict[str, str]]:
    # "Разные меры" считаем по сочетанию типа + акта + требуемого документа.
    # Это убирает дубли одного и того же требования с разными текстами description.
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, str]] = []
    for m in rows:
        mtype = (m.measure_type or "").strip().lower()
        reg = (m.regulatory_act or "").strip()
        doc = (m.document_required or "").strip()
        desc = (m.description or "").strip()
        key = (mtype, reg, doc)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "measure_type": mtype,
                "regulatory_act": reg,
                "document_required": doc,
                "description": desc,
            }
        )
    out.sort(
        key=lambda x: (
            x["measure_type"],
            x["regulatory_act"],
            x["document_required"],
            x["description"],
        )
    )
    return out


def _analyze_suspicious(code10: str, uniq: list[dict[str, str]]) -> list[str]:
    tags: list[str] = []
    if len(uniq) > SUSPICIOUS_THRESHOLD:
        tags.append(
            f"[SUSPICIOUS] На код ложится слишком много мер: {len(uniq)} (> {SUSPICIOUS_THRESHOLD})."
        )

    measure_types = {m["measure_type"] for m in uniq}
    if _is_vet_phyto_unexpected_chapter(code10) and {"vet_control", "phyto_control"} & measure_types:
        tags.append(
            "[SUSPICIOUS] Для группы 50-63/64/68-76/84-97 найден vet_control/phyto_control (возможное ложное наследование)."
        )

    if _is_food(code10):
        has_low_voltage_refs = any(
            "004/2011" in " ".join(
                [m["regulatory_act"], m["document_required"], m["description"]]
            )
            for m in uniq
        )
        if has_low_voltage_refs:
            tags.append(
                "[SUSPICIOUS] Для пищевого кода (01-24) найдено упоминание ТР ТС 004/2011."
            )
    return tags


def _mass_inheritance_warnings(db) -> list[str]:
    rows = db.execute(
        text(
            """
            SELECT
                COALESCE(TRIM(regulatory_act), '') AS act,
                COUNT(DISTINCT commodity_code) AS codes_count
            FROM non_tariff_measures
            WHERE LENGTH(COALESCE(commodity_code, '')) = 10
            GROUP BY COALESCE(TRIM(regulatory_act), '')
            HAVING COUNT(DISTINCT commodity_code) > :threshold
            ORDER BY codes_count DESC, act ASC
            """
        ),
        {"threshold": MASS_INHERITANCE_THRESHOLD},
    ).fetchall()
    out: list[str] = []
    for act, count in rows:
        act_name = act or "<без акта>"
        out.append(
            f"[WARNING] Мера {act_name} привязана к {int(count)} кодам. Возможна ошибка слишком широкого префикса."
        )
    return out


def _write_report() -> None:
    QC_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with QC_REPORT_PATH.open("w", encoding="utf-8") as fh:
        def emit(line: str = "") -> None:
            print(line)
            fh.write(line + "\n")

        emit("QC REPORT: нетарифные привязки / шум-контроль")
        emit(f"Сформировано: {datetime.now().isoformat(timespec='seconds')}")
        emit(f"Файл отчета: {QC_REPORT_PATH}")
        emit("=" * 96)

        with SessionLocal() as db:
            mass_alerts = _mass_inheritance_warnings(db)
            emit("Глобальный детектор массового наследования:")
            if mass_alerts:
                for line in mass_alerts:
                    emit(f"  - {line}")
            else:
                emit("  - [OK] Массовых наследований по порогу не найдено.")
            emit("-" * 96)

            for idx, raw_code in enumerate(TEST_CODES, start=1):
                code10 = _pad10(raw_code)
                found_code, title, raw_rows, source_mode = _collect_effective_measures(db, code10)
                emit(f"[{idx}] Код: {code10}")
                if not found_code:
                    emit("Наименование: <не найдено в tnved_commodities>")
                    emit("Меры: 0")
                    emit("Аномалии: [SUSPICIOUS] Код не найден в каталоге.")
                    emit("-" * 96)
                    continue

                emit(f"Наименование: {title or '<пусто>'}")
                emit(f"Resolved commodity code: {found_code}")
                emit(f"Источник мер: {source_mode}")
                emit(f"Сырых строк мер: {len(raw_rows)}")

                uniq = _unique_measures(raw_rows)
                emit(f"Уникальных мер: {len(uniq)}")
                emit("Список мер:")
                if not uniq:
                    emit("  - <нет мер>")
                else:
                    for m in uniq:
                        emit(
                            "  - "
                            f"[{m['measure_type'] or 'unknown'}] "
                            f"{m['regulatory_act'] or '<без акта>'} | "
                            f"doc: {m['document_required'] or '<без документа>'}"
                        )

                suspicious_tags = _analyze_suspicious(code10, uniq)
                emit("Аномалии:")
                if suspicious_tags:
                    for tag in suspicious_tags:
                        emit(f"  - {tag}")
                else:
                    emit("  - [OK] Подозрительных эвристических сигналов не найдено.")
                emit("-" * 96)


def main() -> None:
    _write_report()


if __name__ == "__main__":
    main()

