"""Regression tests for user-facing NTM issuer and permit labels."""

from app.api.tnved_catalog import (
    _MEASURE_TYPE_TO_BADGE,
    _convert_ntm_v2_to_display,
    _measure_type_label,
)


def test_nf_display_is_fsb_notification_not_fstec() -> None:
    row = _convert_ntm_v2_to_display(
        "8517130000",
        [{"permit_type": "НФ", "description": "", "legal_ref": "Решение Коллегии ЕЭК №30"}],
    )[0]

    assert row["measure_type"] == "fsb"
    assert row["type_label"] == "Нотификация ФСБ"
    assert row["document_required"].startswith("Нотификация ФСБ")
    assert "ФСТЭК" not in row["type_label"]
    assert _MEASURE_TYPE_TO_BADGE["fsb"] == "НФ"


def test_legacy_fsetc_label_remains_export_control_not_notification() -> None:
    label = _measure_type_label("fsetc")

    assert label == "Требования ФСТЭК в сфере экспортного контроля"
    assert "Нотификация" not in label
    assert _MEASURE_TYPE_TO_BADGE["fsetc"] == "ФСТЭК"
