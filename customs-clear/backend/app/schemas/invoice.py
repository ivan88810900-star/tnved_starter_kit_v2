from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class InvoiceLine(BaseModel):
    """
    Строка разобранного инвойса/пакинга для /api/documents/ved-intelligent-analyze.
    Схема намеренно допускает дополнительные поля, т.к. пайплайн обогащает item динамически.
    """

    model_config = ConfigDict(extra="allow")

    name: str = ""
    suggested_hs_code: str = ""
    price: float = 0.0
    net_weight_kg: float | None = None
    currency: str = "RUB"

    # Vision-интеграция
    image_paths: list[str] = Field(default_factory=list)
    ai_visual_description: str = ""


class VedIntelligentAnalyzeResponse(BaseModel):
    """
    Контракт ответа /api/documents/ved-intelligent-analyze.
    Дополнительные ключи разрешены (статусы, ai_summary, payment_profile и др.).
    """

    model_config = ConfigDict(extra="allow")

    status: str = "OK"
    items: list[InvoiceLine] = Field(default_factory=list)

