#!/usr/bin/env python3
"""
Сбор ПКР (предварительных решений) с портала Alta.ru — обход глав ТН ВЭД 01–97.

Используются прямые GET-запросы (без заполнения форм на странице). Отбор «шумовых»
совпадений — локально через Gemini (колонка ``target_entity`` в БД).

Пример установки и запуска на **macOS** (из каталога ``customs-clear/backend``)::

  pip3 install playwright
  playwright install chromium
  python3 scripts/sync_tks_predecisions.py --dry-run --chapters 01,02
  python3 scripts/sync_tks_predecisions.py --test-chapter 64 --headful

При заглушке WAF/Cloudflare скрипт ждёт 60 с и повторно проверяет страницу (удобно в **headful**).

Источник: https://www.alta.ru/clasres/?srch_str=NN (публичный реестр; при необходимости — поиск через форму на ``/clasres/``).
Сохранение: normative_store.upsert_classification_decision (уникальность decision_number).

(Ранее скрипт обращался к TKS.ru; логика переведена на Alta.ru из-за нестабильного поиска TKS.)
"""

from __future__ import annotations

import argparse
import html as html_module
import json
import os
import random
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.parse import urlparse

PLAYWRIGHT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
ALTA_DEBUG_DUMP_NAME = "alta_clasres_debug_dump.html"
ALTA_CLASRES_BASE = "https://www.alta.ru/clasres/"

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
ALTA_SESSION_DIR = _ROOT / "data" / "alta_session"
DEFAULT_STORAGE_STATE_PATH = ALTA_SESSION_DIR / "storage_state.json"
DEFAULT_SESSION_STORAGE_PATH = ALTA_SESSION_DIR / "session_storage.json"

from dotenv import load_dotenv

load_dotenv(_ROOT / ".env")
load_dotenv()

from app.db import SessionLocal
from app.models.core import TnvedEntry
from app.models.tnved import Commodity

_RE_NOTHING_FOUND = re.compile(
    r"ничего\s+не\s+найдено|не\s+найдено\s+по\s+запросу|классификационных\s+решений\s+не\s+найдено|\bне\s+найдено\b|результатов\s*:\s*0",
    re.I | re.UNICODE,
)
# В дампе curl/Playwright часто приходит заглушка без таблицы ПКР (не путать с «нет результатов»).
_RE_ACCESS_DENIED = re.compile(r"доступ\s+запрещ", re.I | re.UNICODE)

# Таблица результатов (ожидание после ручного прохождения WAF).
ALTA_RESULT_TABLE_SELECTOR = (
    "table.table, .table-responsive table, .search-results table, "
    "table.table-striped, table.table-bordered, table.pkr-table, "
    "#content table, main .table-responsive table, main table, article table, table"
)


def _load_session_storage(path: Path) -> dict[str, str]:
    try:
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                out: dict[str, str] = {}
                for k, v in raw.items():
                    ks = str(k or "").strip()
                    if not ks:
                        continue
                    out[ks] = str(v or "")
                return out
    except Exception as e:
        print(f"[session] warning: не удалось прочитать sessionStorage ({path}): {e}", file=sys.stderr)
    return {}


def _attach_session_storage_init_script(context: Any, session_map: dict[str, str]) -> None:
    if not session_map:
        return
    payload = json.dumps(session_map, ensure_ascii=False)
    js = (
        "() => {\n"
        "  try {\n"
        "    if (!location || !String(location.hostname || '').endsWith('alta.ru')) return;\n"
        f"    const data = {payload};\n"
        "    for (const [k, v] of Object.entries(data)) {\n"
        "      try { sessionStorage.setItem(String(k), String(v ?? '')); } catch (_) {}\n"
        "    }\n"
        "  } catch (_) {}\n"
        "}"
    )
    try:
        context.add_init_script(js)
    except Exception as e:
        print(f"[session] warning: не удалось подключить init_script sessionStorage: {e}", file=sys.stderr)


def _save_session_storage(page: Any, path: Path) -> None:
    try:
        if page is None:
            return
        data = page.evaluate(
            """() => {
              const out = {};
              try {
                if (!location || !String(location.hostname || '').endsWith('alta.ru')) return out;
                for (let i = 0; i < sessionStorage.length; i++) {
                  const key = sessionStorage.key(i);
                  if (!key) continue;
                  out[key] = sessionStorage.getItem(key) || "";
                }
              } catch (_) {}
              return out;
            }"""
        )
        if not isinstance(data, dict):
            data = {}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[session] warning: не удалось сохранить sessionStorage ({path}): {e}", file=sys.stderr)


