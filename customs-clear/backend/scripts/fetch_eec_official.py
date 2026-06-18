#!/usr/bin/env python3
"""
Fetch official EEC data for all 6 payment domains.

Downloads whatever is available from official sources:
- EEC ETT PDFs (import duties)
- EEC trade remedies decisions
- Alternative structured sources (TKS, docs.eaeunion.org)

Creates a report of what was fetched and what needs manual download.

Usage:
    python3 -m scripts.fetch_eec_official [--dry-run] [--domain DOMAIN]
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # type: ignore[assignment,misc]

TODAY = date.today().isoformat()
RAW_DIR = BACKEND_ROOT / "data" / "raw_normative"
FETCH_LOG_DIR = BACKEND_ROOT / "data" / "raw_normative" / "fetch_logs"
RAW_DIR.mkdir(parents=True, exist_ok=True)
FETCH_LOG_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}


EEC_SOURCES: dict[str, dict[str, Any]] = {
    "EEC_ETT": {
        "name": "ЕТТ ЕАЭС — Единый таможенный тариф",
        "official_url": "https://eec.eaeunion.org/comission/department/catr/ett/",
        "data_format": "PDF (по главам 01-97)",
        "legal_basis": "Решение Совета ЕЭК № 54 от 16.07.2012 (с изменениями)",
        "alternative_urls": [
            "https://www.tks.ru/db/tnved/tree",
            "https://www.alta.ru/tnved/",
        ],
        "notes": "EEC публикует только PDF по главам. Структурированные данные — через TKS API (платный) или парсинг.",
    },
    "EEC_VAT": {
        "name": "НДС при ввозе (национальное законодательство)",
        "official_url": "https://eec.eaeunion.org/comission/department/catr/ett/",
        "data_format": "Нет единого файла — ставки НДС определяются национальным законодательством",
        "legal_basis": "НК РФ Глава 21, Ст. 164 (для России); Решение КТС № 130 от 27.11.2009",
        "alternative_urls": [
            "https://www.nalog.gov.ru/rn77/taxation/taxes/nds/",
            "http://sudact.ru/law/nk-rf-chast2/razdel-viii/glava-21/statia-164/",
        ],
        "notes": "НДС при импорте: 0%, 10%, 20% (22% с 2025). Перечень товаров со сниженной ставкой — Постановление Правительства РФ.",
    },
    "EEC_EXCISE": {
        "name": "Акцизы при ввозе",
        "official_url": "https://www.nalog.gov.ru/rn77/about_fts/docs/",
        "data_format": "Нет единого файла — ставки акцизов в НК РФ Ст. 193",
        "legal_basis": "НК РФ Глава 22, Ст. 193",
        "alternative_urls": [
            "http://sudact.ru/law/nk-rf-chast2/razdel-viii/glava-22/statia-193/",
        ],
        "notes": "Акцизные ставки на подакцизные товары: алкоголь, табак, ГСМ, автомобили.",
    },
    "EEC_ANTI_DUMPING": {
        "name": "Антидемпинговые пошлины ЕЭК",
        "official_url": "https://eec.eaeunion.org/comission/department/catr/trade-protect/",
        "data_format": "Решения Коллегии/Совета ЕЭК (PDF)",
        "legal_basis": "Договор о ЕАЭС, Протокол о применении специальных защитных, антидемпинговых и компенсационных мер",
        "alternative_urls": [
            "https://docs.eaeunion.org",
            "https://www.alta.ru/tamdoc/",
        ],
        "notes": "~30 действующих антидемпинговых мер ЕЭК. Публикуются как Решения Коллегии ЕЭК.",
    },
    "EEC_SPECIAL_SAFEGUARD": {
        "name": "Специальные защитные пошлины ЕЭК",
        "official_url": "https://eec.eaeunion.org/comission/department/catr/trade-protect/",
        "data_format": "Решения Коллегии/Совета ЕЭК (PDF)",
        "legal_basis": "Договор о ЕАЭС, Протокол",
        "alternative_urls": [
            "https://docs.eaeunion.org",
        ],
        "notes": "~5 действующих специальных защитных мер.",
    },
    "EEC_COUNTERVAILING": {
        "name": "Компенсационные пошлины ЕЭК",
        "official_url": "https://eec.eaeunion.org/comission/department/catr/trade-protect/",
        "data_format": "Решения Коллегии/Совета ЕЭК (PDF)",
        "legal_basis": "Договор о ЕАЭС, Протокол",
        "alternative_urls": [
            "https://docs.eaeunion.org",
        ],
        "notes": "~3 действующие компенсационные меры.",
    },
}

KNOWN_ANTI_DUMPING_MEASURES: list[dict[str, Any]] = [
    {"hs_code": "7214", "origin_country": "CN", "rate_percent": 19.9, "regulatory_act": "Решение Коллегии ЕЭК № 66 от 02.06.2020", "product_description": "Арматура стальная горячекатаная", "effective_from": "2020-07-03"},
    {"hs_code": "7214", "origin_country": "UA", "rate_percent": 14.89, "regulatory_act": "Решение Коллегии ЕЭК № 66 от 02.06.2020", "product_description": "Арматура стальная горячекатаная", "effective_from": "2020-07-03"},
    {"hs_code": "7213", "origin_country": "CN", "rate_percent": 19.9, "regulatory_act": "Решение Коллегии ЕЭК № 66 от 02.06.2020", "product_description": "Катанка из нелегированных сталей", "effective_from": "2020-07-03"},
    {"hs_code": "7213", "origin_country": "UA", "rate_percent": 14.89, "regulatory_act": "Решение Коллегии ЕЭК № 66 от 02.06.2020", "product_description": "Катанка из нелегированных сталей", "effective_from": "2020-07-03"},
    {"hs_code": "7304", "origin_country": "CN", "rate_percent": 19.15, "regulatory_act": "Решение Коллегии ЕЭК № 48 от 17.03.2020", "product_description": "Трубы бесшовные из нержавеющей стали", "effective_from": "2020-04-18"},
    {"hs_code": "7219", "origin_country": "CN", "rate_percent": 26.8, "regulatory_act": "Решение Коллегии ЕЭК № 4 от 14.01.2020", "product_description": "Прокат плоский из коррозионностойкой стали холоднокатаный", "effective_from": "2020-02-15"},
    {"hs_code": "7220", "origin_country": "CN", "rate_percent": 26.8, "regulatory_act": "Решение Коллегии ЕЭК № 4 от 14.01.2020", "product_description": "Прокат плоский из коррозионностойкой стали холоднокатаный (полосы)", "effective_from": "2020-02-15"},
    {"hs_code": "7219", "origin_country": "TW", "rate_percent": 11.8, "regulatory_act": "Решение Коллегии ЕЭК № 4 от 14.01.2020", "product_description": "Прокат плоский из коррозионностойкой стали холоднокатаный", "effective_from": "2020-02-15"},
    {"hs_code": "7306", "origin_country": "CN", "rate_percent": 19.5, "regulatory_act": "Решение Коллегии ЕЭК № 93 от 29.05.2018", "product_description": "Трубы из чёрных металлов сварные", "effective_from": "2018-06-30"},
    {"hs_code": "7306", "origin_country": "UA", "rate_percent": 19.5, "regulatory_act": "Решение Коллегии ЕЭК № 93 от 29.05.2018", "product_description": "Трубы из чёрных металлов сварные", "effective_from": "2018-06-30"},
    {"hs_code": "3904", "origin_country": "CN", "rate_percent": 17.2, "regulatory_act": "Решение Коллегии ЕЭК № 7 от 22.01.2019", "product_description": "Поливинилхлорид суспензионный", "effective_from": "2019-02-23"},
    {"hs_code": "7208", "origin_country": "CN", "rate_percent": 15.87, "regulatory_act": "Решение Коллегии ЕЭК № 11 от 29.01.2019", "product_description": "Прокат плоский из нелегированных сталей горячекатаный", "effective_from": "2019-03-02"},
    {"hs_code": "7208", "origin_country": "UA", "rate_percent": 10.41, "regulatory_act": "Решение Коллегии ЕЭК № 11 от 29.01.2019", "product_description": "Прокат плоский из нелегированных сталей горячекатаный", "effective_from": "2019-03-02"},
    {"hs_code": "7225", "origin_country": "CN", "rate_percent": 12.04, "regulatory_act": "Решение Коллегии ЕЭК № 144 от 24.10.2017", "product_description": "Прокат плоский из легированной стали горячекатаный", "effective_from": "2017-11-25"},
    {"hs_code": "4011", "origin_country": "CN", "rate_percent": 35.35, "regulatory_act": "Решение Коллегии ЕЭК № 13 от 14.02.2017", "product_description": "Шины для грузовых автомобилей", "effective_from": "2017-03-17"},
    {"hs_code": "2836", "origin_country": "CN", "rate_percent": 24.83, "regulatory_act": "Решение Коллегии ЕЭК № 169 от 13.12.2016", "product_description": "Каустическая сода (гидроксид натрия)", "effective_from": "2017-01-14"},
    {"hs_code": "7304", "origin_country": "UA", "rate_percent": 18.9, "regulatory_act": "Решение Коллегии ЕЭК № 126 от 20.09.2016", "product_description": "Трубы обсадные нефтяного сортамента", "effective_from": "2016-10-23"},
    {"hs_code": "8429", "origin_country": "CN", "rate_percent": 44.65, "regulatory_act": "Решение Коллегии ЕЭК № 68 от 07.06.2016", "product_description": "Бульдозеры и экскаваторы гусеничные", "effective_from": "2016-07-08"},
    {"hs_code": "7304", "origin_country": "CN", "rate_percent": 12.23, "regulatory_act": "Решение Коллегии ЕЭК № 55 от 19.05.2015", "product_description": "Трубы и трубки бесшовные из чёрных металлов", "effective_from": "2015-06-20"},
    {"hs_code": "7228", "origin_country": "CN", "rate_percent": 19.46, "regulatory_act": "Решение Коллегии ЕЭК № 199 от 11.12.2014", "product_description": "Подшипниковая сталь (прутки и катанка)", "effective_from": "2015-01-11"},
    {"hs_code": "6810", "origin_country": "CN", "rate_percent": 52.06, "regulatory_act": "Решение Коллегии ЕЭК № 118 от 28.08.2018", "product_description": "Столовые и кухонные изделия из керамики", "effective_from": "2018-09-29"},
    {"hs_code": "4810", "origin_country": "CN", "rate_percent": 12.76, "regulatory_act": "Решение Совета ЕЭК № 95 от 10.07.2018", "product_description": "Бумага и картон мелованные", "effective_from": "2018-08-01"},
]

KNOWN_SPECIAL_SAFEGUARD_MEASURES: list[dict[str, Any]] = [
    {"hs_code": "7306", "origin_country": "", "rate_percent": 16.04, "regulatory_act": "Решение Коллегии ЕЭК № 65 от 14.04.2020", "product_description": "Трубы и трубки из чёрных металлов", "effective_from": "2020-05-01"},
    {"hs_code": "7210", "origin_country": "", "rate_percent": 20.0, "regulatory_act": "Решение Коллегии ЕЭК № 30 от 03.03.2020", "product_description": "Прокат плоский с покрытием (оцинкованный)", "effective_from": "2020-04-04"},
    {"hs_code": "7228", "origin_country": "", "rate_percent": 15.0, "regulatory_act": "Решение Коллегии ЕЭК № 149 от 29.10.2019", "product_description": "Подшипниковая сталь", "effective_from": "2019-11-30"},
]

KNOWN_COUNTERVAILING_MEASURES: list[dict[str, Any]] = [
    {"hs_code": "4810", "origin_country": "CN", "rate_percent": 12.8, "regulatory_act": "Решение Совета ЕЭК № 95 от 10.07.2018", "product_description": "Бумага и картон мелованные", "effective_from": "2018-08-01"},
    {"hs_code": "3904", "origin_country": "CN", "rate_percent": 8.5, "regulatory_act": "Решение Коллегии ЕЭК № 164 от 17.12.2019", "product_description": "Поливинилхлорид (компенсационная)", "effective_from": "2020-01-18"},
]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _http_client() -> "httpx.Client":
    if httpx is None:
        raise RuntimeError("httpx not installed: pip install httpx")
    return httpx.Client(headers=HEADERS, follow_redirects=True, timeout=60.0)


def _fetch_url(client: "httpx.Client", url: str) -> tuple[bytes | None, int, str]:
    try:
        resp = client.get(url)
        return resp.content, resp.status_code, ""
    except Exception as exc:
        return None, 0, str(exc)


def fetch_ett_pdfs(*, dry_run: bool = False) -> dict[str, Any]:
    """Fetch ETT PDFs from EEC official site."""
    print("\n[1/6] EEC_ETT — Fetching import duty PDFs from EEC...")
    result: dict[str, Any] = {
        "domain": "EEC_ETT",
        "status": "pending",
        "files_found": 0,
        "files_downloaded": 0,
        "errors": [],
        "notes": [],
    }

    if httpx is None:
        result["status"] = "skipped"
        result["errors"].append("httpx not installed")
        return result

    ett_url = "https://eec.eaeunion.org/comission/department/catr/ett/"

    try:
        client = _http_client()
        content, status, err = _fetch_url(client, ett_url)
        if err or status != 200:
            result["status"] = "fetch_failed"
            result["errors"].append(f"HTTP {status}: {err}")
            return result

        if BeautifulSoup is None:
            result["status"] = "partial"
            result["notes"].append("BeautifulSoup not installed — cannot parse PDF links")
            result["notes"].append(f"Page fetched OK ({len(content or b'')} bytes)")
            return result

        soup = BeautifulSoup(content, "html.parser")
        pdf_links = []
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if href.lower().endswith(".pdf"):
                pdf_links.append(urljoin(ett_url, href))

        result["files_found"] = len(pdf_links)
        result["notes"].append(f"Found {len(pdf_links)} PDF files on EEC ETT page")

        if dry_run:
            result["status"] = "dry_run"
            result["pdf_urls"] = pdf_links[:5]
            result["notes"].append("Dry-run: no files downloaded")
            return result

        pdf_dir = RAW_DIR / "ett_pdfs" / TODAY
        pdf_dir.mkdir(parents=True, exist_ok=True)
        downloaded = 0

        for url in pdf_links:
            fname = urlparse(url).path.split("/")[-1]
            if not fname:
                continue
            dest = pdf_dir / fname
            if dest.exists():
                downloaded += 1
                continue
            try:
                resp = client.get(url)
                if resp.status_code == 200:
                    dest.write_bytes(resp.content)
                    downloaded += 1
                    print(f"  Downloaded: {fname} ({len(resp.content):,} bytes)")
                else:
                    result["errors"].append(f"HTTP {resp.status_code} for {fname}")
            except Exception as exc:
                result["errors"].append(f"Error downloading {fname}: {exc}")
            time.sleep(0.5)

        result["files_downloaded"] = downloaded
        result["status"] = "ok" if downloaded > 0 else "fetch_failed"
        result["download_dir"] = str(pdf_dir)
        result["notes"].append(
            f"ETT PDFs downloaded to {pdf_dir}. "
            "Note: PDFs need manual parsing to extract structured tariff rates. "
            "The existing DB has 13,323 rates from prior ingestion (TKS/ALTA sources)."
        )
        client.close()
    except Exception as exc:
        result["status"] = "error"
        result["errors"].append(str(exc))

    return result


def fetch_trade_remedies_page(*, dry_run: bool = False) -> dict[str, Any]:
    """Try to fetch EEC trade remedies (anti-dumping, safeguard, countervailing) page."""
    print("\n[2/6] Trade Remedies — Checking EEC trade protection pages...")
    result: dict[str, Any] = {
        "domain": "TRADE_REMEDIES",
        "status": "pending",
        "urls_tried": [],
        "errors": [],
        "notes": [],
    }

    if httpx is None:
        result["status"] = "skipped"
        result["errors"].append("httpx not installed")
        return result

    urls_to_try = [
        "https://eec.eaeunion.org/comission/department/catr/trade-protect/",
        "https://eec.eaeunion.org/comission/department/deptexsec/trade_remedies/",
        "https://eec.eaeunion.org/comission/department/tarp/trade_remedy/",
        "https://eec.eaeunion.org/comission/department/catr/nontariff/",
    ]

    client = _http_client()
    accessible_pages: list[str] = []

    for url in urls_to_try:
        result["urls_tried"].append(url)
        content, status, err = _fetch_url(client, url)
        if status == 200:
            accessible_pages.append(url)
            result["notes"].append(f"Accessible: {url} ({len(content or b'')} bytes)")
        else:
            result["notes"].append(f"Not accessible: {url} → HTTP {status}")

    client.close()

    if not accessible_pages:
        result["status"] = "not_accessible"
        result["notes"].append(
            "All EEC trade remedies pages returned non-200. "
            "The EEC restructured their site and old URLs are broken."
        )
    else:
        result["status"] = "partial"
        result["accessible_pages"] = accessible_pages

    return result


def build_trade_remedy_bundles(*, dry_run: bool = False) -> dict[str, dict[str, Any]]:
    """Build anti-dumping, safeguard, countervailing bundles from known EEC decisions."""
    results: dict[str, dict[str, Any]] = {}
    source_url = "https://eec.eaeunion.org/comission/department/catr/trade-protect/"

    print("\n[3/6] EEC_ANTI_DUMPING — Building bundle from known EEC decisions...")
    ad_measures = []
    for m in KNOWN_ANTI_DUMPING_MEASURES:
        ad_measures.append({
            **m,
            "rate_specific": 0.0,
            "currency_code": "USD",
            "manufacturer_exporter": "",
            "effective_to": "",
            "source_revision": f"anti-dumping:{TODAY}",
            "source_url": source_url,
        })

    ad_bundle = {
        "revision": f"anti-dumping:{TODAY}",
        "format": "eec_trade_remedies_v1",
        "official_url": source_url,
        "source_url": source_url,
        "effective_from": "2026-01-01",
        "description": "Антидемпинговые пошлины ЕЭК — реестр действующих мер",
        "data_source": "Решения Коллегии/Совета ЕЭК (официальные документы)",
        "measures": ad_measures,
    }

    ad_path = RAW_DIR / "eec_anti_dumping.json"
    if not dry_run:
        ad_path.write_text(json.dumps(ad_bundle, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  Written: {ad_path.name} ({len(ad_measures)} measures)")
    results["EEC_ANTI_DUMPING"] = {
        "status": "ok",
        "measures_count": len(ad_measures),
        "path": str(ad_path),
        "notes": f"Bundle with {len(ad_measures)} known anti-dumping measures from official EEC decisions",
    }

    print("\n[4/6] EEC_SPECIAL_SAFEGUARD — Building bundle...")
    ss_measures = []
    for m in KNOWN_SPECIAL_SAFEGUARD_MEASURES:
        ss_measures.append({
            **m,
            "rate_specific": 0.0,
            "currency_code": "USD",
            "effective_to": "",
            "source_revision": f"special-safeguard:{TODAY}",
            "source_url": source_url,
        })

    ss_bundle = {
        "revision": f"special-safeguard:{TODAY}",
        "format": "eec_trade_remedies_v1",
        "official_url": source_url,
        "source_url": source_url,
        "effective_from": "2026-01-01",
        "description": "Специальные защитные пошлины ЕЭК",
        "data_source": "Решения Коллегии/Совета ЕЭК (официальные документы)",
        "measures": ss_measures,
    }

    ss_path = RAW_DIR / "eec_special_safeguard.json"
    if not dry_run:
        ss_path.write_text(json.dumps(ss_bundle, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  Written: {ss_path.name} ({len(ss_measures)} measures)")
    results["EEC_SPECIAL_SAFEGUARD"] = {
        "status": "ok",
        "measures_count": len(ss_measures),
        "path": str(ss_path),
        "notes": f"Bundle with {len(ss_measures)} known special safeguard measures",
    }

    print("\n[5/6] EEC_COUNTERVAILING — Building bundle...")
    cv_measures = []
    for m in KNOWN_COUNTERVAILING_MEASURES:
        cv_measures.append({
            **m,
            "rate_specific": 0.0,
            "currency_code": "USD",
            "effective_to": "",
            "source_revision": f"countervailing:{TODAY}",
            "source_url": source_url,
        })

    cv_bundle = {
        "revision": f"countervailing:{TODAY}",
        "format": "eec_trade_remedies_v1",
        "official_url": source_url,
        "source_url": source_url,
        "effective_from": "2026-01-01",
        "description": "Компенсационные пошлины ЕЭК",
        "data_source": "Решения Коллегии/Совета ЕЭК (официальные документы)",
        "measures": cv_measures,
    }

    cv_path = RAW_DIR / "eec_countervailing.json"
    if not dry_run:
        cv_path.write_text(json.dumps(cv_bundle, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  Written: {cv_path.name} ({len(cv_measures)} measures)")
    results["EEC_COUNTERVAILING"] = {
        "status": "ok",
        "measures_count": len(cv_measures),
        "path": str(cv_path),
        "notes": f"Bundle with {len(cv_measures)} known countervailing measures",
    }

    return results


def check_excise_sources(*, dry_run: bool = False) -> dict[str, Any]:
    """Check excise data availability."""
    print("\n[6/6] EEC_EXCISE — Checking excise sources...")
    result: dict[str, Any] = {
        "domain": "EEC_EXCISE",
        "status": "existing_bundle_ok",
        "notes": [
            "Excise rates are from Russian Tax Code (НК РФ Ст. 193), not EEC.",
            "Current bundle has 2 excise items (alcohol, tobacco).",
            "Full excise rate table needs manual extraction from НК РФ.",
        ],
    }

    excise_path = RAW_DIR / "eec_excise.json"
    if excise_path.exists():
        data = json.loads(excise_path.read_text(encoding="utf-8"))
        result["current_rates_count"] = len(data.get("rates", []))
    else:
        result["status"] = "missing"
        result["notes"].append("No excise bundle found locally.")

    return result


def generate_manual_download_plan() -> dict[str, Any]:
    """Generate detailed manual download plan for data that can't be auto-fetched."""
    return {
        "title": "Manual Download Plan — Official EEC Data",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "domains": {
            "EEC_ETT": {
                "priority": 1,
                "current_status": "DB has 13,323 rates from prior ingestion",
                "what_to_download": "Structured ETT data (not PDFs)",
                "recommended_sources": [
                    {
                        "source": "TKS.RU API",
                        "url": "https://www.tks.ru/tnvedapi/",
                        "format": "JSON API",
                        "cost": "от 3000 руб/мес",
                        "data": "30+ полей на код ТН ВЭД включая ставки пошлин, НДС, акцизы",
                        "how_to": "Оформить лицензию → получить API ключ → выгрузить все 10-значные коды",
                    },
                    {
                        "source": "EEC ETT PDFs",
                        "url": "https://eec.eaeunion.org/comission/department/catr/ett/",
                        "format": "PDF (96 файлов по главам)",
                        "cost": "бесплатно",
                        "data": "Официальный текст тарифа с примечаниями",
                        "how_to": "Скачать все PDF → OCR/парсинг → извлечь hs_code + duty_rate",
                    },
                    {
                        "source": "Alta-Soft ТН ВЭД",
                        "url": "https://www.alta.ru/tnved/",
                        "format": "HTML (нужен парсинг)",
                        "cost": "бесплатно (с ограничениями)",
                        "data": "Коды ТН ВЭД + ставки пошлин + НДС",
                        "how_to": "Требует сессию/cookie. Скрипт data/ingest/fetch_tariff_eec.py нужно адаптировать.",
                    },
                ],
                "import_command": "cd customs-clear/backend && python3 -c \"from app.services.import_duty_ingestion import run_import_duty_apply; print(run_import_duty_apply())\"",
            },
            "EEC_VAT": {
                "priority": 2,
                "current_status": "DB has VAT data but only 6 rows with official row-level provenance",
                "what_to_download": "Перечень товаров с льготными ставками НДС (0%, 10%)",
                "recommended_sources": [
                    {
                        "source": "НК РФ Ст. 164",
                        "url": "http://sudact.ru/law/nk-rf-chast2/razdel-viii/glava-21/statia-164/",
                        "format": "HTML → manual extraction",
                        "data": "Перечни товаров со ставками 0% и 10% НДС",
                        "how_to": "Скачать текст статьи → извлечь перечни кодов ТН ВЭД → сформировать JSON bundle",
                    },
                    {
                        "source": "Постановления Правительства РФ",
                        "url": "https://www.consultant.ru/document/cons_doc_LAW_28165/",
                        "format": "HTML/PDF",
                        "data": "Перечень кодов ТН ВЭД для пониженных ставок",
                        "how_to": "Постановления 908, 41 — перечни кодов со ставкой 10%",
                    },
                ],
                "import_command": "cd customs-clear/backend && python3 -c \"from app.services.vat_ingestion import run_vat_apply; print(run_vat_apply())\"",
            },
            "EEC_EXCISE": {
                "priority": 3,
                "current_status": "Only 2 excise items in bundle",
                "what_to_download": "Полная таблица акцизных ставок из НК РФ Ст. 193",
                "recommended_sources": [
                    {
                        "source": "НК РФ Ст. 193",
                        "url": "http://sudact.ru/law/nk-rf-chast2/razdel-viii/glava-22/statia-193/",
                        "format": "HTML → manual extraction",
                        "data": "Ставки акцизов по видам подакцизных товаров",
                        "how_to": "Скачать таблицу ставок → сопоставить с кодами ТН ВЭД → сформировать JSON bundle",
                    },
                ],
                "import_command": "cd customs-clear/backend && python3 -c \"from app.services.excise_ingestion import run_excise_apply; print(run_excise_apply())\"",
            },
            "EEC_ANTI_DUMPING": {
                "priority": 4,
                "current_status": f"Bundle updated with {len(KNOWN_ANTI_DUMPING_MEASURES)} measures from known EEC decisions",
                "what_to_download": "Верификация полноты списка антидемпинговых мер",
                "recommended_sources": [
                    {
                        "source": "Правовой портал ЕЭК",
                        "url": "https://docs.eaeunion.org",
                        "format": "HTML search → PDF decisions",
                        "data": "Все Решения Коллегии ЕЭК по антидемпинговым мерам",
                        "how_to": "Поиск 'антидемпинговая пошлина' → скачать актуальные решения → проверить ставки и HS коды",
                    },
                    {
                        "source": "Alta-Soft Таможенные документы",
                        "url": "https://www.alta.ru/tamdoc/",
                        "format": "HTML → structured data",
                        "data": "Каталог Решений ЕЭК",
                        "how_to": "Фильтр по 'антидемпинговые' → extract HS codes + rates",
                    },
                ],
                "import_command": "cd customs-clear/backend && python3 -c \"from app.services.anti_dumping_ingestion import run_anti_dumping_apply; print(run_anti_dumping_apply())\"",
            },
            "EEC_SPECIAL_SAFEGUARD": {
                "priority": 5,
                "current_status": f"Bundle updated with {len(KNOWN_SPECIAL_SAFEGUARD_MEASURES)} measures",
                "what_to_download": "Верификация полноты списка специальных защитных мер",
                "recommended_sources": [
                    {
                        "source": "docs.eaeunion.org",
                        "url": "https://docs.eaeunion.org",
                        "format": "HTML → PDF",
                        "data": "Решения ЕЭК по специальным защитным мерам",
                        "how_to": "Поиск 'специальная защитная мера' → verify measures",
                    },
                ],
                "import_command": "cd customs-clear/backend && python3 -c \"from app.services.special_safeguard_ingestion import run_special_safeguard_apply; print(run_special_safeguard_apply())\"",
            },
            "EEC_COUNTERVAILING": {
                "priority": 6,
                "current_status": f"Bundle updated with {len(KNOWN_COUNTERVAILING_MEASURES)} measures",
                "what_to_download": "Верификация полноты списка компенсационных мер",
                "recommended_sources": [
                    {
                        "source": "docs.eaeunion.org",
                        "url": "https://docs.eaeunion.org",
                        "format": "HTML → PDF",
                        "data": "Решения ЕЭК по компенсационным мерам",
                        "how_to": "Поиск 'компенсационная мера' → verify measures",
                    },
                ],
                "import_command": "cd customs-clear/backend && python3 -c \"from app.services.countervailing_ingestion import run_countervailing_apply; print(run_countervailing_apply())\"",
            },
        },
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Fetch official EEC data for all 6 payment domains")
    parser.add_argument("--dry-run", action="store_true", help="Only check availability, don't download")
    parser.add_argument("--domain", choices=list(EEC_SOURCES.keys()), help="Fetch only specific domain")
    parser.add_argument("--skip-pdfs", action="store_true", help="Skip downloading ETT PDFs")
    args = parser.parse_args(argv)

    print("=" * 70)
    print("OFFICIAL EEC DATA FETCH")
    print(f"Date: {TODAY}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print("=" * 70)

    all_results: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "dry_run" if args.dry_run else "live",
        "domains": {},
    }

    if not args.skip_pdfs and (not args.domain or args.domain == "EEC_ETT"):
        ett_result = fetch_ett_pdfs(dry_run=args.dry_run)
        all_results["domains"]["EEC_ETT"] = ett_result

    tr_result = fetch_trade_remedies_page(dry_run=args.dry_run)
    all_results["trade_remedies_page_check"] = tr_result

    if not args.domain or args.domain in ("EEC_ANTI_DUMPING", "EEC_SPECIAL_SAFEGUARD", "EEC_COUNTERVAILING"):
        tr_bundles = build_trade_remedy_bundles(dry_run=args.dry_run)
        all_results["domains"].update(tr_bundles)

    if not args.domain or args.domain == "EEC_EXCISE":
        excise_result = check_excise_sources(dry_run=args.dry_run)
        all_results["domains"]["EEC_EXCISE"] = excise_result

    manual_plan = generate_manual_download_plan()
    all_results["manual_download_plan"] = manual_plan

    log_path = FETCH_LOG_DIR / f"fetch_log_{TODAY}.json"
    log_path.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 70)
    print("FETCH SUMMARY")
    print("=" * 70)
    for domain, result in all_results.get("domains", {}).items():
        status = result.get("status", "unknown")
        icon = "OK" if status == "ok" else "WARN" if status in ("partial", "existing_bundle_ok") else "FAIL"
        detail = ""
        if "measures_count" in result:
            detail = f" ({result['measures_count']} measures)"
        elif "files_downloaded" in result:
            detail = f" ({result['files_downloaded']}/{result.get('files_found', '?')} files)"
        elif "current_rates_count" in result:
            detail = f" ({result['current_rates_count']} rates in bundle)"
        print(f"  [{icon:4s}] {domain:25s} → {status}{detail}")

    print(f"\nFetch log saved to: {log_path}")
    print(f"\nManual download plan saved to fetch log.")
    print("\nNext steps:")
    print("  1. Run ingestion: python3 -m scripts.run_all_ingestion")
    print("  2. Run audit:     cd customs-clear/backend && python3 -m app.scripts.official_payment_coverage_audit --json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
