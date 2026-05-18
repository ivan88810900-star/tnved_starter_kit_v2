"""Извлечение номеров СС/ДС/СГР из текста документов (инвойс, PDF)."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Set, Tuple


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def extract_permits_from_text(text: str) -> List[Dict[str, str]]:
    """Находит типовые номера деклараций/сертификатов ЕАЭС и СГР в произвольном тексте."""
    if not text or len(text.strip()) < 5:
        return []

    t = text.replace("\xa0", " ")
    found: List[Tuple[str, str]] = []
    seen: Set[str] = set()

    def add(ptype: str, raw: str) -> None:
        n = _norm(raw)
        if len(n) < 8:
            return
        key = f"{ptype}:{n.upper()}"
        if key in seen:
            return
        seen.add(key)
        found.append((ptype, n))

    # Декларация: ЕАЭС RU Д-xx... / ЕАЭС N RU Д-xx... / EAEU RU D-...
    for m in re.finditer(
        r"(?i)(?:ЕАЭС|EAEU)\s*(?:N|№)?\s*RU\s*[DД]\s*[-–—]?\s*([A-ZА-Я0-9./]{8,80})",
        t,
    ):
        add("ДС", f"ЕАЭС RU Д-{m.group(1)}")

    # Альтернатива: RU Д- без префикса ЕАЭС
    for m in re.finditer(
        r"(?i)\bRU\s*[DД]\s*[-–—]?\s*([A-ZА-Я0-9./]{8,80})",
        t,
    ):
        add("ДС", f"ЕАЭС RU Д-{m.group(1)}")

    # Сертификат: ЕАЭС RU С-...
    for m in re.finditer(
        r"(?i)(?:ЕАЭС|EAEU)\s*RU\s*[CС]\s*[-–—]?\s*([A-ZА-Я0-9./]{8,80})",
        t,
    ):
        add("СС", f"ЕАЭС RU С-{m.group(1)}")

    # СГР: RU.XX.XX.НГ01.ВШХ... (типовой формат)
    for m in re.finditer(
        r"\bRU\.\d{2}\.\d{2}\.[A-ZА-Я0-9]{2,10}\.[A-ZА-Я0-9]{2,20}\b",
        t,
        re.I,
    ):
        add("СГР", m.group(0).upper())

    # 10-значный ТН ВЭД рядом с «декларац» / «сертификат» — не добавляем как документ

    return [{"type": p, "number": n} for p, n in found]


def merge_permit_lists(
    manual: List[Dict[str, str]],
    extracted: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    """Объединяет ручной ввод и извлечённые номера без дубликатов."""
    out: List[Dict[str, str]] = []
    seen: Set[str] = set()
    for src in (manual, extracted):
        for p in src:
            t = (p.get("type") or "").strip().upper()
            n = (p.get("number") or "").strip()
            if not n:
                continue
            if t in ("СЕРТИФИКАТ",):
                t = "СС"
            if t in ("ДЕКЛАРАЦИЯ",):
                t = "ДС"
            key = f"{t}:{n.upper()}"
            if key in seen:
                continue
            seen.add(key)
            out.append({"type": t, "number": n})
    return out
