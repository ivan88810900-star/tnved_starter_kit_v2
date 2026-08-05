"""Self-contained leaf-input tests for the Canonical Parser → Builder boundary."""

from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from app.services.tree_engine import (
    CanonicalTreeProvider,
    ParsedCommodityRecord,
    TreeBuilder,
    TreeParseResult,
    TreeParser,
)


def _record(code: str, description: str = "test") -> ParsedCommodityRecord:
    return ParsedCommodityRecord(
        code10=code,
        description=description,
        raw_description=description,
        import_duty="",
    )


class TreeParserLeafFlagTests(unittest.TestCase):
    def test_parser_does_not_treat_prefix_only_l4_rate_as_exact_leaf(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "CREATE TABLE hs_rates ("
                        "id INTEGER PRIMARY KEY, hs_code VARCHAR(10), hs_prefix VARCHAR(10))"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO hs_rates (id, hs_code, hs_prefix) "
                        "VALUES (1, 'unrelated', '0101000000')"
                    )
                )

            with Session(engine) as db:
                flags = TreeParser._load_leaf_flags(
                    db,
                    [_record("0101000000")],
                )

            self.assertEqual(flags, {"0101000000": False})
        finally:
            engine.dispose()

    def test_parser_collects_exact_l4_and_inherited_l6_evidence(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "CREATE TABLE hs_rates ("
                        "id INTEGER PRIMARY KEY, hs_code VARCHAR(10), hs_prefix VARCHAR(10))"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO hs_rates (id, hs_code, hs_prefix) "
                        "VALUES (:id, :hs_code, :hs_prefix)"
                    ),
                    [
                        {"id": 1, "hs_code": "0101000000", "hs_prefix": None},
                        {"id": 2, "hs_code": "unrelated", "hs_prefix": "010121"},
                    ],
                )

            records = [
                _record("0101000000"),
                _record("0101210000"),
                _record("0101290000"),
                _record("0101211000"),
            ]
            with Session(engine) as db:
                flags = TreeParser._load_leaf_flags(db, records)

            self.assertEqual(
                flags,
                {
                    "0101000000": True,
                    "0101210000": True,
                    "0101290000": False,
                },
            )
        finally:
            engine.dispose()

    def test_parser_supports_compact_gate2_schema_without_hs_prefix(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "CREATE TABLE hs_rates ("
                        "id INTEGER PRIMARY KEY, hs_code VARCHAR(10))"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO hs_rates (id, hs_code) "
                        "VALUES (1, '0201100000')"
                    )
                )

            records = [_record("0201000000"), _record("0201100000")]
            with Session(engine) as db:
                flags = TreeParser._load_leaf_flags(db, records)

            self.assertEqual(
                flags,
                {"0201000000": False, "0201100000": True},
            )
        finally:
            engine.dispose()

    def test_builder_uses_explicit_parse_result_without_database_access(self) -> None:
        parsed = TreeParseResult(
            commodities=[
                _record("9876", "Heading"),
                _record("9876130000", "– terminal L6"),
            ],
            chapter_notes={},
            db_codes=frozenset({"9876", "9876130000"}),
            leaf_flags={"9876130000": True},
        )

        model = TreeBuilder().build_model(parsed)
        node = model.get_by_code("9876130000")

        self.assertIsNotNone(node)
        self.assertTrue(node.metadata.get("is_leaf"))
        self.assertFalse(node.metadata.get("is_codeless"))

    def test_provider_build_reads_all_inputs_from_one_session(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "CREATE TABLE tnved_sections ("
                        "id INTEGER PRIMARY KEY, roman_number VARCHAR(16), "
                        "title TEXT, notes TEXT)"
                    )
                )
                connection.execute(
                    text(
                        "CREATE TABLE tnved_chapters ("
                        "id INTEGER PRIMARY KEY, section_id INTEGER, code VARCHAR(16), "
                        "title TEXT, notes TEXT)"
                    )
                )
                connection.execute(
                    text(
                        "CREATE TABLE tnved_commodities ("
                        "id INTEGER PRIMARY KEY, chapter_id INTEGER, code VARCHAR(32), "
                        "description TEXT, unit VARCHAR(64), import_duty TEXT, "
                        "supp_unit VARCHAR(16), weight_coeff FLOAT)"
                    )
                )
                connection.execute(
                    text(
                        "CREATE TABLE hs_rates ("
                        "id INTEGER PRIMARY KEY, hs_code VARCHAR(10))"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO tnved_sections "
                        "(id, roman_number, title, notes) "
                        "VALUES (1, 'TEST', 'Test section', '')"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO tnved_chapters "
                        "(id, section_id, code, title, notes) "
                        "VALUES (1, 1, '98', 'Test chapter', '')"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO tnved_commodities "
                        "(id, chapter_id, code, description, unit, import_duty, "
                        "supp_unit, weight_coeff) VALUES "
                        "(1, 1, '9876', 'Heading', '', '', '', 0), "
                        "(2, 1, '9876130000', 'Terminal L6', '', '', '', 0)"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO hs_rates (id, hs_code) "
                        "VALUES (1, '9876130000')"
                    )
                )

            session_count = 0

            def session_factory() -> Session:
                nonlocal session_count
                session_count += 1
                return Session(engine)

            model = CanonicalTreeProvider()._build(session_factory)

            self.assertEqual(session_count, 1)
            node = model.get_by_code("9876130000")
            self.assertIsNotNone(node)
            self.assertTrue(node.metadata.get("is_leaf"))
        finally:
            engine.dispose()

    def test_parser_keeps_concurrent_sqlite_write_outside_snapshot(self) -> None:
        with TemporaryDirectory() as directory:
            database = f"{directory}/snapshot.db"
            reader_engine = create_engine(f"sqlite+pysqlite:///{database}")
            writer_engine = create_engine(f"sqlite+pysqlite:///{database}")
            try:
                with reader_engine.begin() as connection:
                    connection.execute(text("PRAGMA journal_mode=WAL"))
                    connection.execute(
                        text(
                            "CREATE TABLE tnved_sections ("
                            "id INTEGER PRIMARY KEY, roman_number VARCHAR(16), "
                            "title TEXT, notes TEXT)"
                        )
                    )
                    connection.execute(
                        text(
                            "CREATE TABLE tnved_chapters ("
                            "id INTEGER PRIMARY KEY, section_id INTEGER, "
                            "code VARCHAR(16), title TEXT, notes TEXT)"
                        )
                    )
                    connection.execute(
                        text(
                            "CREATE TABLE tnved_commodities ("
                            "id INTEGER PRIMARY KEY, chapter_id INTEGER, "
                            "code VARCHAR(32), description TEXT, unit VARCHAR(64), "
                            "import_duty TEXT, supp_unit VARCHAR(16), weight_coeff FLOAT)"
                        )
                    )
                    connection.execute(
                        text(
                            "CREATE TABLE hs_rates ("
                            "id INTEGER PRIMARY KEY, hs_code VARCHAR(10))"
                        )
                    )
                    connection.execute(
                        text(
                            "INSERT INTO tnved_sections "
                            "(id, roman_number, title, notes) "
                            "VALUES (1, 'TEST', 'Test section', '')"
                        )
                    )
                    connection.execute(
                        text(
                            "INSERT INTO tnved_chapters "
                            "(id, section_id, code, title, notes) "
                            "VALUES (1, 1, '98', 'Test chapter', '')"
                        )
                    )
                    connection.execute(
                        text(
                            "INSERT INTO tnved_commodities "
                            "(id, chapter_id, code, description, unit, import_duty, "
                            "supp_unit, weight_coeff) VALUES "
                            "(1, 1, '9876', 'Heading', '', '', '', 0), "
                            "(2, 1, '9876130000', 'Terminal L6', '', '', '', 0)"
                        )
                    )

                write_triggered = False

                @event.listens_for(reader_engine, "after_cursor_execute")
                def insert_rate_after_commodity_read(
                    connection,  # noqa: ANN001, ARG001
                    cursor,  # noqa: ANN001, ARG001
                    statement,  # noqa: ANN001
                    parameters,  # noqa: ANN001, ARG001
                    context,  # noqa: ANN001, ARG001
                    executemany,  # noqa: ANN001, ARG001
                ) -> None:
                    nonlocal write_triggered
                    if write_triggered or "FROM tnved_commodities" not in statement:
                        return
                    write_triggered = True
                    with writer_engine.begin() as writer:
                        writer.execute(
                            text(
                                "INSERT INTO hs_rates (id, hs_code) "
                                "VALUES (1, '9876130000')"
                            )
                        )

                with Session(reader_engine) as db:
                    parsed = TreeParser().parse(db)

                self.assertTrue(write_triggered)
                self.assertEqual(parsed.leaf_flags, {"9876130000": False})
                with writer_engine.connect() as connection:
                    self.assertEqual(
                        connection.execute(
                            text("SELECT COUNT(*) FROM hs_rates")
                        ).scalar_one(),
                        1,
                    )
            finally:
                reader_engine.dispose()
                writer_engine.dispose()


if __name__ == "__main__":
    unittest.main()
