import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

# Явно подхватываем backend/.env даже если uvicorn запущен не из каталога backend
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_BACKEND_ROOT / ".env")
load_dotenv()

from .services.normative_store import (
    get_integrated_data_stats,
    get_normative_data_hints,
    init_db,
    list_source_status,
    list_sync_log,
)
from .services.rate_limit_middleware import RateLimitMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger
from sqlalchemy import text

from .api import (
    admin_v1,
    ai,
    alta_integrations,
    analytics,
    assistant,
    auth,
    calculator,
    payments,
    classify,
    classify_feedback,
    compliance,
    currency,
    documents,
    documents_v1,
    finance,
    non_tariff,
    permits,
    regulatory,
    risk,
    search,
    sources,
    trois,
    tnved,
    tnved_catalog,
)
from .db import engine
from .services.exchange_rates import update_exchange_rates_from_cbrf


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    try:
        await update_exchange_rates_from_cbrf()
    except Exception as e:
        logger.warning(f"exchange_rates: автообновление курсов пропущено: {e}")
    try:
        from .services.permits_jobs import mark_interrupted_jobs_on_startup

        mark_interrupted_jobs_on_startup()
    except Exception as e:
        logger.warning(f"permits_verify_jobs: пометка прерванных заданий пропущена: {e}")
    try:
        from .services.ved_intel_jobs import mark_interrupted_ved_intel_jobs_on_startup

        mark_interrupted_ved_intel_jobs_on_startup()
    except Exception as e:
        logger.warning(f"ved_intel_jobs: пометка прерванных заданий пропущена: {e}")
    try:
        from .services.scheduler import shutdown_apscheduler, start_apscheduler

        start_apscheduler()
    except ImportError:
        logger.warning("Пакет apscheduler не установлен — планировщик отключён")
    except Exception as e:
        logger.warning(f"Планировщик не запущен: {e}")
    yield
    try:
        from .services.scheduler import shutdown_apscheduler

        shutdown_apscheduler()
    except Exception:
        pass


app = FastAPI(title="CustomsClear API", version="1.0.0", lifespan=lifespan)

# CORS — для десктопа и веба
origins = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000,http://127.0.0.1:8001").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in origins if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_rpm = int(os.getenv("RATE_LIMIT_PER_MINUTE", "0") or "0")
if os.getenv("RATE_LIMIT_ENABLED", "").lower() in ("1", "true", "yes") and _rpm > 0:
    app.add_middleware(RateLimitMiddleware, per_minute=_rpm)
    logger.info(f"Rate limit: {_rpm} запросов/мин на IP для /api/*")


@app.get("/api/health")
async def health() -> JSONResponse:
    """Простой endpoint для проверки состояния сервиса."""
    return JSONResponse({"status": "OK"})


@app.get("/api/health/normative")
async def health_normative() -> JSONResponse:
    """Сводка нормативной БД и hints (как в /api/sources/status) — для алертов."""
    return JSONResponse(
        {
            "status": "OK",
            "stats": get_integrated_data_stats(),
            "hints": get_normative_data_hints(),
        }
    )


@app.get("/api/health/ready")
async def health_ready() -> JSONResponse:
    """Готовность: БД + опционально Redis."""
    from .services.cache_layer import redis_ping

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        return JSONResponse(
            {"status": "not_ready", "database": False, "error": str(e)},
            status_code=503,
        )
    rping = await redis_ping()
    llm_env = (
        os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
        or ""
    ).strip()
    return JSONResponse(
        {
            "status": "ready",
            "database": True,
            "redis": rping,
            "assistant_llm_configured": bool(llm_env),
        }
    )


@app.get("/api/health/data-pipeline")
async def health_data_pipeline() -> JSONResponse:
    """Сводка нормативных источников и последних синхронизаций — для мониторинга/алертов."""
    sources = list_source_status()
    sync_tail = list_sync_log(limit=8)
    any_stale = any(bool(s.get("is_stale")) for s in sources)
    last_err = next(
        (e for e in sync_tail if (e.get("status") or "").upper() == "ERROR"),
        None,
    )
    body = {
        "status": "DEGRADED" if any_stale or last_err else "OK",
        "any_stale_source": any_stale,
        "sources": sources,
        "sync_log_tail": sync_tail,
        "last_sync_error": last_err,
        "stats": get_integrated_data_stats(),
    }
    return JSONResponse(body, status_code=200)


app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"])
app.include_router(ai.router, prefix="/api/ai", tags=["ai"])
app.include_router(documents.router, prefix="/api/documents", tags=["documents"])
app.include_router(documents_v1.router, prefix="/api/v1/documents", tags=["documents-v1"])
app.include_router(classify.router, prefix="/api/classify", tags=["classify"])
app.include_router(
    classify_feedback.router,
    prefix="/api/classify/feedback",
    tags=["classify-feedback"],
)
app.include_router(trois.router, prefix="/api/trois", tags=["trois"])
app.include_router(calculator.router, prefix="/api/calculator", tags=["calculator"])
app.include_router(payments.router, prefix="/api/payments", tags=["payments"])
app.include_router(currency.router, prefix="/api/currency", tags=["currency"])
app.include_router(finance.router, prefix="/api/v1/finance", tags=["finance"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(non_tariff.router, prefix="/api/non_tariff", tags=["non_tariff"])
app.include_router(regulatory.router, prefix="/api/regulatory", tags=["regulatory"])
app.include_router(assistant.router, prefix="/api/assistant", tags=["assistant"])
app.include_router(assistant.chat_router, prefix="/api/v1/assistant", tags=["assistant-v1"])
app.include_router(sources.router, prefix="/api/sources", tags=["sources"])
app.include_router(compliance.router, prefix="/api/compliance", tags=["compliance"])
app.include_router(risk.router, prefix="/api/risk", tags=["risk"])
app.include_router(search.router, prefix="/api/search", tags=["search"])
app.include_router(permits.router, prefix="/api/permits", tags=["permits"])
app.include_router(alta_integrations.router, prefix="/api/integrations/alta", tags=["integrations-alta"])
app.include_router(tnved.router, prefix="/api/tnved", tags=["tnved"])
app.include_router(
    tnved_catalog.router,
    prefix="/api/v1/tnved",
    tags=["tnved-catalog"],
)
app.include_router(admin_v1.router, prefix="/api/v1/admin", tags=["admin-v1"])

# Статика фронтенда (для десктоп-сборки)
# PyInstaller: sys._MEIPASS; иначе backend/../static
_BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
_STATIC_DIR = _BASE / "static"
if _STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=_STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}")
    async def serve_spa(path: str):
        """SPA: статические файлы или index.html для маршрутов."""
        if path.startswith("api"):
            return JSONResponse({"error": "Not found"}, status_code=404)
        fp = Path(_STATIC_DIR) / path
        if path and fp.is_file():
            return FileResponse(fp)
        return FileResponse(_STATIC_DIR / "index.html")
