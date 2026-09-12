from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from ..db import is_read_only_mode
from ..services.normative_store import get_integrated_data_stats, get_normative_data_hints, list_source_status, list_sync_log
from ..services.regulatory_source_completeness import (
    list_registry_snapshot,
    run_regulatory_source_completeness_report,
)
from ..services.regulatory_source_updates import (
    build_update_plan,
    list_regulatory_source_reviews,
    load_last_update_report,
    regulatory_review_queue_summary,
    resolve_regulatory_source_review,
    run_regulatory_update_cycle,
)
from ..services.scheduler import is_scheduler_running, regulatory_jobs_status
from ..services.official_payment_coverage_audit import run_official_payment_coverage_audit
from ..services.payment_data_coverage import run_payment_data_coverage_report
from ..services.payment_data_normalization import run_payment_data_normalization_report
from ..services.import_duty_ingestion import run_import_duty_apply, run_import_duty_dry_run
from ..services.excise_ingestion import run_excise_apply, run_excise_dry_run
from ..services.vat_ingestion import run_vat_apply, run_vat_dry_run
from ..services.anti_dumping_ingestion import run_anti_dumping_apply, run_anti_dumping_dry_run
from ..services.countervailing_ingestion import run_countervailing_apply, run_countervailing_dry_run
from ..services.special_safeguard_ingestion import run_special_safeguard_apply, run_special_safeguard_dry_run
from ..services.payment_source_ingestion import (
    run_payment_source_ingestion_dry_run,
    run_payment_source_ingestion_plan,
)
from ..services.payment_source_registry import list_payment_registry_snapshot
from ..services.normative_bundle import import_normative_bundle_bytes
from ..services.source_import import import_normative_file
from ..services.data_refresh_service import check_data_freshness, run_full_data_refresh
from ..services.source_sync import sync_all_sources, sync_normative_bundle_url
from ..services.tamdoc_sync import (
    approve_tamdoc_candidate,
    approve_tamdoc_candidates_batch,
    list_tamdoc_candidates,
    reject_tamdoc_candidate,
    sync_tamdoc_archive,
    sync_tamdoc_documents,
    sync_tamdoc_targeted,
)
from ..services.trois_sync import sync_trois_sources
from ..security import require_admin_token
from .tnved_catalog import clear_preview_cache

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


router = APIRouter()


class RegulatoryReviewResolutionIn(BaseModel):
    asserted_by: str = Field(min_length=1, max_length=128)
    resolution_ref: str = Field(min_length=1, max_length=2048)
    evidence_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    evidence_generation: int = Field(ge=1)


@router.get("/status")
async def sources_status() -> JSONResponse:
    return JSONResponse(
        {
            "status": "OK",
            "sources": list_source_status(),
            "stats": get_integrated_data_stats(),
            "hints": get_normative_data_hints(),
        }
    )


@router.get("/registry")
async def sources_registry() -> JSONResponse:
    """Статический реестр нормативных источников с уровнями полномочий (без DB-проб)."""
    return JSONResponse(list_registry_snapshot())


@router.get("/completeness")
async def sources_completeness() -> JSONResponse:
    """Gap-отчёт полноты нормативных источников: missing/stale/partial/parser_failed."""
    return JSONResponse(run_regulatory_source_completeness_report())


@router.get("/updates/plan")
async def sources_updates_plan() -> JSONResponse:
    """Lifecycle-policy каждого источника: auto, validation, review или disabled."""
    return JSONResponse(build_update_plan())


@router.get("/updates/status")
async def sources_updates_status() -> JSONResponse:
    """Последний persisted-отчёт и следующее расписание обновлений."""
    last_run = load_last_update_report()
    review_queue = regulatory_review_queue_summary()
    effective_status = (
        "review_required"
        if review_queue["notification_required"]
        else (
            "ok"
            if last_run and str(last_run.get("status") or "") == "review_required"
            else (str(last_run.get("status") or "unknown") if last_run else "never_run")
        )
    )
    return JSONResponse(
        {
            "status": effective_status,
            "read_only": is_read_only_mode(),
            "scheduler": {
                "running": is_scheduler_running(),
                "jobs": regulatory_jobs_status(),
            },
            "last_run": last_run,
            "review_queue": review_queue,
        }
    )


