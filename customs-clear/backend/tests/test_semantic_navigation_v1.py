"""Semantic Navigation v1 — минимальные проверки (экспериментальный слой)."""

from __future__ import annotations

import unittest

try:
    from app.db import SessionLocal
    from app.models.tnved import Commodity
    from app.services.normative_store import init_db
    from app.services.semantic_navigation import (
        GROUP_NODE_TYPES,
        SemanticNavigationBuilder,
        SemanticNavigationValidator,
        SemanticNodeType,
    )
    from app.services.tnved_tree.data_access import exclude_obsolete_reserved
    from app.services.tnved_tree.helpers import digits

    _OK = True
except ImportError:
    _OK = False


def _db_codes(db, heading4: str) -> set[str]:
    rows = exclude_obsolete_reserved(
        db.query(Commodity.code).filter(Commodity.code.like(f"{heading4}%"))
    ).all()
    out: set[str] = set()
    for (code,) in rows:
        d = digits(code)
        if not d:
            continue
        if len(d) <= 4:
            out.add(d.zfill(4))
        else:
            full = d.zfill(10)[:10]
            out.add(full)
            # 4-значная позиция реальна, т.к. tnved_commodities хранит только
            # 10-значные коды (pad XXXX000000), а 4-значный код — её позиция.
            out.add(full[:4])
    return out


@unittest.skipUnless(_OK, "semantic navigation tests need FastAPI app deps")
class SemanticNavigationV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()
        cls.builder = SemanticNavigationBuilder()
        cls.validator = SemanticNavigationValidator()

    def test_0302_builds_without_error(self) -> None:
        with SessionLocal() as db:
            tree = self.builder.build_heading(db, "0302")
        self.assertEqual(tree.heading, "0302")
        self.assertEqual(tree.root.node_type, SemanticNodeType.HEADING)
        self.assertEqual(tree.root.code, "0302")
        self.assertTrue(tree.root.children, "heading 0302 должен иметь потомков")

    def test_0302_real_codes_preserved(self) -> None:
        with SessionLocal() as db:
            tree = self.builder.build_heading(db, "0302")
            db_codes = _db_codes(db, "0302")
        present = set(tree.real_codes_in_tree())
        # все реальные коды (кроме pad) достижимы в дереве
        expected = set(tree.expected_real_codes)
        self.assertEqual(expected - present, set(), "потеряны реальные коды heading")
        # все коды дерева существуют в БД
        self.assertTrue(present.issubset(db_codes), "в дереве есть код вне БД")

    def test_no_fake_codes(self) -> None:
        with SessionLocal() as db:
            tree = self.builder.build_heading(db, "0302")
            db_codes = _db_codes(db, "0302")
        for node in tree.all_nodes():
            if node.carries_real_code and node.code:
                self.assertIn(node.code, db_codes, f"fake-код в дереве: {node.code}")

    def test_group_nodes_have_no_commodity_code(self) -> None:
        with SessionLocal() as db:
            tree = self.builder.build_heading(db, "0302")
        groups = [n for n in tree.all_nodes() if n.node_type in GROUP_NODE_TYPES]
        self.assertTrue(groups, "для 0302 ожидаются semantic-группы")
        for g in groups:
            self.assertIsNone(g.code, f"group-узел не должен иметь код: {g.title}")

    def test_validator_no_critical_issues(self) -> None:
        with SessionLocal() as db:
            tree = self.builder.build_heading(db, "0302")
            db_codes = _db_codes(db, "0302")
            result = self.validator.validate(tree, db_codes=frozenset(db_codes))
        self.assertFalse(
            result.has_critical,
            msg=f"critical issues: {[i.message for i in result.critical_issues[:5]]}",
        )

    def _group_titles(self, heading: str) -> set[str]:
        with SessionLocal() as db:
            tree = self.builder.build_heading(db, heading)
        return {
            n.title.lower()
            for n in tree.all_nodes()
            if n.node_type == SemanticNodeType.CLASSIFICATION_GROUP
        }

    def test_expected_groups_found_for_0302(self) -> None:
        titles = self._group_titles("0302")
        for expected in ("лососевые", "камбалообразные", "тунец"):
            self.assertIn(expected, titles, f"0302 должен содержать группу {expected!r}")

    def test_0303_tunets_not_a_single_75_code_group(self) -> None:
        with SessionLocal() as db:
            tree = self.builder.build_heading(db, "0303")
        tunets = [
            n
            for n in tree.all_nodes()
            if n.node_type == SemanticNodeType.CLASSIFICATION_GROUP
            and n.title.strip().lower() == "тунец"
        ]
        self.assertTrue(tunets, "0303 должен иметь группу 'тунец'")
        max_codes = max(
            sum(1 for d in g.iter_descendants() if d.carries_real_code and d.code)
            for g in tunets
        )
        self.assertLess(
            max_codes,
            75,
            f"группа 'тунец' поглощает слишком много кодов: {max_codes}",
        )

    def test_8517_rejects_technical_param_headers(self) -> None:
        with SessionLocal() as db:
            tree = self.builder.build_heading(db, "8517")
        titles = {
            n.title.strip().lower()
            for n in tree.all_nodes()
            if n.node_type == SemanticNodeType.CLASSIFICATION_GROUP
        }
        self.assertNotIn("10 ггц", titles)
        self.assertNotIn("1610 нм", titles)
        rejected = {t.lower() for (t, _r, _s) in tree.rejected_candidates}
        self.assertIn("10 ггц", rejected)
        self.assertIn("1610 нм", rejected)

    def test_real_codes_reachable_and_no_fakes_all_headings(self) -> None:
        for heading in ("0302", "0303", "5208", "8517"):
            with SessionLocal() as db:
                tree = self.builder.build_heading(db, heading)
                db_codes = _db_codes(db, heading)
                result = self.validator.validate(tree, db_codes=frozenset(db_codes))
            present = set(tree.real_codes_in_tree())
            self.assertEqual(
                set(tree.expected_real_codes) - present,
                set(),
                f"{heading}: потеряны реальные коды",
            )
            self.assertFalse(
                result.has_critical,
                f"{heading}: critical issues: "
                f"{[i.message for i in result.critical_issues[:3]]}",
            )


if __name__ == "__main__":
    unittest.main()
