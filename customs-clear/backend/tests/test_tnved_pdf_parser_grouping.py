from scripts.tnved_pdf_parser import _build_tnved_rows, _group_by_y


def _word(text: str, *, x0: float, top: float) -> dict[str, float | str]:
    return {
        "text": text,
        "x0": x0,
        "x1": x0 + 6.0,
        "top": top,
    }


def test_group_by_y_uses_distance_instead_of_rounding_bucket_boundary() -> None:
    words = [
        _word("прочие", x0=245.57, top=542.26936),
        _word("8544", x0=99.264, top=542.50936),
    ]

    rows = _group_by_y(words, tolerance=5)

    assert len(rows) == 1
    assert {word["text"] for word in next(iter(rows.values()))} == {"8544", "прочие"}


def test_split_baselines_keep_full_code_description_unit_and_duty_together() -> None:
    words = [
        _word("8544", x0=99.264, top=542.50936),
        _word("49", x0=128.424, top=542.50936),
        _word("930", x0=144.624, top=542.50936),
        _word("9", x0=167.408, top=542.50936),
        _word("–", x0=187.100, top=542.26936),
        _word("прочие", x0=245.570, top=542.26936),
        _word("–", x0=415.030, top=542.50936),
        _word("12,5", x0=476.500, top=541.43032),
    ]

    rows = _build_tnved_rows([(words, 0.0)])

    assert len(rows) == 1
    assert rows[0].code == "8544499309"
    assert rows[0].description == "– прочие"
    assert rows[0].unit == "–"
    assert rows[0].duty == "12,5"
