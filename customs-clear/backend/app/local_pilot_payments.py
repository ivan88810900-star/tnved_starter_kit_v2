"""Payment preview for the local pilot. Only the disposable public SQLite copy is writable."""
import re
import sqlite3
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

from fastapi import APIRouter, HTTPException
from sqlalchemy import event, inspect
from sqlalchemy.schema import CreateTable

from .api.calculator import CalculatorRequest, compute_checked
from .api.payments import payment_quote
from .db import Base, engine
from .schemas.payment_quote import PaymentQuoteRequest, PaymentQuoteResponse
from .services.tnved_presentation import PresentationIntegrityError
from .services.tnved_recovery_store import SourceTextProvenanceError, TnvedRecoveryStore


def catalog_code_issue(store: TnvedRecoveryStore, code: str) -> dict | None:
    if not re.fullmatch(r"[0-9]{2,10}", code):
        raise HTTPException(422, "Для расчёта нужен товарный код ТН ВЭД.")
    row = store.lookup(code)
    if row is None:
        raise HTTPException(404, "Код отсутствует в локальном справочнике.")
    if len(code) == 10 and row["code"] == code and row["kind"] == "coded" and not store.has_children(code):
        return None
    return {
        "status": "CLARIFICATION_NEEDED", "hs_code": code,
        "message": "Выберите конечную товарную позицию в справочнике.",
        "suggested_codes": [],
    }


@contextmanager
def pilot_catalog_reader(catalog: Path, check_snapshot: Callable[[], None]):
    try:
        check_snapshot()
        with TnvedRecoveryStore(catalog) as store:
            yield store
        check_snapshot()
    except (OSError, sqlite3.Error, SourceTextProvenanceError, PresentationIntegrityError) as exc:
        raise HTTPException(503, "Не удалось проверить товар по локальному справочнику.") from exc


def pilot_payment_router(catalog: Path, check_snapshot: Callable[[], None], scratch_db: Path) -> APIRouter:
    if engine.url.drivername != "sqlite" or engine.url.database != str(scratch_db):
        raise RuntimeError("Expected the pilot's disposable SQLite copy")
    # Start with an empty economic store. The retained ETT rows remain exclusively
    # in their pinned, read-only chapter databases and are never admitted as rates.
    with engine.begin() as connection:
        existing = set(inspect(connection).get_table_names())
        if existing != {"tr_ts_acts"}:
            raise RuntimeError("Unexpected contents of the public registry copy")
        for table in Base.metadata.sorted_tables:
            if table.name not in existing:
                connection.execute(CreateTable(table))

    @event.listens_for(engine, "checkout")
    def read_only_checkout(dbapi_connection, _record, _proxy):
        dbapi_connection.execute("PRAGMA query_only=ON")

    router = APIRouter()

    @router.post("/api/calculator/calculate", include_in_schema=False)
    @router.post("/api/calculator/compute")
    async def compute(req: CalculatorRequest):
        with pilot_catalog_reader(catalog, check_snapshot) as store:
            # The pilot has no history service. Discard the normal form's save flag.
            preview = req.model_copy(update={"hs_code": req.hs_code.strip().replace(" ", ""), "save_history": False})
            return await compute_checked(preview, lambda code: catalog_code_issue(store, code))

    @router.post("/api/payments/quote", response_model=PaymentQuoteResponse)
    async def quote(req: PaymentQuoteRequest):
        with pilot_catalog_reader(catalog, check_snapshot) as store:
            code = req.hs_code.strip().replace(" ", "")
            issue = catalog_code_issue(store, code)
            if issue:
                raise HTTPException(422, issue["message"])
            return await payment_quote(req.model_copy(update={"hs_code": code}))

    return router
