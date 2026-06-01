"""Импорт единого пакета: ТН ВЭД (наименования), ставки, нетарифка, примечания."""
from __future__ import annotations

import json
import re
from typing import Any

from loguru import logger

from .normative_store import (
    append_sync_log,
    normalize_hs_duty_rate_string,
    upsert_hs_rate,
    upsert_normative_note,
    upsert_non_tariff_rule,
    upsert_source_status,
    upsert_tnved_entry,
)


BUNDLE_FORMAT_KEY = "customs_clear_normative_bundle"
BUNDLE_VERSION = 1


def _is_bundle_payload(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    if data.get("format") == BUNDLE_FORMAT_KEY:
        return True
    if data.get(BUNDLE_FORMAT_KEY) is True:
        return True
    # Эвристика: явные секции пакета
    if "tnved" in data and isinstance(data["tnved"], list):
        return True
    if "notes" in data and "rates" in data:
        return True
    return False


def _norm_hs(s: Any) -> str:
    d = re.sub(r"\D", "", str(s or ""))[:10]
    return d


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(str(v).replace(",", "."))
    except Exception:
        return default


def _to_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in {"1", "true", "yes", "y", "да"}


def _normalize_rate_row(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Совместимо с source_import._normalize_row (без циклического импорта)."""
    row = dict(raw)
    hc_raw = row.get("hs_code")
    if hc_raw is not None and str(hc_raw).strip():
        digits = re.sub(r"\D", "", str(hc_raw))[:10]
        if len(digits) >= 4:
            row["hs_code"] = digits
            if not str(row.get("hs_prefix") or "").strip():
                row["hs_prefix"] = digits[:4]
    hs_prefix = str(row.get("hs_prefix") or row.get("hs_code") or "").strip()
    if not hs_prefix:
        return None
    return {
        "hs_code": str(row.get("hs_code") or hs_prefix).strip(),
        "hs_prefix": hs_prefix,
        "duty_rate": normalize_hs_duty_rate_string(row.get("duty_rate")),
        "vat_import_rate": _to_float(row.get("vat_import_rate"), 22.0),
        "vat_rule": str(row.get("vat_rule") or "none").strip(),
        "vat_rule_basis": str(row.get("vat_rule_basis") or "").strip(),
        "excise_type": str(row.get("excise_type") or "none").strip(),
        "excise_value": _to_float(row.get("excise_value"), 0.0),
        "excise_basis": str(row.get("excise_basis") or "").strip(),
        "has_antidumping": _to_bool(row.get("has_antidumping")),
        "antidumping_type": str(row.get("antidumping_type") or "none").strip(),
        "antidumping_value": _to_float(row.get("antidumping_value"), 0.0),
        "antidumping_condition": str(row.get("antidumping_condition") or "").strip(),
        "antidumping_countries": str(row.get("antidumping_countries") or "").strip(),
        "valid_from": str(row.get("valid_from") or "").strip(),
        "valid_to": str(row.get("valid_to") or "").strip(),
        "source_url": str(row.get("source_url") or "").strip(),
        "source_revision": str(row.get("source_revision") or "").strip(),
    }


def import_normative_bundle_dict(
    data: dict[str, Any],
    *,
    filename: str = "bundle.json",
    source_code: str = "NORMATIVE_BUNDLE",
    source_name: str = "Пакет ТН ВЭД / ЕТТ / нетарифка",
) -> dict[str, Any]:
    revision = str(data.get("revision") or data.get("source_revision") or "bundle-import")
    official_base = str(
        data.get("official_ett_url")
        or "https://eec.eaeunion.org/comission/department/catr/ett/"
    )
    official_nts = str(
        data.get("official_nts_url")
        or "https://eec.eaeunion.org/comission/department/nts/"
    )

    n_tnved = n_rates = n_nt = n_notes = 0
    skipped = {"tnved": 0, "rates": 0, "non_tariff": 0, "notes": 0}

    for raw in data.get("tnved") or []:
        if not isinstance(raw, dict):
            skipped["tnved"] += 1
            continue
        code = _norm_hs(raw.get("hs_code"))
        if len(code) < 2:
            skipped["tnved"] += 1
            continue
        upsert_tnved_entry(
            {
                "hs_code": code,
                "parent_hs": _norm_hs(raw.get("parent_hs")) or "",
                "level": int(raw.get("level") or len(code)),
                "title": str(raw.get("title") or raw.get("name") or "").strip(),
                "description": str(raw.get("description") or raw.get("text") or "").strip(),
                "chapter": str(raw.get("chapter") or code[:2]).strip()[:2],
                "source_url": str(raw.get("source_url") or official_base).strip(),
                "source_revision": str(raw.get("source_revision") or revision).strip(),
            }
        )
        n_tnved += 1

    for raw in data.get("rates") or data.get("rows") or []:
        if not isinstance(raw, dict):
            skipped["rates"] += 1
            continue
        try:
            row = _normalize_rate_row(raw)
            if row:
                # _normalize_rate_row всегда кладёт ключ source_revision (возможно ""),
                # поэтому setdefault не сработает. Наследуем bundle revision для blank/None.
                if not str(row.get("source_revision") or "").strip():
                    row["source_revision"] = revision
                upsert_hs_rate(row)
                n_rates += 1
            else:
                skipped["rates"] += 1
        except Exception as e:
            logger.warning(f"Bundle rate row skip: {e}")
            skipped["rates"] += 1

    for raw in data.get("non_tariff_rules") or data.get("non_tariff") or []:
        if not isinstance(raw, dict):
            skipped["non_tariff"] += 1
            continue
        pref = _norm_hs(raw.get("hs_prefix") or raw.get("hs_code"))
        if len(pref) < 2:
            skipped["non_tariff"] += 1
            continue
        upsert_non_tariff_rule(
            {
                "name": str(raw.get("name") or "Правило").strip(),
                "hs_prefix": pref[:10],
                "tr_ts": str(raw.get("tr_ts") or raw.get("tr_ts_codes") or "").strip(),
                "required_permits": str(raw.get("required_permits") or raw.get("permits") or "").strip(),
                "tr_ts_edition": str(raw.get("tr_ts_edition") or raw.get("tr_edition") or "").strip(),
                "exception_note": str(raw.get("exception_note") or raw.get("exceptions") or "").strip(),
                "priority": int(raw.get("priority") or 0),
                "valid_from": str(raw.get("valid_from") or "").strip(),
                "valid_to": str(raw.get("valid_to") or "").strip(),
                "source_url": str(raw.get("source_url") or official_nts).strip(),
                "source_revision": str(raw.get("source_revision") or revision).strip(),
            }
        )
        n_nt += 1

    for raw in data.get("notes") or []:
        if not isinstance(raw, dict):
            skipped["notes"] += 1
            continue
        st = str(raw.get("scope_type") or "prefix").strip().lower()
        if st not in ("hs_code", "prefix", "chapter", "global"):
            st = "prefix"
        sv = str(raw.get("scope_value") or raw.get("hs_code") or raw.get("prefix") or "").strip()
        if st == "global":
            sv = ""
        else:
            sv = _norm_hs(sv) if st != "chapter" else re.sub(r"\D", "", sv)[:2]
        cat = str(raw.get("category") or "general").strip().lower()
        if cat not in ("tnved", "ett", "non_tariff", "general"):
            cat = "general"
        upsert_normative_note(
            {
                "scope_type": st,
                "scope_value": sv,
                "category": cat,
                "title": str(raw.get("title") or "").strip() or "Примечание",
                "body": str(raw.get("body") or raw.get("text") or "").strip(),
                "source_url": str(raw.get("source_url") or official_base).strip(),
                "source_revision": str(raw.get("source_revision") or revision).strip(),
                "sort_order": int(raw.get("sort_order") or 0),
            }
        )
        n_notes += 1

    note_txt = (
        f"Пакет {filename}: ТН ВЭД={n_tnved}, ставки={n_rates}, "
        f"нетариф={n_nt}, примечания={n_notes}; пропуски={skipped}"
    )
    upsert_source_status(
        source_code=source_code,
        source_name=source_name,
        source_url=filename,
        revision=revision,
        is_stale=False,
        note=note_txt,
    )
    append_sync_log(
        source_code=source_code,
        status="OK",
        revision=revision,
        rows_affected=n_tnved + n_rates + n_nt + n_notes,
        note=note_txt,
    )
    logger.info(note_txt)
    return {
        "status": "OK",
        "revision": revision,
        "imported": {
            "tnved": n_tnved,
            "rates": n_rates,
            "non_tariff_rules": n_nt,
            "notes": n_notes,
        },
        "skipped": skipped,
    }


def import_normative_bundle_bytes(
    content: bytes,
    filename: str = "bundle.json",
    **kwargs: Any,
) -> dict[str, Any]:
    data = json.loads(content.decode("utf-8", errors="strict"))
    if not isinstance(data, dict):
        raise ValueError("Пакет должен быть JSON-объектом")
    if not _is_bundle_payload(data):
        raise ValueError(
            "Не распознан пакет. Укажите format: 'customs_clear_normative_bundle' "
            "или передайте ключи tnved / rates / notes."
        )
    data.setdefault("format", BUNDLE_FORMAT_KEY)
    data.setdefault("bundle_version", BUNDLE_VERSION)
    return import_normative_bundle_dict(data, filename=filename, **kwargs)
