"""Фоновая синхронизация нормативных данных: моки внешних источников, LLM-извлечение, UPSERT в БД."""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from ..db import SessionLocal
from ..datetime_util import utc_now_naive
from ..models import RegulatoryAiExtract, RegulatorySyncEvent, RegulatorySyncState
from .gemini_genai_configure import configure_google_generativeai, resolved_gemini_model_name

_sync_lock = asyncio.Lock()

REGULATORY_AI_PROMPT = (
    "Извлеки из этого таможенного акта правила. Верни JSON массив объектов: код ТН ВЭД, "
    "тип меры (tr_ts, vet_control, other), название документа. "
    "В каждом объекте используй ключи на английском: \"hs_code\", \"measure_type\", \"document_name\". "
    "Только валидный JSON-массив, без пояснений и без markdown."
)

_ALLOWED_MEASURE = frozenset({"tr_ts", "vet_control", "other"})


def _extract_json_array(raw: str) -> str:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    if text.startswith("[") and text.endswith("]"):
        return text
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    raise ValueError("В ответе LLM не найден JSON-массив")


def _normalize_hs(raw: object) -> str:
    code = re.sub(r"\D", "", str(raw or ""))
    if not code:
        return ""
    if len(code) > 10:
        code = code[:10]
    if len(code) not in (4, 6, 10):
        # допускаем 8 знаков как префикс
        if len(code) < 4:
            return ""
    return code


def _normalize_measure(raw: object) -> str:
    m = str(raw or "").strip().lower()
    if m in _ALLOWED_MEASURE:
        return m
    if "вет" in m or "vet" in m:
        return "vet_control"
    if "тр" in m or "tr" in m or "техреглам" in m:
        return "tr_ts"
    return "other"


def mock_fetch_eec_rss_items() -> list[dict[str, str]]:
    """Заглушка: записи как из RSS ЕЭК (заголовок + текст)."""
    return [
        {
            "title": "Решение Совета ЕЭК (мок) о применении ТР ТС 037/2016",
            "link": "https://eec.eaeunion.org/commission/department/catr/ett/",
            "summary": (
                "Для кодов ТН ВЭД 9403500000 и 9403609000 установлены обязательные требования "
                "технического регламента ТР ТС 037/2016 «О безопасности мебельной продукции»."
            ),
        },
    ]


def mock_fetch_fts_open_data_snippet() -> str:
    """Заглушка: фрагмент открытых данных / сводки ФТС по пошлинам."""
    return (
        "Сводная выгрузка (мок): обновлены ставки ввозных пошлин для группы ТН ВЭД 85 "
        "(электромашины и оборудование) по актуальному перечню ЕТТ ЕАЭС."
    )


def _append_event(db: Any, message: str, level: str = "info") -> None:
    db.add(RegulatorySyncEvent(created_at=utc_now_naive(), level=level, message=message))


def _get_state_row(db: Any) -> RegulatorySyncState:
    row = db.query(RegulatorySyncState).filter(RegulatorySyncState.id == 1).first()
    if row is None:
        row = RegulatorySyncState(
            id=1,
            last_completed_at=None,
            last_trigger="",
            last_error="",
            rows_upserted=0,
        )
        db.add(row)
        db.flush()
    return row


def upsert_ai_extracts(db: Any, items: list[dict[str, Any]], excerpt: str) -> tuple[int, int]:
    """UPSERT в regulatory_ai_extracts. Возвращает (inserted, updated)."""
    inserted = 0
    updated = 0
    now = utc_now_naive()
    ex = (excerpt or "")[:2000]
    for it in items:
        hs = _normalize_hs(it.get("hs_code"))
        if not hs:
            continue
        doc = str(it.get("document_name") or "").strip()[:512] or "Неизвестный документ"
        mt = _normalize_measure(it.get("measure_type"))
        existing = (
            db.query(RegulatoryAiExtract)
            .filter(
                RegulatoryAiExtract.hs_code_norm == hs,
                RegulatoryAiExtract.document_name == doc,
                RegulatoryAiExtract.measure_type == mt,
            )
            .first()
        )
        if existing is None:
            db.add(
                RegulatoryAiExtract(
                    hs_code_norm=hs,
                    measure_type=mt,
                    document_name=doc,
                    source_excerpt=ex,
                    created_at=now,
                    updated_at=now,
                )
            )
            inserted += 1
        else:
            existing.source_excerpt = ex
            existing.updated_at = now
            updated += 1
    return inserted, updated


