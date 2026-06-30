"""Recovery — стадия восстановления неявной структуры внутри tree_engine.

ADR-0001 (Canonical TNVED Model) фиксирует Recovery как **стадию внутри
`tree_engine`** (а не отдельный top-level module). Её задача — восстановить
структуру, которой нет в БД явно: pad-имена заголовков, синтез бескодовых
L6/L8-заголовков, breadcrumb, выбор «лучшего имени», снятие ведущих тире,
pad-subheading-group и маркировку типов узлов.

TASK-CANONICAL-002 переносит сюда recovery-логику из legacy
`tnved_tree/build_tree.py` (lift-and-shift с типизацией), сохраняя структурную
parity. `StructureNormalizer` — **чистый** (без БД, без `uuid4`, без времени и
случайности): leaf-флаги предвычисляются вне нормализатора и передаются
аргументом (`leaf_flags`). Сборка иерархии (stack/parent-children) — это
ответственность `Builder`, а НЕ нормализатора.

Не переносится сюда (см. TASK-CANONICAL-002 «Список логики, которую переносить
запрещено»): stack-сборка иерархии, прямой вызов БД (`is_leaf_hs_code`), resolve
ставок/permit/measures, секционная обёртка, сериализация, semantic-группы,
изменение самого `build_tree()`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..tnved_tree import (
    best_name_for_group,
    is_direct_position_subheading,
    is_meaningful_name,
    needs_pad_subheading_group,
    node_level,
    split_position_pad_name,
    strip_leading_dashes,
)
from .models import ParsedCommodityRecord


@dataclass
class RecoveredNode:
    """Узел после recovery: атрибуты восстановлены, иерархия — задача Builder.

    `synthetic_leaf` — описатель синтетического листа (для одиночных L6/L8 без
    детей, `KNOWN_PITFALLS` §2/§3). Сам лист материализует Builder.
    """

    code: str
    name: str
    import_duty: str
    notes: str
    display_code: str
    level: int
    is_leaf: bool
    is_codeless: bool
    is_group: bool
    is_synthetic: bool = False
    synthetic_leaf: "RecoveredNode | None" = None


@dataclass
class RecoveredHeading:
    """Восстановленная 4-значная позиция с плоским списком классифицированных
    дочерних кодов. Cross-level nesting Builder выполняет сам (stack)."""

    code: str
    name: str
    notes: str
    use_subheading_group: bool
    subheading_group: RecoveredNode | None
    direct_l6: frozenset[str]
    entries: list[RecoveredNode] = field(default_factory=list)


@dataclass
class _HeadingDraft:
    code: str
    name: str
    notes: str


class StructureNormalizer:
    """Стадия Recovery: восстановление атрибутов/синтеза без сборки иерархии."""

    def normalize(
        self,
        records: list[ParsedCommodityRecord],
        *,
        chapter_notes: dict[str, str],
        leaf_flags: dict[str, bool],
    ) -> list[RecoveredHeading]:
        """Плоские записи Parser → восстановленные позиции (без stack-сборки).

        Эквивалентно recovery-части legacy `build_tree()`; иерархию собирает
        Builder. `leaf_flags` — предвычисленные вне нормализатора leaf-признаки
        (см. `_is_leaf`), чтобы стадия оставалась чистой (без БД).
        """
        headings: dict[str, _HeadingDraft] = {}
        ten_by_code: dict[str, dict[str, str]] = {}

        for rec in records:
            code = rec.code10
            if len(code) <= 4:
                key4 = code.zfill(4)
                if key4 not in headings:
                    headings[key4] = _HeadingDraft(
                        code=key4,
                        name=(rec.description or "").strip(),
                        notes=chapter_notes.get(key4, ""),
                    )
                elif not headings[key4].name:
                    headings[key4].name = (rec.description or "").strip()
            else:
                code10 = code.zfill(10)[:10]
                raw_name = (rec.description or "").strip()
                ten_by_code[code10] = {
                    "code": code10,
                    "raw_name": raw_name,
                    "name": strip_leading_dashes(raw_name),
                    "import_duty": rec.import_duty or "",
                }

        for code10 in ten_by_code:
            p4 = code10[:4]
            if p4 not in headings:
                headings[p4] = _HeadingDraft(code=p4, name="", notes=chapter_notes.get(p4, ""))

        by_heading: dict[str, list[str]] = {}
        for code10 in ten_by_code:
            by_heading.setdefault(code10[:4], []).append(code10)

        result: list[RecoveredHeading] = []
        for p4 in sorted(headings):
            draft = headings[p4]
            codes = sorted(by_heading.get(p4, []))

            pad_code = p4 + "000000"
            deeper = [c for c in codes if c != pad_code]
            pad_sub = ""
            if pad_code in ten_by_code:
                raw_pad = ten_by_code[pad_code].get("raw_name") or ""
                title, sub = split_position_pad_name(raw_pad)
                if title and (not draft.name or not is_meaningful_name(draft.name)):
                    draft.name = title
                pad_sub = sub
                if not pad_sub and (not draft.name or not is_meaningful_name(draft.name)):
                    draft.name = title or ten_by_code[pad_code]["name"]
                codes = deeper

            level6_codes = [c for c in codes if node_level(c) == 6]
            direct_l6 = {c for c in level6_codes if is_direct_position_subheading(c)}
            use_subheading_group = needs_pad_subheading_group(pad_sub, level6_codes)

            subheading_group: RecoveredNode | None = None
            if use_subheading_group:
                pad_raw = ten_by_code.get(pad_code, {})
                subheading_group = RecoveredNode(
                    code=pad_code,
                    name=pad_sub,
                    import_duty=pad_raw.get("import_duty", ""),
                    notes=draft.notes,
                    display_code=pad_code,
                    level=node_level(pad_code),
                    is_leaf=False,
                    is_codeless=True,
                    is_group=True,
                )

            # «Есть потомок» по позиционному правилу stack-сборки Builder: код имеет
            # детей ⇔ следующий по порядку код глубже по уровню (нести под него).
            # Это точно повторяет уровневую (а не префиксную) вложенность legacy
            # build_tree: напр. L9 0305399010 попадает под L8 0305395000, т.к.
            # промежуточного L8 0305399000 нет в БД.
            levels = [node_level(c) for c in codes]
            entries: list[RecoveredNode] = []
            for i, c in enumerate(codes):
                has_children = i + 1 < len(codes) and levels[i + 1] > levels[i]
                entries.append(
                    self._classify_entry(
                        c,
                        ten_by_code[c],
                        draft.notes,
                        leaf_flags,
                        has_children,
                    )
                )

            result.append(
                RecoveredHeading(
                    code=p4,
                    name=draft.name,
                    notes=draft.notes,
                    use_subheading_group=use_subheading_group,
                    subheading_group=subheading_group,
                    direct_l6=frozenset(direct_l6),
                    entries=entries,
                )
            )

        return result

    def recover_group_name(self, leaf_names: list[str]) -> str:
        """Лучшее имя синтетического заголовка из имён листьев (`best_name_for_group`).

        Вызывается Builder'ом после сборки (нужны листья), но логика выбора —
        здесь (recovery item 6). Имена листьев уже очищены `strip_leading_dashes`.
        """
        return best_name_for_group([{"name": name} for name in leaf_names])

    @staticmethod
    def _is_leaf(code: str, leaf_flags: dict[str, bool]) -> bool:
        """Чистый эквивалент `is_leaf_hs_code` по предвычисленным leaf_flags.

        Коды, не оканчивающиеся на «0000», — всегда листья (как в
        `normative_store.is_leaf_hs_code`); неоднозначные «…0000» берутся из
        `leaf_flags` (наличие строки в `hs_rates`, посчитано вне нормализатора).
        """
        if len(code) != 10:
            return False
        if code.endswith("0000"):
            return leaf_flags.get(code, False)
        return True

    def _classify_entry(
        self,
        code: str,
        raw: dict[str, str],
        notes: str,
        leaf_flags: dict[str, bool],
        has_children: bool,
    ) -> RecoveredNode:
        lvl = node_level(code)
        name = raw["name"]
        duty = raw.get("import_duty", "")

        def make(
            *,
            is_leaf: bool,
            is_codeless: bool,
            is_group: bool,
            display_code: str,
            synthetic_leaf: RecoveredNode | None = None,
            is_synthetic: bool = False,
        ) -> RecoveredNode:
            return RecoveredNode(
                code=code,
                name=name,
                import_duty=duty,
                notes=notes,
                display_code=display_code,
                level=lvl,
                is_leaf=is_leaf,
                is_codeless=is_codeless,
                is_group=is_group,
                is_synthetic=is_synthetic,
                synthetic_leaf=synthetic_leaf,
            )

        if has_children:
            # _classify: узел с детьми → бескодовый заголовок (display не меняется).
            return make(is_leaf=False, is_codeless=True, is_group=True, display_code=code)

        # Childless: повторяет ветви _classify для L6 / L8 / прочих уровней.
        if lvl == 6:
            if self._is_leaf(code, leaf_flags):
                return make(is_leaf=True, is_codeless=False, is_group=False, display_code=code)
            synthetic_leaf = RecoveredNode(
                code=code,
                name=name,
                import_duty=duty,
                notes=notes,
                display_code=code,
                level=lvl,
                is_leaf=True,
                is_codeless=False,
                is_group=False,
                is_synthetic=True,
            )
            return make(
                is_leaf=False,
                is_codeless=True,
                is_group=True,
                display_code=code[:6],
                synthetic_leaf=synthetic_leaf,
            )

        if lvl == 8:
            if self._is_leaf(code, leaf_flags):
                return make(is_leaf=True, is_codeless=False, is_group=False, display_code=code)
            synthetic_leaf = RecoveredNode(
                code=code,
                name=name,
                import_duty=duty,
                notes=notes,
                display_code=code,
                level=lvl,
                is_leaf=True,
                is_codeless=False,
                is_group=False,
                is_synthetic=True,
            )
            return make(
                is_leaf=False,
                is_codeless=True,
                is_group=True,
                display_code=code[:8],
                synthetic_leaf=synthetic_leaf,
            )

        leaf = self._is_leaf(code, leaf_flags)
        return make(is_leaf=leaf, is_codeless=not leaf, is_group=not leaf, display_code=code)
