"""Герметичные тесты логики оценки источников предрешений ФТС (без сети)."""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND / "scripts"))

import probe_fcs_sources as probe_mod  # noqa: E402


class TestClassifyStatus:
    def test_unreachable_when_none(self) -> None:
        assert probe_mod.classify_status(None, "usable_html") == "unreachable"

    def test_antibot_for_403_429(self) -> None:
        assert probe_mod.classify_status(403, "antibot") == "antibot"
        assert probe_mod.classify_status(429, "usable_html") == "antibot"

    def test_not_found_for_404(self) -> None:
        assert probe_mod.classify_status(404, "unknown") == "not_found"

    def test_wrong_section_flagged(self) -> None:
        # folder/519 отдаёт 200, но это статистика, а не предрешения.
        assert probe_mod.classify_status(200, "wrong_section") == "reachable_but_wrong_section"

    def test_js_rendered_flagged(self) -> None:
        assert probe_mod.classify_status(200, "js_rendered") == "reachable_but_js_rendered"

    def test_plain_reachable(self) -> None:
        assert probe_mod.classify_status(200, "usable_html") == "reachable"

    def test_server_error(self) -> None:
        assert probe_mod.classify_status(503, "usable_html") == "server_error"


class TestSourceCandidatesIntegrity:
    def test_folder_519_is_marked_wrong_section(self) -> None:
        by_code = {c.code: c for c in probe_mod.FCS_SOURCE_CANDIDATES}
        assert "customs_folder_519" in by_code
        assert by_code["customs_folder_519"].expected_kind == "wrong_section"

    def test_all_candidates_have_note(self) -> None:
        for c in probe_mod.FCS_SOURCE_CANDIDATES:
            assert c.note.strip(), f"{c.code} без пояснения"
            assert c.url.startswith("https://")
