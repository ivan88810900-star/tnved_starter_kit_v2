from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy.orm import selectinload

from app.api.tnved_catalog import _build_preview_payload, _measure_label
from app.db import SessionLocal
from app.models.tnved import Commodity, NonTariffMeasure
from app.services.payment_engine import compute_payments

OUT_PATH = ROOT / "downloads" / "final_qc.txt"

TEST_ITEMS: list[tuple[str, str]] = [
    ("8516710000", "Электронагревательные приборы для приготовления кофе"),
    ("8542319010", "Электронные интегральные схемы: процессоры / аппаратные кошельки"),
    ("3304990000", "Косметические средства по уходу за кожей"),
    ("8421210009", "Оборудование и устройства для фильтрования воды"),
    ("9503004100", "Игрушки мягкие, изображающие животных"),
]

TR_CODE_RE = re.compile(r"\b(\d{3}/\d{4})\b")


def _digits10(code: str) -> str:
    d = "".join(ch for ch in str(code or "") if ch.isdigit())
    return d.zfill(10)[:10]


def _non_tariff_code_candidates(code10: str) -> list[str]:
    d = _digits10(code10)
    return [d, d[:6] + "0000", d[:4] + "000000"]


def _collect_effective_measures(db, code10: str) -> tuple[str | None, str, list, str]:
    """Как в preview: прямые меры позиции или fallback 6/4-значного кода."""
    row = (
        db.query(Commodity)
        .options(selectinload(Commodity.non_tariff_measures))
        .filter(Commodity.code == code10)
        .order_by(Commodity.id.asc())
        .first()
    )
    if not row:
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


def _emit(lines: list[str], sink: list[str], fh) -> None:
    for line in lines:
        print(line)
        sink.append(line)
        fh.write(line + "\n")


def _format_duty_line(bd: dict) -> str:
    dr = bd.get("duty_rate")
    if dr is not None and isinstance(dr, (int, float)):
        return f"{float(dr):g} %"
    if dr is not None:
        return str(dr)
    sel = bd.get("selected_rule") or ""
    if sel:
        return str(sel)
    return "—"


def _format_vat_line(bd: dict) -> str:
    rate = bd.get("vat_rate")
    reason = (bd.get("vat_reason") or "").strip()
    decree = (bd.get("vat_decree_info") or "").strip()
    comment = (bd.get("vat_pref_comment") or "").strip()
    base = f"{float(rate):g} %" if isinstance(rate, (int, float)) else str(rate)
    if isinstance(rate, (int, float)) and abs(float(rate) - 10.0) < 0.01:
        parts = [base]
        if decree:
            parts.append(f"основание: {decree}")
        if comment and comment not in decree:
            parts.append(comment)
        if reason and "22%" not in reason:
            parts.append(f"({reason})")
        return " ".join(parts)
    if reason:
        return f"{base} ({reason})"
    return base


def _format_excise_line(bd: dict) -> str:
    amt = bd.get("excise")
    reason = (bd.get("excise_reason") or "").strip()
    try:
        a = float(amt or 0)
    except (TypeError, ValueError):
        a = 0.0
    if a <= 0 and (not reason or reason == "Не применяется"):
        return "нет"
    if reason:
        return f"{a:g} руб. — {reason}"
    return f"{a:g} руб."


def _payments_for_code(code10: str) -> dict:
    payload = {
        "hs_code": code10,
        "customs_value": 100_000.0,
        "freight": 0.0,
        "quantity": 1.0,
    }
    try:
        return compute_payments(payload)
    except ValueError:
        payload2 = {
            **payload,
            "extra_quantity": 1.0,
            "net_weight_kg": 1.0,
        }
        return compute_payments(payload2)


def _measure_display_lines(rows: list) -> list[str]:
    lines: list[str] = []
    for m in rows:
        mtype = (m.measure_type or "").strip().lower()
        label = _measure_label(mtype)
        act = (m.regulatory_act or "").strip()
        doc = (m.document_required or "").strip()
        title = act or doc or (m.description or "").strip() or "—"
        lines.append(f"[{mtype}] {title}")
    return lines


def _tr_codes_in_measure(m) -> set[str]:
    blob = " ".join(
        [
            m.regulatory_act or "",
            m.document_required or "",
            m.description or "",
        ]
    )
    return set(TR_CODE_RE.findall(blob))


