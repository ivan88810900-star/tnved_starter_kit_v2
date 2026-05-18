from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..security import require_authenticated_user

router = APIRouter(dependencies=[Depends(require_authenticated_user)])


class AiAskRequest(BaseModel):
    question: str = Field(..., min_length=2, max_length=4000)
    code: str = Field("", max_length=64)
    notes: str = Field("", max_length=200000)


@router.post("/ask")
async def ask(req: AiAskRequest):
    q = (req.question or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Вопрос не должен быть пустым")
    try:
        from ..services.ai_assistant import ask_ai_assistant
    except ModuleNotFoundError:
        raise HTTPException(
            status_code=503,
            detail="AI-модуль недоступен: установите backend-зависимости (google-generativeai).",
        )
    # ask_ai_assistant реализует graceful degradation и всегда возвращает строку ответа.
    answer = await ask_ai_assistant(question=q, code=req.code, notes=req.notes)

    return {
        "status": "OK",
        "code": req.code,
        "answer": answer,
    }

