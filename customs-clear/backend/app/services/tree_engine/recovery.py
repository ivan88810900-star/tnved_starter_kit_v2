"""Recovery — стадия восстановления неявной структуры внутри tree_engine.

ADR-0001 (Canonical TNVED Model) фиксирует Recovery как **стадию внутри
`tree_engine`** (а не отдельный top-level module). Её задача — восстановить
структуру, которой нет в БД явно: pad-имена заголовков, синтез бескодовых
L6/L8-заголовков, breadcrumb, выбор «лучшего имени», снятие ведущих тире.

ЭТАП 1 (эта задача, TASK-CANONICAL-001): только **skeleton**. Никакого переноса
recovery-логики — она пока остаётся внутри legacy `_build_tree()/_classify()` и
делегируется Builder'ом. `normalize()` здесь — детерминированный no-op
pass-through: структура дерева не изменяется.

ФАКТИЧЕСКИЙ перенос L6/L8/pad/breadcrumb-логики — в **TASK-CANONICAL-002**.
"""

from __future__ import annotations

from .models import TreeNode, TreeParseResult


class StructureNormalizer:
    """Skeleton стадии Recovery. Пока не нормализует структуру (no-op)."""

    def normalize(
        self,
        roots: list[TreeNode],
        *,
        parse_result: TreeParseResult | None = None,
    ) -> list[TreeNode]:
        """Возвращает дерево без изменений (детерминированный pass-through).

        SKELETON: перенос pad/L6/L8/breadcrumb-логики отложен до
        TASK-CANONICAL-002. Сейчас контракт: вход == выход (та же структура,
        те же узлы), чтобы не менять production-поведение.
        """
        return roots
