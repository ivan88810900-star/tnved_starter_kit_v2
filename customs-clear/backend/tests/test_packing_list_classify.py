"""Тесты оптимизированной пакетной классификации."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.packing_list_classify import classify_packing_rows_optimized
from app.services.packing_list_parser import PackingRow
from app.services.smart_classifier import ClassifyResult, SmartClassifier


@pytest.mark.asyncio
async def test_group_dedup_single_vision_and_classify() -> None:
    SmartClassifier.clear_packing_caches()
    snaps = [
        {"row_num": 2, "name_cn": "染发碗", "material": "塑料", "article": "A1"},
        {"row_num": 3, "name_cn": "染发碗", "material": "塑料", "article": "A2"},
    ]
    images = {
        2: PackingRow(row_num=2, name_cn="染发碗", image_base64="abc"),
        3: PackingRow(row_num=3, name_cn="染发碗", image_base64="def"),
    }

    mock_clf = AsyncMock()
    mock_clf.prepare_translations = AsyncMock(return_value={})
    mock_clf.translate_cached = AsyncMock(return_value="миска для окрашивания")
    mock_clf.get_or_analyze_vision = AsyncMock(return_value="vision text")
    mock_clf.get_or_classify_group = AsyncMock(
        return_value=ClassifyResult(
            results=[{"hs_code": "3924900000", "confidence": 0.9, "description": "d", "rationale": "r"}],
            translation_used="миска",
            status="OK",
        )
    )

    with patch("app.services.packing_list_classify.get_smart_classifier", return_value=mock_clf):
        out = await classify_packing_rows_optimized(snaps, images, max_concurrent=3)

    assert len(out) == 2
    assert out[0]["hs_code"] == "3924900000"
    assert mock_clf.get_or_analyze_vision.await_count == 1
    assert mock_clf.get_or_classify_group.await_count == 1
    SmartClassifier.clear_packing_caches()
