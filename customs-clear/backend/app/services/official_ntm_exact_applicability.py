"""Orchestrate bounded, fact-aware official NTM advisory evaluators.

The broad official contour remains the coverage safety net.  This module adds
explainable exact rules for the small source-backed slices that have been
curated so far, reconciles them with broad candidates, and keeps every result
outside the broker missing-document calculation.

``definite`` here means that the exact code, description and supplied
structured facts satisfy a curated rule.  It is still advisory: facts arrive
from the request, registry evidence is not fetched by this module, and every
row has ``used_for_missing_check=False``.  A separate versioned, default-OFF
bridge controls any future broker rollout.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .official_ntm_curated_enforcement import (
    collect_curated_enforcement_candidates,
)
from .official_ntm_exact_devices import evaluate_exact_device_requirements
from .official_ntm_exact_health import evaluate_exact_health_measures
from .official_ntm_exact_trade import evaluate_exact_trade_measures

EXACT_APPLICABILITY_SOURCE_KIND = "official_ntm_exact_applicability"
EXACT_APPLICABILITY_SOURCE_LABEL = "Точная применимость по официальным перечням"
EXACT_APPLICABILITY_REVISION = "bounded-curated-2026-08-15.1"

_DEVICE_LABELS = {
    "2.16": "Раздел 2.16 — радиоэлектронные и высокочастотные устройства",
    "2.19": "Раздел 2.19 — шифровальные (криптографические) средства",
}

_TRADE_DIAGNOSTIC_RULES: dict[str, dict[str, str | None]] = {
    "D30-1.2-WASTE-FROM-7204": {
        "family": "prohibitions_restrictions",
        "permit_type": "ЗАПРЕТ",
        "section": "1.2",
    },
    "D30-2.2-PESTICIDES-FROM-3808": {
        "family": "licensing",
        "permit_type": "ЛЗ/заключение",
        "section": "2.2",
    },
    "D30-2.3-WASTE-FROM-7204": {
        "family": "licensing",
        "permit_type": "ЗАКЛЮЧЕНИЕ/ЛЗ",
        "section": "2.3",
    },
    "D30-2.30-HCB-2903920000": {
        "family": "licensing",
        "permit_type": "ЛЗ/заключение",
        "section": "2.30",
    },
    "RF-EXPORT-HS-CANDIDATE": {
        "family": "export_control_dual_use",
        "permit_type": "ЛЗ/разрешение ФСТЭК",
        "section": None,
    },
}

_TRADE_RULE_LABELS = {
    "D30-1.2-WASTE-FROM-7204": "Решение №30, раздел 1.2 — опасные отходы из 7204",
    "D30-2.2-PESTICIDES-FROM-3808": "Решение №30, раздел 2.2 — средства защиты растений из 3808",
    "D30-2.3-WASTE-FROM-7204": "Решение №30, раздел 2.3 — контролируемые опасные отходы из 7204",
    "D30-2.30-HCB-2903920000": "Решение №30, раздел 2.30 — гексахлорбензол для лабораторных исследований",
    "RF-EXPORT-HS-CANDIDATE": "Контрольные списки РФ — HS-кандидат для идентификации",
    "RF-PP1284-2.1.1-AMITON": "Постановление Правительства РФ №1284, позиция 2.1.1 — амитон",
}


def _unique_strings(values: Sequence[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _exact_base(
    *,
    source: str,
    family: str,
    permit_type: str,
    applicability: str,
    outcome: str,
    rule_id: str,
    rule_name: str,
    reason: str,
    missing_facts: Sequence[Any],
    source_url: str | None,
    source_revision: str | None,
    matched_hs_scope: str | None,
) -> dict[str, Any]:
    return {
        "source": source,
        "source_kind": source,
        "source_label": EXACT_APPLICABILITY_SOURCE_LABEL,
        "family": family,
        "permit_type": permit_type,
        "tr_ts": None,
        "applicability": applicability,
        "outcome": outcome,
        "rule_id": rule_id,
        "matched_rule": rule_name,
        "matched_hs_scope": matched_hs_scope,
        "rule_name": rule_name,
        "reason": reason,
        "missing_facts": _unique_strings(list(missing_facts)),
        "source_url": source_url,
        "source_revision": source_revision or EXACT_APPLICABILITY_REVISION,
        "used_for_missing_check": False,
        "requires_manual_review": True,
        "exact_advisory": True,
        "evidence_trust": "caller_supplied_structured_facts",
        "trusted_source_verified": False,
    }


def _normalize_device_rows(
    rows: Sequence[Mapping[str, Any]],
    hs_code: str,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw in rows:
        section = str(raw.get("section") or "")
        exclusion = (
            raw.get("exclusion") if isinstance(raw.get("exclusion"), Mapping) else {}
        )
        negative = raw.get("requirement_applicable") is False
        positive = raw.get("requirement_applicable") is True
        applicability = (
            "excluded"
            if negative
            else str(raw.get("applicability") or "needs_clarification")
        )
        outcome = (
            "excluded" if negative else ("required" if positive else "pending_facts")
        )
        fallback_rule_id = (
            f"D30-{section}-EXACT-DEVICE" if section else "D30-EXACT-DEVICE"
        )
        rule_id = str(exclusion.get("rule_id") or fallback_rule_id)
        rule_name = _DEVICE_LABELS.get(section, f"Решение №30, раздел {section}")
        reason = str(exclusion.get("reason") or "")
        if not reason:
            if positive:
                reason = (
                    "По введённым данным точная строка и указанные сведения реестра "
                    "совпадают с товаром/моделью; сервис реестр не проверял."
                )
            else:
                reason = "Нужны перечисленные технические или реестровые сведения для точного вывода."
        source_urls = [str(value) for value in (raw.get("source_urls") or []) if value]
        matched_scope = (
            hs_code if raw.get("hs_scope") else "embedded-component-or-description"
        )
        item = _exact_base(
            source=str(raw.get("source_kind") or "official_ntm_exact_devices_shadow"),
            family=str(raw.get("family") or ""),
            permit_type=str(raw.get("permit_type") or ""),
            applicability=applicability,
            outcome=outcome,
            rule_id=rule_id,
            rule_name=rule_name,
            reason=reason,
            missing_facts=list(raw.get("missing_facts") or []),
            source_url=source_urls[0] if source_urls else None,
            source_revision="Decision-30/current-official-slice|observed:2026-08-15",
            matched_hs_scope=matched_scope,
        )
        item.update(
            {
                "section": section or None,
                "hs_prefix": hs_code if raw.get("hs_scope") else None,
                "direction": raw.get("direction"),
                "requirement_applicable": raw.get("requirement_applicable"),
                "required_document": raw.get("required_document"),
                "exclusion_reason": exclusion.get("reason") if negative else None,
                "evidence": list(raw.get("evidence") or []),
                "source_urls": source_urls,
                "curated_exact": bool(raw.get("curated_exact")),
                # Registry/device rows are advisory only and are deliberately
                # outside the curated enforcement allowlist.
                "eligible_for_enforcement": False,
                "enforcement_eligible": False,
            }
        )
        normalized.append(item)
    return normalized


def _normalize_health_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw in rows:
        outcome = str(raw.get("outcome") or "pending_facts")
        negative = outcome == "excluded"
        applicability = (
            "excluded"
            if negative
            else str(raw.get("applicability") or "needs_clarification")
        )
        rule_id = str(raw.get("matched_rule") or "official-health-exact")
        rule_name = str(raw.get("matched_rule_name") or rule_id)
        reason = str(raw.get("reason") or "")
        if str(raw.get("applicability") or "") == "definite" and reason:
            reason = f"По введённым данным: {reason}"
        item = _exact_base(
            source=str(
                raw.get("source")
                or raw.get("source_kind")
                or "official_ntm_exact_health"
            ),
            family=str(raw.get("family") or ""),
            permit_type=str(raw.get("permit_type") or ""),
            applicability=applicability,
            outcome=outcome,
            rule_id=rule_id,
            rule_name=rule_name,
            reason=reason,
            missing_facts=list(raw.get("missing_facts") or []),
            source_url=str(raw.get("source_url") or "") or None,
            source_revision=str(raw.get("source_revision") or "") or None,
            matched_hs_scope=str(raw.get("matched_hs_scope") or "") or None,
        )
        item.update(dict(raw))
        item.update(
            {
                "source": str(
                    raw.get("source")
                    or raw.get("source_kind")
                    or "official_ntm_exact_health"
                ),
                "source_kind": str(
                    raw.get("source_kind")
                    or raw.get("source")
                    or "official_ntm_exact_health"
                ),
                "source_label": EXACT_APPLICABILITY_SOURCE_LABEL,
                "applicability": applicability,
                "rule_id": rule_id,
                "matched_rule": rule_name,
                "matched_rule_id": rule_id,
                "rule_name": rule_name,
                "reason": reason,
                "requirement_applicable": False
                if negative
                else (True if applicability == "definite" else None),
                "used_for_missing_check": False,
                "requires_manual_review": True,
                "exact_advisory": True,
                "evidence_trust": "caller_supplied_structured_facts",
                "eligible_for_enforcement": False,
                "enforcement_eligible": False,
            }
        )
        normalized.append(item)
    return normalized


def _trade_matched_scope(raw: Mapping[str, Any]) -> str | None:
    evidence = raw.get("matched_rule")
    if isinstance(evidence, Mapping):
        hs = evidence.get("hs")
        if isinstance(hs, Mapping):
            return str(hs.get("value") or hs.get("matched_code") or "") or None
    return str(raw.get("hs_candidate_prefix") or "") or None


def _normalize_trade_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw in rows:
        missing = list(raw.get("missing_facts") or [])
        shadow = str(
            raw.get("shadow_applicability")
            or raw.get("applicability")
            or "needs_clarification"
        )
        applicability = (
            "definite"
            if shadow == "definite" and not missing
            else "needs_clarification"
        )
        rule_id = str(raw.get("rule_id") or "official-trade-exact")
        rule_name = _TRADE_RULE_LABELS.get(
            rule_id, str(raw.get("rule_name") or rule_id)
        )
        if applicability == "definite":
            reason = (
                "По введённым данным точный код, наименование и обязательные характеристики "
                "совпадают с curated-строкой. Сервис доказательства не проверял; вывод остаётся "
                "справочным."
            )
        elif raw.get("candidate_only"):
            reason = (
                "Код является справочным кандидатом. Для точного вывода нужны наименование, "
                "назначение, параметры и применимые исключения."
            )
        else:
            reason = "Для точного вывода не хватает перечисленных характеристик и доказательств."
        item = _exact_base(
            source=str(
                raw.get("source")
                or raw.get("source_kind")
                or "official_ntm_exact_trade"
            ),
            family=str(raw.get("family") or ""),
            permit_type=str(raw.get("permit_type") or ""),
            applicability=applicability,
            outcome="required" if applicability == "definite" else "pending_facts",
            rule_id=rule_id,
            rule_name=rule_name,
            reason=reason,
            missing_facts=missing,
            source_url=str(raw.get("source_url") or "") or None,
            source_revision=str(raw.get("source_revision") or "") or None,
            matched_hs_scope=_trade_matched_scope(raw),
        )
        matched_evidence = raw.get("matched_rule")
        item.update(dict(raw))
        item.update(
            {
                "source": str(
                    raw.get("source")
                    or raw.get("source_kind")
                    or "official_ntm_exact_trade"
                ),
                "source_kind": str(
                    raw.get("source_kind")
                    or raw.get("source")
                    or "official_ntm_exact_trade"
                ),
                "source_label": EXACT_APPLICABILITY_SOURCE_LABEL,
                "applicability": applicability,
                "outcome": "required"
                if applicability == "definite"
                else "pending_facts",
                "rule_id": rule_id,
                "matched_rule": rule_name,
                "matched_rule_evidence": matched_evidence
                if isinstance(matched_evidence, Mapping)
                else None,
                "matched_hs_scope": _trade_matched_scope(raw),
                "reason": reason,
                "note": str(raw.get("reason") or "") or None,
                "requirement_applicable": True if applicability == "definite" else None,
                "used_for_missing_check": False,
                "requires_manual_review": True,
                "exact_advisory": True,
                "evidence_trust": "caller_supplied_structured_facts",
                "eligible_for_enforcement": bool(raw.get("curated_allowlist_eligible")),
                "curated_enforcement_key": rule_id
                if raw.get("curated_allowlist_eligible")
                else None,
            }
        )
        normalized.append(item)
    return normalized


def _normalize_trade_diagnostics(
    diagnostics: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    exclusions: list[dict[str, Any]] = []
    for raw in diagnostics:
        kind = str(raw.get("kind") or "")
        if kind not in {
            "rule_exclusion",
            "direction_exclusion",
            "retired_export_control_code",
        }:
            continue
        rule_id = str(raw.get("rule_id") or "")
        metadata = _TRADE_DIAGNOSTIC_RULES.get(rule_id, {})
        reason = str(raw.get("reason") or "")
        if kind == "direction_exclusion":
            reason = (
                f"Правило действует для направления {raw.get('required_direction')}; "
                f"в запросе указано {raw.get('actual_direction')}."
            )
        elif kind == "rule_exclusion" and rule_id == "D30-2.2-PESTICIDES-FROM-3808":
            reason = (
                "Подпозиция 3808 94 прямо исключена из строки «из 3808» раздела 2.2."
            )
        if kind == "retired_export_control_code":
            reason = (
                f"Код не входит в закреплённый действующий срез; код замены: "
                f"{raw.get('replacement_code') or 'не указан'}."
            )
        exclusions.append(
            {
                "kind": kind,
                "rule_id": rule_id,
                "family": metadata.get("family"),
                "permit_type": metadata.get("permit_type"),
                "section": raw.get("section") or metadata.get("section"),
                "reason": reason,
                "source_url": raw.get("source_url"),
                "source_revision": raw.get("source_revision")
                or raw.get("catalog_revision"),
                "matched_hs": raw.get("matched_hs"),
                "replacement_code": raw.get("replacement_code"),
            }
        )
    return exclusions


def _diagnostic_exclusion_cards(
    exclusions: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for raw in exclusions:
        family = str(raw.get("family") or "")
        permit_type = str(raw.get("permit_type") or "")
        if not family or not permit_type:
            continue
        rule_id = str(raw.get("rule_id") or "official-exclusion")
        rule_name = _TRADE_RULE_LABELS.get(rule_id, f"Точное исключение: {rule_id}")
        item = _exact_base(
            source="official_ntm_exact_trade",
            family=family,
            permit_type=permit_type,
            applicability="excluded",
            outcome="excluded",
            rule_id=rule_id,
            rule_name=rule_name,
            reason=(
                "Точный отрицательный вывод относится только к указанной строке и не исключает другие меры."
            ),
            missing_facts=[],
            source_url=str(raw.get("source_url") or "") or None,
            source_revision=str(raw.get("source_revision") or "") or None,
            matched_hs_scope=str(raw.get("matched_hs") or "") or None,
        )
        item.update(
            {
                "section": raw.get("section"),
                "requirement_applicable": False,
                "exclusion_reason": raw.get("reason"),
                "eligible_for_enforcement": False,
                "enforcement_eligible": False,
            }
        )
        cards.append(item)
    return cards


def _catch_all_card(catch_all: Mapping[str, Any]) -> dict[str, Any] | None:
    status = str(catch_all.get("status") or "")
    if status in {"", "not_applicable_direction"}:
        return None
    risk = status in {"permission_review_required", "prohibited_transaction_risk"}
    missing_facts = list(catch_all.get("missing_facts") or [])
    applicability = (
        "definite" if risk and not missing_facts else "needs_clarification"
    )
    return {
        "source": "official_ntm_exact_trade",
        "source_kind": "official_ntm_exact_trade",
        "source_label": "Всеобъемлющий экспортный контроль РФ",
        "family": "export_control_dual_use",
        "permit_type": "ПРОВЕРКА СДЕЛКИ",
        "tr_ts": None,
        "applicability": applicability,
        "outcome": "transaction_risk" if risk else "screening_required",
        "rule_id": str(catch_all.get("rule_id") or "RF-183-FZ-ARTICLE-20-CATCH-ALL"),
        "matched_rule": "Статья 20 Федерального закона №183-ФЗ",
        "rule_name": "Всеобъемлющий экспортный контроль — проверка конечного использования",
        "reason": str(catch_all.get("reason") or ""),
        "missing_facts": missing_facts,
        "source_url": catch_all.get("source_url"),
        "source_revision": catch_all.get("source_revision"),
        "used_for_missing_check": False,
        "requires_manual_review": True,
        "exact_advisory": False,
        "transaction_level": True,
        "automatic_document_requirement": False,
        "recommended_action": catch_all.get("recommended_action"),
        "eligible_for_enforcement": False,
        "enforcement_eligible": False,
    }


def _localized_catch_all(catch_all: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(catch_all)
    status = str(result.get("status") or "")
    reasons = {
        "prohibited_transaction_risk": (
            "Сведения о конечном использовании указывают на риск, при котором статья 20 "
            "Федерального закона №183-ФЗ может запрещать совершение внешнеэкономической сделки."
        ),
        "permission_review_required": (
            "Сведения о конечном использовании или конечном пользователе требуют отдельной "
            "идентификации и проверки разрешительного порядка по статье 20 №183-ФЗ."
        ),
        "not_detected": (
            "Индикаторы всеобъемлющего экспортного контроля не указаны. Это не является "
            "проверкой конечного пользователя или подтверждением отсутствия риска."
        ),
        "not_applicable_direction": (
            "Transaction-level проверка статьи 20 №183-ФЗ в этом модуле относится к вывозу, "
            "а не к указанному направлению перемещения."
        ),
    }
    if status in reasons:
        result["reason"] = reasons[status]
    return result


def _same_broad_scope(
    broad: Mapping[str, Any],
    exact: Mapping[str, Any],
) -> bool:
    if broad.get("family") != exact.get("family"):
        return False
    broad_section = str(broad.get("section") or "")
    exact_section = str(exact.get("section") or "")
    if broad_section and exact_section:
        return broad_section == exact_section
    # Health rules do not use Decision-30 sections.  The exact code and same
    # document family/permit safely supersede the broader candidate row.
    if str(exact.get("source") or "").startswith("official_ntm_exact_health"):
        return str(broad.get("permit_type") or "") == str(
            exact.get("permit_type") or ""
        )
    return exact.get("family") == "export_control_dual_use"


def _reconcile_requirements(
    broad_requirements: Sequence[Mapping[str, Any]],
    exact_requirements: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    # An exact row replaces only its own broad legal scope.  Other families and
    # sections remain visible so a narrow exclusion cannot become a false
    # global negative.
    remaining_broad = [
        dict(broad)
        for broad in broad_requirements
        if not any(_same_broad_scope(broad, exact) for exact in exact_requirements)
    ]
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for row in [*exact_requirements, *remaining_broad]:
        item = dict(row)
        key = (
            str(item.get("source") or item.get("source_kind") or ""),
            str(item.get("family") or ""),
            str(item.get("permit_type") or ""),
            str(item.get("section") or ""),
            str(item.get("rule_id") or item.get("rule_name") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def evaluate_official_ntm_exact_applicability(
    hs_code: str,
    description: str,
    facts: Mapping[str, Any] | None,
    *,
    broad_requirements: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Evaluate all bounded exact slices and reconcile broad advisory rows."""

    structured_facts: Mapping[str, Any] = facts if isinstance(facts, Mapping) else {}
    if not structured_facts:
        return {
            "source_kind": EXACT_APPLICABILITY_SOURCE_KIND,
            "revision": EXACT_APPLICABILITY_REVISION,
            "requirements": [dict(row) for row in broad_requirements],
            "exact_requirements": [],
            "resolved_exclusions": [],
            "diagnostics": [],
            "catch_all": {},
            "summary": {
                "mode": "broad_candidate_only",
                "structured_fact_keys": [],
                "structured_facts_received": 0,
                "exact_rows_count": 0,
                "definite_advisory_count": 0,
                "excluded_count": 0,
                "exact_needs_clarification_count": 0,
                "missing_fact_keys": [],
                "curated_enforcement_ready_rule_ids": [],
                "broker_effect": False,
                "facts_trust_boundary": "no structured facts supplied",
            },
        }
    device_rows = _normalize_device_rows(
        evaluate_exact_device_requirements(hs_code, description, structured_facts),
        hs_code,
    )
    health_rows = _normalize_health_rows(
        evaluate_exact_health_measures(hs_code, description, structured_facts)
    )
    # Keep the evaluator's own exposure flag out of runtime semantics.  Exact
    # shadow readiness is normalized above; broker rollout has a separate flag.
    trade_result = evaluate_exact_trade_measures(
        hs_code,
        description,
        structured_facts,
        curated_allowlist_enabled=False,
    )
    trade_rows = _normalize_trade_rows(trade_result.get("rows") or [])
    resolved_exclusions = _normalize_trade_diagnostics(
        trade_result.get("diagnostics") or []
    )
    diagnostic_cards = _diagnostic_exclusion_cards(resolved_exclusions)
    catch_all = _localized_catch_all(trade_result.get("catch_all") or {})
    catch_all_card = _catch_all_card(catch_all)

    exact_requirements = [*device_rows, *health_rows, *trade_rows, *diagnostic_cards]
    if catch_all_card is not None:
        exact_requirements.append(catch_all_card)
    requirements = _reconcile_requirements(broad_requirements, exact_requirements)
    exclusion_rows = [
        row for row in exact_requirements if row.get("applicability") == "excluded"
    ]
    positive_rows = [
        row
        for row in exact_requirements
        if row.get("applicability") == "definite"
        and row.get("requirement_applicable") is not False
        and not row.get("transaction_level")
    ]
    curated_ready_rows, _curated_rejected_rows = (
        collect_curated_enforcement_candidates(positive_rows)
    )
    missing_fact_keys = sorted(
        {
            str(value)
            for row in exact_requirements
            for value in (row.get("missing_facts") or [])
            if value
        }
    )
    return {
        "source_kind": EXACT_APPLICABILITY_SOURCE_KIND,
        "revision": EXACT_APPLICABILITY_REVISION,
        "requirements": requirements,
        "exact_requirements": exact_requirements,
        "resolved_exclusions": [*exclusion_rows, *resolved_exclusions],
        "diagnostics": list(trade_result.get("diagnostics") or []),
        "catch_all": catch_all,
        "summary": {
            "mode": "broad_plus_bounded_exact_shadow",
            "structured_fact_keys": sorted(str(key) for key in structured_facts),
            "structured_facts_received": len(structured_facts),
            "exact_rows_count": len(exact_requirements),
            "definite_advisory_count": len(positive_rows),
            "excluded_count": len(exclusion_rows),
            "exact_needs_clarification_count": sum(
                row.get("applicability") == "needs_clarification"
                for row in exact_requirements
            ),
            "missing_fact_keys": missing_fact_keys,
            "curated_shadow_candidate_rule_ids": sorted(
                str(row.get("curated_enforcement_key"))
                for row in positive_rows
                if row.get("curated_enforcement_key")
            ),
            "curated_enforcement_ready_rule_ids": sorted(
                {
                    str(
                        row.get("curated_enforcement_key")
                        or row.get("rule_id")
                    )
                    for row in curated_ready_rows
                }
            ),
            "broker_effect": False,
            "facts_trust_boundary": "caller_supplied; no live registry lookup",
        },
    }


__all__ = [
    "EXACT_APPLICABILITY_REVISION",
    "EXACT_APPLICABILITY_SOURCE_KIND",
    "evaluate_official_ntm_exact_applicability",
]
