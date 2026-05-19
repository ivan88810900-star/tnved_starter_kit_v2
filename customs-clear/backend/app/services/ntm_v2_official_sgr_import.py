"""Импорт нормативного контура СГР (гос. регистрация) в NTM v2 — отдельно от legacy."""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import db
from ..datetime_util import utc_now_naive
from ..models.ntm_v2 import NtmApplicabilityRuleV2, NtmMeasureV2
from .hs_matching import normalize_hs_code
from .ntm_v2_legacy_rules_import import ADVISORY_APPLICABILITIES, advisory_reason_for_applicability

OFFICIAL_SGR_SOURCE_KIND = "official_sgr_registry"
OFFICIAL_SGR_SOURCE_REF_PREFIX = "official_sgr_registry"
OFFICIAL_SGR_SOURCE_LABEL = "Решение ЕЭК №299"
DEFAULT_SEED_PATH = Path(__file__).resolve().parents[2] / "data" / "official_sgr_rules.seed.json"

VALID_APPLICABILITIES = frozenset({"definite", "possible", "needs_clarification"})

_OFFICIAL_DEFINITE_ADVISORY_REASON = (
    "Нормативное правило СГР выявлено по официальному перечню. "
    "Автоматическое включение в обязательные документы пока не активировано."
)


def _env_truthy(name: str) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def is_ntm_v2_official_sgr_advisory_enabled() -> bool:
    """``NTM_V2_OFFICIAL_SGR_ADVISORY_ENABLED``: official SGR в ``advisory_requirements``."""
    return _env_truthy("NTM_V2_OFFICIAL_SGR_ADVISORY_ENABLED")


def should_apply_official_sgr_advisory(explicit: bool | None = None) -> bool:
    if explicit is not None:
        return explicit
    return is_ntm_v2_official_sgr_advisory_enabled()


def official_advisory_reason_for_applicability(applicability: str) -> str:
    app = (applicability or "").strip()
    if app == "definite":
        return _OFFICIAL_DEFINITE_ADVISORY_REASON
    return advisory_reason_for_applicability(app)


def _normalize_desc_markers(values: Any) -> list[str]:
    return [str(x).lower() for x in (values or []) if str(x).strip()]


def official_sgr_description_matches(
    description: str,
    *,
    description_contains_any: list[str] | None = None,
    description_requires_any: list[str] | None = None,
    exclude_if_contains_any: list[str] | None = None,
) -> bool:
    """
    Description gate для official SGR.

    - ``description_contains_any``: хотя бы один маркер категории товара (OR).
    - ``description_requires_any``: хотя бы один обязательный маркер (AND с contains).
    - ``exclude_if_contains_any``: любой маркер исключает правило.
    """
    desc_l = (description or "").lower()
    excludes = _normalize_desc_markers(exclude_if_contains_any)
    if any(x in desc_l for x in excludes if x):
        return False
    contains = _normalize_desc_markers(description_contains_any)
    requires = _normalize_desc_markers(description_requires_any)
    if requires and not any(x in desc_l for x in requires if x):
        return False
    if contains and not any(x in desc_l for x in contains if x):
        return False
    return bool(requires or contains)


def _desc_match_json(rule_row: dict[str, Any]) -> dict[str, Any] | None:
    contains = [str(x).strip() for x in (rule_row.get("description_contains_any") or []) if str(x).strip()]
    requires = [str(x).strip() for x in (rule_row.get("description_requires_any") or []) if str(x).strip()]
    excludes = [str(x).strip() for x in (rule_row.get("exclude_if_contains_any") or []) if str(x).strip()]
    if not contains and not requires and not excludes:
        return None
    payload: dict[str, Any] = {"mode": "official_sgr"}
    if contains:
        payload["description_contains_any"] = contains
        payload["mode"] = "any_substring"
        payload["substrings"] = contains
    if requires:
        payload["description_requires_any"] = requires
        payload["mode"] = "official_sgr_and"
    if excludes:
        payload["exclude_if_contains_any"] = excludes
    payload["official_payload"] = {
        "evidence": str(rule_row.get("evidence") or "")[:500],
        "rule_id": str(rule_row.get("rule_id") or ""),
        "title": str(rule_row.get("title") or "")[:300],
    }
    return payload


def _measure_import_key() -> str:
    return f"{OFFICIAL_SGR_SOURCE_KIND}|sgr|СГР"


def _rule_import_key(rule_id: str) -> str:
    return f"{OFFICIAL_SGR_SOURCE_KIND}|rule:{rule_id}"


def load_official_sgr_payload(path: Path | None = None) -> dict[str, Any]:
    p = path or DEFAULT_SEED_PATH
    raw = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "rules" not in raw:
        raise ValueError("official SGR payload must be object with 'rules' array")
    return raw


