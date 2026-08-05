"""Пользовательский «умный маршрут» по одной позиции ТН ВЭД.

Сервис объединяет два контура, не смешивая их ответственность:

* ``CanonicalModel`` остаётся единственной истиной структуры и реальных кодов;
* ``SemanticNavigationBuilder`` извлекает только бескодовые смысловые подсказки
  из официальных описаний ``tnved_commodities``.

Если смысловой слой нельзя полностью привязать к текущему Canonical snapshot,
сервис не отдаёт частичное дерево: клиент получает безопасный ``DEGRADED`` и
ссылку на обычный каталог. Canonical feature flags при этом не читаются и не
изменяются — endpoint является отдельным additive read-only контуром.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from collections import Counter
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from .semantic_navigation import (
    SemanticNavigationBuilder,
    SemanticNavigationTree,
    SemanticNavigationValidator,
    SemanticNode,
    SemanticNodeType,
    SourceRecord,
)
from .tree_engine import CanonicalModel, get_canonical_model

logger = logging.getLogger(__name__)

_DIGITS_RE = re.compile(r"\D")
_GUIDE_ID_VERSION = "guided-tnved-v1"


def _digits(raw: str) -> str:
    return _DIGITS_RE.sub("", raw or "")


def _identity_text(raw: str) -> str:
    return " ".join(unicodedata.normalize("NFC", raw or "").casefold().split())


def _guide_id(path: tuple[tuple[str, str, int], ...]) -> str:
    encoded = json.dumps(
        (_GUIDE_ID_VERSION, path),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"guide-{hashlib.sha1(encoded).hexdigest()[:24]}"


class GuidedTnvedNavigationService:
    """Строит объяснимый и проверяемый маршрут внутри 4-значной позиции."""

    def __init__(
        self,
        *,
        builder: SemanticNavigationBuilder | None = None,
        validator: SemanticNavigationValidator | None = None,
        model_loader: Callable[[], CanonicalModel | None] = get_canonical_model,
    ) -> None:
        self.builder = builder or SemanticNavigationBuilder()
        self.validator = validator or SemanticNavigationValidator()
        self.model_loader = model_loader

    def build(self, db: Session, heading: str) -> dict[str, Any]:
        heading4 = _digits(heading)
        if len(heading4) != 4:
            raise ValueError("heading must contain exactly 4 digits")
        # Kept for the stable service/API signature; runtime source is the model.
        _ = db

        try:
            model = self.model_loader()
        except Exception:  # обычное дерево должно остаться доступным
            logger.exception(
                "Guided TN VED: CanonicalModel unavailable for heading=%s",
                heading4,
            )
            return self._degraded(heading4, "canonical_model_unavailable")
        if model is None:
            return self._degraded(heading4, "canonical_model_unavailable")

        canonical_heading = (
            model.get_by_code(heading4)
            or model.get_by_display_code(heading4)
        )
        if canonical_heading is None:
            return self._degraded(
                heading4,
                "heading_not_found_in_canonical",
                snapshot_id=model.snapshot_id,
            )

        canonical_source_records = model.source_records_for_heading(heading4)
        if not canonical_source_records:
            logger.warning(
                "Guided TN VED: Canonical source records unavailable for "
                "heading=%s snapshot=%s",
                heading4,
                model.snapshot_id,
            )
            return self._degraded(
                heading4,
                "canonical_source_records_unavailable",
                snapshot_id=model.snapshot_id,
            )

        source_records: list[SourceRecord] = []
        for record in canonical_source_records:
            source_records.append(
                SourceRecord(
                    code=record.code,
                    description=record.description,
                    import_duty=record.import_duty,
                    is_leaf=record.is_leaf,
                    parent_code=record.parent_code,
                )
            )
        try:
            tree = self.builder.build_heading_from_records(heading4, source_records)
        except Exception:  # additive UX не должен ломать каталог
            logger.exception(
                "Guided TN VED: semantic overlay failed for heading=%s",
                heading4,
            )
            return self._degraded(
                heading4,
                "semantic_overlay_unavailable",
                snapshot_id=model.snapshot_id,
            )

        pruned_empty_groups = self._prune_empty_groups(tree)
        canonical_nodes, missing_codes = self._bind_to_canonical(tree, model)
        validation = self.validator.validate(
            tree,
            db_codes=tree.expected_real_codes,
        )
        critical_codes = sorted(
            {issue.code for issue in validation.critical_issues}
        )
        if missing_codes:
            critical_codes.append("canonical_binding_missing")

        if critical_codes:
            logger.warning(
                "Guided TN VED rejected for heading=%s snapshot=%s "
                "critical=%s missing_codes=%s",
                heading4,
                model.snapshot_id,
                sorted(set(critical_codes)),
                len(missing_codes),
            )
            return self._degraded(
                heading4,
                "integrity_gate_failed",
                snapshot_id=model.snapshot_id,
                integrity={
                    "complete": False,
                    "critical_issues": sorted(set(critical_codes)),
                    "missing_canonical_codes": len(missing_codes),
                },
            )

        choices = [
            self._serialize_node(child, model, canonical_nodes)
            for child in tree.root.children
        ]
        real_expected = set(tree.expected_real_codes) - {heading4}
        real_reachable = set(tree.real_codes_in_tree()) - {heading4}
        code_nodes = [
            node
            for node in tree.all_nodes()
            if node.code and node.code != heading4 and node.carries_real_code
        ]
        declarable_leaf_codes = {
            str(node.code)
            for node in code_nodes
            if node.node_type == SemanticNodeType.LEAF
        }
        canonical_leaf_evidence = {
            str(node.code)
            for node in code_nodes
            if node.metadata.get("leaf_evidence") is True
        }
        semantic_nodes = [
            node
            for node in tree.all_nodes()
            if node.node_type
            in {
                SemanticNodeType.CLASSIFICATION_GROUP,
                SemanticNodeType.CLASSIFICATION_SUBGROUP,
            }
        ]
        semantic_subgroup_count = sum(
            node.node_type == SemanticNodeType.CLASSIFICATION_SUBGROUP
            for node in semantic_nodes
        )

        def semantic_depth(node: SemanticNode, current: int = 0) -> int:
            level = current + int(
                node.node_type
                in {
                    SemanticNodeType.CLASSIFICATION_GROUP,
                    SemanticNodeType.CLASSIFICATION_SUBGROUP,
                }
            )
            return max(
                [level]
                + [semantic_depth(child, level) for child in node.children]
            )

        heading_anchor = self._anchor_payload(model, canonical_heading)
        return {
            "status": "OK",
            "engine": {
                "name": "guided_tnved",
                "version": "v1",
                "mode": "canonical_semantic_overlay",
                "snapshot_id": model.snapshot_id,
            },
            "heading": {
                "code": heading4,
                "title": tree.root.title or canonical_heading.title,
                "canonical_anchor": heading_anchor,
            },
            "prompt": (
                "Какой вид товара ближе всего? Выберите смысловую группу, "
                "затем уточняйте до реального кода ТН ВЭД."
            ),
            "choices": choices,
            "integrity": {
                "complete": True,
                "expected_real_codes": len(real_expected),
                "reachable_real_codes": len(real_reachable),
                "canonical_bound_codes": len(real_expected),
                "source_code_nodes": len(real_expected),
                "reachable_source_code_nodes": len(real_reachable),
                "canonical_declarable_leaves": len(canonical_leaf_evidence),
                "declarable_leaf_codes": len(declarable_leaf_codes),
                "canonical_coverage": 1.0,
                "fake_codes": 0,
                "critical_issues": [],
                "semantic_groups": len(semantic_nodes),
                "semantic_subgroups": semantic_subgroup_count,
                "semantic_max_depth": semantic_depth(tree.root),
                "nesting_fallbacks": len(tree.nesting_fallbacks),
                "rejected_unsafe_groups": len(tree.rejected_candidates),
                "pruned_empty_groups": pruned_empty_groups,
            },
            "explanation": {
                "structure_source": "CanonicalModel",
                "semantic_source": "official_tnved_descriptions",
                "groups_have_codes": False,
                "final_choices_are_real_codes": True,
            },
            "fallback": self._fallback(heading4),
        }

    @staticmethod
    def _prune_empty_groups(tree: SemanticNavigationTree) -> int:
        """Не показывать выбор, который не может привести к реальному leaf-коду."""

        pruned = 0

        def has_leaf(node: SemanticNode) -> bool:
            return node.node_type == SemanticNodeType.LEAF or any(
                has_leaf(child) for child in node.children
            )

        def walk(node: SemanticNode) -> None:
            nonlocal pruned
            retained: list[SemanticNode] = []
            for child in node.children:
                walk(child)
                if child.is_group and not has_leaf(child):
                    pruned += 1
                    continue
                retained.append(child)
            node.children = retained

        walk(tree.root)
        return pruned

    def _bind_to_canonical(
        self,
        tree: SemanticNavigationTree,
        model: CanonicalModel,
    ) -> tuple[dict[str, Any], list[str]]:
        """Назначить стабильные IDs и привязать каждый реальный код к Canonical."""

        canonical_nodes: dict[str, Any] = {}
        missing_codes: list[str] = []

        for node in tree.all_nodes():
            if not node.code:
                continue
            canonical = (
                model.get_by_code(node.code)
                or model.get_by_display_code(node.code)
            )
            if canonical is None:
                missing_codes.append(node.code)
                continue
            canonical_nodes[node.code] = canonical

        def walk(
            node: SemanticNode,
            *,
            parent_id: str | None,
            parent_path: tuple[tuple[str, str, int], ...],
            sibling_ordinal: int,
        ) -> None:
            canonical = canonical_nodes.get(node.code or "")
            segment_value = node.code or _identity_text(node.title)
            segment = (node.node_type.value, segment_value, sibling_ordinal)
            path = (*parent_path, segment)
            node.id = canonical.stable_id if canonical is not None else _guide_id(path)
            node.parent_id = parent_id

            sibling_counts: Counter[tuple[str, str]] = Counter()
            for child in node.children:
                key = (
                    child.node_type.value,
                    child.code or _identity_text(child.title),
                )
                ordinal = sibling_counts[key]
                sibling_counts[key] += 1
                walk(
                    child,
                    parent_id=node.id,
                    parent_path=path,
                    sibling_ordinal=ordinal,
                )

        walk(
            tree.root,
            parent_id=None,
            parent_path=(),
            sibling_ordinal=0,
        )
        return canonical_nodes, sorted(set(missing_codes))

    def _serialize_node(
        self,
        node: SemanticNode,
        model: CanonicalModel,
        canonical_nodes: dict[str, Any],
    ) -> dict[str, Any]:
        children = [
            self._serialize_node(child, model, canonical_nodes)
            for child in node.children
        ]
        is_leaf = node.node_type == SemanticNodeType.LEAF
        leaf_count = (1 if is_leaf else 0) + sum(
            int(child["result_count"]) for child in children
        )
        code_count = (1 if node.code else 0) + sum(
            int(child["code_count"]) for child in children
        )

        if node.node_type in {
            SemanticNodeType.CLASSIFICATION_GROUP,
            SemanticNodeType.CLASSIFICATION_SUBGROUP,
        }:
            role = "semantic_choice"
        elif is_leaf:
            role = "declarable_code"
        else:
            role = "code_branch"

        canonical = canonical_nodes.get(node.code or "")
        return {
            "id": node.id,
            "kind": node.node_type.value,
            "role": role,
            "title": node.title,
            "code": node.code,
            "is_leaf": is_leaf,
            "result_count": leaf_count,
            "code_count": code_count,
            "confidence": (
                node.metadata.get("confidence")
                if role == "semantic_choice"
                else None
            ),
            "canonical_anchor": (
                self._anchor_payload(model, canonical)
                if canonical is not None
                else None
            ),
            "children": children,
        }

    @staticmethod
    def _anchor_payload(model: CanonicalModel, node: Any) -> dict[str, Any] | None:
        anchor = model.anchor(node)
        if anchor is None:
            return None
        return {
            "stable_id": anchor.stable_id,
            "snapshot_id": anchor.snapshot_id,
            "code": anchor.code,
            "node_type": anchor.node_type.value,
        }

    @staticmethod
    def _fallback(heading4: str) -> dict[str, str]:
        return {
            "type": "catalog_children",
            "href": f"/api/v1/tnved/children/{heading4}",
            "label": "Открыть обычное дерево ТН ВЭД",
        }

    def _degraded(
        self,
        heading4: str,
        reason: str,
        *,
        snapshot_id: str | None = None,
        integrity: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "status": "DEGRADED",
            "engine": {
                "name": "guided_tnved",
                "version": "v1",
                "mode": "safe_fallback",
                "snapshot_id": snapshot_id,
            },
            "heading": {
                "code": heading4,
                "title": "",
                "canonical_anchor": None,
            },
            "prompt": "",
            "choices": [],
            "integrity": integrity
            or {
                "complete": False,
                "critical_issues": [reason],
            },
            "reason": reason,
            "message": (
                "Умный маршрут временно недоступен. "
                "Обычное дерево ТН ВЭД продолжает работать."
            ),
            "fallback": self._fallback(heading4),
        }


_guided_navigation = GuidedTnvedNavigationService()


def build_guided_tnved_navigation(
    db: Session,
    heading: str,
) -> dict[str, Any]:
    """Модульный фасад для API."""

    return _guided_navigation.build(db, heading)
