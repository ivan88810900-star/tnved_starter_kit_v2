"""Shadow-сравнение структурного слоя ``/children``: legacy vs canonical.

ADR-0001 §8 (Этап 2/3): пока canonical read-path выключен, можно параллельно
сверять его результат с legacy в проде под флагом ``CANONICAL_TREE_SHADOW`` без
влияния на ответ. Здесь — чистые (без БД, без сети) функции сравнения
**структуры и контента** узлов в legacy-форме (dict из ``TreeSerializer`` /
``_build_tree``).

Сравнивается только **структурный слой** (то, что меняет эта задача): код, имя,
флаги, display_code, import_duty, notes и вложенность. Overlay/enrichment
(ставки/меры из ``_serialize_tree_node``) сюда НЕ входит — он не меняется.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


def node_fingerprint(node: Mapping[str, Any]) -> tuple[Any, ...]:
    """Структурно-контентный отпечаток legacy-узла (рекурсивно по детям).

    Учитывает поля, за которые отвечает структурный слой; порядок детей значим.
    """
    children = node.get("children") or []
    return (
        node.get("code") or "",
        (node.get("name") or "").strip(),
        node.get("display_code") or "",
        bool(node.get("is_leaf")),
        bool(node.get("is_codeless")),
        bool(node.get("is_group")),
        (node.get("import_duty") or "").strip(),
        (node.get("notes") or "").strip(),
        tuple(node_fingerprint(ch) for ch in children),
    )


def children_fingerprint(children: Sequence[Mapping[str, Any]]) -> tuple[Any, ...]:
    """Отпечаток списка прямых потомков (то, что реально отдаёт ``/children``)."""
    return tuple(node_fingerprint(ch) for ch in children)


@dataclass
class ShadowComparison:
    """Итог shadow-сравнения одного ``/children`` запроса."""

    code: str
    match: bool
    reason: str = ""
    legacy_count: int = 0
    canonical_count: int = 0
    revision: str | None = None

    def as_log_fields(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "match": self.match,
            "reason": self.reason,
            "legacy_count": self.legacy_count,
            "canonical_count": self.canonical_count,
            "revision": self.revision,
        }


def compare_children(
    code: str,
    legacy_children: Sequence[Mapping[str, Any]] | None,
    canonical_children: Sequence[Mapping[str, Any]] | None,
    *,
    revision: str | None = None,
) -> ShadowComparison:
    """Сравнить прямые потомки legacy vs canonical для кода узла.

    ``canonical_children == None`` трактуется как «canonical не смог разрешить
    узел» (mismatch с причиной), что в shadow только логируется.
    """
    legacy_list = list(legacy_children or [])
    if canonical_children is None:
        return ShadowComparison(
            code=code,
            match=False,
            reason="canonical_unresolved",
            legacy_count=len(legacy_list),
            canonical_count=0,
            revision=revision,
        )
    canonical_list = list(canonical_children)
    legacy_fp = children_fingerprint(legacy_list)
    canonical_fp = children_fingerprint(canonical_list)
    if legacy_fp == canonical_fp:
        return ShadowComparison(
            code=code,
            match=True,
            legacy_count=len(legacy_list),
            canonical_count=len(canonical_list),
            revision=revision,
        )
    reason = (
        "count_mismatch"
        if len(legacy_list) != len(canonical_list)
        else "fingerprint_mismatch"
    )
    return ShadowComparison(
        code=code,
        match=False,
        reason=reason,
        legacy_count=len(legacy_list),
        canonical_count=len(canonical_list),
        revision=revision,
    )
