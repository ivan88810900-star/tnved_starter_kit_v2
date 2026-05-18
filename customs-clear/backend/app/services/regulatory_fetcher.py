"""Скачивание и сохранение ведомственных документов (каркас)."""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy.exc import IntegrityError

from ..db import SessionLocal
from ..models.regulatory import RegulatoryDocument, RegulatorySyncLog

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
STORAGE_DIR = _BACKEND_ROOT / "data" / "regulatory_documents"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)


def _make_doc_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def _parse_doc_number_and_date(text: str) -> tuple[str | None, date | None]:
    num_match = re.search(r"№\s*([А-ЯA-Z0-9\-/]+)", text)
    doc_number = num_match.group(1).strip() if num_match else None

    date_match = re.search(
        r"(\d{1,2})[.\s]+(\d{1,2}|[а-яё]+)[.\s]+(\d{4})",
        text,
        re.IGNORECASE,
    )
    doc_date = None
    if date_match:
        try:
            day, month, year = date_match.groups()
            months_ru = {
                "января": 1,
                "февраля": 2,
                "марта": 3,
                "апреля": 4,
                "мая": 5,
                "июня": 6,
                "июля": 7,
                "августа": 8,
                "сентября": 9,
                "октября": 10,
                "ноября": 11,
                "декабря": 12,
            }
            month_l = month.lower()
            month_num = months_ru.get(month_l, int(month) if str(month).isdigit() else None)
            if month_num:
                doc_date = datetime(int(year), month_num, int(day)).date()
        except (ValueError, TypeError, OverflowError):
            pass
    return doc_number, doc_date


def save_document(
    agency: str,
    doc_type: str,
    title: str,
    source_url: str,
    body: str = "",
    html: str | None = None,
    **kwargs: Any,
) -> str | None:
    """Сохраняет документ в БД. Возвращает doc_id или None если уже есть."""
    doc_id = _make_doc_id(source_url)

    with SessionLocal() as db:
        existing = db.query(RegulatoryDocument).filter_by(id=doc_id).first()
        if existing:
            return None

        html_path: str | None = None
        if html:
            html_file = STORAGE_DIR / f"{doc_id}.html"
            html_file.write_text(html, encoding="utf-8")
            html_path = str(html_file)

        doc_number, doc_date = _parse_doc_number_and_date(f"{title} {body[:500]}")

        allowed = {
            "summary",
            "topic_tags",
            "ai_extracted",
            "effective_from",
            "effective_to",
            "language",
            "supersedes_doc_id",
        }
        extra = {k: v for k, v in kwargs.items() if k in allowed}
        status_val = str(kwargs.get("status", "active"))
        quality_val = str(kwargs.get("quality", "unverified"))

        doc = RegulatoryDocument(
            id=doc_id,
            agency=agency,
            doc_type=doc_type,
            doc_number=doc_number,
            doc_date=doc_date,
            title=title.strip(),
            body=body,
            source_url=source_url,
            source_html_path=html_path,
            status=status_val,
            quality=quality_val,
            **extra,
        )
        db.add(doc)
        try:
            db.commit()
            logger.info(f"Документ сохранён: {doc_id} | {title[:80]}")
            return doc_id
        except IntegrityError:
            db.rollback()
            return None


def log_sync_run(
    agency: str,
    source_url: str,
    status: str,
    docs_added: int = 0,
    docs_updated: int = 0,
    docs_skipped: int = 0,
    error: str | None = None,
) -> None:
    with SessionLocal() as db:
        entry = RegulatorySyncLog(
            agency=agency,
            source_url=source_url,
            finished_at=datetime.utcnow(),
            status=status,
            docs_added=docs_added,
            docs_updated=docs_updated,
            docs_skipped=docs_skipped,
            error_message=error,
        )
        db.add(entry)
        db.commit()
