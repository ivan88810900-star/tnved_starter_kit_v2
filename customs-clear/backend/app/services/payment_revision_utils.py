"""Shared helpers для проверки revision официальных платёжных источников (import duty / EEC ETT)."""

from __future__ import annotations

import re

# Для официального EEC/ETT import-duty контура принимаем только явные versioned ревизии.
# Допустимые формы: ett:YYYY-MM-DD | eec-ett:YYYY-MM-DD | eec:ett:YYYY-MM-DD
_EEC_ETT_REVISION_RE = re.compile(r"^(?:ett|eec-ett|eec:ett):\d{4}-\d{2}-\d{2}$")


def is_official_eec_ett_revision(revision: str | None) -> bool:
    """Строгая проверка: revision должна быть explicit versioned EEC/ETT, не произвольная строка.

    Отсекает empty/unknown/seed/fallback/legacy/demo/test/example, а также
    arbitrary non-versioned (`local-copy`, `foo`, `manual`, `prod`, `official`).
    Единый источник истины и для ingestion (apply/dry-run), и для official-only coverage.
    """
    rev = (revision or "").strip().lower()
    if not rev:
        return False
    return bool(_EEC_ETT_REVISION_RE.match(rev))
