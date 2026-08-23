#!/usr/bin/env python3
"""Проверка доступности и изменений всех официальных источников.

Скрипт ничего не импортирует в БД и не меняет правила. Его JSON-отчёт пригоден
для хранения как CI artifact и ручного сравнения при изменении документа.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.official_ntm_contours import (  # noqa: E402
    DECISION_30_216_URL,
    DECISION_30_219_URL,
    DECISION_30_UNIFIED_LIST_URL,
    DECISION_299_LIST_URL,
    PP_2425_URL,
    TR_EAEU_036_URL,
    TR_EAEU_050_URL,
    TR_EAEU_051_URL,
    TR_EAEU_052_URL,
    TR_GENERAL_URL,
    TR_TS_007_URL,
    TR_TS_015_URL,
)
from app.services.official_export_control import FSTEC_IDENTIFICATION_URL, PP_1299_URL  # noqa: E402
from app.services.regulatory_source_registry import (  # noqa: E402
    REGULATORY_SOURCE_REGISTRY,
    SOURCE_OF_TRUTH_LEVELS,
)

SOURCES = {
    "eec_decision30_unified_list": DECISION_30_UNIFIED_LIST_URL,
    "eec_decision30_section_2_16": DECISION_30_216_URL,
    "eec_decision30_section_2_19": DECISION_30_219_URL,
    "eec_decision299_sgr_list": DECISION_299_LIST_URL,
    "eec_decision317_veterinary_list": "https://eec.eaeunion.org/upload/medialibrary/89f/Pr.1-Edinyy-perechen-tov.pdf",
    "eec_decision318_phytosanitary_list": "https://eec.eaeunion.org/upload/medialibrary/60f/x9vhmm3gi76102uwhqlv7iffol64r6lo/Perechen-produktsii.pdf",
    "eec_decision157_phytosanitary_requirements": "https://eec.eaeunion.org/upload/medialibrary/e83/ne3jhyoymc2i57nx91wzn5fihnoi28ap/EKFT-v-red.-Resh.-_80.pdf",
    "rf_pp1299_dual_use": PP_1299_URL,
    "rf_pp1284_chemical_control": "https://publication.pravo.gov.ru/Document/View/0001202207190026",
    "rf_pp1285_nuclear_control": "https://publication.pravo.gov.ru/Document/View/0001202207190029",
    "rf_pp1286_nuclear_dual_use": "https://publication.pravo.gov.ru/Document/View/0001202207190018",
    "rf_pp1287_biological_control": "https://publication.pravo.gov.ru/Document/View/0001202207190030",
    "rf_pp1288_missile_control": "https://publication.pravo.gov.ru/Document/View/0001202207190036",
    "fstec_identification_expertise": FSTEC_IDENTIFICATION_URL,
    "rf_pp_2425": PP_2425_URL,
    "eec_tr_ts_007": TR_TS_007_URL,
    "eec_tr_ts_015": TR_TS_015_URL,
    "eec_tr_eaeu_036": TR_EAEU_036_URL,
    "eec_tr_eaeu_050": TR_EAEU_050_URL,
    "eec_tr_eaeu_051": TR_EAEU_051_URL,
    "eec_tr_eaeu_052": TR_EAEU_052_URL,
    "eec_technical_regulations": TR_GENERAL_URL,
    "eec_sanitary_measures": "https://eec.eaeunion.org/comission/department/depsanmer/regulation/sanitarnye-mery.php",
    "eec_veterinary_measures": "https://eec.eaeunion.org/comission/department/depsanmer/regulation/veterinarno-sanitarnye-mery.php",
    "eec_phytosanitary_measures": "https://eec.eaeunion.org/comission/department/depsanmer/regulation/karantinnye-fitosanitarnye-mery.php",
}

# Реестр является основным каталогом. Точные URL отдельных приложений к НПА
# выше сохраняются дополнительно, потому что одна карточка источника может
# содержать несколько юридически значимых документов.
for _entry in REGULATORY_SOURCE_REGISTRY:
    if _entry.official_url and _entry.authority_level in SOURCE_OF_TRUTH_LEVELS:
        SOURCES.setdefault(_entry.source_id, _entry.official_url)


def _load_state(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {"sources": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("sources"), dict):
            return data
    except Exception:
        pass
    return {"sources": {}}


def monitor_sources(timeout: float = 60.0, *, previous_state: dict[str, Any] | None = None) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    previous_sources = (previous_state or {}).get("sources") or {}
    has_previous_baseline = bool(previous_sources)
    headers = {"User-Agent": "Tariff-regulatory-source-monitor/2.0"}
    next_sources = dict(previous_sources)
    with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers, trust_env=False) as client:
        for source_id, url in SOURCES.items():
            previous = previous_sources.get(source_id) or {}
            request_headers: dict[str, str] = {}
            if previous.get("etag"):
                request_headers["If-None-Match"] = str(previous["etag"])
            if previous.get("last_modified"):
                request_headers["If-Modified-Since"] = str(previous["last_modified"])
            try:
                response = client.get(url, headers=request_headers)
                if response.status_code == 304 and previous.get("sha256"):
                    row = {
                        "source_id": source_id,
                        "url": url,
                        "final_url": previous.get("final_url") or url,
                        "status_code": 304,
                        "ok": True,
                        "not_modified": True,
                        "changed": False,
                        "new_source": False,
                        "content_type": previous.get("content_type"),
                        "content_length": previous.get("content_length"),
                        "etag": response.headers.get("etag") or previous.get("etag"),
                        "last_modified": response.headers.get("last-modified") or previous.get("last_modified"),
                        "sha256": previous.get("sha256"),
                    }
                    rows.append(row)
                    continue
                body = response.content
                digest = hashlib.sha256(body).hexdigest()
                ok = response.status_code == 200 and len(body) > 100
                is_new = ok and not bool(previous.get("sha256"))
                changed = ok and bool(previous.get("sha256")) and previous.get("sha256") != digest
                row = {
                    "source_id": source_id,
                    "url": url,
                    "final_url": str(response.url),
                    "status_code": response.status_code,
                    "ok": ok,
                    "not_modified": False,
                    "changed": changed,
                    "new_source": is_new,
                    "content_type": response.headers.get("content-type"),
                    "content_length": len(body),
                    "etag": response.headers.get("etag"),
                    "last_modified": response.headers.get("last-modified"),
                    "sha256": digest,
                }
                rows.append(row)
                if ok:
                    next_sources[source_id] = {
                        key: row.get(key)
                        for key in (
                            "url",
                            "final_url",
                            "content_type",
                            "content_length",
                            "etag",
                            "last_modified",
                            "sha256",
                        )
                    }
            except Exception as exc:
                rows.append(
                    {
                        "source_id": source_id,
                        "url": url,
                        "ok": False,
                        "changed": False,
                        "new_source": False,
                        "error": str(exc),
                    }
                )
    changed_ids = [row["source_id"] for row in rows if row.get("changed")]
    new_ids = [row["source_id"] for row in rows if row.get("new_source")]
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "all_available": all(row.get("ok") is True for row in rows),
        "had_previous_baseline": has_previous_baseline,
        "changed_source_ids": changed_ids,
        "new_source_ids": new_ids,
        "review_required": bool(changed_ids or (has_previous_baseline and new_ids)),
        "sources": rows,
        "next_state": {
            "version": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "sources": next_sources,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--state", type=Path, help="Persisted checksum/ETag baseline")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--strict", action="store_true", help="Exit 1 if any source is unavailable")
    args = parser.parse_args()
    previous_state = _load_state(args.state)
    report = monitor_sources(args.timeout, previous_state=previous_state)
    next_state = report.pop("next_state")
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    if args.state:
        args.state.parent.mkdir(parents=True, exist_ok=True)
        args.state.write_text(json.dumps(next_state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if report["all_available"] or not args.strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