def import_official_sgr_rules_to_ntm_v2(
    payload: dict[str, Any] | None = None,
    session: Session | None = None,
    *,
    seed_path: Path | None = None,
) -> dict[str, Any]:
    """
    Идемпотентный импорт official SGR rules → ``ntm_measures_v2`` + ``ntm_applicability_rules_v2``.

    Не затрагивает legacy ``source_kind`` и не подключается к production broker.
    """
    data = payload if payload is not None else load_official_sgr_payload(seed_path)
    rules_in = data.get("rules") or []
    source_document = str(data.get("source_document") or "official_sgr_registry")
    source_revision = str(data.get("source_revision") or "")
    source_url = str(data.get("source_url") or "")

    close_session = False
    if session is None:
        session = db.SessionLocal()
        close_session = True
    now = utc_now_naive()
    measures_created = 0
    rules_created = 0
    rules_updated = 0
    rules_skipped = 0
    rules_invalid = 0

    try:
        mik = _measure_import_key()
        measure = session.scalar(select(NtmMeasureV2).where(NtmMeasureV2.import_key == mik))
        if measure is None:
            measure = NtmMeasureV2(
                measure_kind="sgr",
                permit_type="СГР",
                title="Государственная регистрация продукции (официальный контур)",
                short_description=json.dumps(
                    {"legal_ref": source_document, "source_revision": source_revision},
                    ensure_ascii=False,
                ),
                tr_ts_act_code="",
                regulatory_document_id="EEC-299",
                valid_from=None,
                valid_to=None,
                status="active",
                source_kind=OFFICIAL_SGR_SOURCE_KIND,
                source_ref=source_url or OFFICIAL_SGR_SOURCE_REF_PREFIX,
                import_key=mik,
                created_at=now,
                updated_at=now,
            )
            session.add(measure)
            session.flush()
            measures_created = 1
        else:
            measure.title = "Государственная регистрация продукции (официальный контур)"
            measure.regulatory_document_id = measure.regulatory_document_id or "EEC-299"
            measure.updated_at = now

        for row in rules_in:
            if not isinstance(row, dict):
                rules_invalid += 1
                continue
            rule_id = str(row.get("rule_id") or "").strip()
            if not rule_id:
                rules_invalid += 1
                continue
            app = str(row.get("applicability") or "possible").strip()
            if app not in VALID_APPLICABILITIES:
                rules_invalid += 1
                continue

            hs_scope = normalize_hs_code(str(row.get("hs_scope") or ""))
            hs_mode = str(row.get("hs_scope_mode") or "prefix").strip() or "prefix"
            desc_json = _desc_match_json(row)
            rk = _rule_import_key(rule_id)
            existing = session.scalar(
                select(NtmApplicabilityRuleV2).where(NtmApplicabilityRuleV2.rule_import_key == rk)
            )
            requires_review = bool(row.get("requires_manual_review", app != "definite"))
            priority = int(row.get("priority") or 0)

            if existing is None:
                session.add(
                    NtmApplicabilityRuleV2(
                        measure_id=measure.id,
                        direction="import",
                        country_iso=None,
                        hs_scope_mode=hs_mode,
                        hs_code=hs_scope,
                        excluded_hs_json=None,
                        description_match_json=desc_json,
                        applicability=app,
                        requires_manual_review=requires_review,
                        priority=priority,
                        valid_from=None,
                        valid_to=None,
                        source_kind=OFFICIAL_SGR_SOURCE_KIND,
                        source_ref=f"{OFFICIAL_SGR_SOURCE_REF_PREFIX}:{rule_id}",
                        rule_import_key=rk,
                        created_at=now,
                        updated_at=now,
                    )
                )
                rules_created += 1
            else:
                existing.measure_id = measure.id
                existing.hs_scope_mode = hs_mode
                existing.hs_code = hs_scope
                existing.description_match_json = desc_json
                existing.applicability = app
                existing.requires_manual_review = requires_review
                existing.priority = priority
                existing.source_ref = f"{OFFICIAL_SGR_SOURCE_REF_PREFIX}:{rule_id}"
                existing.updated_at = now
                rules_updated += 1
                rules_skipped += 1

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        if close_session:
            session.close()

    return {
        "source_document": source_document,
        "source_revision": source_revision,
        "rules_in_payload": len(rules_in),
        "rules_invalid": rules_invalid,
        "measures_created": measures_created,
        "rules_created": rules_created,
        "rules_updated": rules_updated,
        "rules_skipped_duplicates": rules_skipped,
        "source_kind": OFFICIAL_SGR_SOURCE_KIND,
    }


