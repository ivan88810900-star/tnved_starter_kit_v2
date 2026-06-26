from __future__ import annotations

import os
import re
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.schemas.invoice import AnalyzeInvoiceResponse

# ── Make the existing app/ package importable ────────────────────────────────
_BACKEND_DIR = Path(__file__).resolve().parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


def _parse_origins(raw: str) -> list[str]:
    values = [x.strip() for x in (raw or "").split(",")]
    return [x for x in values if x]


# ── App factory ──────────────────────────────────────────────────────────────
app = FastAPI(
    title="VED·AI SaaS Backend",
    version="2.0.0",
    description="Единый backend: анализ инвойса + полный API ТН ВЭД ЕАЭС.",
)

frontend_origins = _parse_origins(
    os.getenv(
        "FRONTEND_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000",
    )
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=frontend_origins if frontend_origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Mount existing routers from app/ ────────────────────────────────────────
def _mount_existing_routers() -> None:
    try:
        from app.db import init_db
        init_db()
    except Exception as exc:
        print(f"[main] DB init skipped: {exc}")

    try:
        from app.routers.codes import router as codes_router
        app.include_router(codes_router, prefix="/api")
        print("[main] codes router mounted at /api/codes")
    except Exception as exc:
        print(f"[main] codes router skipped: {exc}")

    try:
        from app.routers.tariff import router as tariff_router
        app.include_router(tariff_router, prefix="/api")
        print("[main] tariff router mounted at /api/tariff")
    except Exception as exc:
        print(f"[main] tariff router skipped: {exc}")

    try:
        from app.routers.notes import router as notes_router
        app.include_router(notes_router, prefix="/api")
        print("[main] notes router mounted at /api/notes")
    except Exception as exc:
        print(f"[main] notes router skipped: {exc}")

    try:
        from app.routers.vat import router as vat_router
        app.include_router(vat_router, prefix="/api")
        print("[main] vat router mounted at /api/vat")
    except Exception as exc:
        print(f"[main] vat router skipped: {exc}")


_mount_existing_routers()


# ── Health ───────────────────────────────────────────────────────────────────
@app.get("/health", tags=["system"])
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "ved-ai-saas-backend",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@app.get("/api/db-stats", tags=["system"])
def db_stats() -> dict[str, Any]:
    """Статистика по базе данных для страницы Обзор."""
    try:
        from app.db import SessionLocal
        from sqlalchemy import text
        db = SessionLocal()
        try:
            def count(table: str) -> int:
                try:
                    return db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0
                except Exception:
                    return 0

            return {
                "ok": True,
                "sections": count("tnved_sections"),
                "chapters": count("tnved_chapters"),
                "commodities": count("tnved_commodities"),
                "hs_codes": count("hs_codes"),
                "tariff_rates": count("tariff_rates"),
                "ntm_measures": count("ntm_measures"),
                "data_sources": count("data_sources"),
                "vat_rules": count("vat_rules"),
            }
        finally:
            db.close()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ── Invoice analysis ─────────────────────────────────────────────────────────
def _mock_items() -> list[dict[str, Any]]:
    return [
        {
            "name": "Смартфон с тепловизором IP68",
            "hs_code": "8517130000",
            "hs_code_view": "8517 13 000 0",
            "finance": {"duty_rate": "0%", "vat_rate": 22, "excise": 0},
            "non_tariff_docs": [
                "СС ТР ТС 020/2011 — электромагнитная совместимость",
                "ТР ЕАЭС 037/2016 — ограничение опасных веществ",
                "Нотификация ФСБ России",
            ],
            "risks": [
                "Возможен санкционный контроль (EU/US high-tech restrictions).",
            ],
            "opi_steps": [
                "ОПИ 1: функционально товар относится к аппаратуре связи (гр. 85).",
                "ОПИ 6: детализация до субпозиции 8517 13 000 0.",
            ],
            "payment_profile": {
                "status": "EMBARGO",
                "hs_code": "8517130000",
                "country": "CN",
                "breakdown": {
                    "base_duty": 0.0,
                    "vat": 0.0,
                    "excise": 0.0,
                    "anti_dumping": 0.0,
                    "customs_fee": 0.0,
                    "total_payable": 0.0,
                },
                "documents": [
                    {
                        "doc_type": "Запрет",
                        "legal_ref": "geo_special_duties / санкционные меры",
                        "title": "Запрет ввоза по геополитическим мерам",
                        "detail": "Ввоз товара запрещен по действующим ограничительным мерам.",
                        "source": "geo_special_duties",
                        "priority": 1000,
                    }
                ],
                "geo": {
                    "embargo": True,
                    "measure_type": "embargo",
                    "document_basis": "Нормативные ограничительные меры (демо-режим).",
                    "document_link": "",
                },
                "data_quality": {"confidence": "high"},
            },
        },
        {
            "name": "Набор «Юный химик»",
            "hs_code": "9503007000",
            "hs_code_view": "9503 00 700 0",
            "finance": {"duty_rate": "10%", "vat_rate": 10, "excise": 0},
            "non_tariff_docs": [
                "СС ТР ТС 008/2011 — безопасность игрушек",
                "Маркировка «Честный знак»",
            ],
            "risks": [],
            "opi_steps": [
                "ОПИ 1: классификация в группе 95 (игрушки, игры).",
                "ОПИ 3б: определяющее свойство комплекта — игрушка.",
                "ОПИ 6: итоговая детализация 9503 00 700 0.",
            ],
            "payment_profile": {
                "status": "OK",
                "hs_code": "9503007000",
                "country": "CN",
                "breakdown": {
                    "base_duty": 12500.0,
                    "vat": 51250.0,
                    "excise": 0.0,
                    "anti_dumping": 0.0,
                    "customs_fee": 7750.0,
                    "total_payable": 71500.0,
                },
                "documents": [
                    {
                        "doc_type": "ДС",
                        "legal_ref": "ТР ТС 008/2011",
                        "title": "Декларация о соответствии ТР ТС 008/2011",
                        "detail": "Требуется ДС для выпуска в обращение детских наборов.",
                        "source": "compliance_resolver",
                        "priority": 950,
                    },
                    {
                        "doc_type": "Лицензия",
                        "legal_ref": "ФСТЭК/Минпромторг",
                        "title": "Лицензия ФСТЭК (при наличии контролируемых компонентов)",
                        "detail": "Проверить необходимость лицензии по профилю комплекта и составу реагентов.",
                        "source": "compliance_resolver",
                        "priority": 700,
                    },
                ],
                "geo": {"embargo": False},
                "data_quality": {"confidence": "medium"},
            },
        },
    ]


def _customs_backend_import_path() -> Path:
    return Path(__file__).resolve().parents[1] / "customs-clear" / "backend"


# Фасад и тяжёлый бэкенд оба используют пакетное имя ``app`` — без swap ``sys.modules``
# импорт ``app.services.*`` из customs-clear не сработает после ``from app.schemas...``.
_heavy_backend_import_lock = threading.Lock()


def _run_with_heavy_backend_imports(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Временно подменяет дерево ``app.*`` в ``sys.modules`` на пакеты из ``customs-clear/backend``.

    На ``sys.path`` одновременно лежат фасад ``backend/`` (есть ``app/__init__.py``) и
    ``customs-clear/backend`` (без ``app/__init__.py``). Импорт ``app.db`` иначе закрепляет
    *фасадный* ``app``, и ``app.services.classification_feedback_service`` не находится.
    Поэтому на время импорта убираем корень фасада из ``sys.path`` и ставим тяжёлый бэкенд первым.
    """
    customs = _customs_backend_import_path()
    if not customs.is_dir():
        raise HTTPException(
            status_code=503,
            detail="Тяжёлый бэкенд (customs-clear/backend) не найден — feedback недоступен.",
        )
    heavy_root = str(customs.resolve())
    facade_root = str(_BACKEND_DIR.resolve())
    with _heavy_backend_import_lock:
        saved_app_tree: dict[str, Any] = {}
        to_drop = [k for k in list(sys.modules) if k == "app" or k.startswith("app.")]
        for k in to_drop:
            saved_app_tree[k] = sys.modules.pop(k)
        path_backup = sys.path.copy()
        try:
            sys.path[:] = [heavy_root] + [
                p for p in path_backup if os.path.abspath(os.path.expanduser(p)) != facade_root
            ]
            from app.db import SessionLocal as HeavySession  # type: ignore[import-not-found]
            from app.services.classification_feedback_service import (  # type: ignore[import-not-found]
                approve_classification,
                build_embedding_for_example,
            )

            return fn(HeavySession, approve_classification, build_embedding_for_example, *args, **kwargs)
        finally:
            to_clean = [k for k in list(sys.modules) if k == "app" or k.startswith("app.")]
            for k in to_clean:
                sys.modules.pop(k, None)
            sys.modules.update(saved_app_tree)
            sys.path[:] = path_backup


async def _try_real_invoice_parse(uploaded_file: UploadFile) -> dict[str, Any] | None:
    customs_backend = _customs_backend_import_path()
    if not customs_backend.exists():
        return None
    backend_path_str = str(customs_backend)
    if backend_path_str not in sys.path:
        sys.path.insert(0, backend_path_str)
    try:
        from app.services.document_invoice_analyze import analyze_invoice_file  # type: ignore
    except Exception:
        return None
    try:
        file_bytes = await uploaded_file.read()
        parsed = await analyze_invoice_file(
            data=file_bytes,
            filename=uploaded_file.filename or "invoice.bin",
            content_type=uploaded_file.content_type,
        )
    except Exception:
        return None
    if parsed.get("status") != "OK":
        return {"status": "ERROR", "error": parsed.get("error") or "Ошибка парсинга"}
    items: list[dict[str, Any]] = []
    for row in parsed.get("items") or []:
        if not isinstance(row, dict):
            continue
        hs = "".join(ch for ch in str(row.get("suggested_hs_code") or "") if ch.isdigit())[:10]
        payment_profile = row.get("payment_profile")
        if payment_profile is None:
            enrichment = row.get("enrichment")
            if isinstance(enrichment, dict):
                payment_profile = enrichment.get("payment_profile")
        items.append({
            "name": str(row.get("name") or "").strip() or "Товар без названия",
            "hs_code": hs,
            "hs_code_view": hs,
            "finance": {"duty_rate": "—", "vat_rate": 22, "excise": 0},
            "non_tariff_docs": ["Проверить документы по профилю ТН ВЭД"],
            "risks": [],
            "opi_steps": ["Режим MVP: возвращён результат базового парсера инвойса."],
            "payment_profile": payment_profile if isinstance(payment_profile, dict) else None,
        })
    return {"status": "OK", "mode": "real_parser", "source": parsed.get("source"), "items": items}


@app.post("/api/analyze-invoice", tags=["invoice"], response_model=AnalyzeInvoiceResponse)
async def analyze_invoice(
    file: UploadFile | None = File(default=None),
    use_mock: bool = Form(default=True),
) -> dict[str, Any]:
    if use_mock or file is None:
        return {"status": "OK", "mode": "mock", "items_count": 2, "items": _mock_items()}

    real = await _try_real_invoice_parse(file)
    if real is None or real.get("status") != "OK":
        return {
            "status": "OK",
            "mode": "mock_fallback",
            "warning": (real or {}).get("error") or "Реальный parser недоступен.",
            "items_count": 2,
            "items": _mock_items(),
        }
    items = list(real.get("items") or [])
    return {
        "status": "OK",
        "mode": real.get("mode", "real_parser"),
        "source": real.get("source", ""),
        "items_count": len(items),
        "items": items,
    }


# ── Classification feedback (facade → heavy backend, тот же DB что и RAG) ─────


class ApproveClassificationRequest(BaseModel):
    """Утверждение «описание товара → 10-значный код ТН ВЭД» для самообучения RAG."""

    original_description: str = Field(
        ...,
        min_length=3,
        max_length=8000,
        description="Оригинальное описание товара из инвойса",
    )
    approved_hs_code: str = Field(
        ...,
        description="Подтверждённый код ТН ВЭД (цифры, допускаются пробелы)",
    )
    user_note: str | None = Field(default=None, max_length=2000)
    user_id: str | None = Field(default=None, max_length=128)
    invoice_context: str | None = Field(default=None, max_length=4000)


class ApproveClassificationResponse(BaseModel):
    example_id: int
    hs_code: str
    description: str
    source: str
    created: bool
    embedding_scheduled: bool


def _facade_classify_feedback_handler(
    payload: ApproveClassificationRequest,
    background_tasks: BackgroundTasks,
) -> ApproveClassificationResponse:
    hs_clean = re.sub(r"\D", "", payload.approved_hs_code or "")[:10]
    if len(hs_clean) != 10:
        raise HTTPException(
            status_code=400,
            detail="approved_hs_code должен содержать ровно 10 цифр",
        )

    pieces: list[str] = [payload.original_description.strip()]
    if payload.invoice_context and payload.invoice_context.strip():
        pieces.append(f"[Контекст инвойса] {payload.invoice_context.strip()}")
    full_description = "\n".join(p for p in pieces if p)[:8000]

    note = (payload.user_note or "").strip()
    uid = (payload.user_id or "").strip() or None

    def _inner(HeavySession: Any, approve_classification: Any, build_embedding_for_example: Any) -> ApproveClassificationResponse:
        db = HeavySession()
        try:
            result = approve_classification(
                db,
                description=full_description,
                approved_hs_code=hs_clean,
                user_note=note,
                user_id=uid,
            )
            db.commit()
        except ValueError as exc:
            db.rollback()
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"persist failed: {exc!s}") from exc
        finally:
            db.close()

        example_id = int(result["example_id"])
        scheduled = False
        try:
            background_tasks.add_task(build_embedding_for_example, example_id)
            scheduled = True
        except Exception:
            scheduled = False

        return ApproveClassificationResponse(
            example_id=example_id,
            hs_code=str(result["hs_code"]),
            description=str(result["description"]),
            source=str(result["source"]),
            created=bool(result["created"]),
            embedding_scheduled=scheduled,
        )

    return _run_with_heavy_backend_imports(_inner)


@app.post(
    "/api/classify/feedback/approve",
    tags=["invoice", "classify-feedback"],
    status_code=201,
    response_model=ApproveClassificationResponse,
    summary="Подтвердить код ТН ВЭД (feedback loop → база прецедентов)",
)
async def classify_feedback_approve(
    payload: ApproveClassificationRequest,
    background_tasks: BackgroundTasks,
) -> ApproveClassificationResponse:
    """Проброс на ``customs-clear/backend``: запись в ``declaration_examples`` + фоновый эмбеддинг."""
    return _facade_classify_feedback_handler(payload, background_tasks)
