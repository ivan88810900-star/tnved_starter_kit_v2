from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

PaymentLineStatus = Literal[
    "applied",
    "not_applicable",
    "manual_override",
    "manual_review_required",
    "unknown",
    "not_configured",
    "embargo",
]


class PaymentQuoteLineItem(BaseModel):
    code: str = Field(description="Стабильный идентификатор строки (duty, vat, customs_fee, excise, antidumping, special_duty).")
    label: str
    amount_rub: float | None = Field(
        default=None,
        description="Сумма в руб.; null если сумма не определена (manual_review / unknown).",
    )
    status: PaymentLineStatus
    reason: str = ""
    source: str = ""
    rate_label: str | None = None


class PaymentQuoteAssumption(BaseModel):
    key: str
    label: str
    value: str


class PaymentQuoteWarning(BaseModel):
    code: str
    message: str
    severity: Literal["info", "warning", "error"] = "warning"


class PaymentQuoteRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    hs_code: str
    customs_value: float
    invoice_currency: str = Field(default="RUB", validation_alias=AliasChoices("invoice_currency", "currency"))
    freight: float = 0.0
    insurance: float | None = None
    duty_rate: float | None = None
    vat_rate: float | None = None
    excise: float | None = None
    country: str | None = Field(default=None, validation_alias=AliasChoices("country", "country_of_origin"))
    quantity: float | None = None
    net_weight_kg: float | None = Field(default=None, validation_alias=AliasChoices("net_weight_kg", "weight_kg"))
    extra_quantity: float | None = None
    apply_reduced_vat: bool = False
    description: str | None = Field(default=None, description="Описание товара (контекст для UI, не влияет на расчёт).")


class PaymentQuoteResponse(BaseModel):
    status: str
    hs_code: str
    country: str | None = None
    description: str | None = None
    customs_value_rub: float
    invoice_currency: str
    line_items: list[PaymentQuoteLineItem] = Field(default_factory=list)
    total_payable_rub: float | None = Field(
        default=None,
        description="Итого к уплате; null если есть неопределённые обязательные строки.",
    )
    total_partial_rub: float | None = Field(
        default=None,
        description="Частичная сумма по строкам с известными amount_rub (для справки).",
    )
    warnings: list[PaymentQuoteWarning] = Field(default_factory=list)
    assumptions: list[PaymentQuoteAssumption] = Field(default_factory=list)
    data_quality: dict | None = None
    sources: list[dict] = Field(default_factory=list)
    legal_basis: dict | None = None
    geo: dict | None = None
