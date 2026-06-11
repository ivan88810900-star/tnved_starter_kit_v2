"""Shared helpers для проверки revision официальных платёжных источников (import duty / EEC ETT)."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

# Для официального EEC/ETT import-duty контура принимаем только явные versioned ревизии.
# Допустимые формы: ett:YYYY-MM-DD | eec-ett:YYYY-MM-DD | eec:ett:YYYY-MM-DD
_EEC_ETT_REVISION_RE = re.compile(r"^(?:ett|eec-ett|eec:ett):\d{4}-\d{2}-\d{2}$")
# VAT contour: vat:YYYY-MM-DD | eec-vat:YYYY-MM-DD | eec:vat:YYYY-MM-DD (+ shared ETT forms).
_EEC_VAT_REVISION_RE = re.compile(r"^(?:vat|eec-vat|eec:vat):\d{4}-\d{2}-\d{2}$")
# Excise contour: excise:YYYY-MM-DD | eec-excise:YYYY-MM-DD | eec:excise:YYYY-MM-DD.
_EEC_EXCISE_REVISION_RE = re.compile(r"^(?:excise|eec-excise|eec:excise):\d{4}-\d{2}-\d{2}$")
# Anti-dumping contour: anti-dumping:YYYY-MM-DD | eec-anti-dumping:YYYY-MM-DD | eec:anti-dumping:YYYY-MM-DD
_EEC_ANTI_DUMPING_REVISION_RE = re.compile(
    r"^(?:anti-dumping|antidumping|eec-anti-dumping|eec:anti-dumping):\d{4}-\d{2}-\d{2}$"
)

_UNSAFE_OFFICIAL_URL_EXACT = frozenset({"", "manual", "local-copy"})
_UNSAFE_OFFICIAL_URL_SUBSTRINGS = (
    "example.com",
    "localhost",
    "127.0.0.1",
    "seed://",
    "file://",
)


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


def is_official_vat_ingestion_revision(revision: str | None) -> bool:
    """Строгая revision только для VAT ingestion (не import-duty ETT).

    Принимает: vat:YYYY-MM-DD | eec-vat:YYYY-MM-DD | eec:vat:YYYY-MM-DD.
    Отклоняет ett:/eec-ett:/eec:ett: и произвольные non-versioned строки.
    """
    rev = (revision or "").strip().lower()
    if not rev:
        return False
    return bool(_EEC_VAT_REVISION_RE.match(rev))


def is_official_vat_revision(revision: str | None) -> bool:
    """Строгая проверка revision для official VAT contour (SourceStatus EEC_VAT).

    Принимает VAT-specific формы и legacy shared ETT versioned revisions из старых
    VAT import runs (ett:/eec-ett:/eec:ett:) — но не duty-only arbitrary strings.
    """
    rev = (revision or "").strip().lower()
    if not rev:
        return False
    if _EEC_VAT_REVISION_RE.match(rev):
        return True
    return bool(_EEC_ETT_REVISION_RE.match(rev))


def is_official_vat_row_marker(*, vat_source_code: str | None, vat_source_revision: str | None) -> bool:
    """Row-level official VAT proof: marker записан VAT apply для конкретной строки."""
    code = (vat_source_code or "").strip().upper()
    if code != "EEC_VAT":
        return False
    return is_official_vat_ingestion_revision(vat_source_revision)


def is_official_excise_ingestion_revision(revision: str | None) -> bool:
    """Строгая revision только для excise ingestion (не import-duty / VAT)."""
    rev = (revision or "").strip().lower()
    if not rev:
        return False
    return bool(_EEC_EXCISE_REVISION_RE.match(rev))


def is_official_excise_revision(revision: str | None) -> bool:
    """Строгая проверка revision для official excise contour (SourceStatus EEC_EXCISE)."""
    return is_official_excise_ingestion_revision(revision)


def is_official_excise_row_marker(
    *, excise_source_code: str | None, excise_source_revision: str | None
) -> bool:
    """Row-level official excise proof: marker записан excise apply для конкретной строки."""
    code = (excise_source_code or "").strip().upper()
    if code != "EEC_EXCISE":
        return False
    return is_official_excise_ingestion_revision(excise_source_revision)


def is_wrong_domain_revision_in_excise_bundle(revision: str | None) -> bool:
    """Import-duty / VAT revision внутри excise bundle — wrong domain для excise ingestion."""
    rev = (revision or "").strip().lower()
    if not rev:
        return False
    if _EEC_EXCISE_REVISION_RE.match(rev):
        return False
    return bool(_EEC_ETT_REVISION_RE.match(rev)) or bool(_EEC_VAT_REVISION_RE.match(rev))


def is_wrong_domain_eec_ett_revision_in_vat_bundle(revision: str | None) -> bool:
    """ETT duty revision внутри VAT bundle — wrong domain для VAT ingestion."""
    rev = (revision or "").strip().lower()
    if not rev:
        return False
    return bool(_EEC_ETT_REVISION_RE.match(rev)) and not bool(_EEC_VAT_REVISION_RE.match(rev))


def is_vat_only_bundle_path(rel_path: str) -> bool:
    """Путь VAT-only bundle — не должен использоваться import-duty discovery."""
    if is_anti_dumping_only_bundle_path(rel_path):
        return False
    norm = rel_path.replace("\\", "/").lower()
    return norm.endswith("/eec_ett_vat.json") or "/eec_ett_vat.json" in norm


def is_excise_only_bundle_path(rel_path: str) -> bool:
    """Путь excise-only bundle — не должен использоваться import-duty / VAT discovery."""
    norm = rel_path.replace("\\", "/").lower()
    return norm.endswith("/eec_excise.json") or "/eec_excise.json" in norm


def is_anti_dumping_only_bundle_path(rel_path: str) -> bool:
    """Путь anti-dumping-only bundle — не должен использоваться duty/VAT/excise discovery."""
    norm = rel_path.replace("\\", "/").lower()
    return "eec_anti_dumping" in norm or "anti_dumping" in norm


def is_import_duty_bundle_path(rel_path: str) -> bool:
    """Путь import-duty bundle — исключает VAT-only / excise-only / anti-dumping-only файлы."""
    if is_vat_only_bundle_path(rel_path) or is_excise_only_bundle_path(rel_path):
        return False
    if is_anti_dumping_only_bundle_path(rel_path):
        return False
    norm = rel_path.replace("\\", "/").lower()
    return (
        "eec_ett_import_duty" in norm
        or "eec_ett_normative_bundle" in norm
        or "normative_bundle" in norm
    )


def _url_netloc(url: str) -> str:
    return urlparse(url.strip()).netloc.lower()


def is_conservative_official_excise_source_url(
    url: str | None, *, registry_official_url: str | None = None
) -> bool:
    """Консервативная проверка official excise URL — блокирует unsafe placeholders."""
    raw = (url or "").strip()
    if not raw:
        return False
    lower = raw.lower()
    if lower in {"manual", "local-copy", "unknown"}:
        return False
    if "example.com" in lower or "localhost" in lower or "127.0.0.1" in lower:
        return False
    if lower.startswith(("seed://", "file://")):
        return False
    if not lower.startswith("https://"):
        return False
    netloc = _url_netloc(raw)
    if not netloc:
        return False
    if netloc == "nalog.gov.ru" or netloc.endswith(".nalog.gov.ru"):
        return True
    if registry_official_url:
        reg_netloc = _url_netloc(registry_official_url)
        if reg_netloc and netloc == reg_netloc:
            return True
        if reg_netloc and netloc.endswith(reg_netloc):
            return True
    return False


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


def is_unsafe_official_source_url(url: str | None) -> bool:
    """Reject seed/demo/local/blank URLs for official ingestion provenance."""
    u = (url or "").strip().lower()
    if not u or u in _UNSAFE_OFFICIAL_URL_EXACT:
        return True
    return any(token in u for token in _UNSAFE_OFFICIAL_URL_SUBSTRINGS)


def is_official_anti_dumping_ingestion_revision(revision: str | None) -> bool:
    """Strict revision only for anti-dumping ingestion (not duty/VAT/excise)."""
    rev = (revision or "").strip().lower()
    if not rev:
        return False
    return bool(_EEC_ANTI_DUMPING_REVISION_RE.match(rev))


def is_official_anti_dumping_revision(revision: str | None) -> bool:
    """Revision proof for official anti-dumping contour (SourceStatus EEC_ANTI_DUMPING)."""
    return is_official_anti_dumping_ingestion_revision(revision)


def is_official_anti_dumping_row_marker(
    *, source_code: str | None, source_revision: str | None
) -> bool:
    """Row-level official anti-dumping proof on special_duties."""
    code = (source_code or "").strip().upper()
    if code != "EEC_ANTI_DUMPING":
        return False
    return is_official_anti_dumping_ingestion_revision(source_revision)


def is_wrong_domain_revision_in_anti_dumping_bundle(revision: str | None) -> bool:
    """Duty/VAT/excise revisions inside anti-dumping bundle — wrong domain."""
    rev = (revision or "").strip().lower()
    if not rev:
        return False
    if _EEC_ANTI_DUMPING_REVISION_RE.match(rev):
        return False
    return bool(
        _EEC_ETT_REVISION_RE.match(rev)
        or _EEC_VAT_REVISION_RE.match(rev)
        or _EEC_EXCISE_REVISION_RE.match(rev)
    )


def is_wrong_domain_anti_dumping_revision_in_duty_bundle(revision: str | None) -> bool:
    """Anti-dumping revision inside import-duty bundle — wrong domain."""
    rev = (revision or "").strip().lower()
    if not rev:
        return False
    return bool(_EEC_ANTI_DUMPING_REVISION_RE.match(rev))


def is_wrong_domain_anti_dumping_revision_in_vat_bundle(revision: str | None) -> bool:
    """Anti-dumping revision inside VAT bundle — wrong domain."""
    return is_wrong_domain_anti_dumping_revision_in_duty_bundle(revision)


def raw_measure_rows(payload: dict[str, Any]) -> tuple[list[Any] | None, str | None]:
    """Safe access to anti-dumping bundle measures/rows containers."""
    raw_measures = payload.get("measures")
    if raw_measures is not None and not isinstance(raw_measures, list):
        return None, "malformed_measures_container"
    raw_rows = payload.get("rows")
    if raw_rows is not None and not isinstance(raw_rows, list):
        return None, "malformed_rows_container"
    if isinstance(raw_measures, list):
        return raw_measures, None
    if isinstance(raw_rows, list):
        return raw_rows, None
    return [], None