async def process_new_document_with_ai(text: str) -> list[dict[str, Any]]:
    """
    Отправляет текст акта в Gemini, парсит JSON-массив
    [{ hs_code, measure_type, document_name }, ...].
    Без ключа — возвращает пустой список (без исключения).
    """
    body = (text or "").strip()
    if not body:
        return []

    key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    if not key:
        logger.warning("process_new_document_with_ai: нет GEMINI_API_KEY/GOOGLE_API_KEY — пропуск LLM")
        return []

    try:
        import google.generativeai as genai
    except ModuleNotFoundError:
        logger.warning("process_new_document_with_ai: google.generativeai не установлен")
        return []

    model_name = resolved_gemini_model_name()
    configure_google_generativeai(genai, api_key=key)
    model = genai.GenerativeModel(model_name)

    user_msg = REGULATORY_AI_PROMPT + "\n\n---\n\n" + body[:48_000]

    def _call() -> str:
        resp = model.generate_content(
            user_msg,
            generation_config={"temperature": 0.1, "max_output_tokens": 8192},
        )
        return (getattr(resp, "text", "") or "").strip()

    try:
        raw = await asyncio.to_thread(_call)
    except Exception as e:
        logger.exception(f"Gemini regulatory extract: {e}")
        return []

    if not raw:
        return []
    try:
        payload = _extract_json_array(raw)
        data = json.loads(payload)
    except (ValueError, json.JSONDecodeError) as e:
        logger.warning(f"regulatory AI JSON: {e}; snippet={raw[:400]!r}")
        return []

    if not isinstance(data, list):
        return []

    out: list[dict[str, Any]] = []
    for el in data:
        if not isinstance(el, dict):
            continue
        hs = _normalize_hs(el.get("hs_code"))
        if not hs:
            continue
        out.append(
            {
                "hs_code": hs,
                "measure_type": _normalize_measure(el.get("measure_type")),
                "document_name": str(el.get("document_name") or "").strip()[:512],
            }
        )
    return out


def _prune_old_events(db: Any, keep: int = 200) -> None:
    anchor = (
        db.query(RegulatorySyncEvent)
        .order_by(RegulatorySyncEvent.created_at.desc())
        .offset(keep)
        .first()
    )
    if anchor is None:
        return
    db.query(RegulatorySyncEvent).filter(RegulatorySyncEvent.created_at < anchor.created_at).delete(
        synchronize_session=False
    )


async def sync_daily_regulatory_data(trigger: str = "scheduled") -> dict[str, Any]:
    """
    Полный цикл: моки источников, LLM по документам, UPSERT извлечений, журнал событий.
    """
    async with _sync_lock:
        summary: dict[str, Any] = {"trigger": trigger, "ok": True, "rows_inserted": 0, "rows_updated": 0}
        with SessionLocal() as db:
            try:
                _append_event(
                    db,
                    f"Старт синхронизации ({'по расписанию' if trigger == 'scheduled' else 'вручную'})",
                    "info",
                )

                fts = mock_fetch_fts_open_data_snippet()
                _append_event(db, "Обновлены ставки пошлин для 85 группы (мок ФТС / ЕТТ).", "info")
                _append_event(
                    db,
                    f"Детали выгрузки (мок): {fts[:180]}{'…' if len(fts) > 180 else ''}",
                    "info",
                )

                total_ins = 0
                total_upd = 0
                for item in mock_fetch_eec_rss_items():
                    title = item.get("title") or "Документ"
                    blob = f"{title}\n{item.get('summary', '')}"
                    extracted = await process_new_document_with_ai(blob)
                    ins, upd = upsert_ai_extracts(db, extracted, excerpt=blob)
                    total_ins += ins
                    total_upd += upd
                    if ins or upd:
                        for rule in extracted[:3]:
                            dn = rule.get("document_name") or title
                            _append_event(
                                db,
                                f"Добавлены/обновлены правила по {rule.get('hs_code')}: {dn[:120]}",
                                "info",
                            )
                        if "037/2016" in title or any("037" in str(r.get("document_name", "")) for r in extracted):
                            _append_event(db, "Добавлен ТР ТС 037/2016 (фрагмент из мок-ленты)", "info")

                st = _get_state_row(db)
                st.last_completed_at = utc_now_naive()
                st.last_trigger = trigger
                st.last_error = ""
                st.rows_upserted = total_ins + total_upd
                summary["rows_inserted"] = total_ins
                summary["rows_updated"] = total_upd

                _append_event(
                    db,
                    f"Синхронизация завершена: новых записей {total_ins}, обновлено {total_upd}.",
                    "info",
                )
                _prune_old_events(db)
                db.commit()
            except Exception as e:
                logger.exception(f"sync_daily_regulatory_data: {e}")
                db.rollback()
                summary["ok"] = False
                summary["error"] = str(e)
                with SessionLocal() as db2:
                    _append_event(db2, f"Ошибка синхронизации: {e}", "error")
                    st = _get_state_row(db2)
                    st.last_completed_at = utc_now_naive()
                    st.last_trigger = trigger
                    st.last_error = str(e)[:4000]
                    db2.commit()
        return summary


