from __future__ import annotations

import asyncio
import json
import os
import random
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from loguru import logger
from sqlalchemy import desc

from ..db import SessionLocal
from ..models.core import TrTsAct
from ..models.tnved import Commodity, NonTariffMeasure, SpecialDuty, TamdocSyncCandidate, VatPreference
from .gemini_genai_configure import configure_google_generativeai
from .normative_store import append_sync_log, upsert_source_status

TAMDOC_INDEX_URL = os.getenv("TAMDOC_INDEX_URL", "https://www.alta.ru/tamdoc/").strip()
TAMDOC_SYNC_ENABLED = os.getenv("TAMDOC_SYNC_ENABLED", "1").lower() in ("1", "true", "yes")
# 0 = без лимита (полный обход индекса).
TAMDOC_MAX_DOCS = int(os.getenv("TAMDOC_MAX_DOCS", "0") or "0")
TAMDOC_TARGETED_MAX_DOCS = int(os.getenv("TAMDOC_TARGETED_MAX_DOCS", "0") or "0")
TAMDOC_REQUEST_TIMEOUT = float(os.getenv("TAMDOC_REQUEST_TIMEOUT", "40") or "40")
TAMDOC_MIN_DELAY_SEC = float(os.getenv("TAMDOC_MIN_DELAY_SEC", "0.6") or "0.6")
TAMDOC_MAX_DELAY_SEC = float(os.getenv("TAMDOC_MAX_DELAY_SEC", "1.6") or "1.6")
TAMDOC_RETRY_COUNT = int(os.getenv("TAMDOC_RETRY_COUNT", "4") or "4")
TAMDOC_BACKOFF_BASE_SEC = float(os.getenv("TAMDOC_BACKOFF_BASE_SEC", "1.2") or "1.2")
TAMDOC_PROXY = (os.getenv("TAMDOC_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or "").strip()
TAMDOC_LOCAL_DIR = Path(os.getenv("TAMDOC_LOCAL_DIR", str(Path(__file__).resolve().parents[2] / "downloads")))
TAMDOC_ARCHIVE_DIR = Path(os.getenv("TAMDOC_ARCHIVE_DIR", str(TAMDOC_LOCAL_DIR / "tamdoc_archive")))
TAMDOC_ARCHIVE_MAX_FILES = int(os.getenv("TAMDOC_ARCHIVE_MAX_FILES", "0") or "0")
TAMDOC_ARCHIVE_USE_AI = os.getenv("TAMDOC_ARCHIVE_USE_AI", "1").lower() in ("1", "true", "yes")
TAMDOC_ARCHIVE_AI_MODEL = (os.getenv("TAMDOC_ARCHIVE_AI_MODEL") or "gemini-1.5-flash").strip()
TAMDOC_ARCHIVE_AI_MAX_CHARS = int(os.getenv("TAMDOC_ARCHIVE_AI_MAX_CHARS", "50000") or "50000")

ALLOWED_MEASURE_TYPES = {
    "ban",
    "license",
    "certificate",
    "vet_control",
    "phyto_control",
    "tr_ts",
    "marking",
    "sgr",
    "fsetc",
    "fsb",
    "other",
}
COUNTRY_HINTS = {
    "китай": "CN",
    "кнр": "CN",
    "малайз": "MY",
    "турц": "TR",
    "индия": "IN",
    "корея": "KR",
    "япони": "JP",
    "сша": "US",
    "евросоюз": "EU",
    "европейского союза": "EU",
    "украин": "UA",
    "белорус": "BY",
    "казахстан": "KZ",
}
TARGETED_VAT_KEYWORDS = (
    "ндс",
    "пп рф № 908",
    "пп рф № 688",
    "налог",
)
TARGETED_SPECIAL_KEYWORDS = (
    "антидемп",
    "компенсацион",
    "специальн",
    "защитн",
    "пошлин",
)
TR_TS_CODE_RE = re.compile(r"\b(\d{3}/\d{4})\b")
TR_TS_HINT_RE = re.compile(r"(?:\bтр\s*(?:тс|еаэс)\b|техническ\w*\s+регламент)", re.IGNORECASE)
AI_MODEL_CANDIDATES = [
    TAMDOC_ARCHIVE_AI_MODEL,
    "gemini-1.5-flash",
    "gemini-1.5-flash-latest",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
]
USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
]
REFERERS = [
    "https://www.alta.ru/",
    "https://www.alta.ru/tamdoc/",
    "https://yandex.ru/",
    "https://www.google.com/",
]
FALLBACK_DOC_RECORDS = [
    {"url": "https://www.alta.ru/tamdoc/10sr0317/", "title": "Решение КТС № 317"},
    {"url": "https://www.alta.ru/tamdoc/10sr0318/", "title": "Решение КТС № 318"},
    {"url": "https://www.alta.ru/tamdoc/10sr0299/", "title": "Решение КТС № 299"},
    {"url": "https://www.alta.ru/tamdoc/15kr0030/", "title": "Решение Коллегии ЕЭК № 30"},
    {"url": "https://www.alta.ru/tamdoc/04ps0908/", "title": "ПП РФ № 908"},
    {"url": "https://www.alta.ru/tamdoc/13ps0688/", "title": "ПП РФ № 688"},
    {"url": "https://www.alta.ru/tamdoc/21ps1982/", "title": "ПП РФ № 1982"},
    {"url": "https://www.alta.ru/tamdoc/14uk0560/", "title": "Указ Президента РФ № 560"},
    {"url": "https://www.alta.ru/tamdoc/14ps0778/", "title": "ПП РФ № 778"},
    {"url": "https://www.alta.ru/tamdoc/22ps0353/", "title": "ПП РФ № 353"},
]
LOCAL_FALLBACK_MAP = {
    "https://www.alta.ru/tamdoc/10sr0317/": "decision_317.html",
    "https://www.alta.ru/tamdoc/10sr0318/": "decision_318.html",
    "https://www.alta.ru/tamdoc/15kr0030/": "decision_30.html",
}


def _normalize_hs(raw: str) -> str:
    d = re.sub(r"\D", "", raw or "")
    if len(d) in (2, 4, 6, 10):
        return d
    return ""


def _extract_hs_codes(text: str) -> list[str]:
    pattern = re.compile(r"(?<!\d)(\d{2}(?:[\s.]?\d{2})?(?:[\s.]?\d{2})?(?:[\s.]?\d{3}[\s.]?\d)?)(?!\d)")
    out: list[str] = []
    seen: set[str] = set()
    for m in pattern.finditer(text or ""):
        code = _normalize_hs(m.group(1))
        if not code:
            continue
        if code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def _extract_country_codes(text: str) -> list[str]:
    low = (text or "").lower()
    out: list[str] = []
    for token, code in COUNTRY_HINTS.items():
        if token in low and code not in out:
            out.append(code)
    return out


def _extract_percent_rates(text: str) -> list[float]:
    rates: list[float] = []
    for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*%", text or ""):
        try:
            val = float(m.group(1).replace(",", "."))
        except ValueError:
            continue
        if 0.0 <= val <= 500.0:
            rates.append(val)
    return rates


def _extract_vat_rates(text: str) -> list[int]:
    out: list[int] = []
    if re.search(r"\b10\s*%", text or ""):
        out.append(10)
    if re.search(r"\b0\s*%", text or ""):
        out.append(0)
    return out


def _measure_type_hint(text: str) -> str:
    low = (text or "").lower()
    if TR_TS_HINT_RE.search(low):
        return "tr_ts"
    if "ветеринар" in low:
        return "vet_control"
    if "фитосанитар" in low or "карантин" in low:
        return "phyto_control"
    if "лиценз" in low:
        return "license"
    if "запрет" in low:
        return "ban"
    if "сертифик" in low or "декларац" in low:
        return "certificate"
    return "other"


def _default_document_required(measure_type: str) -> str:
    mtype = (measure_type or "").strip().lower()
    if mtype == "tr_ts":
        return "Сертификат/декларация соответствия ТР ТС/ТР ЕАЭС"
    if mtype in {"license", "certificate", "other"}:
        return "Лицензия/сертификат/разрешение по документу"
    if mtype == "vet_control":
        return "Ветеринарный сертификат"
    if mtype == "phyto_control":
        return "Фитосанитарный сертификат"
    if mtype == "ban":
        return "Подтверждение отсутствия запрета/ограничения"
    return "Лицензия/сертификат/разрешение по документу"


def _looks_like_tr_ts_doc(title: str, text: str) -> bool:
    blob = f"{title}\n{text}"
    return bool(TR_TS_HINT_RE.search(blob))


def _detect_archive_doc_type(file_name: str, title: str, text: str) -> str:
    low_file = (file_name or "").lower()
    if re.search(r"(tr_ts|tr-eaes|tr_eaes|techreg|tech_reg|tehreg|тртс|тр_тс)", low_file):
        return "tr_ts"
    if re.search(r"(nds|vat|pp_?908|pp_?688|_908|_688)", low_file):
        return "vat"
    if re.search(r"(antidump|special|compens|защит|антидемп|компенсац)", low_file):
        return "special"
    if _looks_like_tr_ts_doc(title, text):
        return "tr_ts"
    if _looks_like_vat_doc(title, text) and _looks_like_special_doc(title, text):
        return "mixed"
    if _looks_like_vat_doc(title, text):
        return "vat"
    if _looks_like_special_doc(title, text):
        return "special"
    return "other"


def _extract_tr_ts_act_codes(blob: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for code in TR_TS_CODE_RE.findall(blob or ""):
        if code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def _extract_tr_ts_year_tokens(blob: str) -> set[str]:
    years: set[str] = set()
    for code in TR_TS_CODE_RE.findall(blob or ""):
        try:
            years.add(code.split("/", 1)[1])
        except Exception:
            continue
    return years


def _extract_tr_ts_title_line(text: str, code: str) -> str:
    for raw in (text or "").splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        low = line.lower()
        if code in line and ("тр тс" in low or "тр еаэс" in low or "техническ" in low):
            return line[:700]
    return ""


def _upsert_tr_ts_acts(act_codes: list[str], *, title: str, text: str, source_url: str, source_revision: str) -> tuple[int, int]:
    if not act_codes:
        return 0, 0
    created = 0
    updated = 0
    with SessionLocal() as db:
        for code in act_codes:
            snippet = _extract_tr_ts_title_line(text, code)
            label_prefix = "ТР ЕАЭС" if re.search(rf"тр\s*еаэс\s*{re.escape(code)}", f"{title}\n{text}", re.IGNORECASE) else "ТР ТС"
            short_name = f"{label_prefix} {code}"[:512]
            full_title = (snippet or title or short_name)[:4000]
            row = db.query(TrTsAct).filter(TrTsAct.act_code == code).first()
            if row is None:
                db.add(
                    TrTsAct(
                        act_code=code,
                        short_name=short_name,
                        full_title=full_title,
                        edition_note="Импортировано из локального архива tamdoc.",
                        source_url=source_url[:4000],
                        source_revision=source_revision[:128],
                    )
                )
                created += 1
            else:
                changed = False
                if not (row.short_name or "").strip():
                    row.short_name = short_name
                    changed = True
                if not (row.full_title or "").strip():
                    row.full_title = full_title
                    changed = True
                if source_url and row.source_url != source_url:
                    row.source_url = source_url[:4000]
                    changed = True
                if source_revision and row.source_revision != source_revision:
                    row.source_revision = source_revision[:128]
                    changed = True
                if changed:
                    updated += 1
        db.commit()
    return created, updated


def _extract_json_array_payload(raw: str) -> str:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    if text.startswith("[") and text.endswith("]"):
        return text
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    raise ValueError("AI response does not contain JSON array")


def _extract_archive_measures_with_ai(text: str, title: str, doc_type: str, file_name: str) -> list[dict[str, str]]:
    if not TAMDOC_ARCHIVE_USE_AI:
        return []
    api_key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    if not api_key:
        return []
    try:
        import google.generativeai as genai  # type: ignore
    except Exception as exc:
        logger.warning(f"archive AI parser unavailable (google.generativeai): {exc}")
        return []

    prompt = (
        "Ты парсер нормативных актов. Верни строго JSON-массив объектов.\n"
        "Формат объекта: hs_code (2/4/6/10 цифр), measure_type "
        "(ban|license|certificate|vet_control|phyto_control|tr_ts|other), "
        "document_required (строка), description (строка), regulatory_act (строка).\n"
        "Если данных нет, верни []. Никакого текста кроме JSON.\n"
        f"Имя файла: {file_name}\n"
        f"Предполагаемый тип документа: {doc_type}\n"
        f"Заголовок: {title}\n\n"
        f"Текст документа:\n{text[: max(2000, TAMDOC_ARCHIVE_AI_MAX_CHARS)]}"
    )

    configure_google_generativeai(genai, api_key=api_key)
    last_exc: Exception | None = None
    items: list[dict[str, str]] = []
    for model_name in [m for i, m in enumerate(AI_MODEL_CANDIDATES) if m and m not in AI_MODEL_CANDIDATES[:i]]:
        try:
            model = genai.GenerativeModel(model_name)
            resp = model.generate_content(prompt, generation_config={"temperature": 0.0})
            payload = _extract_json_array_payload((getattr(resp, "text", "") or "").strip())
            data = json.loads(payload)
            if not isinstance(data, list):
                continue
            for raw in data:
                if not isinstance(raw, dict):
                    continue
                hs = _normalize_hs(str(raw.get("hs_code") or ""))
                if not hs:
                    continue
                mtype = str(raw.get("measure_type") or doc_type or "other").strip().lower()
                if mtype not in ALLOWED_MEASURE_TYPES:
                    mtype = doc_type if doc_type in ALLOWED_MEASURE_TYPES else "other"
                desc = re.sub(r"\s+", " ", str(raw.get("description") or "")).strip()
                doc_req = re.sub(r"\s+", " ", str(raw.get("document_required") or "")).strip()
                reg_act = re.sub(r"\s+", " ", str(raw.get("regulatory_act") or "")).strip()
                items.append(
                    {
                        "hs_code": hs,
                        "measure_type": mtype,
                        "document_required": (doc_req or _default_document_required(mtype))[:255],
                        "description": (desc or title)[:1000],
                        "regulatory_act": (reg_act or title)[:255],
                    }
                )
            if items:
                return items
        except Exception as exc:
            last_exc = exc
            continue
    if last_exc:
        logger.warning(f"archive AI parser failed, fallback used: {last_exc}")
    return []


def _extract_archive_measures_fallback(text: str, title: str, doc_type: str) -> list[dict[str, str]]:
    rows = _extract_lines_with_code(text, max_lines=400)
    if not rows:
        hs_candidates = _extract_hs_codes(text)[:500]
        if doc_type == "tr_ts":
            years = _extract_tr_ts_year_tokens(text)
            hs_candidates = [h for h in hs_candidates if h not in years]
        rows = [(hs, title) for hs in hs_candidates[:400]]
    if not rows:
        return []

    mtype = doc_type if doc_type in ALLOWED_MEASURE_TYPES else _measure_type_hint(text)
    if mtype not in ALLOWED_MEASURE_TYPES:
        mtype = "other"
    doc_required = _default_document_required(mtype)
    reg_act = title[:255] if title else "Локальный архив tamdoc"
    out: list[dict[str, str]] = []
    for hs, desc in rows:
        code = _normalize_hs(hs)
        if not code:
            continue
        out.append(
            {
                "hs_code": code,
                "measure_type": mtype,
                "document_required": doc_required,
                "description": (desc or title or "Требование из локального архива tamdoc")[:1000],
                "regulatory_act": reg_act,
            }
        )
    return out


def _extract_archive_measures(text: str, title: str, doc_type: str, file_name: str) -> tuple[list[dict[str, str]], str]:
    ai_rows = _extract_archive_measures_with_ai(text=text, title=title, doc_type=doc_type, file_name=file_name)
    if ai_rows:
        return ai_rows, "ai"
    return _extract_archive_measures_fallback(text=text, title=title, doc_type=doc_type), "fallback"


def _extract_lines_with_code(text: str, max_lines: int = 25) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    line_re = re.compile(r"^\s*(\d{2}(?:[\s.]?\d{2})?(?:[\s.]?\d{2})?(?:[\s.]?\d{3}[\s.]?\d)?)\s+(.+)$")
    for line in (text or "").splitlines():
        m = line_re.match(line.strip())
        if not m:
            continue
        hs = _normalize_hs(m.group(1))
        if not hs:
            continue
        desc = re.sub(r"\s+", " ", m.group(2)).strip()
        key = (hs, desc)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
        if len(out) >= max_lines:
            break
    return out


async def _fetch_html(client: httpx.AsyncClient, url: str) -> str:
    last_exc: Exception | None = None
    for attempt in range(1, max(1, TAMDOC_RETRY_COUNT) + 1):
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": random.choice(REFERERS),
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code in (403, 429, 503):
                raise httpx.HTTPStatusError(
                    f"temporary block status={resp.status_code}",
                    request=resp.request,
                    response=resp,
                )
            resp.raise_for_status()
            return resp.text
        except Exception as exc:
            last_exc = exc
            wait_s = TAMDOC_BACKOFF_BASE_SEC * attempt + random.uniform(0.4, 1.3)
            logger.warning(f"tamdoc fetch retry {attempt}/{TAMDOC_RETRY_COUNT} url={url}: {exc}")
            await asyncio.sleep(wait_s)
    local_file = LOCAL_FALLBACK_MAP.get(url)
    if local_file:
        fp = TAMDOC_LOCAL_DIR / local_file
        if fp.exists():
            try:
                logger.warning(f"tamdoc fetch fallback local file: {fp}")
                return fp.read_text(encoding="utf-8", errors="ignore")
            except Exception as read_exc:
                raise RuntimeError(f"Не удалось скачать {url}; fallback тоже не прочитан: {read_exc}") from read_exc
    raise RuntimeError(f"Не удалось скачать {url}: {last_exc}")


def _extract_text_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    root = None
    for selector in ("article", "main", ".document-text", ".article-content", ".content", ".entry-content"):
        node = soup.select_one(selector)
        if node and node.get_text(strip=True):
            root = node
            break
    if root is None:
        root = soup.body or soup
    text = root.get_text("\n", strip=True)
    text = re.sub(r"\n{2,}", "\n\n", text)
    return text.strip()


def _extract_doc_records(index_html: str, base_url: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(index_html, "lxml")
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for a in soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        if "/tamdoc/" not in href:
            continue
        url = urljoin(base_url, href)
        if not url.endswith("/"):
            url += "/"
        # Пропускаем корневую страницу.
        if url.rstrip("/") == TAMDOC_INDEX_URL.rstrip("/"):
            continue
        # Документы обычно /tamdoc/<id>/.
        if not re.search(r"/tamdoc/[0-9a-zA-Z_-]+/$", url):
            continue
        if url in seen:
            continue
        seen.add(url)
        title = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()
        links.append({"url": url, "title": title})
    return links


def _extract_doc_links(index_html: str, base_url: str) -> list[str]:
    return [x["url"] for x in _extract_doc_records(index_html, base_url)]


def _looks_like_vat_doc(title: str, text: str) -> bool:
    blob = f"{title}\n{text}".lower()
    return any(k in blob for k in TARGETED_VAT_KEYWORDS)


def _looks_like_special_doc(title: str, text: str) -> bool:
    blob = f"{title}\n{text}".lower()
    return any(k in blob for k in TARGETED_SPECIAL_KEYWORDS)


def _expand_targets(hs_code: str, all_codes: set[str], leaf_codes: list[str]) -> list[str]:
    if hs_code in all_codes:
        return [hs_code]
    if len(hs_code) in (2, 4, 6):
        return [c for c in leaf_codes if c.startswith(hs_code)]
    return []


def _upsert_vat_preferences(hs_codes: list[str], vat_rates: list[int], decree_info: str, comment: str) -> tuple[int, int]:
    if not hs_codes or not vat_rates:
        return 0, 0
    created = 0
    updated = 0
    with SessionLocal() as db:
        for hs in hs_codes:
            for rate in vat_rates:
                row = (
                    db.query(VatPreference)
                    .filter(
                        VatPreference.hs_code_prefix == hs[:10],
                        VatPreference.vat_rate == rate,
                        VatPreference.decree_info == decree_info,
                    )
                    .first()
                )
                if row:
                    row.comment = comment
                    updated += 1
                else:
                    db.add(
                        VatPreference(
                            hs_code_prefix=hs[:10],
                            vat_rate=rate,
                            decree_info=decree_info,
                            comment=comment,
                        )
                    )
                    created += 1
        db.commit()
    return created, updated


def _upsert_special_duties(
    hs_codes: list[str],
    country_codes: list[str],
    percent_rates: list[float],
    regulatory_act: str,
) -> tuple[int, int]:
    if not hs_codes or not percent_rates:
        return 0, 0
    countries = country_codes or ["ALL"]
    created = 0
    updated = 0
    rate = max(percent_rates)
    with SessionLocal() as db:
        for hs in hs_codes:
            for cc in countries:
                row = (
                    db.query(SpecialDuty)
                    .filter(
                        SpecialDuty.hs_code_prefix == hs[:10],
                        SpecialDuty.origin_country == cc,
                        SpecialDuty.regulatory_act == regulatory_act,
                    )
                    .first()
                )
                if row:
                    row.rate_percent = rate
                    row.currency_code = "RUB"
                    updated += 1
                else:
                    db.add(
                        SpecialDuty(
                            hs_code_prefix=hs[:10],
                            origin_country=cc,
                            rate_percent=rate,
                            rate_specific=0.0,
                            currency_code="RUB",
                            regulatory_act=regulatory_act,
                        )
                    )
                    created += 1
        db.commit()
    return created, updated


def _upsert_non_tariff(
    lines: list[tuple[str, str]],
    measure_type: str,
    regulatory_act: str,
    document_required: str,
) -> tuple[int, int]:
    if not lines:
        return 0, 0
    created = 0
    duplicates = 0
    mtype = measure_type if measure_type in ALLOWED_MEASURE_TYPES else "other"
    with SessionLocal() as db:
        all_codes = {x[0] for x in db.query(Commodity.code).all()}
        leaf_codes = [c for c in all_codes if len(c) == 10]
        staged: set[tuple[str, str, str]] = set()
        batch: list[NonTariffMeasure] = []
        existing = {
            (
                m.commodity_code,
                (m.measure_type or "").strip().lower(),
                (m.regulatory_act or "").strip(),
            )
            for m in db.query(NonTariffMeasure).all()
        }
        for hs, desc in lines:
            targets = _expand_targets(hs, all_codes, leaf_codes)
            for code in targets:
                key = (code, mtype, (regulatory_act or "").strip())
                if key in existing or key in staged:
                    duplicates += 1
                    continue
                staged.add(key)
                batch.append(
                    NonTariffMeasure(
                        commodity_code=code,
                        measure_type=mtype,
                        description=desc,
                        document_required=document_required,
                        regulatory_act=regulatory_act,
                    )
                )
        if batch:
            db.bulk_save_objects(batch)
            db.commit()
            created = len(batch)
    return created, duplicates


def _stage_candidate(
    *,
    url: str,
    title: str,
    doc_type: str,
    hs_codes: list[str],
    country_codes: list[str],
    vat_rates: list[int],
    percent_rates: list[float],
    measure_type_hint: str,
    excerpt: str,
    status: str = "pending",
    error_message: str = "",
) -> int:
    hs_prefix = (hs_codes[0] if hs_codes else "")[:10]
    vat_text = ",".join(str(x) for x in sorted(set(vat_rates)))[:32]
    pct_text = ",".join(str(x) for x in sorted(set(round(p, 4) for p in percent_rates)))[:64]
    countries_text = ",".join(sorted(set(country_codes)))[:128]
    normalized_excerpt = re.sub(r"\s+", " ", excerpt or "").strip()[:3000]
    with SessionLocal() as db:
        row = (
            db.query(TamdocSyncCandidate)
            .filter(
                TamdocSyncCandidate.doc_url == url,
                TamdocSyncCandidate.doc_type == doc_type,
                TamdocSyncCandidate.hs_prefix == hs_prefix,
            )
            .first()
        )
        if row:
            row.doc_title = title[:255]
            row.status = status[:32]
            row.country_codes = countries_text
            row.vat_rates = vat_text
            row.percent_rates = pct_text
            row.measure_type_hint = (measure_type_hint or "other")[:32]
            row.excerpt = normalized_excerpt
            row.error_message = (error_message or "")[:512]
            db.commit()
            return row.id
        obj = TamdocSyncCandidate(
            doc_url=url[:512],
            doc_title=title[:255],
            doc_type=doc_type[:32],
            status=status[:32],
            hs_prefix=hs_prefix,
            country_codes=countries_text,
            vat_rates=vat_text,
            percent_rates=pct_text,
            measure_type_hint=(measure_type_hint or "other")[:32],
            excerpt=normalized_excerpt,
            error_message=(error_message or "")[:512],
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return int(obj.id)


def list_tamdoc_candidates(limit: int = 100, status: str | None = None) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        q = db.query(TamdocSyncCandidate)
        if status:
            q = q.filter(TamdocSyncCandidate.status == status.strip()[:32])
        rows = q.order_by(desc(TamdocSyncCandidate.updated_at), desc(TamdocSyncCandidate.id)).limit(limit).all()
        return [
            {
                "id": r.id,
                "doc_url": r.doc_url,
                "doc_title": r.doc_title,
                "doc_type": r.doc_type,
                "status": r.status,
                "hs_prefix": r.hs_prefix,
                "country_codes": r.country_codes,
                "vat_rates": r.vat_rates,
                "percent_rates": r.percent_rates,
                "measure_type_hint": r.measure_type_hint,
                "excerpt": r.excerpt,
                "error_message": r.error_message,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]


def _csv_to_ints(raw: str) -> list[int]:
    out: list[int] = []
    for p in (raw or "").split(","):
        p = p.strip()
        if not p:
            continue
        try:
            out.append(int(float(p)))
        except ValueError:
            continue
    return sorted(set(out))


def _csv_to_floats(raw: str) -> list[float]:
    out: list[float] = []
    for p in (raw or "").split(","):
        p = p.strip().replace(",", ".")
        if not p:
            continue
        try:
            out.append(float(p))
        except ValueError:
            continue
    return sorted(set(out))


def _csv_to_tokens(raw: str) -> list[str]:
    out: list[str] = []
    for p in (raw or "").split(","):
        p = p.strip().upper()
        if p and p not in out:
            out.append(p)
    return out


def _guess_title_from_text(text: str, fallback: str) -> str:
    line = (text or "").splitlines()
    for raw in line[:8]:
        t = re.sub(r"\s+", " ", raw).strip()
        if len(t) >= 8:
            return t[:255]
    return fallback[:255]


def _iter_archive_files(base_dir: Path, max_files: int | None) -> list[Path]:
    if not base_dir.exists() or not base_dir.is_dir():
        return []
    exts = {".html", ".htm", ".txt", ".md"}
    files = [p for p in base_dir.rglob("*") if p.is_file() and p.suffix.lower() in exts]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if max_files is None or int(max_files) <= 0:
        return files
    return files[: int(max_files)]


def approve_tamdoc_candidate(candidate_id: int, include_non_tariff: bool = False) -> dict[str, Any]:
    with SessionLocal() as db:
        row = db.query(TamdocSyncCandidate).filter(TamdocSyncCandidate.id == int(candidate_id)).first()
        if not row:
            return {"status": "ERROR", "error": "candidate_not_found", "candidate_id": candidate_id}

        hs = (row.hs_prefix or "").strip()
        vat_rates = _csv_to_ints(row.vat_rates)
        percent_rates = _csv_to_floats(row.percent_rates)
        country_codes = _csv_to_tokens(row.country_codes)
        decree_info = (f"{row.doc_title} ({row.doc_url})" if row.doc_title else row.doc_url)[:255]
        comment = (row.excerpt or "")[:250]

        vat_created = vat_updated = 0
        sp_created = sp_updated = 0
        nt_created = nt_duplicates = 0

        if not hs:
            row.status = "rejected"
            row.error_message = "Нельзя применить: отсутствует hs_prefix в кандидате"
            db.commit()
            return {"status": "REJECTED", "candidate_id": row.id, "reason": row.error_message}

        if row.doc_type in {"vat", "mixed"} and vat_rates:
            vat_created, vat_updated = _upsert_vat_preferences(
                hs_codes=[hs],
                vat_rates=vat_rates,
                decree_info=decree_info,
                comment=comment,
            )
        if row.doc_type in {"special", "mixed"} and percent_rates:
            sp_created, sp_updated = _upsert_special_duties(
                hs_codes=[hs],
                country_codes=country_codes,
                percent_rates=percent_rates,
                regulatory_act=decree_info,
            )
        if include_non_tariff and hs:
            mtype = row.measure_type_hint if row.measure_type_hint in ALLOWED_MEASURE_TYPES else "other"
            doc_req = _default_document_required(mtype)
            nt_created, nt_duplicates = _upsert_non_tariff(
                lines=[(hs, comment or "Требование из tamdoc (staging)")],
                measure_type=mtype,
                regulatory_act=decree_info,
                document_required=doc_req,
            )

        row.status = "approved"
        row.error_message = ""
        db.commit()
        return {
            "status": "OK",
            "candidate_id": row.id,
            "applied": {
                "vat_created": vat_created,
                "vat_updated": vat_updated,
                "special_created": sp_created,
                "special_updated": sp_updated,
                "non_tariff_created": nt_created,
                "non_tariff_duplicates": nt_duplicates,
            },
        }


def reject_tamdoc_candidate(candidate_id: int, reason: str = "") -> dict[str, Any]:
    with SessionLocal() as db:
        row = db.query(TamdocSyncCandidate).filter(TamdocSyncCandidate.id == int(candidate_id)).first()
        if not row:
            return {"status": "ERROR", "error": "candidate_not_found", "candidate_id": candidate_id}
        row.status = "rejected"
        row.error_message = (reason or "Отклонено вручную")[:512]
        db.commit()
        return {"status": "OK", "candidate_id": row.id, "new_status": row.status}


def approve_tamdoc_candidates_batch(
    limit: int = 0,
    status: str = "pending",
    include_non_tariff: bool = False,
) -> dict[str, Any]:
    with SessionLocal() as db:
        q = (
            db.query(TamdocSyncCandidate.id)
            .filter(TamdocSyncCandidate.status == status[:32])
            .order_by(TamdocSyncCandidate.updated_at.asc(), TamdocSyncCandidate.id.asc())
        )
        if limit is not None and int(limit) > 0:
            q = q.limit(int(limit))
        ids = [r.id for r in q.all()]
    ok = 0
    rejected = 0
    errors = 0
    for cid in ids:
        res = approve_tamdoc_candidate(int(cid), include_non_tariff=include_non_tariff)
        if res.get("status") == "OK":
            ok += 1
        elif res.get("status") == "REJECTED":
            rejected += 1
        else:
            errors += 1
    return {
        "status": "OK" if errors == 0 else "WARNING",
        "processed": len(ids),
        "approved": ok,
        "rejected": rejected,
        "errors": errors,
    }


def sync_tamdoc_archive(
    archive_dir: str | None = None,
    max_files: int | None = None,
    staging_only: bool = True,
    include_non_tariff: bool = True,
    auto_approve_pending: bool = False,
) -> dict[str, Any]:
    base_dir = Path(archive_dir).expanduser().resolve() if archive_dir else TAMDOC_ARCHIVE_DIR.resolve()
    limit = max_files if max_files is not None else TAMDOC_ARCHIVE_MAX_FILES
    files = _iter_archive_files(base_dir, limit)
    if not files:
        return {
            "status": "SKIPPED",
            "source": "ALTA_TAMDOC_ARCHIVE",
            "note": f"Нет файлов в архиве: {base_dir}",
            "archive_dir": str(base_dir),
        }

    docs_processed = 0
    docs_errors = 0
    staged_ok = 0
    staged_errors = 0
    vat_created = vat_updated = 0
    sp_created = sp_updated = 0
    nt_created = nt_duplicates = 0
    vat_candidates = 0
    special_candidates = 0
    tr_ts_docs = 0
    tr_ts_acts_created = 0
    tr_ts_acts_updated = 0
    ai_docs = 0
    fallback_docs = 0

    for fp in files:
        try:
            raw = fp.read_text(encoding="utf-8", errors="ignore")
            text = _extract_text_from_html(raw) if fp.suffix.lower() in {".html", ".htm"} else raw
            title = _guess_title_from_text(text, fp.stem)
            doc_type = _detect_archive_doc_type(fp.name, title, text)
            is_tr_ts = doc_type == "tr_ts"
            is_vat = doc_type in {"vat", "mixed"}
            is_special = doc_type in {"special", "mixed"}

            vat_rates = _extract_vat_rates(text) if is_vat else []
            rates = _extract_percent_rates(text) if is_special else []
            countries = _extract_country_codes(text) if is_special else []
            extracted_items, parser_mode = _extract_archive_measures(text=text, title=title, doc_type=doc_type, file_name=fp.name)
            if parser_mode == "ai" and extracted_items:
                ai_docs += 1
            else:
                fallback_docs += 1

            hs_codes: list[str] = []
            for row in extracted_items:
                hs = _normalize_hs(str(row.get("hs_code") or ""))
                if hs and hs not in hs_codes:
                    hs_codes.append(hs)
            if not hs_codes:
                hs_candidates = _extract_hs_codes(text)[:160]
                if is_tr_ts:
                    years = _extract_tr_ts_year_tokens(text)
                    hs_candidates = [h for h in hs_candidates if h not in years]
                for hs in hs_candidates[:120]:
                    if hs not in hs_codes:
                        hs_codes.append(hs)

            tr_ts_codes = _extract_tr_ts_act_codes(f"{title}\n{text}") if is_tr_ts else []
            if tr_ts_codes:
                tr_ts_docs += 1
                c_act, u_act = _upsert_tr_ts_acts(
                    tr_ts_codes,
                    title=title,
                    text=text,
                    source_url=f"file://{fp}",
                    source_revision="archive",
                )
                tr_ts_acts_created += c_act
                tr_ts_acts_updated += u_act

            _stage_candidate(
                url=f"file://{fp}",
                title=title,
                doc_type=doc_type,
                hs_codes=hs_codes,
                country_codes=countries,
                vat_rates=vat_rates,
                percent_rates=rates,
                measure_type_hint="tr_ts" if is_tr_ts else _measure_type_hint(text),
                excerpt=text[:1200],
                status="pending" if hs_codes else "skipped",
                error_message="" if hs_codes else "Коды ТН ВЭД не найдены",
            )
            staged_ok += 1
            if not hs_codes:
                docs_processed += 1
                continue

            if is_vat:
                vat_candidates += 1
                if vat_rates and not staging_only:
                    decree = "ПП РФ (из локального архива)"
                    mdec = re.search(r"(пп\s*рф\s*№\s*\d+)", f"{title}\n{text}".lower())
                    if mdec:
                        decree = mdec.group(1).upper().replace("ПП РФ", "ПП РФ")
                    c1, u1 = _upsert_vat_preferences(
                        hs_codes=hs_codes,
                        vat_rates=vat_rates,
                        decree_info=decree[:255],
                        comment=title[:250],
                    )
                    vat_created += c1
                    vat_updated += u1

            if is_special:
                special_candidates += 1
                if rates and not staging_only:
                    c2, u2 = _upsert_special_duties(
                        hs_codes=hs_codes,
                        country_codes=countries,
                        percent_rates=rates,
                        regulatory_act=title[:250],
                    )
                    sp_created += c2
                    sp_updated += u2

            if include_non_tariff:
                grouped: dict[tuple[str, str, str], list[tuple[str, str]]] = {}
                if extracted_items:
                    for item in extracted_items:
                        hs = _normalize_hs(str(item.get("hs_code") or ""))
                        if not hs:
                            continue
                        mtype = str(item.get("measure_type") or ("tr_ts" if is_tr_ts else _measure_type_hint(text))).strip().lower()
                        if is_tr_ts:
                            mtype = "tr_ts"
                        if mtype not in ALLOWED_MEASURE_TYPES:
                            mtype = "other"
                        doc_req = (str(item.get("document_required") or "") or _default_document_required(mtype))[:255]
                        reg_act = (str(item.get("regulatory_act") or "") or title)[:255]
                        desc = (str(item.get("description") or "") or title or "Требование из архива tamdoc")[:1000]
                        grouped.setdefault((mtype, reg_act, doc_req), []).append((hs, desc))

                if not grouped:
                    lines = _extract_lines_with_code(text, max_lines=240)
                    if is_tr_ts and tr_ts_codes:
                        act_suffix = ", ".join(tr_ts_codes)
                        reg_act = f"{title} ({act_suffix})"[:255]
                        grouped[("tr_ts", reg_act, _default_document_required("tr_ts"))] = lines or [
                            (hs, f"Требование ТР ТС/ТР ЕАЭС ({act_suffix})")
                            for hs in hs_codes[:240]
                        ]
                    elif lines:
                        hint = _measure_type_hint(text)
                        grouped[(hint, title[:255], _default_document_required(hint))] = lines

                for (mtype, reg_act, doc_req), rows in grouped.items():
                    if not rows:
                        continue
                    c3, d3 = _upsert_non_tariff(
                        lines=rows,
                        measure_type=mtype,
                        regulatory_act=reg_act,
                        document_required=doc_req,
                    )
                    nt_created += c3
                    nt_duplicates += d3

            docs_processed += 1
        except Exception as exc:
            docs_errors += 1
            staged_errors += 1
            try:
                _stage_candidate(
                    url=f"file://{fp}",
                    title=fp.name,
                    doc_type="other",
                    hs_codes=[],
                    country_codes=[],
                    vat_rates=[],
                    percent_rates=[],
                    measure_type_hint="other",
                    excerpt="",
                    status="error",
                    error_message=str(exc),
                )
            except Exception:
                pass
            logger.warning(f"ALTA TAMDOC ARCHIVE: ошибка {fp}: {exc}")

    batch_result = None
    if auto_approve_pending:
        approve_limit = len(files) if (limit is None or int(limit) <= 0) else max(1, int(limit))
        batch_result = approve_tamdoc_candidates_batch(
            limit=approve_limit,
            status="pending",
            include_non_tariff=include_non_tariff,
        )

    summary = {
        "status": "OK" if docs_errors == 0 else "WARNING",
        "source": "ALTA_TAMDOC_ARCHIVE",
        "archive_dir": str(base_dir),
        "files_seen": len(files),
        "docs_processed": docs_processed,
        "docs_errors": docs_errors,
        "staging_only": staging_only,
        "staged_ok": staged_ok,
        "staged_errors": staged_errors,
        "vat_candidates": vat_candidates,
        "special_candidates": special_candidates,
        "vat_created": vat_created,
        "vat_updated": vat_updated,
        "special_created": sp_created,
        "special_updated": sp_updated,
        "non_tariff_created": nt_created,
        "non_tariff_duplicates": nt_duplicates,
        "tr_ts_docs": tr_ts_docs,
        "tr_ts_acts_created": tr_ts_acts_created,
        "tr_ts_acts_updated": tr_ts_acts_updated,
        "ai_docs": ai_docs,
        "fallback_docs": fallback_docs,
        "auto_approve_pending": auto_approve_pending,
        "batch_approve": batch_result,
    }
    upsert_source_status(
        source_code="ALTA_TAMDOC_ARCHIVE",
        source_name="ALTA ТамДок (локальный архив)",
        source_url=f"file://{base_dir}",
        revision=f"docs:{docs_processed}",
        is_stale=False if docs_errors == 0 else True,
        note=str(summary),
    )
    append_sync_log(
        source_code="ALTA_TAMDOC_ARCHIVE",
        status="OK" if docs_errors == 0 else "WARNING",
        revision=f"docs:{docs_processed}",
        rows_affected=vat_created + sp_created + nt_created + tr_ts_acts_created + staged_ok,
        note=str(summary),
    )
    return summary


async def sync_tamdoc_documents(max_docs: int | None = None) -> dict[str, Any]:
    if not TAMDOC_SYNC_ENABLED:
        return {"status": "SKIPPED", "source": "ALTA_TAMDOC", "note": "TAMDOC_SYNC_ENABLED=false"}

    limit = max_docs if max_docs is not None else TAMDOC_MAX_DOCS
    try:
        async with httpx.AsyncClient(
            timeout=TAMDOC_REQUEST_TIMEOUT,
            follow_redirects=True,
            proxy=TAMDOC_PROXY or None,
        ) as client:
            used_fallback_index = False
            try:
                index_html = await _fetch_html(client, TAMDOC_INDEX_URL)
                links = _extract_doc_links(index_html, TAMDOC_INDEX_URL)
            except Exception as index_exc:
                logger.warning(f"ALTA TAMDOC: индекс недоступен, fallback-список: {index_exc}")
                used_fallback_index = True
                links = [r["url"] for r in FALLBACK_DOC_RECORDS]
            if limit is not None and int(limit) > 0:
                links = links[: int(limit)]
                lim_label = str(int(limit))
            else:
                lim_label = "ALL"
            logger.info(f"ALTA TAMDOC: найдено ссылок={len(links)} (лимит={lim_label})")

            docs_processed = 0
            vat_created = vat_updated = 0
            sp_created = sp_updated = 0
            nt_created = nt_duplicates = 0
            errors = 0

            for url in links:
                try:
                    html = await _fetch_html(client, url)
                    text = _extract_text_from_html(html)
                    hs_codes = _extract_hs_codes(text)
                    if not hs_codes:
                        docs_processed += 1
                        continue

                    title = ""
                    mtitle = re.search(r"^\s*Title:\s*(.+)$", text, flags=re.IGNORECASE | re.MULTILINE)
                    if mtitle:
                        title = mtitle.group(1).strip()
                    if not title:
                        title = f"ALTA tamdoc {url}"

                    low = text.lower()

                    # VAT preferences (10% / 0%)
                    if "ндс" in low:
                        vrates = _extract_vat_rates(text)
                        decree = "ПП РФ № 908/688"
                        mdec = re.search(r"пп\s*рф\s*№\s*\d+", low)
                        if mdec:
                            decree = mdec.group(0).upper().replace("ПП РФ", "ПП РФ")
                        c1, u1 = _upsert_vat_preferences(
                            hs_codes=hs_codes,
                            vat_rates=vrates,
                            decree_info=decree,
                            comment=title[:250],
                        )
                        vat_created += c1
                        vat_updated += u1

                    # Special duties (anti-dumping/protective/compensatory)
                    if any(k in low for k in ("антидемп", "компенсацион", "защитн", "специальн")) and "пошлин" in low:
                        countries = _extract_country_codes(text)
                        rates = _extract_percent_rates(text)
                        c2, u2 = _upsert_special_duties(
                            hs_codes=hs_codes,
                            country_codes=countries,
                            percent_rates=rates,
                            regulatory_act=title[:250],
                        )
                        sp_created += c2
                        sp_updated += u2

                    # Non-tariff hints from lines with code
                    lines = _extract_lines_with_code(text, max_lines=25)
                    if lines:
                        mtype = _measure_type_hint(text)
                        doc_req = _default_document_required(mtype)
                        c3, d3 = _upsert_non_tariff(
                            lines=lines,
                            measure_type=mtype,
                            regulatory_act=title[:250],
                            document_required=doc_req,
                        )
                        nt_created += c3
                        nt_duplicates += d3

                    docs_processed += 1
                    if TAMDOC_MAX_DELAY_SEC > 0:
                        await asyncio.sleep(random.uniform(TAMDOC_MIN_DELAY_SEC, TAMDOC_MAX_DELAY_SEC))
                except Exception as doc_exc:
                    errors += 1
                    try:
                        _stage_candidate(
                            url=url,
                            title=f"ALTA tamdoc {url}",
                            doc_type="other",
                            hs_codes=[],
                            country_codes=[],
                            vat_rates=[],
                            percent_rates=[],
                            measure_type_hint="other",
                            excerpt="",
                            status="error",
                            error_message=str(doc_exc),
                        )
                    except Exception:
                        pass
                    logger.warning(f"ALTA TAMDOC: ошибка обработки {url}: {doc_exc}")

        summary = {
            "status": "OK" if errors == 0 else "WARNING",
            "source": "ALTA_TAMDOC",
            "docs_processed": docs_processed,
            "docs_errors": errors,
            "vat_created": vat_created,
            "vat_updated": vat_updated,
            "special_created": sp_created,
            "special_updated": sp_updated,
            "non_tariff_created": nt_created,
            "non_tariff_duplicates": nt_duplicates,
            "links_seen": len(links),
            "used_fallback_index": used_fallback_index,
        }
        upsert_source_status(
            source_code="ALTA_TAMDOC",
            source_name="ALTA ТамДок (автопарсинг)",
            source_url=TAMDOC_INDEX_URL,
            revision=f"docs:{docs_processed}",
            is_stale=False if errors == 0 else True,
            note=str(summary),
        )
        append_sync_log(
            source_code="ALTA_TAMDOC",
            status="OK" if errors == 0 else "WARNING",
            revision=f"docs:{docs_processed}",
            rows_affected=vat_created + sp_created + nt_created,
            note=str(summary),
        )
        return summary
    except Exception as exc:
        upsert_source_status(
            source_code="ALTA_TAMDOC",
            source_name="ALTA ТамДок (автопарсинг)",
            source_url=TAMDOC_INDEX_URL,
            revision="unavailable",
            is_stale=True,
            note=f"Ошибка синхронизации: {exc}",
        )
        append_sync_log(
            source_code="ALTA_TAMDOC",
            status="ERROR",
            revision="unavailable",
            rows_affected=0,
            note=str(exc),
        )
        return {"status": "ERROR", "source": "ALTA_TAMDOC", "error": str(exc)}


async def sync_tamdoc_targeted(max_docs: int | None = None, staging_only: bool = False) -> dict[str, Any]:
    """Целевой парсинг документов tamdoc для НДС-льгот и спецпошлин."""
    if not TAMDOC_SYNC_ENABLED:
        return {"status": "SKIPPED", "source": "ALTA_TAMDOC_TARGETED", "note": "TAMDOC_SYNC_ENABLED=false"}

    limit = max_docs if max_docs is not None else TAMDOC_TARGETED_MAX_DOCS
    try:
        async with httpx.AsyncClient(
            timeout=TAMDOC_REQUEST_TIMEOUT,
            follow_redirects=True,
            proxy=TAMDOC_PROXY or None,
        ) as client:
            used_fallback_index = False
            try:
                index_html = await _fetch_html(client, TAMDOC_INDEX_URL)
                records = _extract_doc_records(index_html, TAMDOC_INDEX_URL)
            except Exception as index_exc:
                logger.warning(f"ALTA TAMDOC TARGETED: индекс недоступен, fallback-список: {index_exc}")
                used_fallback_index = True
                records = FALLBACK_DOC_RECORDS.copy()
            if limit is not None and int(limit) > 0:
                records = records[: int(limit)]
                lim_label = str(int(limit))
            else:
                lim_label = "ALL"
            logger.info(f"ALTA TAMDOC TARGETED: кандидатов={len(records)} (лимит={lim_label})")

            vat_candidates = 0
            sp_candidates = 0
            docs_processed = 0
            vat_created = vat_updated = 0
            sp_created = sp_updated = 0
            staged_ok = 0
            staged_errors = 0
            errors = 0

            for rec in records:
                url = rec["url"]
                title = rec.get("title", "")[:250] or f"ALTA tamdoc {url}"
                try:
                    html = await _fetch_html(client, url)
                    text = _extract_text_from_html(html)
                    hs_codes = _extract_hs_codes(text)
                    if not hs_codes:
                        _stage_candidate(
                            url=url,
                            title=title,
                            doc_type="other",
                            hs_codes=[],
                            country_codes=[],
                            vat_rates=[],
                            percent_rates=[],
                            measure_type_hint="other",
                            excerpt=text[:1200],
                            status="skipped",
                            error_message="Коды ТН ВЭД не найдены",
                        )
                        staged_ok += 1
                        docs_processed += 1
                        continue

                    measure_hint = _measure_type_hint(text)
                    is_vat = _looks_like_vat_doc(title, text)
                    is_special = _looks_like_special_doc(title, text)
                    if is_vat and is_special:
                        doc_type = "mixed"
                    elif is_vat:
                        doc_type = "vat"
                    elif is_special:
                        doc_type = "special"
                    else:
                        doc_type = "other"
                    vat_rates = _extract_vat_rates(text) if is_vat else []
                    rates = _extract_percent_rates(text) if is_special else []
                    countries = _extract_country_codes(text) if is_special else []

                    _stage_candidate(
                        url=url,
                        title=title,
                        doc_type=doc_type,
                        hs_codes=hs_codes,
                        country_codes=countries,
                        vat_rates=vat_rates,
                        percent_rates=rates,
                        measure_type_hint=measure_hint,
                        excerpt=text[:1200],
                        status="pending",
                    )
                    staged_ok += 1

                    if _looks_like_vat_doc(title, text):
                        vat_candidates += 1
                        if vat_rates and not staging_only:
                            decree = ""
                            mdec = re.search(r"(пп\s*рф\s*№\s*\d+)", f"{title}\n{text}".lower())
                            if mdec:
                                decree = mdec.group(1).upper().replace("ПП РФ", "ПП РФ")
                            decree = decree or "ПП РФ (из документа tamdoc)"
                            c1, u1 = _upsert_vat_preferences(
                                hs_codes=hs_codes,
                                vat_rates=vat_rates,
                                decree_info=decree,
                                comment=title[:250],
                            )
                            vat_created += c1
                            vat_updated += u1

                    if _looks_like_special_doc(title, text):
                        sp_candidates += 1
                        if rates and not staging_only:
                            c2, u2 = _upsert_special_duties(
                                hs_codes=hs_codes,
                                country_codes=countries,
                                percent_rates=rates,
                                regulatory_act=title[:250],
                            )
                            sp_created += c2
                            sp_updated += u2

                    docs_processed += 1
                    if TAMDOC_MAX_DELAY_SEC > 0:
                        await asyncio.sleep(random.uniform(TAMDOC_MIN_DELAY_SEC, TAMDOC_MAX_DELAY_SEC))
                except Exception as doc_exc:
                    errors += 1
                    staged_errors += 1
                    try:
                        _stage_candidate(
                            url=url,
                            title=title,
                            doc_type="other",
                            hs_codes=[],
                            country_codes=[],
                            vat_rates=[],
                            percent_rates=[],
                            measure_type_hint="other",
                            excerpt="",
                            status="error",
                            error_message=str(doc_exc),
                        )
                    except Exception:
                        pass
                    logger.warning(f"ALTA TAMDOC TARGETED: ошибка обработки {url}: {doc_exc}")

        summary = {
            "status": "OK" if errors == 0 else "WARNING",
            "source": "ALTA_TAMDOC_TARGETED",
            "docs_processed": docs_processed,
            "docs_errors": errors,
            "vat_candidates": vat_candidates,
            "special_candidates": sp_candidates,
            "vat_created": vat_created,
            "vat_updated": vat_updated,
            "special_created": sp_created,
            "special_updated": sp_updated,
            "staging_only": staging_only,
            "staged_ok": staged_ok,
            "staged_errors": staged_errors,
            "links_seen": len(records),
            "used_fallback_index": used_fallback_index,
        }
        upsert_source_status(
            source_code="ALTA_TAMDOC_TARGETED",
            source_name="ALTA ТамДок (целевой парсинг НДС/спецпошлин)",
            source_url=TAMDOC_INDEX_URL,
            revision=f"docs:{docs_processed}",
            is_stale=False if errors == 0 else True,
            note=str(summary),
        )
        append_sync_log(
            source_code="ALTA_TAMDOC_TARGETED",
            status="OK" if errors == 0 else "WARNING",
            revision=f"docs:{docs_processed}",
            rows_affected=vat_created + sp_created + staged_ok,
            note=str(summary),
        )
        return summary
    except Exception as exc:
        upsert_source_status(
            source_code="ALTA_TAMDOC_TARGETED",
            source_name="ALTA ТамДок (целевой парсинг НДС/спецпошлин)",
            source_url=TAMDOC_INDEX_URL,
            revision="unavailable",
            is_stale=True,
            note=f"Ошибка синхронизации: {exc}",
        )
        append_sync_log(
            source_code="ALTA_TAMDOC_TARGETED",
            status="ERROR",
            revision="unavailable",
            rows_affected=0,
            note=str(exc),
        )
        return {"status": "ERROR", "source": "ALTA_TAMDOC_TARGETED", "error": str(exc)}