def official_sgr_seed_rule_matches_position(
    row: dict[str, Any],
    hs_code: str,
    description: str = "",
) -> bool:
    """Матчинг правила из seed JSON (без БД) — та же семантика, что ``official_sgr_rule_matches_position``."""
    hs_scope = normalize_hs_code(str(row.get("hs_scope") or ""))
    hs_mode = str(row.get("hs_scope_mode") or "prefix").strip() or "prefix"
    norm = normalize_hs_code(hs_code)
    desc_l = (description or "").lower()
    contains = row.get("description_contains_any")
    requires = row.get("description_requires_any")
    excludes = row.get("exclude_if_contains_any")
    has_desc_gate = bool(_normalize_desc_markers(contains) or _normalize_desc_markers(requires) or _normalize_desc_markers(excludes))

    if hs_mode == "description_only":
        return official_sgr_description_matches(
            description,
            description_contains_any=contains if isinstance(contains, list) else None,
            description_requires_any=requires if isinstance(requires, list) else None,
            exclude_if_contains_any=excludes if isinstance(excludes, list) else None,
        )

    if not norm:
        return False
    if hs_mode == "exact" and hs_scope and norm != hs_scope:
        return False
    if hs_scope and not norm.startswith(hs_scope):
        return False
    if has_desc_gate:
        return official_sgr_description_matches(
            description,
            description_contains_any=contains if isinstance(contains, list) else None,
            description_requires_any=requires if isinstance(requires, list) else None,
            exclude_if_contains_any=excludes if isinstance(excludes, list) else None,
        )
    return bool(hs_scope)


def evaluate_official_sgr_from_seed_payload(
    payload: dict[str, Any],
    hs_code: str,
    description: str = "",
) -> dict[str, Any]:
    """Оценка позиции по правилам seed (без импорта в БД)."""
    matched: list[dict[str, Any]] = []
    for row in payload.get("rules") or []:
        if not isinstance(row, dict):
            continue
        if not official_sgr_seed_rule_matches_position(row, hs_code, description):
            continue
        app = str(row.get("applicability") or "").strip()
        matched.append(
            {
                "rule_id": row.get("rule_id"),
                "applicability": app,
                "hs_prefix": normalize_hs_code(str(row.get("hs_scope") or "")) or None,
                "title": row.get("title"),
                "category": row.get("category"),
            }
        )
    definite = [m for m in matched if m.get("applicability") == "definite"]
    advisory = [m for m in matched if m.get("applicability") in ADVISORY_APPLICABILITIES]
    return {
        "matched_rules": matched,
        "has_definite_sgr": bool(definite),
        "has_advisory_sgr": bool(advisory),
        "definite_rules": definite,
        "advisory_rules": advisory,
    }


def official_sgr_rule_matches_position(
    rule: NtmApplicabilityRuleV2,
    hs_code: str,
    description: str = "",
    *,
    as_of: date | None = None,
) -> bool:
    """Runtime-матчинг official SGR rule (без записи в broker)."""
    from .ntm_engine_v2 import _rule_and_measure_active, _rule_hs_matches

    ref = as_of or date.today()
    if rule.source_kind != OFFICIAL_SGR_SOURCE_KIND:
        return False
    if not _rule_and_measure_active(rule, ref):
        return False
    norm = normalize_hs_code(hs_code)
    if not norm:
        return False
    if not _rule_hs_matches(norm, rule):
        return False

    dm = rule.description_match_json if isinstance(rule.description_match_json, dict) else {}
    contains = dm.get("description_contains_any") or dm.get("substrings")
    requires = dm.get("description_requires_any")
    excludes = dm.get("exclude_if_contains_any")
    has_desc_gate = bool(
        _normalize_desc_markers(contains)
        or _normalize_desc_markers(requires)
        or _normalize_desc_markers(excludes)
    )
    hp = normalize_hs_code(rule.hs_code)
    if has_desc_gate:
        return official_sgr_description_matches(
            description,
            description_contains_any=contains if isinstance(contains, list) else None,
            description_requires_any=requires if isinstance(requires, list) else None,
            exclude_if_contains_any=excludes if isinstance(excludes, list) else None,
        )
    if hp:
        return True
    return False