LAW_PORTAL_SINGLE_RAG_PROMPT = (
    "Это нормативный документ таможенного законодательства.\n"
    "1. Выдели все коды ТН ВЭД (10 знаков или коды групп, если в тексте явно указаны как позиции/подсубпозиции ТН ВЭД).\n"
    "2. Кратко сформулируй правило для декларанта (запрет, пошлина, требование документа, срок, орган и т.п.).\n"
    "3. Верни результат в JSON одного объекта (без markdown):\n"
    '{"hs_codes":["0000000000"],"declarant_rule":"…","measure_type":"other"}\n'
    "Поле hs_codes — массив строк; если конкретных кодов нет, передай пустой массив [].\n"
    "measure_type: одно из tr_ts, vet_control, license, ban, export_control, currency, valuation, classification, other.\n"
    "Поле declarant_rule — строка на русском, 1–5 предложений."
)


LAW_PORTAL_BATCH_PROMPT = (
    "Ты анализируешь пакет нормативных документов с портала law.tks.ru / TKS (таможня, ВЭД). "
    "Для КАЖДОГО документа по его индексу верни извлечения.\n"
    "Если документ явно ссылается на конкретные коды ТН ВЭД (10 знаков) — перечисли их в hs_codes.\n"
    "Если это общее правило (валюта, страна, процедура без привязки к коду) — заполни general_rule краткой формулировкой применения, hs_codes оставь пустым массивом.\n"
    "declarant_rule — обязательное поле: 1–3 предложения на русском, что должен учесть декларант на практике (действия, сроки, риски). "
    "Если к ТН ВЭД не привязано — всё равно заполни declarant_rule по сути текста.\n"
    "measure_type: одно из tr_ts, vet_control, license, ban, export_control, currency, valuation, classification, other.\n"
    "Верни ТОЛЬКО валидный JSON объекта вида:\n"
    '{"documents":[{"index":0,"items":[{"hs_codes":["6404110000"],"measure_type":"tr_ts","document_name":"кратко",'
    '"excerpt":"цитата или краткий выжимок","declarant_rule":"суть для декларанта"},'
    '{"hs_codes":[],"measure_type":"currency","document_name":"кратко","general_rule":"формулировка","excerpt":"","declarant_rule":"что делать декларанту"}]}]}\n'
    "Без markdown и без пояснений вне JSON."
)


def _normalize_hs_law(raw: object) -> str:
    code = _normalize_hs(raw)
    if code:
        return code
    return "0000000000"


def _normalize_measure_law(raw: object) -> str:
    m = str(raw or "").strip().lower()
    allowed = frozenset(
        {
            "tr_ts",
            "vet_control",
            "license",
            "ban",
            "export_control",
            "currency",
            "valuation",
            "classification",
            "other",
        }
    )
    if m in allowed:
        return m
    if "вет" in m or "vet" in m:
        return "vet_control"
    if "тр" in m or "tr" in m or "техреглам" in m:
        return "tr_ts"
    if "лиценз" in m:
        return "license"
    if "запрет" in m or "ban" in m or "эмбарго" in m:
        return "ban"
    if "экспорт" in m or "фстэк" in m or "двойн" in m:
        return "export_control"
    if "валют" in m:
        return "currency"
    if "стоимост" in m or "цен" in m or "valuation" in m:
        return "valuation"
    if "классиф" in m or "тн вэд" in m or "tnved" in m:
        return "classification"
    return "other"


def _extract_json_object(raw: str) -> str:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    if text.startswith("{") and text.endswith("}"):
        return text
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    raise ValueError("В ответе LLM не найден JSON-объект")


