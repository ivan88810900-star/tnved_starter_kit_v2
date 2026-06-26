"""Pydantic-схемы для /api/codes/*.

Фиксируют контракт, на который опирается фронтенд (см. frontend/web/src/types).
"""

from __future__ import annotations

from typing import Optional, List, Literal

from pydantic import BaseModel, Field


HsLevel = Literal["chapter", "heading", "subheading", "item", "section"]


class TariffInfo(BaseModel):
    duty: Optional[str] = None
    vat: Optional[float | int | str] = None
    vat_source: Optional[str] = None
    vat_reason: Optional[str] = None
    add: Optional[str] = None


class PermitMeasure(BaseModel):
    type: str = ""
    document: Optional[str] = None
    description: Optional[str] = None


class CodeNode(BaseModel):
    code: str
    title_ru: Optional[str] = None
    title_full: Optional[str] = Field(
        default=None,
        description="Полный таможенный текст: склеенный путь от главы к узлу.",
    )
    level: Optional[HsLevel] = None
    parent: Optional[str] = None
    chapter: Optional[str] = None
    has_children: Optional[bool] = None
    is_codeless: Optional[bool] = None
    tariff: Optional[TariffInfo] = None
    measures: Optional[List[PermitMeasure]] = None


class CodePathItem(BaseModel):
    code: str
    title_ru: Optional[str] = None
    title_full: Optional[str] = None
    level: Optional[HsLevel] = None


class CodeDetail(BaseModel):
    code: str
    title_ru: Optional[str] = None
    title_full: Optional[str] = None
    level: Optional[HsLevel] = None
    parent: Optional[str] = None
    path: List[CodePathItem] = []
    tariff: Optional[TariffInfo] = None
    measures: List[PermitMeasure] = []
    children: List[CodeNode] = []
