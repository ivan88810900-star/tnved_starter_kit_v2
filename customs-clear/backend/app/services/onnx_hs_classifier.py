"""Локальный классификатор ТН ВЭД через ONNX (опционально, onnxruntime).

Контракт модели:
- один вход float32, форма ``[batch, feature_dim]`` (batch обычно 1; feature_dim любой, подстраиваем хэш-вектор);
- один выход логитов float32, форма ``[batch, num_classes]``.

Список кодов ТН ВЭД (по индексу класса): JSON-массив строк в файле из ``ONNX_HS_LABELS_PATH``.

Важно: хэш-признаки из текста — **заглушка для проводки графа**; для боя замените модель на экспорт с реальным векторизатором
(см. ``docs/integration/ONNX_HS_CLASSIFIER.md``).
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional

import numpy as np
from loguru import logger


def _model_path() -> str:
    return (os.getenv("ONNX_HS_CLASSIFIER_PATH") or "").strip()


def _labels_path() -> str:
    return (os.getenv("ONNX_HS_LABELS_PATH") or "").strip()


def _feature_dim_env() -> str:
    return (os.getenv("ONNX_HS_FEATURE_DIM") or "").strip()


def is_onnx_classifier_configured() -> bool:
    p, l = _model_path(), _labels_path()
    return bool(p and l and os.path.isfile(p) and os.path.isfile(l))


def _digits_hs(s: str) -> str:
    return re.sub(r"\D", "", (s or ""))[:10]


@lru_cache(maxsize=8)
def _load_labels_cached(lab_path: str) -> tuple[str, ...]:
    with open(lab_path, encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, list):
        raise ValueError("ONNX_HS_LABELS_PATH: ожидается JSON-массив строк")
    out: List[str] = []
    for x in raw:
        d = _digits_hs(str(x))
        if len(d) >= 4:
            out.append(d.ljust(10, "0")[:10])
    return tuple(out)


def _description_feature_vector(description: str, dim: int) -> np.ndarray:
    """Детерминированный псевдо-эмбеддинг фиксированной размерности (для совместимости с входом ONNX)."""
    v = np.zeros((1, dim), dtype=np.float32)
    b = description.encode("utf-8", errors="ignore")
    for i, byte in enumerate(b[:4096]):
        j = (byte * (i + 1) + i) % dim
        v[0, j] += float(byte) / 255.0
    n = float(np.linalg.norm(v))
    if n > 1e-6:
        v /= n
    return v


@lru_cache(maxsize=8)
def _session_and_meta_cached(model_path: str, dim_hint: str):
    import onnxruntime as ort  # noqa: WPS433 — опциональная зависимость

    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    session = ort.InferenceSession(model_path, so, providers=["CPUExecutionProvider"])
    inp = session.get_inputs()[0]
    name = inp.name
    shape = inp.shape
    dim = None
    for s in reversed(shape):
        if isinstance(s, int) and s > 0:
            dim = s
            break
    if dim is None and dim_hint.isdigit():
        dim = int(dim_hint)
    if dim is None:
        raise ValueError(
            f"ONNX: не удалось определить размерность входа из shape={shape}; "
            f"задайте ONNX_HS_FEATURE_DIM",
        )
    out0 = session.get_outputs()[0]
    return session, name, dim, out0.name


def run_classify(description: str) -> Optional[Dict[str, Any]]:
    """Синхронный вызов ONNX. None — не настроено, ошибка или пустой текст."""
    if not is_onnx_classifier_configured():
        return None
    desc = (description or "").strip()
    if len(desc) < 3:
        return None
    mp, lp = _model_path(), _labels_path()
    hint = _feature_dim_env() or "auto"
    try:
        labels = list(_load_labels_cached(lp))
        session, in_name, dim, _out_name = _session_and_meta_cached(mp, hint)
        feats = _description_feature_vector(desc, dim)
        logits = session.run(None, {in_name: feats})[0]
        log = np.asarray(logits, dtype=np.float32).reshape(1, -1)[0]
        n_class = log.shape[0]
        if len(labels) < n_class:
            logger.warning(
                f"ONNX: в labels {len(labels)} записей, в модели {n_class} классов — обрежем до min",
            )
        usable = min(len(labels), n_class)
        if usable == 0:
            return None
        log = log[:usable]
        idx = int(np.argmax(log))
        e = np.exp(log - np.max(log))
        prob = float(e[idx] / (e.sum() + 1e-9))
        code = labels[idx]
        return {
            "status": "OK",
            "query": desc,
            "classifier_source": "onnx_local",
            "results": [
                {
                    "code": code,
                    "name": "Локальная модель ONNX",
                    "duty_rate": "n/a",
                    "permits": [],
                    "confidence": round(min(prob, 1.0), 4),
                    "recommended": True,
                    "reasoning": "argmax по логитам ONNX (см. ONNX_HS_CLASSIFIER.md)",
                }
            ],
        }
    except ImportError:
        logger.warning("ONNX_HS_* заданы, но пакет onnxruntime не установлен (pip install onnxruntime)")
        return None
    except Exception as e:
        logger.warning(f"ONNX классификатор: {e}")
        return None


def clear_caches() -> None:
    _load_labels_cached.cache_clear()
    _session_and_meta_cached.cache_clear()