def _persist_browser_state(context: Any, page: Any, storage_state_path: Path, session_storage_path: Path) -> None:
    try:
        storage_state_path.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(storage_state_path))
    except Exception as e:
        print(f"[session] warning: не удалось сохранить storage_state ({storage_state_path}): {e}", file=sys.stderr)
    _save_session_storage(page, session_storage_path)


def _alta_clasres_url(search_term: str, page_num: int = 1) -> str:
    """Прямой GET-поиск на публичной странице /clasres/."""
    query = re.sub(r"\D", "", str(search_term or "")).strip()
    q = quote(query, safe="")
    if page_num <= 1:
        return f"{ALTA_CLASRES_BASE}?tnfiltr={q}&srchstr="
    return f"{ALTA_CLASRES_BASE}?tnfiltr={q}&srchstr=&page={int(page_num)}"


def _clean_field(s: str) -> str:
    """Убирает лишние пробелы, переводы строк и HTML-сущности."""
    t = html_module.unescape(s or "")
    t = t.replace("\xa0", " ")
    t = re.sub(r"[\r\n\t]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _body_text(page: Any) -> str:
    try:
        return str(page.locator("body").inner_text(timeout=20000) or "")
    except Exception:
        return ""


def _page_html_lower(page: Any) -> str:
    try:
        return (page.content() or "").lower()
    except Exception:
        return ""


def _looks_like_captcha(page: Any) -> bool:
    h = _page_html_lower(page)
    if "подтвердите, что вы не робот" in h:
        return True
    if "prove you are human" in h or "i am not a robot" in h:
        return True
    return False


def _looks_like_waf_or_cf_challenge(page: Any) -> bool:
    """Cloudflare / межстраничная проверка (часто без текста «Доступ запрещен» в body)."""
    h = _page_html_lower(page)
    if "cf-browser-verification" in h or "challenge-platform" in h:
        return True
    if "cloudflare" in h and ("just a moment" in h or "checking your browser" in h):
        return True
    return False


def _wait_for_manual_interaction(page: Any, wait_sec: int) -> None:
    sec = max(10, int(wait_sec))
    print(
        "\n[MANUAL] При необходимости введите запрос в поле поиска на странице Alta вручную "
        "(и/или пройдите проверку), затем дождитесь обновления списка.\n"
        f"[MANUAL] Ожидание {sec} с...\n",
        flush=True,
    )
    try:
        page.wait_for_timeout(sec * 1000)
    except Exception:
        pass


def _pause_for_manual_waf_then_recover(page: Any, debug_dump_path: Path) -> bool:
    """
    Ждёт 60 с для ручного прохождения капчи/WAF в окне браузера, затем дополнительно ждёт таблицу.
    Возвращает True, если заглушка «Доступ запрещен» исчезла и можно продолжать разбор.
    """
    print(
        "\n[!!!] ВНИМАНИЕ: Сработала защита Alta.ru. Пожалуйста, пройдите проверку (капчу) "
        "в открытом окне браузера. Скрипт ждет 60 секунд...\n",
        flush=True,
    )
    try:
        page.wait_for_timeout(60000)
    except Exception:
        pass

    try:
        page.wait_for_selector(ALTA_RESULT_TABLE_SELECTOR, state="visible", timeout=120_000)
    except Exception:
        pass

    body = _body_text(page)
    if _RE_ACCESS_DENIED.search(body):
        print(
            "  После ожидания защита Alta.ru всё ещё активна (нет доступа к контенту). "
            f"См. дамп {debug_dump_path.name}",
            file=sys.stderr,
        )
        _save_debug_html(page, debug_dump_path)
        return False

    if _looks_like_waf_or_cf_challenge(page) and not _extract_alta_pkr_rows(page):
        try:
            page.wait_for_timeout(30000)
        except Exception:
            pass
        body2 = _body_text(page)
        if _RE_ACCESS_DENIED.search(body2):
            _save_debug_html(page, debug_dump_path)
            return False

    return True


def _wait_manual_captcha_interaction(page: Any) -> None:
    print(
        "Обнаружена капча или блокирующая проверка. Ожидание 20 с для ручного прохождения "
        "(запустите с --headful при необходимости).",
        flush=True,
    )
    try:
        page.wait_for_timeout(20000)
    except Exception:
        pass


def _save_debug_html(page: Any, dump_path: Path) -> None:
    try:
        dump_path.write_text(page.content(), encoding="utf-8")
    except Exception as e:
        print(f"  [debug] не удалось сохранить дамп: {e}", file=sys.stderr)


def _extract_alta_pkr_rows(page: Any) -> list[dict[str, str]]:
    """
    Парсинг таблицы результатов ПКР на Alta.ru (классический ``<table>`` или сетка ``div``).

    В актуальном дампе при блокировке IP приходит только заглушка «Доступ запрещен» — без ``<table>``.
    При нормальном ответе ищем таблицу по типичным классам/контейнерам и строки с кодом 10 цифр.
    """
    js = r"""
    () => {
      function clean(t) {
        return (t || '').replace(/\xa0/g, ' ').replace(/\s+/g, ' ').trim();
      }
      function rowCells(tr) {
        return Array.from(tr.querySelectorAll('th,td')).map(n => clean(n.innerText));
      }
      const order = [
        'table.table',
        '.table-responsive table',
        '.search-results table',
        'table.table-striped',
        'table.table-bordered',
        'table.pkr-table',
        '#content table',
        '.content table',
        'main .table-responsive table',
        'main table',
        'div.site-content table',
        'article table',
        'table[class*="pkr"]',
        'table'
      ];
      let table = null;
      for (const sel of order) {
        const el = document.querySelector(sel);
        if (!el) continue;
        const ntr = el.querySelectorAll('tr').length;
        if (ntr >= 2) {
          table = el;
          break;
        }
      }
      if (!table) {
        const grids = document.querySelectorAll(
          '[class*="search-result"] [class*="row"], .pkr-results .row, .table-like > div, [role="row"]'
        );
        const outDiv = [];
        for (const row of grids) {
          const txt = clean(row.innerText || '');
          const m = txt.match(/(\d{10})/);
          if (!m) continue;
          const parts = txt.split(/\s{2,}|\t/).filter(Boolean);
          const dm = txt.match(/[№N]\s*[\d\-\/\w]+/);
          const dpart = (dm ? dm[0] : ('ALTA-' + m[1]));
          const idt = txt.match(/\d{2}[.\/]\d{2}[.\/]\d{2,4}/);
          outDiv.push({
            hs_code: m[1],
            product_name: parts[1] || '',
            description: parts.slice(2).join(' ').slice(0, 2000),
            decision_number: dpart.slice(0, 128),
            issue_date: (idt ? idt[0] : '').slice(0, 32),
          });
        }
        if (outDiv.length) return outDiv;

        // Актуальная вёрстка Alta: карточки в .pClasres_result .boxSubstrate
        const cards = document.querySelectorAll(
          '.pClasres_result .boxSubstrate, .pClasres_result .boxSubstrate-offset-0'
        );
        const outCards = [];
        function mkStableId(code, text, idx) {
          const src = String(code || '') + '|' + String(text || '').slice(0, 4000);
          let h = 0;
          for (let i = 0; i < src.length; i++) {
            h = ((h << 5) - h) + src.charCodeAt(i);
            h |= 0;
          }
          const n = Math.abs(h).toString(36);
          return ('ALTA-' + String(code || '0000') + '-' + n + '-' + String(idx + 1)).slice(0, 128);
        }
        for (let i = 0; i < cards.length; i++) {
          const card = cards[i];
          const heading = card.querySelector('a.h4, a[name], a[href*="tnved="], a[href*="/tnved/code/"]');
          const headingText = clean((heading && heading.innerText) || '');
          const descNode = card.querySelector('.result_search');
          const description = clean((descNode && descNode.innerText) || '');
          const codeFromHeading = String(headingText || '').replace(/\D/g, '').slice(0, 10);
          let hsCode = codeFromHeading;
          if (!hsCode || hsCode.length < 4) {
            const inDesc = description.match(/\b(\d{4,10})\b/);
            hsCode = inDesc ? String(inDesc[1]).slice(0, 10) : '';
          }
          if (!hsCode || hsCode.length < 4) continue;
          let decisionRaw = '';
          const dm = description.match(/(?:№|N)\s*[\dA-Za-zА-Яа-я\-\/]{4,}/);
          if (dm) {
            decisionRaw = clean(dm[0]).slice(0, 128);
          } else {
            decisionRaw = mkStableId(hsCode, description, i);
          }
          const dateMatch = description.match(/\b\d{2}[.\/]\d{2}[.\/]\d{2,4}\b/);
          const issueDate = dateMatch ? clean(dateMatch[0]).slice(0, 32) : '';
          let productName = '';
          if (description) {
            productName = clean(description.split(/[.;]\s*/)[0] || '').slice(0, 512);
          }
          outCards.push({
            hs_code: hsCode,
            product_name: productName,
            description: description.slice(0, 12000),
            decision_number: decisionRaw,
            issue_date: issueDate,
          });
        }
        if (outCards.length) return outCards;
        return [];
      }

      const trs = Array.from(table.querySelectorAll('tbody tr, tr'));
      if (trs.length < 1) return [];

      let headerIdx = 0;
      for (let i = 0; i < Math.min(4, trs.length); i++) {
        if (trs[i].querySelector('th')) {
          headerIdx = i;
          break;
        }
        const cells = rowCells(trs[i]);
        const j = cells.join(' ').toLowerCase();
        if ((j.includes('код') && (j.includes('тн') || j.includes('вэд') || j.includes('тнвэд'))) ||
            (j.includes('наимен') || j.includes('описание'))) {
          headerIdx = i;
          break;
        }
      }

      const headCells = rowCells(trs[headerIdx]);
      const lowHead = headCells.map(h => h.toLowerCase());
      const idx = {
        code: lowHead.findIndex(h =>
          (h.includes('код') && (h.includes('тн') || h.includes('вэд') || h.includes('тнвэд'))) ||
          /^код\s*$/i.test(h)
        ),
        name: lowHead.findIndex(h => h.includes('наимен') && !h.includes('кратк')),
        desc: lowHead.findIndex(h =>
          h.includes('описание') || (h.includes('товар') && h.includes('опис'))
        ),
        basis: lowHead.findIndex(h =>
          h.includes('обоснован') || (h.includes('сведен') && h.includes('документ'))
        ),
        doc: lowHead.findIndex(h =>
          h.includes('номер') || h.includes('пкр') || h.includes('реш') ||
          (h.includes('документ') && !h.includes('сведен'))
        ),
        date: lowHead.findIndex(h => h.includes('дата')),
      };

      const out = [];
      for (let i = headerIdx + 1; i < trs.length; i++) {
        const cells = rowCells(trs[i]);
        if (cells.length < 1) continue;
        if (!cells.some(c => /\d/.test(c))) continue;

        const codeRaw = idx.code >= 0 ? cells[idx.code] : cells[0];
        const digits = String(codeRaw || '').replace(/\D/g, '').slice(0, 10);
        if (digits.length < 4) continue;

        let product_name = idx.name >= 0 ? (cells[idx.name] || '') : '';
        let description = idx.desc >= 0 ? (cells[idx.desc] || '') : '';
        if (!product_name && idx.desc < 0 && cells.length > 1) {
          product_name = cells[1] || '';
        }
        if (!description && idx.name >= 0 && idx.desc >= 0) {
          description = cells[idx.desc] || '';
        }

        let basis = idx.basis >= 0 ? (cells[idx.basis] || '') : '';
        let docCell = idx.doc >= 0 ? (cells[idx.doc] || '') : '';
        if (!docCell && basis) {
          const m = String(basis).match(/(\d{6,}[\/\-]?\d*|[№N]\s*[\d\-\/]+)/);
          if (m) docCell = m[0];
        }
        let decision_raw = docCell || basis || '';
        if (!/\d/.test(String(decision_raw))) {
          const joined = cells.join(' ');
          const m2 = joined.match(/(\d{4,}[\/\-]\d{2,}|[№N]\s*[\d\w\-\/]{4,})/);
          if (m2) decision_raw = m2[0];
        }
        if (!decision_raw) decision_raw = 'ALTA-' + digits + '-' + String(i);

        const issue_date = idx.date >= 0 ? (cells[idx.date] || '') : '';

        out.push({
          hs_code: digits,
          product_name: clean(product_name),
          description: clean([description, basis].filter(Boolean).join(' | ')),
          decision_number: clean(decision_raw).slice(0, 128),
          issue_date: clean(issue_date).slice(0, 32),
        });
      }
      return out;
    }
    """
    try:
        data = page.evaluate(js)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    rows: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        hs = re.sub(r"\D", "", str(item.get("hs_code") or ""))[:10]
        if len(hs) < 4:
            continue
        dn = _clean_field(str(item.get("decision_number") or ""))
        if not dn:
            continue
        rows.append(
            {
                "hs_code": hs,
                "product_name": _clean_field(str(item.get("product_name") or "")),
                "description": _clean_field(str(item.get("description") or "")),
                "decision_number": dn[:128],
                "issue_date": _clean_field(str(item.get("issue_date") or ""))[:32],
            }
        )
    return rows


def _entity_fallback(product_name: str, description: str) -> str:
    base = (product_name or "").strip() or (description or "").strip()
    base = re.sub(r"\s+", " ", base)
    return base[:512]


def _extract_core_entity(description: str, product_name: str = "", *, skip_ai: bool) -> str:
    if skip_ai:
        return _entity_fallback(product_name, description)
    text_block = (description or "").strip()
    if product_name:
        text_block = f"Наименование: {product_name.strip()}\n{text_block}".strip()
    if not text_block:
        return ""
    prompt = (
        "Проанализируй текст таможенного решения. Твоя задача — извлечь только ГЛАВНЫЙ объект "
        "классификации (1-3 слова, например 'Шуруп стальной', 'Насос центробежный'). Игнорируй "
        "детали упаковки, составные части или назначение, если они не являются самим товаром.\n\n"
        f"Текст:\n{text_block[:12000]}\n\n"
        "Ответ: одна строка — только объект (1-3 слова), без кавычек, без пояснений."
    )
    try:
        from app.services.invoice_analyzer import _gemini_generate

        raw = _gemini_generate(prompt, max_output_tokens=256, temperature=0.05)
    except Exception:
        return _entity_fallback(product_name, description)
    line = (raw or "").strip().splitlines()[0] if raw else ""
    line = line.strip().strip("\"'«»")
    line = re.sub(r"\s+", " ", line)
    return (line or _entity_fallback(product_name, description))[:512]


def _chapter_position_terms(ch: str) -> list[str]:
    """
    Возвращает список 4-значных товарных позиций для главы (минимум 4 цифры для Alta).
    Берём из локальной БД; если БД пуста — используем безопасный fallback XX00..XX99.
    """
    ch2 = re.sub(r"\D", "", str(ch or "")).zfill(2)[:2]
    terms: set[str] = set()
    try:
        with SessionLocal() as db:
            for hs_code, chapter in db.query(TnvedEntry.hs_code, TnvedEntry.chapter).all():
                code = re.sub(r"\D", "", str(hs_code or ""))[:10]
                if len(code) < 4:
                    continue
                ch_db = re.sub(r"\D", "", str(chapter or "")).zfill(2)[:2]
                if ch_db == ch2 or code.startswith(ch2):
                    terms.add(code[:4])
            if not terms:
                for (code_raw,) in db.query(Commodity.code).all():
                    code = re.sub(r"\D", "", str(code_raw or ""))[:10]
                    if len(code) >= 4 and code.startswith(ch2):
                        terms.add(code[:4])
    except Exception as e:
        print(f"  [{ch2}] warning: не удалось получить 4-значные позиции из БД: {e}", file=sys.stderr)
    out = sorted(t for t in terms if len(t) == 4 and t.startswith(ch2))
    fallback = [f"{ch2}{i:02d}" for i in range(100)]
    if not out:
        return fallback
    seen = set(out)
    out.extend([x for x in fallback if x not in seen])
    return out


def _try_clasres_form_search(page: Any, search_term: str) -> bool:
    """
    Если прямой GET ``?srch_str=`` не привёл к распознаваемой таблице — открыть ``/clasres/``
    и отправить поиск через форму на странице (вводим минимум 4-значную позицию).
    """
    q = re.sub(r"\D", "", str(search_term or "")).strip()
    if len(q) < 4:
        return False
    base = ALTA_CLASRES_BASE.rstrip("/") + "/"
    try:
        page.goto(base, wait_until="domcontentloaded", timeout=90000)
    except Exception:
        return False
    try:
        page.wait_for_timeout(1500)
    except Exception:
        pass
    form_selectors = (
        'form[action="/clasres/"]',
        'main form[action*="clasres"]',
        '.pClasres_body form[action*="clasres"]',
    )
    for form_sel in form_selectors:
        try:
            form = page.locator(form_sel).first
            if not form.count() or not form.is_visible():
                continue
            code_input = form.locator('input[name="tnfiltr"], input#tnfiltr').first
            if not code_input.count() or not code_input.is_visible():
                continue
            code_input.fill(q, timeout=10000)
            # Не допускаем попадания 4-значного кода в поле "Наименование товара".
            name_input = form.locator('input[name="srchstr"], input[name="srch_str"]').first
            if name_input.count():
                try:
                    name_input.fill("", timeout=3000)
                except Exception:
                    pass
            for sub in (
                'button[type="submit"]',
                'input[type="submit"]',
                'button:has-text("Искать")',
                'input[value*="Искать"]',
            ):
                try:
                    btn = form.locator(sub).first
                    if btn.count() and btn.is_visible():
                        btn.click(timeout=15000)
                        try:
                            page.wait_for_load_state("domcontentloaded", timeout=90000)
                        except Exception:
                            pass
                        return True
                except Exception:
                    continue
            try:
                code_input.press("Enter")
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=90000)
                except Exception:
                    pass
                return True
            except Exception:
                return False
        except Exception:
            continue
    return False