def upsert_regulatory_ai_from_law_items(db: Any, items: list[dict[str, Any]]) -> tuple[int, int]:
    """UPSERT в regulatory_ai_extracts из извлечений law-portal (в т.ч. общие правила: hs=0000000000)."""
    inserted = 0
    updated = 0
    now = utc_now_naive()
    for it in items:
        hs = _normalize_hs_law(it.get("hs_code"))
        if not hs:
            hs = "0000000000"
        doc = str(it.get("document_name") or "").strip()[:512] or "Law.tks.ru"
        mt = _normalize_measure_law(it.get("measure_type"))
        ex = str(it.get("source_excerpt") or it.get("excerpt") or "")[:2000]
        gr = str(it.get("general_rule") or "").strip()
        decl = str(it.get("declarant_rule") or it.get("declarant_summary") or "").strip()
        if gr:
            ex = (ex + "\n\nОбщее правило: " + gr)[:2000]
        if decl:
            ex = (ex + ("\n\n" if ex else "") + "Для декларанта: " + decl)[:2000]
        existing = (
            db.query(RegulatoryAiExtract)
            .filter(
                RegulatoryAiExtract.hs_code_norm == hs,
                RegulatoryAiExtract.document_name == doc,
                RegulatoryAiExtract.measure_type == mt,
            )
            .first()
        )
        if existing is None:
            db.add(
                RegulatoryAiExtract(
                    hs_code_norm=hs,
                    measure_type=mt,
                    document_name=doc,
                    source_excerpt=ex,
                    created_at=now,
                    updated_at=now,
                )
            )
            inserted += 1
        else:
            existing.source_excerpt = ex
            existing.updated_at = now
            updated += 1
        # Следующая итерация должна видеть только что добавленную строку (иначе дубликат UNIQUE).
        db.flush()
    return inserted, updated


async def process_law_portal_single_document_with_ai(
    *,
    title: str,
    url: str,
    body: str,
    topic_category: str,
) -> list[dict[str, Any]]:
    """
    Один документ law.tks.ru → плоский список для upsert_regulatory_ai_from_law_items.
    topic_category — метка раздела (например topics:7), попадает в контекст промпта.
    """
    key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    if not key:
        logger.warning("law portal single: нет GEMINI_API_KEY/GOOGLE_API_KEY")
        return []
    try:
        import google.generativeai as genai
    except ModuleNotFoundError:
        logger.warning("law portal single: google.generativeai не установлен")
        return []

    snippet = (body or "")[:18_000]
    user_msg = (
        LAW_PORTAL_SINGLE_RAG_PROMPT
        + f"\n\nРаздел портала: {topic_category}\nЗаголовок: {title}\nURL: {url}\n\nТекст документа:\n{snippet}"
    )

    model_name = resolved_gemini_model_name()
    configure_google_generativeai(genai, api_key=key)
    model = genai.GenerativeModel(model_name)

    def _call() -> str:
        resp = model.generate_content(
            user_msg,
            generation_config={"temperature": 0.12, "max_output_tokens": 4096},
        )
        return (getattr(resp, "text", "") or "").strip()

    try:
        raw = await asyncio.to_thread(_call)
    except Exception as e:
        logger.exception(f"law portal single Gemini: {e}")
        return []
    if not raw:
        return []
    try:
        payload = _extract_json_object(raw)
        data = json.loads(payload)
    except (ValueError, json.JSONDecodeError) as e:
        logger.warning(f"law portal single JSON: {e}; snippet={raw[:400]!r}")
        return []

    if not isinstance(data, dict):
        return []

    hs_list = data.get("hs_codes")
    if hs_list is None and data.get("codes") is not None:
        hs_list = data.get("codes")
    if not isinstance(hs_list, list):
        hs_list = []

    mt = _normalize_measure_law(data.get("measure_type"))
    doc_name = str(data.get("document_name") or title or "Документ law.tks.ru")[:512]
    decl = str(data.get("declarant_rule") or data.get("declarant_summary") or "").strip()
    excerpt = str(data.get("excerpt") or "").strip()
    gr = str(data.get("general_rule") or "").strip()

    flat: list[dict[str, Any]] = []
    for raw_hs in hs_list:
        hs_one = _normalize_hs(raw_hs)
        if not hs_one:
            continue
        flat.append(
            {
                "hs_code": hs_one,
                "measure_type": mt,
                "document_name": doc_name,
                "source_excerpt": excerpt,
                "general_rule": gr,
                "declarant_rule": decl,
            }
        )
    if not flat:
        if not decl and not excerpt and not gr:
            return []
        flat.append(
            {
                "hs_code": "0000000000",
                "measure_type": mt,
                "document_name": doc_name,
                "source_excerpt": excerpt,
                "general_rule": gr,
                "declarant_rule": decl,
            }
        )
    return flat


