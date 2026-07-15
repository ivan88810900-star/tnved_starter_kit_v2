"""Evidence-first summaries for the declarant assistant.

The assistant must remain useful when no external LLM is configured.  This module
builds a compact, auditable fact bundle from existing product services and renders
a conservative deterministic answer.  An LLM may later rewrite that draft, but it
must not become the source of tariff, payment, NTM, or sanctions facts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from .non_tariff_service import check_position_non_tariff
from .normative_store import get_tnved_context_for_hs
from .tnved_code_card import canonical_anchor_for_hs, canonical_anchors_for_hs_codes
from .tnved_fts import search_commodities_smart

_VALID_HS_LENGTHS = {4, 6, 8, 10}
_TEN_DIGIT_RE = re.compile(r"(?<!\d)((?:\d[\s-]*){9}\d)(?!\d)")
_LABELLED_CODE_RE = re.compile(
    r"(?:тн\s*вэд|код)[^\d]{0,24}((?:\d[\s-]*){4,10})",
    flags=re.IGNORECASE,
)

_PAYMENT_FIELDS: tuple[str, ...] = (
    "total_payable",
    "customs_value_rub",
    "duty_rate_pct",
    "vat_rate_pct",
    "duty_rub",
    "vat_rub",
    "excise_rub",
    "customs_fee_rub",
    "antidumping_rub",
    "special_duties_rub",
    "vat_base_rub",
)

_PAYMENT_KEYWORDS = (
    "платеж",
    "пошлин",
    "ндс",
    "сбор",
    "стоим",
    "сколько",
    "итого",
)
_DOCUMENT_KEYWORDS = (
    "документ",
    "сертифик",
    "деклараци",
    "разреш",
    "нетариф",
    "тр тс",
    "сгр",
    "лиценз",
)
_RISK_KEYWORDS = (
    "риск",
    "санкц",
    "эмбарго",
    "огранич",
    "контрагент",
)
_CLASSIFICATION_KEYWORDS = (
    "код",
    "тн вэд",
    "классиф",
    "позици",
)

_ASSISTANT_SEARCH_STOP_WORDS = frozenset(
    {
        "а",
        "без",
        "в",
        "вед",
        "вэд",
        "для",
        "документ",
        "документы",
        "есть",
        "и",
        "как",
        "какая",
        "какие",
        "какой",
        "код",
        "мне",
        "найди",
        "найти",
        "нужен",
        "нужна",
        "нужны",
        "о",
        "определи",
        "по",
        "подбери",
        "подобрать",
        "платежи",
        "проверить",
        "риски",
        "сколько",
        "тн",
        "товар",
        "товара",
        "у",
        "что",
    }
)


def _digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))[:10]


def _trim(value: Any, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _first_nonempty(*values: Any) -> str:
    for value in values:
        text = _trim(value)
        if text:
            return text
    return ""


def _extract_hs_from_text(value: str) -> str:
    text = value or ""
    match = _TEN_DIGIT_RE.search(text)
    if match:
        digits = _digits(match.group(1))
        if len(digits) == 10:
            return digits
    match = _LABELLED_CODE_RE.search(text)
    if match:
        digits = _digits(match.group(1))
        if len(digits) in _VALID_HS_LENGTHS:
            return digits
    return ""


def _assistant_product_query(message: str) -> str:
    """Remove conversational scaffolding before sending text to catalogue search."""
    words = re.findall(r"[\w-]+", (message or "").lower().replace("ё", "е"), flags=re.UNICODE)
    meaningful = [
        word
        for word in words
        if len(word) >= 2 and word not in _ASSISTANT_SEARCH_STOP_WORDS
    ]
    cleaned = " ".join(meaningful[:10]).strip()
    return cleaned if len(cleaned) >= 2 else (message or "").strip()[:160]


def _resolve_hs_code(
    message: str,
    history: list[dict[str, Any]],
    current_context: dict[str, Any],
) -> tuple[str, str]:
    context_code = _digits(current_context.get("hs_code"))
    if len(context_code) in _VALID_HS_LENGTHS:
        return context_code, "calculator_context"

    message_code = _extract_hs_from_text(message)
    if message_code:
        return message_code, "current_message"

    for item in reversed(history[-12:]):
        if str(item.get("role") or "").strip().lower() != "user":
            continue
        code = _extract_hs_from_text(str(item.get("text") or item.get("content") or ""))
        if code:
            return code, "conversation_history"
    return "", "none"


def _source_kind(source_id: str) -> str:
    source = (source_id or "").lower()
    if source.startswith("official_") or source in {"eec_ett", "eec"}:
        return "official"
    if source.startswith("legacy_") or source in {"runtime_triggers", "domain_default"}:
        return "internal_advisory"
    if source == "calculator_snapshot":
        return "calculation"
    if source == "canonical_tnved":
        return "canonical"
    return "local_registry"


@dataclass
class _CitationCollector:
    items: list[dict[str, Any]] = field(default_factory=list)
    _by_key: dict[tuple[str, str, str], str] = field(default_factory=dict)

    def add(
        self,
        *,
        source_id: str,
        title: str,
        kind: str | None = None,
        url: str | None = None,
        status: str | None = None,
        excerpt: str | None = None,
    ) -> str:
        clean_source = _trim(source_id, 120) or "internal"
        clean_title = _trim(title, 220) or clean_source
        clean_url = _trim(url, 600) or None
        key = (clean_source, clean_title, clean_url or "")
        existing = self._by_key.get(key)
        if existing:
            return existing
        citation_id = f"S{len(self.items) + 1}"
        item: dict[str, Any] = {
            "id": citation_id,
            "source_id": clean_source,
            "title": clean_title,
            "kind": kind or _source_kind(clean_source),
        }
        if clean_url:
            item["url"] = clean_url
        if status:
            item["status"] = _trim(status, 100)
        if excerpt:
            item["excerpt"] = _trim(excerpt, 420)
        self.items.append(item)
        self._by_key[key] = citation_id
        return citation_id


def _payment_snapshot(context: dict[str, Any], citations: _CitationCollector) -> dict[str, Any] | None:
    values = {key: context.get(key) for key in _PAYMENT_FIELDS if context.get(key) is not None}
    if not values:
        return None

    excerpt_parts: list[str] = []
    if values.get("total_payable") is not None:
        excerpt_parts.append(f"итого {values['total_payable']} руб.")
    if values.get("duty_rate_pct") is not None:
        excerpt_parts.append(f"пошлина {values['duty_rate_pct']}%")
    if values.get("vat_rate_pct") is not None:
        excerpt_parts.append(f"НДС {values['vat_rate_pct']}%")
    citation_id = citations.add(
        source_id="calculator_snapshot",
        title="Снимок расчёта платежей Tariff",
        status="calculated",
        excerpt="; ".join(excerpt_parts) or "Переданные суммы расчёта",
    )

    source_citation_ids: list[str] = []
    for row in list(context.get("payment_sources") or [])[:8]:
        if not isinstance(row, dict):
            continue
        title = _first_nonempty(row.get("name"), row.get("source"), "Источник расчёта")
        source_citation_ids.append(
            citations.add(
                source_id=_first_nonempty(row.get("source_code"), row.get("name"), "payment_source"),
                title=title,
                kind="official" if "ЕАЭС" in title or "НК РФ" in title else "local_registry",
                url=_trim(row.get("url"), 600) or None,
                status=_first_nonempty(row.get("revision"), "integrated"),
                excerpt=_trim(row.get("data_info"), 420) or None,
            )
        )

    return {
        **values,
        "data_quality": context.get("payment_data_quality")
        if isinstance(context.get("payment_data_quality"), dict)
        else {},
        "legal_basis": context.get("payment_legal_basis")
        if isinstance(context.get("payment_legal_basis"), dict)
        else {},
        "citation_ids": list(dict.fromkeys([citation_id, *source_citation_ids])),
    }


def _note_rows(raw: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in list(raw or [])[:6]:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "title": _trim(item.get("title"), 240),
                "body_excerpt": _trim(item.get("body"), 500),
                "source_url": _trim(item.get("source_url"), 600) or None,
                "source_revision": _trim(item.get("source_revision"), 120) or None,
            }
        )
    return rows


def _normative_summary(
    raw: dict[str, Any],
    citations: _CitationCollector,
) -> dict[str, Any]:
    block = raw.get("normative_block") if isinstance(raw.get("normative_block"), dict) else {}

    def normalize_docs(rows: Any, *, advisory: bool = False) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in list(rows or [])[:12]:
            if not isinstance(row, dict):
                continue
            source_id = _first_nonempty(row.get("source"), "normative_rules")
            source_label = _first_nonempty(row.get("source_label"), source_id)
            citation_id = citations.add(
                source_id=source_id,
                title=source_label,
                url=_trim(row.get("source_url"), 600) or None,
                status=_first_nonempty(row.get("applicability"), "advisory" if advisory else "definite"),
                excerpt=_first_nonempty(row.get("reason"), row.get("note"), row.get("description")) or None,
            )
            out.append(
                {
                    "permit_type": _trim(row.get("permit_type"), 80),
                    "tr_ts": _trim(row.get("tr_ts"), 120) or None,
                    "applicability": _first_nonempty(
                        row.get("applicability"),
                        "advisory" if advisory else "definite",
                    ),
                    "reason": _first_nonempty(row.get("reason"), row.get("note"), row.get("description")),
                    "citation_id": citation_id,
                }
            )
        return out

    return {
        "status": _first_nonempty(block.get("status"), raw.get("status"), "UNKNOWN"),
        "required_documents": normalize_docs(block.get("required_documents")),
        "unconfirmed_documents": normalize_docs(block.get("missing_documents")),
        "advisory_requirements": normalize_docs(block.get("advisory_requirements"), advisory=True),
        "tr_ts": [_trim(value, 120) for value in list(block.get("tr_ts") or [])[:12] if _trim(value, 120)],
        "empty_message": _trim(block.get("empty_message"), 500) or None,
    }


def _risk_summary(raw: dict[str, Any], citations: _CitationCollector) -> dict[str, Any]:
    block = raw.get("risk_block") if isinstance(raw.get("risk_block"), dict) else {}
    signals: list[dict[str, Any]] = []
    for row in list(block.get("signals") or [])[:12]:
        if not isinstance(row, dict):
            continue
        source_id = _first_nonempty(row.get("source"), "risk_registry")
        citation_id = citations.add(
            source_id=source_id,
            title=_first_nonempty(row.get("source_label"), source_id),
            url=_trim(row.get("source_url"), 600) or None,
            status=_first_nonempty(row.get("severity"), "signal"),
            excerpt=_trim(row.get("explanation"), 420) or None,
        )
        signals.append(
            {
                "category": _trim(row.get("category"), 100),
                "severity": _first_nonempty(row.get("severity"), "unknown"),
                "explanation": _trim(row.get("explanation"), 600),
                "match_method": _trim(row.get("match_method"), 160) or None,
                "matched_hs_prefix": _trim(row.get("matched_hs_prefix"), 20) or None,
                "matched_country": _trim(row.get("matched_country"), 20) or None,
                "matched_entity": _trim(row.get("matched_entity"), 220) or None,
                "citation_id": citation_id,
            }
        )

    coverage: list[dict[str, Any]] = []
    for row in list(block.get("source_coverage") or [])[:10]:
        if not isinstance(row, dict):
            continue
        citation_id = citations.add(
            source_id=_first_nonempty(row.get("source_id"), "risk_coverage"),
            title=_first_nonempty(row.get("title"), row.get("source_id"), "Источник риск-скрининга"),
            url=_trim(row.get("source_url"), 600) or None,
            status=_first_nonempty(row.get("coverage_status"), "unknown"),
            excerpt="; ".join(_trim(gap, 180) for gap in list(row.get("known_gaps") or [])[:3] if _trim(gap, 180))
            or None,
        )
        coverage.append(
            {
                "source_id": _trim(row.get("source_id"), 120),
                "title": _trim(row.get("title"), 220),
                "coverage_status": _first_nonempty(row.get("coverage_status"), "unknown"),
                "manual_review_required": bool(row.get("manual_review_required")),
                "citation_id": citation_id,
            }
        )

    scope = [
        {
            "code": _trim(row.get("code"), 40),
            "label": _trim(row.get("label"), 140),
            "status": _first_nonempty(row.get("status"), "not_checked"),
            "value": _trim(row.get("value"), 220) or None,
            "explanation": _trim(row.get("explanation"), 420),
        }
        for row in list(block.get("screening_scope") or [])[:6]
        if isinstance(row, dict)
    ]
    return {
        "status": _first_nonempty(block.get("status"), "MANUAL_REVIEW"),
        "overall_severity": _first_nonempty(block.get("overall_severity"), "unknown"),
        "coverage_complete": bool(block.get("coverage_complete")),
        "signals": signals,
        "source_coverage": coverage,
        "screening_scope": scope,
        "warnings": [_trim(item, 500) for item in list(block.get("warnings") or [])[:8] if _trim(item, 500)],
        "empty_message": _trim(block.get("empty_message"), 600) or None,
        "canonical_anchor": block.get("canonical_anchor")
        if isinstance(block.get("canonical_anchor"), dict)
        else None,
    }


async def build_chat_grounding_bundle(
    *,
    message: str,
    history: list[dict[str, Any]],
    current_context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build a bounded, server-owned evidence bundle for one chat turn."""
    context = dict(current_context or {})
    citations = _CitationCollector()
    limitations: list[str] = []
    facts_used: list[str] = []
    hs_code, hs_source = _resolve_hs_code(message, history, context)
    product_name = _first_nonempty(context.get("product_name"))
    country = _first_nonempty(context.get("origin_country"), context.get("country")).upper() or None

    payment = _payment_snapshot(context, citations)
    if payment:
        facts_used.append("payments")
        quality = payment.get("data_quality") or {}
        if str(quality.get("confidence") or "").lower() in {"low", "none"}:
            limitations.append("Качество совпадения ставки в переданном расчёте низкое — ставку нужно перепроверить.")
        if str(quality.get("antidumping_status") or "").lower() == "manual_review":
            limitations.append("Антидемпинговая мера требует ручной проверки.")

    tnved: dict[str, Any] | None = None
    normative: dict[str, Any] | None = None
    risk: dict[str, Any] | None = None
    canonical_anchor: dict[str, Any] | None = None

    if hs_code:
        try:
            raw_tnved = get_tnved_context_for_hs(hs_code)
            official_url = _trim(raw_tnved.get("official_ett_url"), 600) or None
            eec_citation = citations.add(
                source_id="eec_ett",
                title="ТН ВЭД ЕАЭС и Единый таможенный тариф — ЕЭК",
                kind="official",
                url=official_url,
                status=_first_nonempty(raw_tnved.get("source_revision"), "reference"),
                excerpt=_first_nonempty(raw_tnved.get("title"), raw_tnved.get("description")) or None,
            )
            canonical_anchor = canonical_anchor_for_hs(hs_code)
            anchor_citation: str | None = None
            if canonical_anchor:
                anchor_citation = citations.add(
                    source_id="canonical_tnved",
                    title="Canonical TN VED Model",
                    kind="canonical",
                    status=_first_nonempty(canonical_anchor.get("snapshot_id"), "resolved"),
                    excerpt=(
                        f"stable_id={canonical_anchor.get('stable_id')}; "
                        f"code={canonical_anchor.get('code')}"
                    ),
                )
            tnved = {
                "hs_code": hs_code,
                "hs_source": hs_source,
                "title": _trim(raw_tnved.get("title"), 600),
                "description": _trim(raw_tnved.get("description"), 800),
                "breadcrumb": [
                    {
                        "hs_code": _trim(row.get("hs_code"), 20),
                        "title": _trim(row.get("title"), 260),
                    }
                    for row in list(raw_tnved.get("breadcrumb") or [])[:10]
                    if isinstance(row, dict)
                ],
                "notes": _note_rows(raw_tnved.get("notes")),
                "source_revision": _trim(raw_tnved.get("source_revision"), 120),
                "citation_ids": [value for value in (eec_citation, anchor_citation) if value],
            }
            facts_used.append("tnved")
        except Exception as exc:  # additive grounding must not break the chat
            logger.warning("assistant grounding: TN VED context failed: {}", exc)
            limitations.append("Карточка ТН ВЭД временно недоступна; код не подтверждён по справочнику.")

        try:
            nt_description = product_name or "—"
            raw_non_tariff = await check_position_non_tariff(
                hs_code,
                nt_description,
                country,
                [],
                skip_registry_verify=True,
            )
            normative = _normative_summary(raw_non_tariff, citations)
            risk = _risk_summary(raw_non_tariff, citations)
            if canonical_anchor is None and isinstance(risk.get("canonical_anchor"), dict):
                canonical_anchor = risk["canonical_anchor"]
            facts_used.extend(["requirements", "risk"])
            if not risk.get("coverage_complete"):
                limitations.append(
                    "Санкционный скрининг имеет неполное покрытие; отсутствие совпадений не означает отсутствие риска."
                )
        except Exception as exc:  # no 500 when optional evidence services degrade
            logger.warning("assistant grounding: NTM/risk context failed: {}", exc)
            limitations.append("Нетарифные требования и риск-контур временно не удалось проверить.")

    candidates: list[dict[str, Any]] = []
    search_meta: dict[str, Any] = {}
    if not hs_code:
        try:
            product_query = _assistant_product_query(message)
            search_outcome = search_commodities_smart(product_query, limit=5)
            raw_candidates = search_outcome.get("results")
            if isinstance(raw_candidates, list):
                anchors = canonical_anchors_for_hs_codes(
                    [_digits(row.get("code")) for row in raw_candidates if isinstance(row, dict)]
                )
                for row in raw_candidates[:5]:
                    if not isinstance(row, dict):
                        continue
                    code = _digits(row.get("code"))
                    candidates.append(
                        {
                            "code": code,
                            "name": _trim(row.get("description"), 500),
                            "match_reason": _first_nonempty(row.get("match_reason"), "full_text"),
                            "canonical_anchor": anchors.get(code),
                        }
                    )
                if candidates:
                    facts_used.append("search_candidates")
                    citations.add(
                        source_id="eec_ett",
                        title="ТН ВЭД ЕАЭС и Единый таможенный тариф — ЕЭК",
                        kind="official",
                        url="https://eec.eaeunion.org/comission/department/catr/ett/",
                        status="candidate_search",
                        excerpt="Кандидаты из локальной проекции номенклатуры; не финальная классификация.",
                    )
            else:
                limitations.append("Полнотекстовый поиск по номенклатуре временно недоступен.")
            search_meta = {
                "strategy": search_outcome.get("strategy"),
                "query": product_query,
                "effective_query": search_outcome.get("effective_query"),
                "corrected_query": search_outcome.get("corrected_query"),
            }
        except Exception as exc:
            logger.warning("assistant grounding: product search failed: {}", exc)
            limitations.append("Не удалось подобрать кандидатов ТН ВЭД по описанию.")

    if hs_code:
        coverage = "grounded"
    elif candidates:
        coverage = "partial"
        limitations.append("Кандидаты поиска не являются подтверждённым кодом ТН ВЭД.")
    else:
        coverage = "needs_context"
        limitations.append("Для предметного ответа нужен код ТН ВЭД или подробное описание товара.")

    return {
        "question": _trim(message, 8000),
        "resolved_hs_code": hs_code or None,
        "hs_source": hs_source,
        "product_name": product_name or None,
        "country": country,
        "tnved": tnved,
        "payment": payment,
        "requirements": normative,
        "risk": risk,
        "search_candidates": candidates,
        "search": search_meta,
        "canonical_anchor": canonical_anchor,
        "coverage": coverage,
        "facts_used": list(dict.fromkeys(facts_used)),
        "citations": citations.items,
        "limitations": list(dict.fromkeys(limitations)),
    }


