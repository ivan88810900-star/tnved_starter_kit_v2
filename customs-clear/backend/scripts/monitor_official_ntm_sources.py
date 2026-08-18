#!/usr/bin/env python3
"""Проверка доступности и контрольных сумм официальных источников NTM.

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


def monitor_sources(timeout: float = 60.0) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    headers = {"User-Agent": "Tariff-NTM-source-monitor/1.0"}
    with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers, trust_env=False) as client:
        for source_id, url in SOURCES.items():
            try:
                response = client.get(url)
                body = response.content
                rows.append({
                    "source_id": source_id,
                    "url": url,
                    "final_url": str(response.url),
                    "status_code": response.status_code,
                    "ok": response.status_code == 200 and len(body) > 100,
                    "content_type": response.headers.get("content-type"),
                    "content_length": len(body),
                    "etag": response.headers.get("etag"),
                    "last_modified": response.headers.get("last-modified"),
                    "sha256": hashlib.sha256(body).hexdigest(),
                })
            except Exception as exc:
                rows.append({"source_id": source_id, "url": url, "ok": False, "error": str(exc)})
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "all_available": all(row.get("ok") is True for row in rows),
        "sources": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--strict", action="store_true", help="Exit 1 if any source is unavailable")
    args = parser.parse_args()
    report = monitor_sources(args.timeout)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    return 0 if report["all_available"] or not args.strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