async def process_law_portal_documents_batch_with_ai(
    documents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    documents: [{ "index": int, "title": str, "url": str, "category": str, "text": str }, ...]
    Возвращает плоский список dict для upsert_regulatory_ai_from_law_items:
    hs_code, measure_type, document_name, source_excerpt, general_rule (опц.).
    """
    if not documents:
        return []
    key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    if not key:
        logger.warning("law portal batch: нет GEMINI_API_KEY/GOOGLE_API_KEY")
        return []

    try:
        import google.generativeai as genai
    except ModuleNotFoundError:
        logger.warning("law portal batch: google.generativeai не установлен")
        return []

    parts: list[str] = []
    for i, d in enumerate(documents):
        idx = int(d.get("index", i))
        title = str(d.get("title") or "")[:400]
        url = str(d.get("url") or "")[:500]
        cat = str(d.get("category") or "")[:120]
        body = str(d.get("text") or "")[:12_000]
        parts.append(f"### Документ index={idx}\nЗаголовок: {title}\nURL: {url}\nРаздел: {cat}\n\n{body}\n")
    user_msg = LAW_PORTAL_BATCH_PROMPT + "\n\n" + "\n".join(parts)

    model_name = resolved_gemini_model_name()
    configure_google_generativeai(genai, api_key=key)
    model = genai.GenerativeModel(model_name)

    def _call() -> str:
        resp = model.generate_content(
            user_msg,
            generation_config={"temperature": 0.15, "max_output_tokens": 8192},
        )
        return (getattr(resp, "text", "") or "").strip()

    try:
        raw = await asyncio.to_thread(_call)
    except Exception as e:
        logger.exception(f"law portal batch Gemini: {e}")
        return []

    if not raw:
        return []
    try:
        payload = _extract_json_object(raw)
        data = json.loads(payload)
    except (ValueError, json.JSONDecodeError) as e:
        logger.warning(f"law portal batch JSON: {e}; snippet={raw[:500]!r}")
        return []

    docs_block = data.get("documents") if isinstance(data, dict) else None
    if not isinstance(docs_block, list):
        return []

    by_idx: dict[int, dict[str, Any]] = {}
    for i, d in enumerate(documents):
        if isinstance(d, dict):
            by_idx[int(d.get("index", i))] = d

    flat: list[dict[str, Any]] = []
    for block in docs_block:
        if not isinstance(block, dict):
            continue
        idx = int(block.get("index", -1))
        items = block.get("items")
        if not isinstance(items, list):
            continue
        base_title = str((by_idx.get(idx) or {}).get("title") or "")[:200]
        for el in items:
            if not isinstance(el, dict):
                continue
            hs_list = el.get("hs_codes")
            mt = _normalize_measure_law(el.get("measure_type"))
            doc_name = str(el.get("document_name") or base_title or "Документ")[:512]
            excerpt = str(el.get("excerpt") or "")[:1500]
            general_rule = str(el.get("general_rule") or "").strip()
            declarant_rule = str(el.get("declarant_rule") or el.get("declarant_summary") or "").strip()
            if isinstance(hs_list, list) and hs_list:
                for raw_hs in hs_list:
                    hs_one = _normalize_hs(raw_hs)
                    if not hs_one:
                        continue
                    flat.append(
                        {
                            "hs_code": hs_one,
                            "measure_type": mt,
                            "document_name": doc_name,
                            "source_excerpt": excerpt,
                            "general_rule": general_rule,
                            "declarant_rule": declarant_rule,
                        }
                    )
            else:
                if not excerpt and not general_rule and not declarant_rule:
                    continue
                flat.append(
                    {
                        "hs_code": "0000000000",
                        "measure_type": mt,
                        "document_name": doc_name,
                        "source_excerpt": excerpt,
                        "general_rule": general_rule,
                        "declarant_rule": declarant_rule,
                    }
                )
    return flat


def get_sync_status_payload() -> dict[str, Any]:
    """Данные для GET /api/v1/admin/sync/status (без проверки токена — вызывать после require_admin)."""
    from .scheduler import is_scheduler_running, regulatory_job_next_run_iso

    with SessionLocal() as db:
        st = db.query(RegulatorySyncState).filter(RegulatorySyncState.id == 1).first()
        last_iso = None
        if st and st.last_completed_at:
            last_iso = st.last_completed_at.replace(tzinfo=timezone.utc).isoformat()
        events = (
            db.query(RegulatorySyncEvent)
            .order_by(RegulatorySyncEvent.created_at.desc())
            .limit(30)
            .all()
        )
        log_lines = [
            {
                "at": e.created_at.replace(tzinfo=timezone.utc).isoformat() if e.created_at else "",
                "level": e.level,
                "message": e.message,
            }
            for e in reversed(events)
        ]

    return {
        "scheduler_running": is_scheduler_running(),
        "last_sync_iso": last_iso,
        "next_sync_iso": regulatory_job_next_run_iso(),
        "recent_log": log_lines,
    }
