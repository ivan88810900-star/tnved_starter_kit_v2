"""Локальный ONNX-классификатор: без реального .onnx — мок сессии."""
from __future__ import annotations

import json
from unittest.mock import patch

import numpy as np

from app.services import onnx_hs_classifier as onc


def test_description_feature_vector_shape() -> None:
    v = onc._description_feature_vector("тест 测试", 64)
    assert v.shape == (1, 64)
    assert abs(float(np.linalg.norm(v)) - 1.0) < 1e-3


def test_run_classify_mock_session(tmp_path, monkeypatch) -> None:
    model = tmp_path / "dummy.onnx"
    model.write_bytes(b"")
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps(["1111111111", "2222222222", "3333333333"]))
    monkeypatch.setenv("ONNX_HS_CLASSIFIER_PATH", str(model))
    monkeypatch.setenv("ONNX_HS_LABELS_PATH", str(labels))
    onc.clear_caches()

    class FakeSess:
        def run(self, _outs, feed):
            assert "i" in feed
            return [np.array([[0.1, 9.0, 0.2]], dtype=np.float32)]

    fake = (FakeSess(), "i", 8, "o")
    with patch.object(onc, "_session_and_meta_cached", return_value=fake):
        out = onc.run_classify("электрический чайник")
    assert out is not None
    assert out["classifier_source"] == "onnx_local"
    assert out["results"][0]["code"] == "2222222222"
