"""Данные для продуктовой карточки ТН ВЭД: предварительные решения по коду."""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from ..models.core import ClassificationDecision, PreliminaryDecision
from .tree_engine import CanonicalModel, get_canonical_model

_DIGITS_RE = re.compile(r"\D")
logger = logging.getLogger(__name__)


def _digits(raw: str) -> str:
    return _DIGITS_RE.sub("", raw or "")


def hs_prefix_candidates(hs_code: str) -> list[str]:
    """Префиксы от точного 10-значного кода до 4-значной группы."""
    d = _digits(hs_code)
    if len(d) < 4:
        return []
    out: list[str] = []
    if len(d) >= 10:
        out.append(d[:10])
    if len(d) >= 6:
        out.append(d[:6])
    if len(d) >= 4:
        out.append(d[:4])
    return list(dict.fromkeys(out))


def canonical_anchor_for_hs(
    hs_code: str,
    *,
    model: CanonicalModel | None = None,
) -> dict[str, Any] | None:
    """Resolve an additive Canonical anchor without changing legacy card behavior.

    A supplied model makes the resolver cheap for batch/search callers and directly
    testable. Without one, the shared provider is used. Provider/build failures are a
    soft miss: search and code-card endpoints must keep their existing DB fallback.
    """
    code = _digits(hs_code)
    if len(code) not in (4, 6, 8, 10):
        return None
    if model is None:
        try:
            model = get_canonical_model()
        except Exception:  # noqa: BLE001 — additive bridge must not break legacy card
            logger.exception("Canonical anchor unavailable for TN VED code=%r", hs_code)
            return None
    if model is None:
        return None

    node = model.get_by_code(code) or model.get_by_display_code(code)
    if node is None:
        return None
    anchor = model.anchor(node)
    if anchor is None:
        return None
    return {
        "stable_id": anchor.stable_id,
        "snapshot_id": anchor.snapshot_id,
        "code": anchor.code,
        "node_type": anchor.node_type.value,
    }


def canonical_anchors_for_hs_codes(hs_codes: list[str]) -> dict[str, dict[str, Any]]:
    """Resolve many search hits against one shared Canonical snapshot."""
    if not hs_codes:
        return {}
    try:
        model = get_canonical_model()
    except Exception:  # noqa: BLE001 — search remains available through legacy/FTS
        logger.exception("Canonical anchors unavailable for TN VED search")
        return {}
    if model is None:
        return {}

    resolved: dict[str, dict[str, Any]] = {}
    for raw in hs_codes:
        code = _digits(raw)
        anchor = canonical_anchor_for_hs(code, model=model)
        if anchor is not None:
            resolved[code] = anchor
    return resolved


def _serialize_classification(row: ClassificationDecision) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": "classification",
        "hs_code": (row.hs_code or "").strip(),
        "decision_number": (row.decision_number or "").strip(),
        "issue_date": (row.issue_date or "").strip(),
        "product_name": (row.product_name or "").strip(),
        "target_entity": (row.target_entity or "").strip(),
        "description": (row.description or "").strip(),
        "source": "fts",
    }


def _serialize_preliminary(row: PreliminaryDecision) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": "preliminary",
        "hs_code": (row.hs_code or "").strip(),
        "description": (row.description or "").strip(),
        "source": (row.source or "ifcg").strip() or "ifcg",
    }


def find_preliminary_decisions_for_hs(
    db: Session,
    hs_code: str,
    *,
    classification_limit: int = 10,
    preliminary_limit: int = 10,
) -> dict[str, Any]:
    """
    Предварительные / классификационные решения по префиксу кода ТН ВЭД.
    Возвращает две группы: официальные решения ФТС и прочие (IFCG и др.).
    """
    prefixes = hs_prefix_candidates(hs_code)
    if not prefixes:
        return {
            "classification_decisions": [],
            "preliminary_decisions": [],
            "total_count": 0,
            "empty_message": "Укажите код ТН ВЭД из 4 или 10 цифр для поиска решений.",
        }

    cls_limit = max(1, min(classification_limit, 30))
    prelim_limit = max(1, min(preliminary_limit, 30))

    classification: list[dict[str, Any]] = []
    seen_cls: set[int] = set()
    for pref in prefixes:
        if len(classification) >= cls_limit:
            break
        rows = (
            db.query(ClassificationDecision)
            .filter(ClassificationDecision.hs_code.like(f"{pref}%"))
            .order_by(ClassificationDecision.issue_date.desc(), ClassificationDecision.id.desc())
            .limit(cls_limit)
            .all()
        )
        for row in rows:
            if row.id in seen_cls:
                continue
            seen_cls.add(row.id)
            classification.append(_serialize_classification(row))
            if len(classification) >= cls_limit:
                break

    preliminary: list[dict[str, Any]] = []
    seen_pre: set[int] = set()
    for pref in prefixes:
        if len(preliminary) >= prelim_limit:
            break
        rows = (
            db.query(PreliminaryDecision)
            .filter(PreliminaryDecision.hs_code.like(f"{pref}%"))
            .order_by(PreliminaryDecision.id.desc())
            .limit(prelim_limit)
            .all()
        )
        for row in rows:
            if row.id in seen_pre:
                continue
            seen_pre.add(row.id)
            preliminary.append(_serialize_preliminary(row))
            if len(preliminary) >= prelim_limit:
                break

    total = len(classification) + len(preliminary)
    empty_message = (
        "По этому коду предварительные решения в базе не найдены. "
        "Импортируйте датасет решений ФТС или синхронизируйте IFCG."
        if total == 0
        else ""
    )

    return {
        "classification_decisions": classification,
        "preliminary_decisions": preliminary,
        "total_count": total,
        "empty_message": empty_message,
    }
