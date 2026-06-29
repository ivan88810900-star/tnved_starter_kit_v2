"""Построение иерархического дерева ТН ВЭД 4 → 10 (перенос из tnved_catalog)."""

from __future__ import annotations

from typing import Any

from .helpers import (
    best_name_for_group,
    collect_leaf_names,
    digits,
    format_duty,
    is_direct_position_subheading,
    is_meaningful_name,
    make_tree_node,
    needs_pad_subheading_group,
    node_level,
    split_position_pad_name,
    strip_leading_dashes,
)


def build_tree(rows: list[Any], chapter_notes: dict[str, str]) -> list[dict[str, Any]]:
    """
    Плоский список tnved_commodities (10-значные коды с паддингом) → дерево
    позиция(4) → субпозиция(6) → подсубпозиция(8) → национальный код(10).
    """
    parents: dict[str, dict[str, Any]] = {}
    ten_by_code: dict[str, dict[str, str]] = {}

    for r in rows:
        raw_code = (r.code or "").strip()
        d = digits(raw_code)
        if not d:
            continue

        if len(d) <= 4:
            key4 = d.zfill(4)
            if key4 not in parents:
                parents[key4] = make_tree_node(
                    key4,
                    (r.description or "").strip(),
                    "",
                    chapter_notes.get(key4, ""),
                    is_leaf=False,
                    is_codeless=False,
                    is_group=True,
                )
            elif not parents[key4]["name"]:
                parents[key4]["name"] = (r.description or "").strip()
        else:
            code10 = d.zfill(10)[:10]
            ten_by_code[code10] = {
                "code": code10,
                "raw_name": (r.description or "").strip(),
                "name": strip_leading_dashes((r.description or "").strip()),
                "import_duty": format_duty(r.import_duty),
            }

    for code10 in ten_by_code:
        p4 = code10[:4]
        if p4 not in parents:
            parents[p4] = make_tree_node(
                p4,
                "",
                "",
                chapter_notes.get(p4, ""),
                is_leaf=False,
                is_codeless=False,
                is_group=True,
            )

    by_heading: dict[str, list[str]] = {}
    for code10 in ten_by_code:
        by_heading.setdefault(code10[:4], []).append(code10)

    for p4, codes in by_heading.items():
        heading = parents[p4]
        codes.sort()

        pad_code = p4 + "000000"
        deeper = [c for c in codes if c != pad_code]
        pad_sub = ""
        if pad_code in ten_by_code:
            raw_pad = ten_by_code[pad_code].get("raw_name") or ""
            title, sub = split_position_pad_name(raw_pad)
            if title and (not heading["name"] or not is_meaningful_name(heading["name"])):
                heading["name"] = title
            pad_sub = sub
            if not pad_sub and (not heading["name"] or not is_meaningful_name(heading["name"])):
                heading["name"] = title or ten_by_code[pad_code]["name"]
            codes = deeper
        elif pad_code in ten_by_code and not deeper:
            cand = ten_by_code[pad_code]["name"]
            if cand and (not heading["name"] or not is_meaningful_name(heading["name"])):
                heading["name"] = cand

        level6_codes = [c for c in codes if node_level(c) == 6]
        direct_l6 = {c for c in level6_codes if is_direct_position_subheading(c)}
        use_subheading_group = needs_pad_subheading_group(pad_sub, level6_codes)

        subheading_group: dict[str, Any] | None = None
        if use_subheading_group:
            pad_raw = ten_by_code.get(pad_code, {})
            subheading_group = make_tree_node(
                pad_code,
                pad_sub,
                pad_raw.get("import_duty", ""),
                heading["notes"],
                is_leaf=False,
                is_codeless=True,
                is_group=True,
            )
            heading["children"].append(subheading_group)

        stack: list[tuple[int, dict[str, Any]]] = []
        for code10 in codes:
            lvl = node_level(code10)
            raw = ten_by_code[code10]
            node = make_tree_node(
                code10,
                raw["name"],
                raw["import_duty"],
                heading["notes"],
                is_leaf=True,
                is_codeless=False,
                is_group=False,
            )
            if use_subheading_group and lvl == 6 and code10 not in direct_l6:
                while stack:
                    stack.pop()
                parent_node = subheading_group
            else:
                while stack and stack[-1][0] >= lvl:
                    stack.pop()
                parent_node = stack[-1][1] if stack else heading
            parent_node["children"].append(node)
            stack.append((lvl, node))

    def _classify(node: dict[str, Any]) -> None:
        for ch in node["children"]:
            _classify(ch)
        if len(node["display_code"]) == 10:
            from ..normative_store import is_leaf_hs_code

            if node["children"]:
                node["is_leaf"] = False
                node["is_codeless"] = True
                node["is_group"] = True
            else:
                lvl = node_level(node["code"])
                if lvl == 6:
                    if is_leaf_hs_code(node["code"]):
                        node["is_leaf"] = True
                        node["is_codeless"] = False
                        node["is_group"] = False
                    else:
                        leaf_child = {
                            **node,
                            "is_leaf": True,
                            "is_codeless": False,
                            "is_group": False,
                            "children": [],
                        }
                        node["children"] = [leaf_child]
                        node["is_leaf"] = False
                        node["is_codeless"] = True
                        node["is_group"] = True
                        node["display_code"] = node["code"][:6]
                elif lvl == 8:
                    if is_leaf_hs_code(node["code"]):
                        node["is_leaf"] = True
                        node["is_codeless"] = False
                        node["is_group"] = False
                    else:
                        leaf_child = {
                            **node,
                            "is_leaf": True,
                            "is_codeless": False,
                            "is_group": False,
                            "children": [],
                        }
                        node["children"] = [leaf_child]
                        node["is_leaf"] = False
                        node["is_codeless"] = True
                        node["is_group"] = True
                        node["display_code"] = node["code"][:8]
                else:
                    leaf = is_leaf_hs_code(node["code"])
                    node["is_leaf"] = leaf
                    node["is_codeless"] = not leaf
                    node["is_group"] = not leaf

    def _sort(node: dict[str, Any]) -> None:
        node["children"].sort(key=lambda x: x["code"])
        for ch in node["children"]:
            _sort(ch)

    for p in parents.values():
        _classify(p)
        _sort(p)
        if not p["name"]:
            leaves: list[dict[str, Any]] = []
            collect_leaf_names(p, leaves)
            p["name"] = best_name_for_group(leaves)

    return sorted(parents.values(), key=lambda x: x["code"])