def _click_alta_next_page(page: Any) -> bool:
    """Следующая страница через UI (если GET page=N не используется)."""
    selectors = (
        'ul.pagination li.next a:not([aria-disabled="true"])',
        'ul.pagination li.next:not(.disabled) a',
        "ul.pagination a:has-text('Вперёд')",
        "ul.pagination a:has-text('Вперед')",
        'a[rel="next"]',
        "a.next-page",
        'a.page-link:has-text("Вперёд")',
        'a.page-link:has-text("Вперед")',
        'a:has-text("Следующая")',
        'a:has-text("следующая")',
        ".pager a:has-text('>')",
    )
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible():
                loc.click(timeout=15000)
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=60000)
                except Exception:
                    pass
                time.sleep(0.5)
                return True
        except Exception:
            continue
    return False


def _parse_loaded_alta_page(
    page: Any,
    ch: str,
    pidx: int,
    debug_dump_path: Path,
    manual_auth_wait_sec: int = 0,
) -> tuple[list[dict[str, str]], str]:
    """
    Обработка уже загруженной страницы. Статусы:
    ``ok`` | ``empty_chapter`` | ``stop`` | ``blocked`` (антидот / заглушка без ПКР).
    """
    page.wait_for_timeout(random.randint(2000, 4000))

    if _looks_like_captcha(page):
        _wait_manual_captcha_interaction(page)

    try:
        body = _body_text(page)
    except Exception as e:
        print(f"Обнаружена капча или сбой чтения страницы: {e}", file=sys.stderr)
        _wait_manual_captcha_interaction(page)
        return [], "stop"

    if _RE_ACCESS_DENIED.search(body) or _looks_like_waf_or_cf_challenge(page):
        recovered = _pause_for_manual_waf_then_recover(page, debug_dump_path)
        if not recovered:
            return [], "blocked"
        try:
            body = _body_text(page)
        except Exception:
            return [], "blocked"

    if _RE_ACCESS_DENIED.search(body):
        print(
            "  Alta.ru по-прежнему возвращает «Доступ запрещен» после паузы. "
            f"Дамп: {debug_dump_path.name}",
            file=sys.stderr,
        )
        _save_debug_html(page, debug_dump_path)
        return [], "blocked"

    if _RE_NOTHING_FOUND.search(body):
        if pidx == 0:
            print(f"  [{ch}] по запросу на Alta.ru записей не найдено (штатно).", flush=True)
            return [], "empty_chapter"
        return [], "stop"

    rows = _extract_alta_pkr_rows(page)

    if not rows:
        if pidx == 0:
            print(
                f"  [{ch}] таблица ПКР не распознана (возможна смена вёрстки или всё ещё заглушка); "
                f"см. {debug_dump_path.name}",
                file=sys.stderr,
            )
            _save_debug_html(page, debug_dump_path)
        return [], "stop"
    return rows, "ok"


