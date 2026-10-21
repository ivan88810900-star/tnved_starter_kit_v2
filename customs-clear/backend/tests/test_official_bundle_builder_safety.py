from __future__ import annotations

from unittest.mock import Mock

import pytest

from scripts import build_official_bundles
from scripts import build_vat_excise_official


@pytest.mark.parametrize(
    ("module", "builder_name"),
    [
        (build_official_bundles, "build_ett_bundle"),
        (build_official_bundles, "build_vat_bundle"),
        (build_official_bundles, "build_excise_bundle"),
        (build_official_bundles, "build_anti_dumping_bundle"),
        (build_official_bundles, "build_special_safeguard_bundle"),
        (build_official_bundles, "build_countervailing_bundle"),
        (build_vat_excise_official, "build_vat_bundle"),
        (build_vat_excise_official, "build_excise_bundle"),
    ],
)
def test_unsafe_builders_refuse_before_database_or_file_access(
    monkeypatch: pytest.MonkeyPatch,
    module: object,
    builder_name: str,
) -> None:
    session = Mock()
    write_bundle = Mock()
    monkeypatch.setattr(module, "SessionLocal", session)
    if hasattr(module, "write_bundle"):
        monkeypatch.setattr(module, "write_bundle", write_bundle)

    with pytest.raises(module.UnsafeBundleBuildError) as exc_info:  # type: ignore[attr-defined]
        getattr(module, builder_name)()

    message = str(exc_info.value)
    assert "immutable official-source snapshot" in message
    assert "today's date" in message
    session.assert_not_called()
    write_bundle.assert_not_called()


@pytest.mark.parametrize(
    "module",
    [build_official_bundles, build_vat_excise_official],
)
def test_unsafe_builder_cli_fails_closed(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    module: object,
) -> None:
    session = Mock()
    monkeypatch.setattr(module, "SessionLocal", session)

    assert module.main() == 2  # type: ignore[attr-defined]

    captured = capsys.readouterr()
    assert "Refusing to build" in captured.err
    assert "immutable official-source snapshot" in captured.err
    assert captured.out == ""
    session.assert_not_called()
