"""Pydantic-схемы для API справочника ТН ВЭД (коды — только строки)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TnvedTreeNode(BaseModel):
    """Узел дерева: вложенные children; code — строка без приведения к числу."""

    model_config = ConfigDict(extra="ignore")

    code: str = Field(..., description="Код позиции (4, 6 или 10 цифр, с ведущими нулями)")
    name: str = Field("", description="Наименование")
    import_duty: str = Field("", description="Текст ставки ввозной пошлины")
    notes: str = Field("", description="Примечания раздела/группы")
    children: list["TnvedTreeNode"] = Field(default_factory=list)


TnvedTreeNode.model_rebuild()


class TnvedTreeResponse(BaseModel):
    status: str = "OK"
    prefix: str = ""
    count_rows: int = 0
    tree: list[TnvedTreeNode] = Field(default_factory=list)


class NonTariffMeasureOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    commodity_code: str
    measure_type: str
    description: str = ""
    document_required: str = ""
    regulatory_act: str = ""


class IntellectualPropertyOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    brand_name: str
    hs_code_prefix: str
    reg_number: str = ""
    right_holder: str = ""


class ChapterOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    code: str
    title: str = ""
    notes: str = ""


class SectionOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    roman_number: str
    title: str = ""
    notes: str = ""


class TnvedCommodityDetailsResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str = "OK"
    code: str
    name: str = ""
    description: str = ""
    unit: str = ""
    supp_unit: str = ""
    weight_coeff: float = 0.0
    import_duty: str = ""
    notes: str = ""
    notes_combined: str = ""
    non_tariff_measures: list[NonTariffMeasureOut] = Field(default_factory=list)
    intellectual_properties: list[IntellectualPropertyOut] = Field(default_factory=list)
    chapter: ChapterOut
    section: SectionOut
