"""Feature flags для canonical read-path дерева ТН ВЭД (ADR-0001 §8, Этап 3).

Централизованный accessor: **никаких** scattered ``os.getenv`` в API/провайдере.
Флаги читаются **на каждый запрос** (request-time), чтобы rollback (переключение
переменной окружения) работал без рестарта процесса.

Оба флага по умолчанию **OFF**:

- ``CANONICAL_TREE_ENABLED`` — при ON структурный слой ``/children`` берётся из
  CanonicalModel (см. ``provider.py``); при OFF — строго legacy path.
- ``CANONICAL_TREE_SHADOW`` — при ON (и ENABLED=OFF) ответ отдаётся legacy, но
  дополнительно в том же запросе безопасно считается canonical-результат и
  сравнивается с legacy; расхождения логируются, на ответ **не** влияют.

Enforcement/adoption-дисциплина ADR: пока Ivan не включит флаг — поведение ровно
как в legacy.
"""

from __future__ import annotations

import os

CANONICAL_TREE_ENABLED_ENV = "CANONICAL_TREE_ENABLED"
CANONICAL_TREE_SHADOW_ENV = "CANONICAL_TREE_SHADOW"

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _env_truthy(name: str) -> bool:
    """True только для явных truthy-значений; отсутствие/пусто/прочее → False."""
    return (os.environ.get(name) or "").strip().lower() in _TRUTHY


def is_canonical_tree_enabled() -> bool:
    """``CANONICAL_TREE_ENABLED`` (default OFF). Читается request-time."""
    return _env_truthy(CANONICAL_TREE_ENABLED_ENV)


def is_canonical_tree_shadow_enabled() -> bool:
    """``CANONICAL_TREE_SHADOW`` (default OFF). Читается request-time."""
    return _env_truthy(CANONICAL_TREE_SHADOW_ENV)