def _citation_suffix(ids: list[str] | tuple[str, ...] | None) -> str:
    clean = [value for value in list(ids or []) if value]
    return " " + " ".join(f"[{value}]" for value in dict.fromkeys(clean)) if clean else ""


def _money(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    rendered = f"{number:,.2f}".replace(",", " ").replace(".00", "")
    return f"{rendered} ₽"


def _rate(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{number:g}%"


def _intent(message: str) -> dict[str, bool]:
    low = (message or "").lower()
    flags = {
        "classification": any(word in low for word in _CLASSIFICATION_KEYWORDS),
        "payment": any(word in low for word in _PAYMENT_KEYWORDS),
        "documents": any(word in low for word in _DOCUMENT_KEYWORDS),
        "risk": any(word in low for word in _RISK_KEYWORDS),
    }
    if not any(flags.values()):
        return {key: True for key in flags}
    return flags


def render_chat_grounded_answer(bundle: dict[str, Any]) -> tuple[str, list[str]]:
    """Render an answer whose factual statements map to returned citation IDs."""
    hs_code = str(bundle.get("resolved_hs_code") or "")
    citations = list(bundle.get("citations") or [])
    eec_ids = [row.get("id") for row in citations if row.get("source_id") == "eec_ett"]
    intent = _intent(str(bundle.get("question") or ""))
    suggestions: list[str] = []

    if not hs_code:
        candidates = list(bundle.get("search_candidates") or [])
        if not candidates:
            answer = (
                "Чтобы дать проверяемый ответ, мне нужен **код ТН ВЭД** либо подробное описание товара: "
                "назначение, материал, принцип работы, комплектность и страна происхождения. "
                "Без этого я не буду угадывать ставку или обязательные документы."
            )
        else:
            corrected = (bundle.get("search") or {}).get("corrected_query")
            intro = "По описанию нашёл возможные позиции"
            if corrected:
                intro += f" после исправления запроса на «{corrected}»"
            lines = [
                f"{idx}. `{row.get('code')}` — {row.get('name') or 'наименование не заполнено'}"
                for idx, row in enumerate(candidates[:5], start=1)
            ]
            answer = (
                f"{intro}:{_citation_suffix(eec_ids)}\n\n"
                + "\n".join(lines)
                + "\n\nЭто **кандидаты поиска, а не подтверждённая классификация**. "
                "Для выбора 10-значного кода нужны характеристики товара и проверка по ОПИ."
            )
        suggestions = [
            "Указать код ТН ВЭД и спросить о документах",
            "Описать материал, назначение и принцип работы товара",
            "Открыть расчёт платежей и передать его в ассистент",
        ]
        return answer, suggestions

    tnved = bundle.get("tnved") if isinstance(bundle.get("tnved"), dict) else {}
    title = _first_nonempty(tnved.get("title"), tnved.get("description"), bundle.get("product_name"))
    tnved_ids = list(tnved.get("citation_ids") or [])
    parts = [
        f"Проверяю позицию **`{hs_code}`**"
        + (f" — {title}" if title else "")
        + f".{_citation_suffix(tnved_ids)}"
    ]
    parts.append(
        "Все требования и суммы ниже привязаны к этому коду. Если код не соответствует фактическим "
        "характеристикам товара, выводы нужно пересчитать."
    )
    if intent["classification"]:
        parts.append(
            "Код взят из переданного контекста или сообщения. Я не подтверждаю соответствие товара коду "
            "без его технических характеристик и последовательной проверки по ОПИ."
        )

    payment = bundle.get("payment") if isinstance(bundle.get("payment"), dict) else None
    if intent["payment"]:
        if payment:
            rows: list[str] = []
            if payment.get("customs_value_rub") is not None:
                rows.append(f"таможенная стоимость — {_money(payment.get('customs_value_rub'))}")
            if payment.get("duty_rub") is not None:
                rows.append(
                    f"пошлина — {_money(payment.get('duty_rub'))}"
                    + (
                        f" ({_rate(payment.get('duty_rate_pct'))})"
                        if payment.get("duty_rate_pct") is not None
                        else ""
                    )
                )
            if payment.get("vat_rub") is not None:
                rows.append(
                    f"НДС — {_money(payment.get('vat_rub'))}"
                    + (
                        f" ({_rate(payment.get('vat_rate_pct'))})"
                        if payment.get("vat_rate_pct") is not None
                        else ""
                    )
                )
            if payment.get("customs_fee_rub") is not None:
                rows.append(f"таможенный сбор — {_money(payment.get('customs_fee_rub'))}")
            if payment.get("antidumping_rub"):
                rows.append(f"антидемпинговая пошлина — {_money(payment.get('antidumping_rub'))}")
            if payment.get("special_duties_rub"):
                rows.append(f"специальные пошлины — {_money(payment.get('special_duties_rub'))}")
            total = payment.get("total_payable")
            lines = "\n".join(f"- {row}" for row in rows)
            total_line = f"\n\n**Итого по снимку: {_money(total)}.**" if total is not None else ""
            parts.append(
                "### Платежи\n"
                + (lines or "В снимке есть расчёт, но детализация сумм не передана.")
                + total_line
                + _citation_suffix(payment.get("citation_ids"))
            )
        else:
            parts.append(
                "### Платежи\nВ текущем контексте нет расчёта. Для суммы нужны как минимум код, "
                "таможенная стоимость и страна происхождения."
            )
            suggestions.append("Рассчитать платежи и открыть консультацию по расчёту")

    requirements = bundle.get("requirements") if isinstance(bundle.get("requirements"), dict) else None
    if intent["documents"]:
        if requirements:
            required = list(requirements.get("required_documents") or [])
            unconfirmed = list(requirements.get("unconfirmed_documents") or [])
            advisory = list(requirements.get("advisory_requirements") or [])
            lines: list[str] = []
            if required:
                rendered = []
                for row in required:
                    label = _first_nonempty(row.get("permit_type"), "разрешительный документ")
                    if row.get("tr_ts"):
                        label += f" — {row['tr_ts']}"
                    rendered.append(f"- {label}{_citation_suffix([row.get('citation_id')])}")
                lines.append("**Обязательные по текущему definite-контуру:**\n" + "\n".join(rendered))
            if unconfirmed:
                names = ", ".join(
                    _first_nonempty(row.get("permit_type"), "документ") for row in unconfirmed
                )
                lines.append(
                    "В чате не переданы номера разрешений, поэтому наличие нужно подтвердить: " + names + "."
                )
            if advisory:
                rendered = []
                for row in advisory:
                    label = _first_nonempty(row.get("permit_type"), row.get("reason"), "требование")
                    rendered.append(f"- {label}{_citation_suffix([row.get('citation_id')])}")
                lines.append(
                    "**Требует уточнения (не считается обязательным автоматически):**\n"
                    + "\n".join(rendered)
                )
            if not lines:
                lines.append(
                    requirements.get("empty_message")
                    or "В локальном контуре обязательные документы не выявлены; это не отменяет проверку характеристик."
                )
            parts.append("### Документы и нетарифные меры\n" + "\n\n".join(lines))
        else:
            parts.append("### Документы\nНетарифный контур не удалось проверить; не буду перечислять документы по памяти.")

    risk = bundle.get("risk") if isinstance(bundle.get("risk"), dict) else None
    if intent["risk"]:
        if risk:
            risk_lines = [
                f"Статус: **{risk.get('overall_severity') or 'unknown'}**."
            ]
            for signal in list(risk.get("signals") or [])[:6]:
                risk_lines.append(
                    f"- {signal.get('explanation') or signal.get('category') or 'Сигнал риска'}"
                    f"{_citation_suffix([signal.get('citation_id')])}"
                )
            if not risk.get("signals"):
                risk_lines.append(
                    "Явные совпадения в доступных локальных источниках не найдены, но это не означает «риска нет»."
                )
            unchecked = [
                row.get("label") or row.get("code")
                for row in list(risk.get("screening_scope") or [])
                if row.get("status") != "checked"
            ]
            if unchecked:
                risk_lines.append("Не проверено: " + ", ".join(str(value) for value in unchecked if value) + ".")
            if not risk.get("coverage_complete"):
                risk_lines.append("Покрытие источников неполное — требуется ручная проверка.")
            coverage_ids = [row.get("citation_id") for row in list(risk.get("source_coverage") or [])[:6]]
            parts.append("### Риски\n" + "\n".join(risk_lines) + _citation_suffix(coverage_ids))
        else:
            parts.append("### Риски\nРиск-контур временно недоступен; результат нельзя считать проверкой на отсутствие риска.")

    suggestions.extend(
        [
            "Какие характеристики нужны для подтверждения кода?",
            "Какие документы нужно запросить у поставщика?",
            "Что в этой проверке осталось неподтверждённым?",
        ]
    )
    return "\n\n".join(parts), list(dict.fromkeys(suggestions))


def build_copilot_deterministic_summary(context: dict[str, Any]) -> dict[str, Any]:
    """Create a useful copilot response before/without any LLM call."""
    positions = context.get("positions") if isinstance(context.get("positions"), list) else None
    rows = positions or [context]
    citations = _CitationCollector()
    summaries: list[str] = []
    risks: list[str] = []
    next_steps: list[str] = []
    classification_notes: list[str] = []
    payment_notes: list[str] = []
    document_notes: list[str] = []
    ntm_notes: list[str] = []
    facts_used: list[str] = []

    for idx, row in enumerate(rows[:50], start=1):
        if not isinstance(row, dict):
            continue
        hs = _digits(row.get("effective_hs_code"))
        prefix = f"Позиция {idx}: " if positions else ""
        tnved = row.get("tnved_from_db") if isinstance(row.get("tnved_from_db"), dict) else {}
        eec_id = citations.add(
            source_id="eec_ett",
            title="ТН ВЭД ЕАЭС и Единый таможенный тариф — ЕЭК",
            kind="official",
            url=_trim(tnved.get("official_ett_url"), 600)
            or "https://eec.eaeunion.org/comission/department/catr/ett/",
            status=_first_nonempty(tnved.get("source_revision"), "reference"),
            excerpt=_first_nonempty(tnved.get("title"), tnved.get("description_excerpt")) or None,
        )
        title = _first_nonempty(tnved.get("title"), row.get("description"))
        summaries.append(
            f"{prefix}`{hs or 'код не определён'}`"
            + (f" — {title}" if title else "")
            + _citation_suffix([eec_id] if hs else [])
        )
        if hs:
            facts_used.append("tnved")
            classification_notes.append(
                f"{prefix}код {hs} используется как рабочий; соответствие описанию требует проверки характеристик по ОПИ."
            )
        else:
            classification_notes.append(f"{prefix}код не определён.")
            next_steps.append(f"{prefix}уточнить характеристики и определить код ТН ВЭД.")

        payment = row.get("payment_summary") if isinstance(row.get("payment_summary"), dict) else None
        if payment:
            facts_used.append("payments")
            pay_id = citations.add(
                source_id=f"calculator_snapshot_{idx}" if positions else "calculator_snapshot",
                title=f"Расчёт платежей Tariff — позиция {idx}" if positions else "Расчёт платежей Tariff",
                kind="calculation",
                status=_first_nonempty(payment.get("status"), "calculated"),
                excerpt=(
                    f"пошлина={payment.get('duty')}; НДС={payment.get('vat')}; "
                    f"итого={payment.get('total_payable')}"
                ),
            )
            payment_source_ids: list[str] = []
            for source in list(payment.get("sources") or [])[:8]:
                if not isinstance(source, dict):
                    continue
                title = _first_nonempty(source.get("name"), "Источник расчёта")
                payment_source_ids.append(
                    citations.add(
                        source_id=_first_nonempty(source.get("source_code"), source.get("name"), "payment_source"),
                        title=title,
                        kind="official" if "ЕАЭС" in title or "НК РФ" in title else "local_registry",
                        url=_trim(source.get("url"), 600) or None,
                        status=_first_nonempty(source.get("revision"), "integrated"),
                        excerpt=_trim(source.get("data_info"), 420) or None,
                    )
                )
            payment_notes.append(
                f"{prefix}итого {_money(payment.get('total_payable'))}, "
                f"пошлина {_money(payment.get('duty'))}, НДС {_money(payment.get('vat'))}"
                f"{_citation_suffix([pay_id, *payment_source_ids])}."
            )
            quality = payment.get("data_quality") if isinstance(payment.get("data_quality"), dict) else {}
            if str(quality.get("confidence") or "").lower() in {"low", "none"}:
                risks.append(f"{prefix}низкая уверенность совпадения ставки — нужна ручная проверка.")
            if str(quality.get("antidumping_status") or "").lower() == "manual_review":
                risks.append(f"{prefix}антидемпинговая мера требует ручной проверки.")

        normative = row.get("normative_requirements") if isinstance(row.get("normative_requirements"), dict) else {}
        if normative:
            facts_used.append("requirements")
        required = list(normative.get("required_documents") or [])
        missing = list(normative.get("missing_documents") or [])
        advisory = list(normative.get("advisory_requirements") or [])
        if required:
            labels = []
            for doc in required[:10]:
                if not isinstance(doc, dict):
                    continue
                source_id = _first_nonempty(doc.get("source"), "normative_rules")
                cite_id = citations.add(
                    source_id=source_id,
                    title=_first_nonempty(doc.get("source_label"), source_id),
                    status=_first_nonempty(doc.get("applicability"), "definite"),
                    excerpt=_first_nonempty(doc.get("reason"), doc.get("note")) or None,
                )
                labels.append(
                    _first_nonempty(doc.get("permit_type"), "документ") + _citation_suffix([cite_id])
                )
            document_notes.append(f"{prefix}обязательные документы: " + ", ".join(labels) + ".")
        elif hs:
            document_notes.append(
                f"{prefix}в текущем definite-контуре обязательные документы не выявлены; характеристики нужно уточнить."
            )
        if missing:
            missing_names = ", ".join(
                _first_nonempty(doc.get("permit_type"), "документ")
                for doc in missing[:10]
                if isinstance(doc, dict)
            )
            risks.append(f"{prefix}не подтверждено наличие документов: {missing_names}.")
            next_steps.append(f"{prefix}запросить и проверить номера разрешительных документов.")
        if advisory:
            ntm_notes.append(
                f"{prefix}{len(advisory)} требований имеют статус possible/needs_clarification и не считаются обязательными автоматически."
            )

        risk = row.get("risk_summary") if isinstance(row.get("risk_summary"), dict) else {}
        if risk:
            facts_used.append("risk")
            risk_citation_ids: list[str] = []
            for source in list(risk.get("source_coverage") or [])[:10]:
                if not isinstance(source, dict):
                    continue
                risk_citation_ids.append(
                    citations.add(
                        source_id=_first_nonempty(source.get("source_id"), "risk_coverage"),
                        title=_first_nonempty(source.get("title"), source.get("source_id"), "Источник риск-скрининга"),
                        url=_trim(source.get("source_url"), 600) or None,
                        status=_first_nonempty(source.get("coverage_status"), "unknown"),
                    )
                )
            for signal in list(risk.get("signals") or [])[:10]:
                if not isinstance(signal, dict):
                    continue
                signal_id = citations.add(
                    source_id=_first_nonempty(signal.get("source"), "risk_signal"),
                    title=_first_nonempty(signal.get("source_label"), signal.get("source"), "Источник риска"),
                    url=_trim(signal.get("source_url"), 600) or None,
                    status=_first_nonempty(signal.get("severity"), "signal"),
                    excerpt=_trim(signal.get("explanation"), 420) or None,
                )
                risk_citation_ids.append(signal_id)
                risks.append(
                    f"{prefix}{_first_nonempty(signal.get('explanation'), signal.get('category'), 'сигнал риска')}"
                    f"{_citation_suffix([signal_id])}."
                )
            severity = _first_nonempty(risk.get("overall_severity"), "unknown")
            if severity not in {"clear", "low"}:
                risks.append(f"{prefix}риск-контур: {severity}{_citation_suffix(risk_citation_ids)}.")
            if not risk.get("coverage_complete"):
                risks.append(
                    f"{prefix}санкционные источники покрыты не полностью"
                    f"{_citation_suffix(risk_citation_ids)}."
                )
                next_steps.append(f"{prefix}выполнить ручной санкционный скрининг контрагента и страны.")

    if not next_steps:
        next_steps.append("Сверить характеристики товара, актуальность источников и разрешительные документы перед подачей ДТ.")

    return {
        "status": "OK",
        "summary": "\n".join(summaries) or "Проверяемые данные по позициям не переданы.",
        "classification_advice": " ".join(classification_notes),
        "payment_comment": " ".join(payment_notes) or "Расчёт платежей не выполнялся или не передан.",
        "non_tariff_comment": " ".join(ntm_notes)
        or "Possible/needs_clarification не повышают статус до обязательного требования.",
        "documents_comment": " ".join(document_notes) or "Подтверждённые требования к документам не переданы.",
        "risks": list(dict.fromkeys(risks)),
        "next_steps": list(dict.fromkeys(next_steps)),
        "citations": citations.items,
        "grounding": {
            "mode": "deterministic",
            "coverage": "grounded" if any(_digits(row.get("effective_hs_code")) for row in rows if isinstance(row, dict)) else "partial",
            "facts_used": list(dict.fromkeys(facts_used)),
            "generated_from_server_facts": True,
        },
        "note": "Фактическая сводка сформирована движком Tariff; внешняя ИИ-модель не использовалась.",
        "disclaimer": (
            "Расчёты и автоматическая проверка не заменяют юридическую экспертизу, "
            "проверку актуальной редакции источников и решение таможенного органа."
        ),
    }
