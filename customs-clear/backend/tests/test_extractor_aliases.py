"""EXTRACTOR_COLUMN_ALIASES_JSON — доп. заголовки колонок."""
from __future__ import annotations

import json

import pandas as pd


def test_extractor_custom_description_header(tmp_path, monkeypatch) -> None:
    import app.services.extractor as ex

    ex._EXTRACTOR_ALIASES = None
    p = tmp_path / "aliases.json"
    p.write_text(json.dumps({"description": ["FOOBAR_UNIQUE_HEADER"]}), encoding="utf-8")
    monkeypatch.setenv("EXTRACTOR_COLUMN_ALIASES_JSON", str(p))
    ex._EXTRACTOR_ALIASES = None

    df = pd.DataFrame([{"FOOBAR_UNIQUE_HEADER": "товар тест", "quantity": 2}])
    out = ex._extract_items_from_dataframe(df)
    assert len(out["items"]) == 1
    assert out["items"][0]["description"] == "товар тест"
    assert out["items"][0]["quantity"] == 2.0

    ex._EXTRACTOR_ALIASES = None
