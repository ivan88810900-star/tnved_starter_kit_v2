from __future__ import annotations

import logging
import random
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal
from app.models.tnved import Commodity, NonTariffMeasure

LOGGER = logging.getLogger("batch_import_alta")


@dataclass(frozen=True)
class SourceSpec:
    url: str
    measure_type: str
    document_required: str
    regulatory_act: str


SOURCES: list[SourceSpec] = [
    SourceSpec(
        url="https://www.alta.ru/tamdoc/10sr0317/",
        measure_type="vet_control",
        document_required="Ветеринарный сертификат",
        regulatory_act="Решение КТС № 317",
    ),
    SourceSpec(
        url="https://www.alta.ru/tamdoc/10sr0318/",
        measure_type="phyto_control",
        document_required="Фитосанитарный сертификат",
        regulatory_act="Решение КТС № 318",
    ),
    SourceSpec(
        url="https://www.alta.ru/tamdoc/10sr0299/",
        measure_type="other",
        document_required="Документы санитарно-эпидемиологического контроля",
        regulatory_act="Решение КТС № 299",
    ),
]


def fetch_and_clean_html(url: str) -> tuple[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Ch-Ua": '"Chromium";v="126", "Google Chrome";v="126", "Not.A/Brand";v="99"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }
    with httpx.Client(headers=headers, follow_redirects=True, timeout=60.0) as client:
        resp = client.get(url)
        resp.raise_for_status()
        html = resp.text

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    for selector in [
        "header",
        "footer",
        "nav",
        "aside",
        ".menu",
        ".navbar",
        ".breadcrumbs",
        ".sidebar",
        ".left-menu",
        ".right-column",
    ]:
        for el in soup.select(selector):
            el.decompose()

    root = None
    for selector in ["article", "main", ".document-text", ".article-content", ".content", ".entry-content"]:
        node = soup.select_one(selector)
        if node and node.get_text(strip=True):
            root = node
            break
    if root is None:
        root = soup.body or soup

    text = root.get_text("\n", strip=True)
    text = re.sub(r"\n{2,}", "\n\n", text).strip()
    return html, text


def _normalize_hs_code(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    return digits if len(digits) in (2, 4, 6, 10) else ""


def _extract_records(html: str, text: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    # 1) Пытаемся брать структуры таблиц.
    soup = BeautifulSoup(html, "lxml")
    for tr in soup.select("table tr"):
        cells = [re.sub(r"\s+", " ", c.get_text(" ", strip=True)).strip() for c in tr.find_all(["td", "th"])]
        if not cells:
            continue
        joined = " | ".join(cells)
        m = re.search(r"(?<!\d)(\d{2}(?:[\s.]?\d{2})?(?:[\s.]?\d{2})?(?:[\s.]?\d{3}[\s.]?\d)?)(?!\d)", joined)
        if not m:
            continue
        hs = _normalize_hs_code(m.group(1))
        if not hs:
            continue
        desc_parts = [c for c in cells if m.group(1) not in c]
        desc = " ".join(desc_parts).strip() or "Требование нетарифного регулирования"
        key = (hs, desc)
        if key in seen:
            continue
        seen.add(key)
        out.append({"hs_code": hs, "description": desc})

    # 2) Fallback по очищенному тексту.
    line_re = re.compile(r"^\s*(\d{2}(?:[\s.]?\d{2})?(?:[\s.]?\d{2})?(?:[\s.]?\d{3}[\s.]?\d)?)\s+(.+)$")
    for line in text.splitlines():
        m = line_re.match(line.strip())
        if not m:
            continue
        hs = _normalize_hs_code(m.group(1))
        if not hs:
            continue
        desc = re.sub(r"\s+", " ", m.group(2)).strip()
        key = (hs, desc)
        if key in seen:
            continue
        seen.add(key)
        out.append({"hs_code": hs, "description": desc})

    return out


def _expand_targets(hs_code: str, all_codes: set[str], leaf_codes: list[str]) -> list[str]:
    if hs_code in all_codes:
        return [hs_code]
    if len(hs_code) in (2, 4, 6):
        return [code for code in leaf_codes if code.startswith(hs_code)]
    return []


def import_records_for_source(spec: SourceSpec, records: list[dict[str, str]]) -> dict[str, int]:
    parsed = len(records)
    inserted = 0
    expanded = 0
    duplicates = 0
    no_targets = 0

    with SessionLocal() as db:
        all_codes = {c[0] for c in db.query(Commodity.code).all()}
        leaf_codes = [c for c in all_codes if len(c) == 10]
        existing_keys = {
            (
                m.commodity_code,
                (m.measure_type or "").strip().lower(),
                (m.regulatory_act or "").strip(),
            )
            for m in db.query(NonTariffMeasure).all()
        }
        staged_keys: set[tuple[str, str, str]] = set()
        batch: list[NonTariffMeasure] = []

        for rec in records:
            hs_code = _normalize_hs_code(rec.get("hs_code", ""))
            if not hs_code:
                continue
            targets = _expand_targets(hs_code, all_codes, leaf_codes)
            if not targets:
                no_targets += 1
                continue
            if hs_code not in all_codes and len(hs_code) in (2, 4, 6):
                expanded += 1
            for code in targets:
                key = (
                    code,
                    spec.measure_type,
                    spec.regulatory_act,
                )
                if key in existing_keys or key in staged_keys:
                    duplicates += 1
                    continue
                staged_keys.add(key)
                batch.append(
                    NonTariffMeasure(
                        commodity_code=code,
                        measure_type=spec.measure_type,
                        description=rec.get("description", "").strip(),
                        document_required=spec.document_required,
                        regulatory_act=spec.regulatory_act,
                    )
                )

        if batch:
            db.bulk_save_objects(batch)
            db.commit()
            inserted = len(batch)

    return {
        "parsed_records": parsed,
        "inserted_rows": inserted,
        "expanded_codes": expanded,
        "duplicates": duplicates,
        "no_targets": no_targets,
    }


def run_batch() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    report: list[tuple[str, dict[str, int] | None, str | None]] = []

    for idx, spec in enumerate(SOURCES, start=1):
        LOGGER.info("=== [%s/%s] Processing %s ===", idx, len(SOURCES), spec.url)
        try:
            html, text = fetch_and_clean_html(spec.url)
            records = _extract_records(html, text)
            stats = import_records_for_source(spec, records)
            report.append((spec.url, stats, None))
            LOGGER.info(
                "Done %s -> parsed=%s inserted=%s",
                spec.url,
                stats["parsed_records"],
                stats["inserted_rows"],
            )
        except Exception as exc:
            LOGGER.error("Failed %s: %s", spec.url, exc)
            report.append((spec.url, None, str(exc)))

        if idx < len(SOURCES):
            delay = random.uniform(20, 40)
            LOGGER.info("Sleep %.1f sec before next URL", delay)
            time.sleep(delay)

    LOGGER.info("=== FINAL REPORT ===")
    for url, stats, err in report:
        if err:
            LOGGER.info("%s -> ERROR: %s", url, err)
        else:
            LOGGER.info(
                "%s -> found=%s, inserted=%s, expanded=%s, duplicates=%s, no_targets=%s",
                url,
                stats["parsed_records"],
                stats["inserted_rows"],
                stats["expanded_codes"],
                stats["duplicates"],
                stats["no_targets"],
            )


if __name__ == "__main__":
    run_batch()

