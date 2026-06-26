"""PDF-отчёт по данным ВЭД (тот же смысл, что JSON-экспорт из UI). PyMuPDF Story + HTML."""
from __future__ import annotations

import html
import json
import os
import tempfile
from typing import Any, Dict, List

import fitz


def _esc(x: Any) -> str:
    if x is None:
        return ""
    return html.escape(str(x), quote=True)


def _truncate(s: str, max_len: int) -> str:
    s = s or ""
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def build_ved_report_html(data: Dict[str, Any]) -> str:
    parts: List[str] = []
    parts.append("<h1>Tariff — отчёт ВЭД</h1>")
    parts.append("<p><em>Справочный документ; юридическая ответственность за декларацию несёт специалист.</em></p>")

    parts.append("<h2>Общие сведения</h2><ul>")
    parts.append(f"<li>Экспорт: {_esc(data.get('exported_at'))}</li>")
    parts.append(f"<li>Документ ID: {_esc(data.get('document_id'))}</li>")
    parts.append(f"<li>ВЭД-статус: {_esc(data.get('ved_intel_status'))}</li>")
    parts.append(f"<li>Проверка: {_esc(data.get('status'))}</li>")
    parts.append("</ul>")

    note = data.get("customs_value_allocation_note")
    if note:
        parts.append(f"<h2>Таможенная стоимость</h2><p>{_esc(note)}</p>")

    dd = data.get("declaration_draft") or {}
    lines = dd.get("declaration_lines") if isinstance(dd, dict) else None
    if isinstance(lines, list) and lines:
        parts.append("<h2>Черновик декларации (строки)</h2>")
        parts.append(
            "<table><thead><tr>"
            "<th>№</th><th>Описание</th><th>ТН ВЭД</th><th>Гр.31</th>"
            "<th>Кол-во</th><th>Ед.</th><th>Брутто, кг</th>"
            "</tr></thead><tbody>"
        )
        for row in lines[:200]:
            if not isinstance(row, dict):
                continue
            desc = _truncate(_esc(row.get("commercial_description")), 240)
            g31 = _truncate(_esc(row.get("graf31_ru")), 200)
            parts.append(
                "<tr>"
                f"<td>{_esc(row.get('line'))}</td>"
                f"<td>{desc}</td>"
                f"<td>{_esc(row.get('hs_code'))}</td>"
                f"<td>{g31}</td>"
                f"<td>{_esc(row.get('quantity'))}</td>"
                f"<td>{_esc(row.get('unit'))}</td>"
                f"<td>{_esc(row.get('weight_gross_kg'))}</td>"
                "</tr>"
            )
        parts.append("</tbody></table>")
        if len(lines) > 200:
            parts.append(f"<p><em>Показаны первые 200 из {len(lines)} строк; полные данные — в JSON.</em></p>")

    pos = data.get("copilot_positions")
    if isinstance(pos, list) and pos:
        parts.append("<h2>Позиции (платежи / нетарифка)</h2>")
        parts.append(
            "<table><thead><tr><th>№</th><th>ТН ВЭД</th><th>Нетарифка</th><th>Платежи Σ, ₽</th></tr></thead><tbody>"
        )
        for i, row in enumerate(pos[:300], start=1):
            if not isinstance(row, dict):
                continue
            parts.append(
                "<tr>"
                f"<td>{i}</td>"
                f"<td>{_esc(row.get('effective_hs_code'))}</td>"
                f"<td>{_esc(row.get('non_tariff_status'))}</td>"
                f"<td>{_esc(row.get('total_payable'))}</td>"
                "</tr>"
            )
        parts.append("</tbody></table>")

    aa = data.get("ai_analyst") or {}
    if isinstance(aa, dict) and any(aa.get(k) for k in ("summary", "classification_advice", "note")):
        parts.append("<h2>ИИ-аналитик</h2>")
        if aa.get("note"):
            parts.append(f"<p><strong>Примечание:</strong> {_esc(aa.get('note'))}</p>")
        if aa.get("summary"):
            parts.append(f"<p>{_esc(aa.get('summary'))}</p>")
        if aa.get("classification_advice"):
            parts.append(f"<p><strong>Классификация:</strong> {_esc(aa.get('classification_advice'))}</p>")
        risks = aa.get("risks")
        if isinstance(risks, list) and risks:
            parts.append("<p><strong>Риски</strong></p><ul>")
            for r in risks[:40]:
                parts.append(f"<li>{_esc(r)}</li>")
            parts.append("</ul>")
        steps = aa.get("next_steps")
        if isinstance(steps, list) and steps:
            parts.append("<p><strong>Дальнейшие шаги</strong></p><ol>")
            for s in steps[:40]:
                parts.append(f"<li>{_esc(s)}</li>")
            parts.append("</ol>")

    ep = data.get("extracted_permits")
    if isinstance(ep, list) and ep:
        parts.append("<h2>Извлечённые номера разрешений</h2><ul>")
        for p in ep[:80]:
            if isinstance(p, dict):
                parts.append(f"<li>{_esc(p.get('type'))}: {_esc(p.get('number'))}</li>")
            else:
                parts.append(f"<li>{_esc(p)}</li>")
        parts.append("</ul>")

    prc = data.get("permits_registry_check")
    if isinstance(prc, list) and prc:
        parts.append("<h2>Проверка реестров (кратко)</h2><ul>")
        for p in prc[:40]:
            if not isinstance(p, dict):
                continue
            parts.append(
                "<li>"
                f"{_esc(p.get('type'))} / {_esc(p.get('number'))} — {_esc(p.get('status'))}"
                f"{(' — ' + _esc(p.get('error'))) if p.get('error') else ''}"
                "</li>"
            )
        parts.append("</ul>")

    summ = data.get("summary")
    if isinstance(summ, dict) and summ:
        parts.append("<h2>Сводка проверки</h2><pre>")
        parts.append(_esc(json.dumps(summ, ensure_ascii=False, indent=2)[:8000]))
        parts.append("</pre>")

    return "\n".join(parts)


_USER_CSS = """
body { font-family: sans-serif; font-size: 10pt; line-height: 1.35; color: #111; }
h1 { font-size: 14pt; margin-bottom: 0.4em; }
h2 { font-size: 11pt; margin-top: 1em; margin-bottom: 0.35em; border-bottom: 1px solid #ccc; }
table { border-collapse: collapse; width: 100%; margin: 0.5em 0; font-size: 9pt; }
th, td { border: 1px solid #bbb; padding: 3px 5px; vertical-align: top; }
th { background: #f0f0f0; }
pre { white-space: pre-wrap; font-size: 8pt; background: #f8f8f8; padding: 8px; }
ul, ol { margin: 0.3em 0 0.6em 1.2em; }
"""


def build_ved_report_pdf(data: Dict[str, Any]) -> bytes:
    """Собирает PDF (A4) из словаря в формате JSON-экспорта вкладки «Документы»."""
    html_body = build_ved_report_html(data)
    mediabox = fitz.paper_rect("a4")
    where = mediabox + (36, 36, -36, -36)
    story = fitz.Story(html_body, user_css=_USER_CSS, em=11)

    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        writer = fitz.DocumentWriter(path)
        more = 1
        while more:
            dev = writer.begin_page(mediabox)
            more, _filled = story.place(where)
            story.draw(dev, None)
            writer.end_page()
        writer.close()
        with open(path, "rb") as f:
            return f.read()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
