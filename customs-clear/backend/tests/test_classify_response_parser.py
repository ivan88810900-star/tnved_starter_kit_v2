"""Парсер ответа LLM-классификатора ТН ВЭД."""

from __future__ import annotations

from app.services.classify_response_parser import parse_classify_response


def test_parse_english_json_results() -> None:
    raw = """
    {
      "results": [
        {"hs_code": "6404110090", "confidence": 0.91, "description": "Обувь", "rationale": "6404"}
      ]
    }
    """
    out = parse_classify_response(raw)
    assert len(out) == 1
    assert out[0]["hs_code"] == "6404110090"
    assert out[0]["confidence"] == 0.91


def test_parse_russian_keys_in_markdown() -> None:
    raw = """```json
{
  "товар": "Кроссовки",
  "варианты": [
    {
      "код_тн_вед": "6404110090",
      "наименование": "Кроссовки спортивные",
      "обоснование": "Синтетический верх",
      "рекомендуемый": true
    },
    {
      "код_тн_вед": "6404120090",
      "наименование": "Альтернатива",
      "обоснование": "6404"
    }
  ]
}
```"""
    out = parse_classify_response(raw)
    assert len(out) == 2
    assert out[0]["hs_code"] == "6404110090"
    assert out[0]["confidence"] == 0.9
    assert "Кроссовки" in out[0]["description"]


def test_strips_spaces_in_hs_code() -> None:
    raw = '{"results":[{"hs_code":"8471 30 0000","confidence":0.85,"description":"Ноутбук","rationale":"8471"}]}'
    out = parse_classify_response(raw)
    assert out[0]["hs_code"] == "8471300000"
