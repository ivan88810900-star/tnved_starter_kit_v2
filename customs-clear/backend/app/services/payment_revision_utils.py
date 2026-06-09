"""Shared helpers для проверки revision официальных платёжных источников (import duty / EEC ETT)."""

from __future__ import annotations

import re
from typing import Any

# Для официального EEC/ETT import-duty контура принимаем только явные versioned ревизии.
# Допустимые формы: ett:YYYY-MM-DD | eec-ett:YYYY-MM-DD | eec:ett:YYYY-MM-DD
_EEC_ETT_REVISION_RE = re.compile(r"^(?:ett|eec-ett|eec:ett):\d{4}-\d{2}-\d{2}$")
# VAT contour: vat:YYYY-MM-DD | eec-vat:YYYY-MM-DD | eec:vat:YYYY-MM-DD (+ shared ETT forms).
_EEC_VAT_REVISION_RE = re.compile(r"^(?:vat|eec-vat|eec:vat):\d{4}-\d{2}-\d{2}$")


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


def is_official_vat_revision(revision: str | None) -> bool:
    """Строгая проверка revision для official VAT contour (SourceStatus EEC_VAT).

    Принимает VAT-specific формы и shared ETT versioned revisions из общих bundle
    (ett:/eec-ett:/eec:ett:) — но не duty-only arbitrary strings.
    """
    rev = (revision or "").strip().lower()
    if not rev:
        return False
    if _EEC_VAT_REVISION_RE.match(rev):
        return True
    return bool(_EEC_ETT_REVISION_RE.match(rev))


def is_vat_only_bundle_path(rel_path: str) -> bool:
    """Путь VAT-only bundle — не должен использоваться import-duty discovery."""
    norm = rel_path.replace("\\", "/").lower()
    return norm.endswith("/eec_ett_vat.json") or "/eec_ett_vat.json" in norm


def is_import_duty_bundle_path(rel_path: str) -> bool:
    """Путь import-duty bundle — исключает VAT-only файлы."""
    if is_vat_only_bundle_path(rel_path):
        return False
    norm = rel_path.replace("\\", "/").lower()
    return (
        "eec_ett_import_duty" in norm
        or "eec_ett_normative_bundle" in norm
        or "normative_bundle" in norm
    )


def raw_rate_rows(payload: dict[str, Any]) -> tuple[list[Any] | None, str | None]:
    """Единый безопасный доступ к bundle rates/rows.

    rates/rows должны быть JSON-массивом. Возвращает (list, None) при валидном контейнере
    (или [] если оба отсутствуют), либо (None, reason) для malformed non-list контейнера.

    Единый helper для import-duty ingestion и generic payment-source plan, чтобы оба
    пути одинаково отбрасывали malformed контейнеры без TypeError/500.
    """
    raw_rates = payload.get("rates")
    if raw_rates is not None and not isinstance(raw_rates, list):
        return None, "malformed_rates_container"
    raw_rows = payload.get("rows")
    if raw_rows is not None and not isinstance(raw_rows, list):
        return None, "malformed_rows_container"
    if isinstance(raw_rates, list):
        return raw_rates, None
    if isinstance(raw_rows, list):
        return raw_rows, None
    return [], None