@router.get("/updates/reviews")
async def sources_updates_reviews(
    status: str = Query(
        "pending",
        pattern="^(pending|resolved|superseded|all)$",
    ),
    limit: int = Query(200, ge=1, le=1000),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> JSONResponse:
    """Durable review items; pending rows are the machine-readable alert contract."""
    require_admin_token(x_admin_token)
    summary = regulatory_review_queue_summary()
    rows = list_regulatory_source_reviews(status=status, limit=limit)  # type: ignore[arg-type]
    return JSONResponse(
        {
            "status": summary["status"],
            "notification_required": summary["notification_required"],
            "review_queue": {key: value for key, value in summary.items() if key != "items"},
            "items": rows,
        }
    )


@router.post("/updates/reviews/{review_id}/resolve")
async def sources_updates_review_resolve(
    review_id: int,
    payload: RegulatoryReviewResolutionIn,
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> JSONResponse:
    """Resolve a reviewed item with named reviewer and durable evidence reference."""
    authenticated_actor = require_admin_token(x_admin_token)
    if is_read_only_mode():
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "read_only_mode",
                "message": "Изменение очереди review запрещено в CUSTOMSCLEAR_READ_ONLY режиме.",
            },
        )
    try:
        row = resolve_regulatory_source_review(
            review_id,
            authenticated_actor=authenticated_actor,
            asserted_by=payload.asserted_by,
            resolution_ref=payload.resolution_ref,
            evidence_sha256=payload.evidence_sha256,
            evidence_generation=payload.evidence_generation,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JSONResponse({"status": "resolved", "review": row})


@router.post("/updates/run")
async def sources_updates_run(
    cadence: str = Query("daily", pattern="^(daily|weekly|monthly|all)$"),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> JSONResponse:
    """Ручной guarded-запуск тех же безопасных structured-sync, что и scheduler."""
    require_admin_token(x_admin_token)
    if is_read_only_mode():
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "read_only_mode",
                "message": "Обновление источников запрещено в CUSTOMSCLEAR_READ_ONLY режиме.",
            },
        )
    return JSONResponse(await run_regulatory_update_cycle(cadence, apply_safe=True))  # type: ignore[arg-type]


@router.get("/payment-coverage")
async def sources_payment_coverage() -> JSONResponse:
    """Диагностика покрытия ТН ВЭД, тарифов, НДС, акциза, торговых мер и курсов валют."""
    return JSONResponse(run_payment_data_coverage_report())


@router.get("/payment-coverage-audit")
async def sources_payment_coverage_audit() -> JSONResponse:
    """Read-only аудит official payment/remedy coverage по шести доменам (EEC_ETT … EEC_COUNTERVAILING)."""
    return JSONResponse(run_official_payment_coverage_audit())


@router.get("/payment-normalization")
async def sources_payment_normalization() -> JSONResponse:
    """Readiness-отчёт нормализации платёжных источников (пошлина, НДС, акциз, антидемпинг)."""
    return JSONResponse(run_payment_data_normalization_report())


@router.get("/payment-ingestion/plan")
async def sources_payment_ingestion_plan() -> JSONResponse:
    """План ingestion официальных платёжных источников (read-only, без мутации БД)."""
    return JSONResponse(run_payment_source_ingestion_plan())


@router.post("/payment-ingestion/dry-run")
async def sources_payment_ingestion_dry_run() -> JSONResponse:
    """Dry-run ingestion: парсинг локальных кандидатов, оценки строк, db_mutated=false."""
    return JSONResponse(run_payment_source_ingestion_dry_run())


@router.post("/payment-ingestion/import-duty/dry-run")
async def sources_import_duty_dry_run() -> JSONResponse:
    """Dry-run import-duty: insert/update/skip counts без мутации БД."""
    return JSONResponse(run_import_duty_dry_run())