def _validate(
    code10: str,
    rows: list,
    display_lines: list[str],
) -> list[str]:
    fails: list[str] = []
    types = {(m.measure_type or "").strip().lower() for m in rows}

    if code10.startswith("3304") or code10.startswith("8421"):
        if "vet_control" in types or "phyto_control" in types:
            fails.append(
                f"[FAIL] {code10}: для косметики (33) или фильтров (84.21) не ожидается vet_control/phyto_control."
            )

    if code10.startswith("9503"):
        has_tr_ts = any((m.measure_type or "").strip().lower() == "tr_ts" for m in rows)
        has_008 = any(
            (m.measure_type or "").strip().lower() == "tr_ts" and "008/2011" in _tr_codes_in_measure(m)
            for m in rows
        )
        if not has_tr_ts or not has_008:
            fails.append(
                f"[FAIL] {code10}: ожидается мера tr_ts с ТР ТС 008/2011 (безопасность игрушек)."
            )

    tr_hits: dict[str, int] = {}
    for m in rows:
        for tc in _tr_codes_in_measure(m):
            tr_hits[tc] = tr_hits.get(tc, 0) + 1
    for tc, cnt in sorted(tr_hits.items()):
        if cnt > 1:
            fails.append(
                f"[FAIL] {code10}: нормативный код {tc} встречается в {cnt} мерах (возможный дубль акта)."
            )

    seen_pair: set[tuple[str, str]] = set()
    for m in rows:
        mtype = (m.measure_type or "").strip().lower()
        act = (m.regulatory_act or "").strip()
        key = (mtype, act)
        if act and key in seen_pair:
            fails.append(
                f"[FAIL] {code10}: дублируется акт для одного кода: [{mtype}] {act}"
            )
        seen_pair.add(key)

    return fails


def run() -> int:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    buffer: list[str] = []
    all_fails: list[str] = []

    with OUT_PATH.open("w", encoding="utf-8") as fh:

        def out(lines: list[str]) -> None:
            _emit(lines, buffer, fh)

        out(["=" * 72, "Final QC — preview + платежи + нетарифка", "=" * 72, ""])

        for code10, hint in TEST_ITEMS:
            code10 = _digits10(code10)
            prev = _build_preview_payload(code10)
            status = prev.get("status", "")

            out([f"📦 Код и наименование: {code10} ({hint})"])
            if status != "OK":
                out([f"   preview status: {status}", f"   detail: {prev.get('detail', prev)}", ""])
                all_fails.append(f"[FAIL] {code10}: preview не OK ({status})")
                continue

            name = (prev.get("name") or "").strip()
            if name:
                out([f"   Каталог: {name}"])

            try:
                pay = _payments_for_code(code10)
            except ValueError as e:
                out([f"   💰 Платежи: ошибка расчёта: {e}", ""])
                all_fails.append(f"[FAIL] {code10}: compute_payments — {e}")
                continue

            bd = pay.get("breakdown") or {}
            out(
                [
                    "💰 Платежи (сценарий: таможенная стоимость 100 000 руб., qty=1):",
                    f"   Пошлина: {_format_duty_line(bd)}",
                    f"   НДС: {_format_vat_line(bd)}",
                    f"   Акциз: {_format_excise_line(bd)}",
                ]
            )

            with SessionLocal() as db:
                eff_code, _title, nt_rows, src = _collect_effective_measures(db, code10)

            out([f"   (нетарифка: источник мер — {src}, commodity {eff_code or code10})"])
            out(["🛡️ Нетарифное регулирование (чистовой срез):"])
            if not nt_rows:
                out(["   — меры не найдены", ""])
            else:
                for line in _measure_display_lines(nt_rows):
                    out([f"   {line}"])
                out([""])

            fails = _validate(code10, nt_rows, _measure_display_lines(nt_rows))
            all_fails.extend(fails)

        out(["—" * 72, "Итог проверок"])
        if all_fails:
            for f in all_fails:
                out([f])
        else:
            out(["[OK] Авто-валидация: замечаний нет."])
        out([""])

    return 1 if all_fails else 0


if __name__ == "__main__":
    raise SystemExit(run())
