"""Protected invoice lines and catalog choices for the local pilot only."""
import math
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel, Field, StringConstraints

from ..local_pilot_payments import pilot_catalog_reader
from ..security import require_authenticated_user
from ..services.declaration_draft_service import normalize_declaration_line
from ..services.extractor import extract_invoice_and_packing_from_files
from ..services.local_pilot_invoice import PilotDrafts, find_candidates, narrow_candidates


class TextLine(BaseModel):
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=1200)]


class TreeAnswers(BaseModel):
    answers: list[Annotated[str, Field(pattern=r"^[0-9a-f]{24}$")]] = Field(default_factory=list, max_length=24)


class ExplicitChoice(TreeAnswers):
    code: str = Field(pattern=r"^[0-9]{10}$")


def _draft_owner(user: dict = Depends(require_authenticated_user)) -> str:
    if user["role"] not in {"admin", "declarant"}:
        raise HTTPException(403, "Для работы с черновиком нужна роль декларанта.")
    return user["username"]


def pilot_invoice_router(catalog: Path, check_snapshot: Callable[[], None], scratch: Path) -> APIRouter:
    drafts = PilotDrafts(scratch)
    router = APIRouter(prefix="/api/local-invoice/drafts")
    owner_dep = Depends(_draft_owner)

    @router.post("")
    def create(body: TextLine, owner: str = owner_dep):
        return drafts.create(owner, [{"line": 1, "description": body.description, "quantity": None, "unit": ""}])

    @router.post("/upload")
    async def upload(file: UploadFile, owner: str = owner_dep):
        if not (file.filename or "").casefold().endswith(".xlsx"):
            raise HTTPException(422, "Загрузите инвойс в формате .xlsx.")
        if file.size is None or file.size > 4 * 1024 * 1024:
            raise HTTPException(413, "Максимальный размер инвойса — 4 МБ.")
        try:
            with zipfile.ZipFile(file.file) as workbook:
                members = workbook.infolist()
                if len(members) > 500 or sum(m.file_size for m in members) > 16 * 1024 * 1024:
                    raise HTTPException(413, "Рабочая книга превышает допустимый объём.")
        except zipfile.BadZipFile as exc:
            raise HTTPException(422, "Не удалось прочитать рабочую книгу .xlsx.") from exc
        await file.seek(0)
        result = await extract_invoice_and_packing_from_files(file)
        rows = []
        for extracted in result["invoice"]["items"]:
            item = normalize_declaration_line(extracted)
            desc = item["description"]
            if not desc or desc.casefold() == "nan":
                continue
            if len(desc) > 1200 or not math.isfinite(item["quantity"]):
                raise HTTPException(422, "Проверьте описание и количество в строке инвойса.")
            unit = item["unit"]
            rows.append({"line": item["line"], "description": desc, "quantity": item["quantity"],
                         "unit": "" if unit.casefold() == "nan" else unit})
        return drafts.create(owner, rows)

    @router.get("/{draft_id}")
    def restore(draft_id: str, owner: str = owner_dep):
        return drafts.read(owner, draft_id)

    def inspect_line(draft_id: str, number: int, owner: str, answers: list[str]) -> dict:
        line = drafts.line(owner, draft_id, number)
        with pilot_catalog_reader(catalog, check_snapshot) as store:
            matches, limited, notice = find_candidates(store, line["description"])
            candidates, question = narrow_candidates(matches, answers)
        return {"candidates": candidates, "question": question, "limited": limited,
                "selected_code": line["selected_code"], "notice": notice}

    @router.post("/{draft_id}/lines/{line}/candidates")
    def candidates(draft_id: str, line: int, body: TreeAnswers, owner: str = owner_dep):
        return inspect_line(draft_id, line, owner, body.answers)

    @router.put("/{draft_id}/lines/{line}/choice")
    def choose(draft_id: str, line: int, body: ExplicitChoice, owner: str = owner_dep):
        suggestions = inspect_line(draft_id, line, owner, body.answers)
        if body.code not in {candidate["code"] for candidate in suggestions["candidates"]}:
            raise HTTPException(422, "Выберите конечный код из кандидатов этой строки.")
        return drafts.choose(owner, draft_id, line, body.code)

    return router
