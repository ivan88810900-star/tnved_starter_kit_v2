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
    type_label: str = ""


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


class ClassificationDecisionOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    kind: str = "classification"
    hs_code: str = ""
    decision_number: str = ""
    issue_date: str = ""
    product_name: str = ""
    target_entity: str = ""
    description: str = ""
    source: str = "fts"


class PreliminaryDecisionOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    kind: str = "preliminary"
    hs_code: str = ""
    description: str = ""
    source: str = "ifcg"


class PreliminaryDecisionsBlockOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    classification_decisions: list[ClassificationDecisionOut] = Field(default_factory=list)
    preliminary_decisions: list[PreliminaryDecisionOut] = Field(default_factory=list)
    total_count: int = 0
    empty_message: str = ""


class PermitMeasureOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str = Field("", description="ДС | СС | СГР | РУ | ЛЗ")
    document: str = ""
    description: str = ""


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
    measures: list[PermitMeasureOut] = Field(default_factory=list)
    intellectual_properties: list[IntellectualPropertyOut] = Field(default_factory=list)
    preliminary_decisions: PreliminaryDecisionsBlockOut = Field(default_factory=PreliminaryDecisionsBlockOut)
    chapter: ChapterOut | None = None
    section: SectionOut | None = None
