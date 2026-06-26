#!/usr/bin/env python3
"""
Генерация эмбеддингов прецедентов классификации для RAG.

Источники:
- classification_decisions (ПКР/классификационные решения),
- regulatory_ai_extracts (только профильные фрагменты с логикой классификации),
- declaration_examples (практические кейсы/формулировки графы 31 из IFCG и др.).

Хранилище векторов:
- tnved_entries (synthetic карточки прецедентов, source_revision=precedent_embeddings_v1),
- tnved_entry_embeddings (JSON-вектор, модель, размер).

Примеры:
  PYTHONPATH=. python3 scripts/generate_embeddings.py --batch-size 8 --sleep-sec 1.2
  PYTHONPATH=. python3 scripts/generate_embeddings.py --source classification_decisions --only-missing
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Iterable

from loguru import logger
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
load_dotenv()

from app.db import SessionLocal
from app.models.core import (
    ClassificationDecision,
    DeclarationExample,
    RegulatoryAiExtract,
    TnvedEntry,
    TnvedEntryEmbedding,
)
from app.services.gemini_embedding_service import embed_texts_gemini
from app.services.gemini_genai_configure import configure_google_generativeai

PRECEDENT_SOURCE_REVISION = "precedent_embeddings_v1"
DEFAULT_EMBED_MODEL = (os.getenv("GEMINI_EMBEDDING_MODEL") or "text-embedding-004").strip()


def _norm_hs(raw: str) -> str:
    return re.sub(r"\D", "", (raw or "").strip())[:10]


def _synthetic_hs_code(source: str, source_id: int) -> str:
    if source == "regulatory_ai_extracts":
        prefix = "R"
    elif source == "declaration_examples":
        prefix = "D"
    else:
        prefix = "C"
    return f"{prefix}{int(source_id):011d}"[:12]


def _is_classification_regulatory_row(row: RegulatoryAiExtract) -> bool:
    """Фильтр профильных extract-строк, связанных с классификацией/ОПИ/кодом."""
    blob = " ".join(
        [
            str(row.measure_type or ""),
            str(row.document_name or ""),
            str(row.source_excerpt or ""),
        ]
    ).lower()
    if not blob.strip():
        return False
    key_tokens = (
        "классиф",
        "тн вэд",
        "тнвэд",
        "код",
        "опи",
        "интерпретац",
        "товарн",
        "позици",
        "пояснен",
        "решени",
        "classification",
        "hs code",
        "tariff heading",
        "interpretation",
    )
    if any(tok in blob for tok in key_tokens):
        return True
    # Если явный код есть и extract длинный — тоже полезно для прецедента.
    hs = _norm_hs(row.hs_code_norm or "")
    return bool(hs and len(str(row.source_excerpt or "").strip()) >= 120)


def _iter_regulatory_rows(limit: int, offset: int) -> Iterable[dict[str, Any]]:
    with SessionLocal() as db:
        q = db.query(RegulatoryAiExtract).order_by(RegulatoryAiExtract.id.asc()).offset(offset)
        if limit > 0:
            q = q.limit(limit)
        for r in q.all():
            if not _is_classification_regulatory_row(r):
                continue
            hs = _norm_hs(r.hs_code_norm or "")
            title = f"[LAW] {(r.document_name or '').strip()}".strip()[:512]
            text = " | ".join(
                x
                for x in [
                    f"Тип меры: {(r.measure_type or '').strip()}",
                    f"HS: {hs}" if hs else "",
                    (r.document_name or "").strip(),
                    (r.source_excerpt or "").strip(),
                ]
                if x
            )[:16000]
            if not text.strip():
                continue
            yield {
                "source_table": "regulatory_ai_extracts",
                "source_id": int(r.id),
                "hs_code_real": hs,
                "title": title,
                "text": text,
            }


def _iter_classification_rows(limit: int, offset: int) -> Iterable[dict[str, Any]]:
    with SessionLocal() as db:
        q = db.query(ClassificationDecision).order_by(ClassificationDecision.id.asc()).offset(offset)
        if limit > 0:
            q = q.limit(limit)
        for r in q.all():
            hs = _norm_hs(r.hs_code or "")
            title = f"[PKR] № {(r.decision_number or '').strip()} | {(r.product_name or '').strip()}".strip()[:512]
            text = " | ".join(
                x
                for x in [
                    f"HS: {hs}" if hs else "",
                    f"Номер решения: {(r.decision_number or '').strip()}",
                    (r.product_name or "").strip(),
                    (r.description or "").strip(),
                    f"Цель классификации: {(r.target_entity or '').strip()}" if (r.target_entity or "").strip() else "",
                ]
                if x
            )[:16000]
            if not text.strip():
                continue
            yield {
                "source_table": "classification_decisions",
                "source_id": int(r.id),
                "hs_code_real": hs,
                "title": title,
                "text": text,
            }


def _iter_declaration_rows(limit: int, offset: int) -> Iterable[dict[str, Any]]:
    with SessionLocal() as db:
        q = db.query(DeclarationExample).order_by(DeclarationExample.id.asc()).offset(offset)
        if limit > 0:
            q = q.limit(limit)
        for r in q.all():
            hs = _norm_hs(r.hs_code or "")
            src = (r.source or "").strip() or "ifcg"
            title = f"[DECL] {(src or 'ifcg').upper()} | HS {(hs or '—')}".strip()[:512]
            text = " | ".join(
                x
                for x in [
                    f"HS: {hs}" if hs else "",
                    f"Источник: {src}",
                    (r.description or "").strip(),
                ]
                if x
            )[:16000]
            if not text.strip():
                continue
            yield {
                "source_table": "declaration_examples",
                "source_id": int(r.id),
                "hs_code_real": hs,
                "title": title,
                "text": text,
            }


def _iter_rows(source: str, limit: int, offset: int) -> Iterable[dict[str, Any]]:
    if source == "regulatory_ai_extracts":
        return _iter_regulatory_rows(limit, offset)
    if source == "classification_decisions":
        return _iter_classification_rows(limit, offset)
    if source == "declaration_examples":
        return _iter_declaration_rows(limit, offset)
    return iter(())


def _upsert_tnved_entry(db, row: dict[str, Any]) -> int:
    hs_synth = _synthetic_hs_code(row["source_table"], int(row["source_id"]))
    hs_real = _norm_hs(str(row.get("hs_code_real") or ""))
    chapter = hs_real[:2] if len(hs_real) >= 2 else ""
    desc = (
        f"SOURCE_TABLE={row['source_table']}; SOURCE_ID={row['source_id']}; "
        f"REAL_HS={hs_real or '—'}; TEXT={row.get('text') or ''}"
    )[:16000]
    obj = db.query(TnvedEntry).filter(TnvedEntry.hs_code == hs_synth).first()
    if obj is None:
        obj = TnvedEntry(
            hs_code=hs_synth,
            parent_hs=hs_real[:6] if len(hs_real) >= 6 else "",
            level=10,
            title=(row.get("title") or "")[:1024],
            description=desc,
            chapter=chapter,
            source_url="",
            source_revision=PRECEDENT_SOURCE_REVISION,
        )
        db.add(obj)
        db.flush()
        return int(obj.id)
    obj.parent_hs = hs_real[:6] if len(hs_real) >= 6 else obj.parent_hs
    obj.level = 10
    obj.title = (row.get("title") or obj.title or "")[:1024]
    obj.description = desc or obj.description
    obj.chapter = chapter or obj.chapter
    obj.source_revision = PRECEDENT_SOURCE_REVISION
    db.flush()
    return int(obj.id)


def _upsert_embedding(db, tnved_entry_id: int, model_name: str, vec: list[float]) -> None:
    obj = db.query(TnvedEntryEmbedding).filter(TnvedEntryEmbedding.tnved_entry_id == int(tnved_entry_id)).first()
    if obj is None:
        obj = TnvedEntryEmbedding(tnved_entry_id=int(tnved_entry_id))
        db.add(obj)
    obj.embedding_model = (model_name or DEFAULT_EMBED_MODEL)[:128]
    obj.embedding_dim = int(len(vec))
    obj.embedding = vec


def _existing_synthetic_hs() -> set[str]:
    with SessionLocal() as db:
        rows = (
            db.query(TnvedEntry.hs_code)
            .join(TnvedEntryEmbedding, TnvedEntryEmbedding.tnved_entry_id == TnvedEntry.id)
            .filter(TnvedEntry.source_revision == PRECEDENT_SOURCE_REVISION)
            .filter(TnvedEntryEmbedding.embedding.isnot(None))
            .all()
        )
    return {str(r[0]) for r in rows if r and r[0]}


def _extract_values_from_sdk_response(resp: Any) -> list[float]:
    """
    Универсальный разбор ответа google.generativeai.embed_content:
    - {"embedding": [..]}
    - {"embedding": {"values":[..]}}
    """
    if not isinstance(resp, dict):
        return []
    emb = resp.get("embedding")
    if isinstance(emb, list):
        try:
            return [float(x) for x in emb]
        except Exception:
            return []
    if isinstance(emb, dict):
        vals = emb.get("values")
        if isinstance(vals, list):
            try:
                return [float(x) for x in vals]
            except Exception:
                return []
    return []


def _is_retryable_embedding_error(exc: Exception) -> bool:
    txt = str(exc or "").lower()
    markers = ("429", "resource_exhausted", "rate", "quota", "timeout", "temporar", "503", "502", "500")
    return any(m in txt for m in markers)


def _embed_texts_sdk(
    texts: list[str],
    *,
    retries: int,
    sleep_sec: float,
) -> tuple[str, list[list[float]]]:
    """
    SDK-вызов через google.generativeai (основной путь по требованию).
    При сбое/отсутствии SDK вызывающий код переключается на REST helper.
    """
    import google.generativeai as genai

    key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("Не задан GEMINI_API_KEY или GOOGLE_API_KEY")
    configure_google_generativeai(genai, api_key=key)
    model_name = DEFAULT_EMBED_MODEL
    model_ref = model_name if model_name.startswith("models/") else f"models/{model_name}"

    vectors: list[list[float]] = []
    for idx, text in enumerate(texts, start=1):
        payload = (str(text or "").strip() or " ")[:16000]
        vec: list[float] = []
        for attempt in range(1, max(1, retries) + 1):
            try:
                resp = genai.embed_content(
                    model=model_ref,
                    content=payload,
                    task_type="retrieval_document",
                )
                vec = _extract_values_from_sdk_response(resp)
                break
            except Exception as e:
                if attempt >= retries or not _is_retryable_embedding_error(e):
                    raise
                backoff = sleep_sec * (attempt + 1)
                logger.warning(
                    "SDK embed retry {}/{} for row {} (sleep {:.2f}s): {}",
                    attempt,
                    retries,
                    idx,
                    backoff,
                    e,
                )
                time.sleep(max(0.2, backoff))
        vectors.append(vec)
        # Мягкий rate limiting между запросами.
        time.sleep(max(0.0, float(sleep_sec)))
    return model_name, vectors


def _embed_texts_with_fallback(
    texts: list[str],
    *,
    batch_size: int,
    retries: int,
    sleep_sec: float,
) -> tuple[str, list[list[float]]]:
    try:
        return _embed_texts_sdk(texts, retries=retries, sleep_sec=sleep_sec)
    except Exception as e:
        logger.warning("SDK embedding failed, fallback to REST helper: {}", e)
        # REST helper внутри сам ретраит 429/5xx.
        model, vectors = embed_texts_gemini(texts, batch_size=batch_size, retries=max(1, retries))
        # И тут тоже делаем паузу, чтобы не перегружать API следующими батчами.
        time.sleep(max(0.0, float(sleep_sec)))
        return model, vectors


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Embeddings (classification_decisions + профильные regulatory_ai_extracts + declaration_examples) "
            "-> tnved_entry_embeddings"
        )
    )
    ap.add_argument(
        "--source",
        action="append",
        choices=["regulatory_ai_extracts", "classification_decisions", "declaration_examples"],
        help="Источник (можно указать несколько раз). По умолчанию: все поддерживаемые источники.",
    )
    ap.add_argument("--limit", type=int, default=0, help="Лимит строк на источник (0 = без лимита)")
    ap.add_argument("--offset", type=int, default=0, help="Смещение по id на источник")
    ap.add_argument("--batch-size", type=int, default=8, help="Размер батча на этап upsert/логирования")
    ap.add_argument("--only-missing", action="store_true", help="Обрабатывать только отсутствующие в индексе")
    ap.add_argument("--retries", type=int, default=4, help="Ретраи для embedding-запросов")
    ap.add_argument("--sleep-sec", type=float, default=0.9, help="Пауза между embedding-запросами (rate limit)")
    args = ap.parse_args()

    sources = args.source or ["regulatory_ai_extracts", "classification_decisions", "declaration_examples"]
    batch_size = max(1, min(64, int(args.batch_size)))
    retries = max(1, int(args.retries))
    sleep_sec = max(0.0, float(args.sleep_sec))
    total_in = 0
    total_saved = 0

    existing = _existing_synthetic_hs() if args.only_missing else set()

    for source in sources:
        rows_raw = list(_iter_rows(source, int(args.limit), max(0, int(args.offset))))
        if args.only_missing and rows_raw:
            rows_raw = [
                r
                for r in rows_raw
                if _synthetic_hs_code(r["source_table"], int(r["source_id"])) not in existing
            ]

        if not rows_raw:
            print(f"[{source}] нет записей для обработки", flush=True)
            continue

        print(f"[{source}] к обработке: {len(rows_raw)}", flush=True)
        total_in += len(rows_raw)

        for i in range(0, len(rows_raw), batch_size):
            chunk = rows_raw[i : i + batch_size]
            texts = [str(r.get("text") or "").strip()[:16000] for r in chunk]
            model_name, vectors = _embed_texts_with_fallback(
                texts,
                batch_size=batch_size,
                retries=retries,
                sleep_sec=sleep_sec,
            )
            saved = 0
            with SessionLocal() as db:
                for row, vec in zip(chunk, vectors):
                    if not vec:
                        continue
                    entry_id = _upsert_tnved_entry(db, row)
                    _upsert_embedding(db, entry_id, model_name, vec)
                    saved += 1
                db.commit()
            total_saved += saved
            print(
                f"[{source}] батч {i // batch_size + 1}: {len(chunk)} -> сохранено {saved} (model={model_name})",
                flush=True,
            )

    print(f"Готово: обработано={total_in}, сохранено={total_saved}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