def scrape_chapter(
    page: Any,
    chapter: str,
    *,
    dry_run: bool,
    max_pages: int,
    upsert_fn: Any,
    upsert_prelim_fn: Any,
    skip_entity_ai: bool,
    debug_dump_path: Path,
    use_url_pagination: bool = True,
    manual_auth_wait_sec: int = 0,
    position_terms: list[str] | None = None,
) -> int:
    ch = re.sub(r"\D", "", (chapter or "").strip()).zfill(2)[:2]
    aggregated: list[dict[str, str]] = []
    search_terms = list(position_terms or _chapter_position_terms(ch))
    print(f"  [{ch}] поиск по {len(search_terms)} товарным позициям (минимум 4 цифры)", flush=True)
    page_cap = int(max_pages) if int(max_pages) > 0 else 1_000_000
    for term_idx, term in enumerate(search_terms):
        form_fallback_done = False
        manual_retry_done = False
        for pidx in range(page_cap):
            if use_url_pagination:
                url = _alta_clasres_url(term, pidx + 1)
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=90000)
                except Exception as e:
                    print(f"  [{ch}/{term}] ошибка загрузки {url}: {e}", file=sys.stderr)
                    _wait_manual_captcha_interaction(page)
                    break
            else:
                if pidx == 0:
                    url = _alta_clasres_url(term, 1)
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=90000)
                    except Exception as e:
                        print(f"  [{ch}/{term}] ошибка загрузки {url}: {e}", file=sys.stderr)
                        _wait_manual_captcha_interaction(page)
                        break
                else:
                    if not _click_alta_next_page(page):
                        break

            rows, status = _parse_loaded_alta_page(
                page,
                ch,
                pidx,
                debug_dump_path,
                manual_auth_wait_sec=manual_auth_wait_sec,
            )
            if (
                pidx == 0
                and status == "stop"
                and not rows
                and not form_fallback_done
                and _try_clasres_form_search(page, term)
            ):
                form_fallback_done = True
                print(f"  [{ch}/{term}] повторный разбор после поиска через форму на /clasres/", flush=True)
                rows, status = _parse_loaded_alta_page(
                    page,
                    ch,
                    pidx,
                    debug_dump_path,
                    manual_auth_wait_sec=manual_auth_wait_sec,
                )
            if (
                pidx == 0
                and status == "stop"
                and not rows
                and not manual_retry_done
                and manual_auth_wait_sec > 0
                and term_idx == 0
            ):
                manual_retry_done = True
                _wait_for_manual_interaction(page, manual_auth_wait_sec)
                if _try_clasres_form_search(page, term):
                    print(f"  [{ch}/{term}] повторный разбор после ручного взаимодействия с формой", flush=True)
                rows, status = _parse_loaded_alta_page(
                    page,
                    ch,
                    pidx,
                    debug_dump_path,
                    manual_auth_wait_sec=manual_auth_wait_sec,
                )
            if status == "empty_chapter":
                break
            if status == "blocked":
                if not aggregated:
                    return 0
                break
            if status == "stop":
                break
            aggregated.extend(rows)

    by_decision: dict[str, dict[str, str]] = {}
    for row in aggregated:
        dn = _clean_field(str(row.get("decision_number") or ""))
        if dn and dn not in by_decision:
            by_decision[dn] = dict(row)

    rows_out: list[dict[str, str]] = []
    for row in by_decision.values():
        row = dict(row)
        row["target_entity"] = _extract_core_entity(
            row.get("description") or "",
            row.get("product_name") or "",
            skip_ai=skip_entity_ai,
        )
        rows_out.append(row)
        if not dry_run and upsert_fn is not None:
            upsert_fn(row)
        if not dry_run and upsert_prelim_fn is not None:
            pre_desc = (
                f"ПКР/предварительное решение ФТС: № {row.get('decision_number') or '—'}; "
                f"дата: {row.get('issue_date') or '—'}; "
                f"товар: {row.get('product_name') or ''}; "
                f"описание: {row.get('description') or ''}"
            ).strip()[:12000]
            upsert_prelim_fn(
                {
                    "hs_code": row.get("hs_code") or "",
                    "description": pre_desc,
                },
                source="fts_alta",
            )

    if dry_run and rows_out:
        print(f"\n[--dry-run] Глава {ch}: распознано записей {len(rows_out)} (upsert в БД не выполняется)", flush=True)
        for i, r in enumerate(rows_out[:200]):
            desc = _clean_field(str(r.get("description") or ""))[:120]
            print(
                f"  {i + 1}. hs_code={r.get('hs_code')}  decision_number={r.get('decision_number')!r}\n"
                f"      product_name={_clean_field(str(r.get('product_name') or ''))[:100]!r}\n"
                f"      description={desc!r}\n"
                f"      issue_date={r.get('issue_date')!r}  target_entity={r.get('target_entity')!r}",
                flush=True,
            )
        if len(rows_out) > 200:
            print(f"  ... и ещё {len(rows_out) - 200} записей (вывод ограничен 200 строками)", flush=True)

    return len(rows_out)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Синхронизация ПКР с Alta.ru → classification_decisions + preliminary_decisions",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Парсинг и вывод записей в консоль без upsert в classification_decisions",
    )
    parser.add_argument(
        "--chapters",
        type=str,
        default="",
        help="Список глав через запятую (напр. 01,39,84). Пусто — цикл 01..97",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=0,
        help="Макс. страниц пагинации на одну главу (GET ?page=N); 0 = до исчерпания (без тестового лимита)",
    )
    parser.add_argument("--headful", action="store_true", help="Показать окно браузера")
    parser.add_argument(
        "--skip-entity-ai",
        action="store_true",
        help="Не вызывать Gemini для target_entity (копия наименования/описания)",
    )
    parser.add_argument(
        "--entity-ai-on-dry-run",
        action="store_true",
        help="В режиме --dry-run всё равно вызывать Gemini (запись в БД не выполняется)",
    )
    parser.add_argument(
        "--test-chapter",
        type=str,
        default=None,
        metavar="NN",
        help="Отладка: одна глава ТН ВЭД (например 64)",
    )
    parser.add_argument(
        "--ui-pagination",
        action="store_true",
        help="Пагинация кликом «Вперёд» вместо GET ?page=N",
    )
    parser.add_argument(
        "--proxy",
        type=str,
        default="",
        help="Опциональный прокси для Playwright (например, http://user:pass@host:port)",
    )
    parser.add_argument(
        "--storage-state",
        type=Path,
        default=DEFAULT_STORAGE_STATE_PATH,
        help=f"Путь для storage_state Playwright (cookies/localStorage), по умолчанию {DEFAULT_STORAGE_STATE_PATH}",
    )
    parser.add_argument(
        "--session-storage",
        type=Path,
        default=DEFAULT_SESSION_STORAGE_PATH,
        help=f"Путь для snapshot sessionStorage Alta, по умолчанию {DEFAULT_SESSION_STORAGE_PATH}",
    )
    parser.add_argument(
        "--manual-auth-wait-sec",
        type=int,
        default=0,
        help="Сколько секунд ждать ручного взаимодействия в окне Alta (0 = полностью автоматический режим)",
    )
    parser.add_argument(
        "--terms",
        type=str,
        default="",
        help="Опционально: список 4-значных позиций через запятую (например 8509,8517); если задано, используется вместо авто-подбора",
    )
    parser.add_argument(
        "--stop-after-empty-chapters",
        type=int,
        default=8,
        help="Остановиться после N подряд глав без данных (0 = не останавливать)",
    )
    args = parser.parse_args()

    if args.test_chapter is not None and str(args.test_chapter).strip():
        tc = re.sub(r"\D", "", str(args.test_chapter).strip())[:2]
        if not tc:
            print("Ошибка: --test-chapter укажите как двузначное число, например 64", file=sys.stderr)
            raise SystemExit(2)
        chapters = [tc.zfill(2)]
    elif args.chapters.strip():
        chapters = [c.strip().zfill(2) for c in args.chapters.split(",") if c.strip()]
    else:
        chapters = [f"{i:02d}" for i in range(1, 98)]

    explicit_terms: list[str] | None = None
    if args.terms.strip():
        explicit_terms = []
        for term in args.terms.split(","):
            digits = re.sub(r"\D", "", str(term or ""))[:10]
            if len(digits) >= 4:
                explicit_terms.append(digits[:4])
        explicit_terms = sorted(set(explicit_terms)) or None

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Установите: pip3 install playwright && playwright install chromium", file=sys.stderr)
        raise SystemExit(2)

    from app.services.normative_store import init_db, upsert_classification_decision, upsert_preliminary_decision

    init_db()
    upsert_fn = None if args.dry_run else upsert_classification_decision
    upsert_prelim_fn = None if args.dry_run else upsert_preliminary_decision

    grand = 0
    empty_streak = 0
    debug_dump_path = Path(_ROOT) / ALTA_DEBUG_DUMP_NAME
    use_url = not bool(args.ui_pagination)
    storage_state_path = Path(args.storage_state).expanduser().resolve()
    session_storage_path = Path(args.session_storage).expanduser().resolve()
    session_storage_path.parent.mkdir(parents=True, exist_ok=True)
    storage_state_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        proxy_cfg = None
        proxy_raw = (args.proxy or "").strip()
        if proxy_raw:
            up = urlparse(proxy_raw)
            if up.scheme and up.hostname and up.port:
                proxy_cfg = {"server": f"{up.scheme}://{up.hostname}:{up.port}"}
                if up.username:
                    proxy_cfg["username"] = up.username
                if up.password:
                    proxy_cfg["password"] = up.password
            else:
                proxy_cfg = {"server": proxy_raw}
        browser = p.chromium.launch(headless=not args.headful, proxy=proxy_cfg)
        context = None
        page = None
        try:
            storage_state_arg = str(storage_state_path) if storage_state_path.is_file() else None
            context = browser.new_context(
                user_agent=PLAYWRIGHT_USER_AGENT,
                locale="ru-RU",
                storage_state=storage_state_arg,
                extra_http_headers={
                    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Referer": "https://www.alta.ru/",
                },
            )
            if storage_state_arg:
                print(f"[session] loaded cookies/localStorage from {storage_state_path}", flush=True)
            sdata = _load_session_storage(session_storage_path)
            if sdata:
                _attach_session_storage_init_script(context, sdata)
                print(f"[session] loaded sessionStorage keys={len(sdata)} from {session_storage_path}", flush=True)
            page = context.new_page()
            for ch in chapters:
                skip_gemini = bool(args.skip_entity_ai) or (
                    bool(args.dry_run) and not bool(args.entity_ai_on_dry_run)
                )
                n = scrape_chapter(
                    page,
                    ch,
                    dry_run=args.dry_run,
                    max_pages=int(args.max_pages),
                    upsert_fn=upsert_fn,
                    upsert_prelim_fn=upsert_prelim_fn,
                    skip_entity_ai=skip_gemini,
                    debug_dump_path=debug_dump_path,
                    use_url_pagination=use_url,
                    manual_auth_wait_sec=max(0, int(args.manual_auth_wait_sec)),
                    position_terms=explicit_terms,
                )
                grand += n
                if n <= 0:
                    empty_streak += 1
                else:
                    empty_streak = 0
                print(f"Глава {ch}: строк {n} ({'dry-run' if args.dry_run else 'upsert'})", flush=True)
                stop_after = max(0, int(args.stop_after_empty_chapters))
                if stop_after and empty_streak >= stop_after:
                    print(
                        f"Остановка: {empty_streak} подряд глав без данных "
                        f"(возможна блокировка источника или капча).",
                        flush=True,
                    )
                    break
        finally:
            if context is not None:
                _persist_browser_state(context, page, storage_state_path, session_storage_path)
                print(
                    f"[session] saved cookies/local/session state: {storage_state_path} ; {session_storage_path}",
                    flush=True,
                )
            browser.close()

    print(f"Всего обработано записей: {grand}", flush=True)


if __name__ == "__main__":
    main()