@router.post("/payment-ingestion/import-duty/apply")
async def sources_import_duty_apply(
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> JSONResponse:
    """Guarded apply import-duty из локального official EEC/ETT bundle."""
    require_admin_token(x_admin_token)
    data = run_import_duty_apply()
    clear_preview_cache()
    return JSONResponse(data)


@router.post("/payment-ingestion/vat/dry-run")
async def sources_vat_dry_run() -> JSONResponse:
    """Dry-run VAT: insert/update/skip counts без мутации БД."""
    return JSONResponse(run_vat_dry_run())


@router.post("/payment-ingestion/vat/apply")
async def sources_vat_apply(
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> JSONResponse:
    """Guarded apply VAT из локального official EEC/ETT bundle."""
    require_admin_token(x_admin_token)
    data = run_vat_apply()
    clear_preview_cache()
    return JSONResponse(data)


@router.post("/payment-ingestion/excise/dry-run")
async def sources_excise_dry_run() -> JSONResponse:
    """Dry-run excise: update/skip counts без мутации БД."""
    return JSONResponse(run_excise_dry_run())


@router.post("/payment-ingestion/excise/apply")
async def sources_excise_apply(
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> JSONResponse:
    """Guarded apply excise из локального official bundle."""
    require_admin_token(x_admin_token)
    data = run_excise_apply()
    clear_preview_cache()
    return JSONResponse(data)


@router.post("/payment-ingestion/anti-dumping/dry-run")
async def sources_anti_dumping_dry_run() -> JSONResponse:
    """Dry-run anti-dumping: insert/update/skip counts без мутации БД."""
    return JSONResponse(run_anti_dumping_dry_run())


@router.post("/payment-ingestion/anti-dumping/apply")
async def sources_anti_dumping_apply(
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> JSONResponse:
    """Guarded apply anti-dumping из локального official EEC bundle."""
    require_admin_token(x_admin_token)
    data = run_anti_dumping_apply()
    clear_preview_cache()
    return JSONResponse(data)


@router.post("/payment-ingestion/special-safeguard/dry-run")
async def sources_special_safeguard_dry_run() -> JSONResponse:
    """Dry-run special-safeguard: insert/update/skip counts без мутации БД."""
    return JSONResponse(run_special_safeguard_dry_run())


@router.post("/payment-ingestion/special-safeguard/apply")
async def sources_special_safeguard_apply(
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> JSONResponse:
    """Guarded apply special-safeguard из локального official EEC bundle."""
    require_admin_token(x_admin_token)
    data = run_special_safeguard_apply()
    clear_preview_cache()
    return JSONResponse(data)


@router.post("/payment-ingestion/countervailing/dry-run")
async def sources_countervailing_dry_run() -> JSONResponse:
    """Dry-run countervailing: insert/update/skip counts без мутации БД."""
    return JSONResponse(run_countervailing_dry_run())


@router.post("/payment-ingestion/countervailing/apply")
async def sources_countervailing_apply(
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> JSONResponse:
    """Guarded apply countervailing из локального official EEC bundle."""
    require_admin_token(x_admin_token)
    data = run_countervailing_apply()
    clear_preview_cache()
    return JSONResponse(data)


@router.get("/payment-ingestion/registry")
async def sources_payment_ingestion_registry() -> JSONResponse:
    """Статический реестр платёжных источников по доменам (import_duty, vat, excise, …)."""
    return JSONResponse({"status": "OK", "sources": list_payment_registry_snapshot()})


@router.get("/log")
async def sources_log(
    source_code: Optional[str] = Query(None, description="Фильтр по коду источника"),
    limit: int = Query(50, ge=1, le=200),
) -> JSONResponse:
    """Журнал синхронизаций нормативных источников."""
    return JSONResponse({"status": "OK", "log": list_sync_log(source_code, limit)})


@router.post("/sync")
async def sources_sync(x_admin_token: str | None = Header(None, alias="X-Admin-Token")) -> JSONResponse:
    """Полная синхронизация: ЕЭК, OData, PDF ЕТТ, фиды."""
    require_admin_token(x_admin_token)
    data = await sync_all_sources()
    clear_preview_cache()
    return JSONResponse(data)


@router.post("/sync/tamdoc")
async def sources_sync_tamdoc(
    max_docs: int = Query(12, ge=1, le=200, description="Сколько документов tamdoc обработать за запуск"),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> JSONResponse:
    """Синхронизация нормативки с alta.ru/tamdoc (автопарсинг в БД)."""
    require_admin_token(x_admin_token)
    data = await sync_tamdoc_documents(max_docs=max_docs)
    clear_preview_cache()
    return JSONResponse(data)


@router.post("/sync/tamdoc/targeted")
async def sources_sync_tamdoc_targeted(
    max_docs: int = Query(60, ge=1, le=500, description="Сколько документов tamdoc обработать за запуск"),
    staging_only: bool = Query(False, description="Только собрать кандидатов в staging, без записи в боевые таблицы"),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> JSONResponse:
    """Целевой парсинг alta.ru/tamdoc для НДС-льгот и спецпошлин."""
    require_admin_token(x_admin_token)
    data = await sync_tamdoc_targeted(max_docs=max_docs, staging_only=staging_only)
    clear_preview_cache()
    return JSONResponse(data)


@router.get("/sync/tamdoc/candidates")
async def sources_sync_tamdoc_candidates(
    limit: int = Query(100, ge=1, le=500),
    status: Optional[str] = Query(None, description="Фильтр: pending|error|skipped|approved|rejected"),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> JSONResponse:
    """Просмотр staging-кандидатов, собранных целевым парсером tamdoc."""
    require_admin_token(x_admin_token)
    return JSONResponse({"status": "OK", "items": list_tamdoc_candidates(limit=limit, status=status)})


@router.post("/sync/tamdoc/candidates/{candidate_id}/approve")
async def sources_sync_tamdoc_candidate_approve(
    candidate_id: int,
    include_non_tariff: bool = Query(False, description="Добавлять ли также generic-запись в non_tariff_measures"),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> JSONResponse:
    require_admin_token(x_admin_token)
    data = approve_tamdoc_candidate(candidate_id=candidate_id, include_non_tariff=include_non_tariff)
    clear_preview_cache()
    if data.get("status") == "ERROR":
        raise HTTPException(status_code=404, detail=str(data.get("error", "candidate_not_found")))
    return JSONResponse(data)


@router.post("/sync/tamdoc/candidates/{candidate_id}/reject")
async def sources_sync_tamdoc_candidate_reject(
    candidate_id: int,
    reason: Optional[str] = Query(None, description="Причина отклонения"),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> JSONResponse:
    require_admin_token(x_admin_token)
    data = reject_tamdoc_candidate(candidate_id=candidate_id, reason=reason or "")
    clear_preview_cache()
    if data.get("status") == "ERROR":
        raise HTTPException(status_code=404, detail=str(data.get("error", "candidate_not_found")))
    return JSONResponse(data)


@router.post("/sync/tamdoc/candidates/approve-batch")
async def sources_sync_tamdoc_candidates_approve_batch(
    limit: int = Query(100, ge=1, le=1000),
    status: str = Query("pending", description="Какой статус кандидатов брать в батч"),
    include_non_tariff: bool = Query(False, description="Добавлять ли также generic-запись в non_tariff_measures"),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> JSONResponse:
    require_admin_token(x_admin_token)
    data = approve_tamdoc_candidates_batch(
        limit=limit,
        status=status,
        include_non_tariff=include_non_tariff,
    )
    clear_preview_cache()
    return JSONResponse(data)


@router.post("/sync/tamdoc/archive")
async def sources_sync_tamdoc_archive(
    archive_dir: Optional[str] = Query(None, description="Путь к локальной папке с документами (.html/.txt/.md)"),
    max_files: int = Query(500, ge=1, le=10000),
    staging_only: bool = Query(True, description="Только staging-кандидаты"),
    include_non_tariff: bool = Query(True, description="Импортировать найденные нетарифные строки в БД"),
    auto_approve_pending: bool = Query(False, description="Авто-апрув всех pending-кандидатов после прохода"),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> JSONResponse:
    require_admin_token(x_admin_token)
    data = sync_tamdoc_archive(
        archive_dir=archive_dir,
        max_files=max_files,
        staging_only=staging_only,
        include_non_tariff=include_non_tariff,
        auto_approve_pending=auto_approve_pending,
    )
    clear_preview_cache()
    return JSONResponse(data)


@router.post("/sync/trois")
async def sources_sync_trois(x_admin_token: str | None = Header(None, alias="X-Admin-Token")) -> JSONResponse:
    """Синхронизация ТРОИС из alta/customs с upsert в БД."""
    require_admin_token(x_admin_token)
    data = await sync_trois_sources()
    clear_preview_cache()
    return JSONResponse(data)


@router.post("/sync/ett")
async def sources_sync_ett(x_admin_token: str | None = Header(None, alias="X-Admin-Token")) -> JSONResponse:
    """Quarantined legacy ETT sync; no downloads, rate writes or cache revision."""
    require_admin_token(x_admin_token)
    from ..services.ett_pdf_parser import sync_ett_from_pdfs
    import os
    max_groups = int(os.getenv("ETT_PDF_MAX_GROUPS", "0") or "0")
    data = await sync_ett_from_pdfs(max_groups=max_groups)
    return JSONResponse(data)


@router.post("/sync/odata")
async def sources_sync_odata(x_admin_token: str | None = Header(None, alias="X-Admin-Token")) -> JSONResponse:
    """Синхронизация OData портала ЕАЭС (льготы, реестры)."""
    require_admin_token(x_admin_token)
    from ..services.ett_odata_parser import sync_all_odata
    data = await sync_all_odata()
    clear_preview_cache()
    return JSONResponse(data)


@router.post("/sync/bundle")
async def sources_sync_bundle(x_admin_token: str | None = Header(None, alias="X-Admin-Token")) -> JSONResponse:
    """Подтянуть пакет ТН ВЭД/ЕТТ/нетарифка с URL из NORMATIVE_BUNDLE_URL."""
    require_admin_token(x_admin_token)
    data = await sync_normative_bundle_url()
    clear_preview_cache()
    return JSONResponse(data)


@router.get("/data/freshness")
async def data_freshness() -> JSONResponse:
    """Check freshness of all data domains (bundles, currency rates)."""
    report = check_data_freshness()
    return JSONResponse(report)


@router.post("/data/refresh")
async def data_refresh(
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> JSONResponse:
    """Run coordinated data refresh: CBR rates + excise/anti-dumping dry-run."""
    require_admin_token(x_admin_token)
    result = await run_full_data_refresh(dry_run=True)
    return JSONResponse(result)


@router.get("/template")
async def sources_template() -> FileResponse:
    """Скачать CSV-шаблон нормативных ставок."""
    tpl = _DATA_DIR / "normative_template.csv"
    if not tpl.exists():
        raise HTTPException(status_code=404, detail="Шаблон не найден")
    return FileResponse(
        path=str(tpl),
        media_type="text/csv; charset=utf-8",
        filename="normative_template.csv",
    )


@router.post("/import")
async def sources_import(
    file: UploadFile = File(...),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> JSONResponse:
    require_admin_token(x_admin_token)
    try:
        content = await file.read()
        result = import_normative_file(file.filename or "normative_file", content)
        clear_preview_cache()
        return JSONResponse(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/import/bundle")
async def sources_import_bundle(
    file: UploadFile = File(...),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> JSONResponse:
    """Импорт JSON-пакета: tnved, rates, non_tariff_rules, notes (см. data/normative_bundle.example.json)."""
    require_admin_token(x_admin_token)
    name = (file.filename or "bundle.json").lower()
    if not name.endswith(".json"):
        raise HTTPException(status_code=400, detail="Ожидается файл .json")
    try:
        content = await file.read()
        result = import_normative_bundle_bytes(content, filename=file.filename or "bundle.json")
        clear_preview_cache()
        return JSONResponse(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/template/bundle")
async def sources_template_bundle() -> FileResponse:
    ex = _DATA_DIR / "normative_bundle.example.json"
    if not ex.exists():
        raise HTTPException(status_code=404, detail="Пример пакета не найден")
    return FileResponse(
        path=str(ex),
        media_type="application/json; charset=utf-8",
        filename="normative_bundle.example.json",
    )