def get_advisory_official_sgr_requirements_v2(
    hs_code: str,
    description: str = "",
    *,
    as_of: date | None = None,
) -> list[dict[str, Any]]:
    """
    Advisory items из ``official_sgr_registry`` (все applicability, без broker).

    ``used_for_missing_check`` всегда ``False``, в т.ч. для ``definite``.
    """
    ev = evaluate_official_sgr_for_position(hs_code, description, as_of=as_of)
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None, str, str]] = set()
    for m in ev.get("matched_rules") or []:
        app = str(m.get("applicability") or "").strip()
        if app not in VALID_APPLICABILITIES:
            continue
        pt = str(m.get("permit_type") or "СГР").strip()
        tr_ts: str | None = None
        dedup = (pt, tr_ts, app, str(m.get("rule_import_key") or ""))
        if dedup in seen:
            continue
        seen.add(dedup)
        title = str(m.get("title") or "").strip()
        evidence = str(m.get("evidence") or "").strip()
        rows.append(
            {
                "permit_type": pt,
                "tr_ts": tr_ts,
                "applicability": app,
                "source": OFFICIAL_SGR_SOURCE_KIND,
                "source_label": OFFICIAL_SGR_SOURCE_LABEL,
                "used_for_missing_check": False,
                "requires_manual_review": bool(m.get("requires_manual_review")),
                "hs_prefix": m.get("hs_prefix"),
                "rule_name": title[:200] if title else None,
                "reason": official_advisory_reason_for_applicability(app),
                "note": evidence[:500] if evidence else None,
            }
        )
    return rows


def _advisory_exact_key(item: dict[str, Any]) -> tuple[str, str | None, str, str, str, str]:
    return (
        str(item.get("source") or ""),
        str(item.get("permit_type") or ""),
        item.get("tr_ts"),
        str(item.get("applicability") or ""),
        str(item.get("hs_prefix") or ""),
        str(item.get("rule_name") or "")[:120],
    )


def _advisory_soft_key(item: dict[str, Any]) -> tuple[str, str | None, str]:
    """Ключ для приоритета official над legacy (без source/rule_name)."""
    return (
        str(item.get("permit_type") or ""),
        item.get("tr_ts"),
        str(item.get("applicability") or ""),
    )


def merge_advisory_legacy_and_official(
    legacy_items: list[dict[str, Any]],
    official_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Official первым; legacy ниже, если не exact-duplicate и не вытеснён soft-key.
    """
    out: list[dict[str, Any]] = []
    seen_exact: set[tuple[str, str | None, str, str, str, str]] = set()
    official_soft: set[tuple[str, str | None, str]] = set()

    for item in official_items:
        ek = _advisory_exact_key(item)
        if ek in seen_exact:
            continue
        seen_exact.add(ek)
        official_soft.add(_advisory_soft_key(item))
        out.append(dict(item))

    for item in legacy_items:
        ek = _advisory_exact_key(item)
        if ek in seen_exact:
            continue
        if _advisory_soft_key(item) in official_soft:
            continue
        seen_exact.add(ek)
        out.append(dict(item))

    return out


def evaluate_official_sgr_for_position(
    hs_code: str,
    description: str = "",
    *,
    as_of: date | None = None,
    session: Session | None = None,
) -> dict[str, Any]:
    """Сводка official SGR по позиции: definite / advisory / matched rules."""
    ref = as_of or date.today()
    close = False
    if session is None:
        session = db.SessionLocal()
        close = True
    matched: list[dict[str, Any]] = []
    try:
        stmt = (
            select(NtmApplicabilityRuleV2)
            .join(NtmMeasureV2, NtmApplicabilityRuleV2.measure_id == NtmMeasureV2.id)
            .where(
                NtmApplicabilityRuleV2.source_kind == OFFICIAL_SGR_SOURCE_KIND,
                NtmMeasureV2.source_kind == OFFICIAL_SGR_SOURCE_KIND,
            )
        )
        for rule in session.scalars(stmt).unique().all():
            if not official_sgr_rule_matches_position(rule, hs_code, description, as_of=ref):
                continue
            dm = rule.description_match_json if isinstance(rule.description_match_json, dict) else {}
            op = dm.get("official_payload") if isinstance(dm.get("official_payload"), dict) else {}
            matched.append(
                {
                    "v2_rule_id": rule.id,
                    "rule_import_key": rule.rule_import_key,
                    "hs_prefix": rule.hs_code or None,
                    "permit_type": "СГР",
                    "applicability": rule.applicability,
                    "requires_manual_review": rule.requires_manual_review,
                    "title": op.get("title") or rule.source_ref,
                    "evidence": op.get("evidence"),
                    "used_for_missing_check": rule.applicability == "definite",
                }
            )
    finally:
        if close:
            session.close()

    definite = [m for m in matched if m["applicability"] == "definite"]
    advisory = [m for m in matched if m["applicability"] in ADVISORY_APPLICABILITIES]
    return {
        "hs_code": normalize_hs_code(hs_code),
        "description": description,
        "matched_rules": matched,
        "has_definite_sgr": bool(definite),
        "has_advisory_sgr": bool(advisory),
        "definite_rules": definite,
        "advisory_rules": advisory,
    }
