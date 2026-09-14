"""Structured transaction facts for conservative official NTM applicability.

The HS code and free-text description remain the first-pass candidate filter.
These optional facts let the official evaluators resolve explicit conditions and
exclusions without treating keywords as legal proof.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


IsoCountryCode = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_upper=True,
        min_length=2,
        max_length=3,
        pattern=r"^[A-Za-z]{2,3}$",
    ),
]


class NtmRegistryMatchFacts(BaseModel):
    """Caller-supplied provenance for one exact official-registry row."""

    model_config = ConfigDict(extra="forbid")

    verified: bool | None = None
    exact_match: bool | None = None
    active: bool | None = None
    exact_model_match: bool | None = None
    registration_number: str | None = Field(default=None, max_length=200)
    number: str | None = Field(default=None, max_length=200)
    registry_number: str | None = Field(default=None, max_length=200)
    source_url: str | None = Field(default=None, max_length=2000)
    evidence_url: str | None = Field(default=None, max_length=2000)
    registry_url: str | None = Field(default=None, max_length=2000)


class NtmCryptoExemptionFacts(BaseModel):
    """Exact facts for one curated section-2.19 exemption."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(min_length=1, max_length=200)
    verified: bool | None = None
    exact_match: bool | None = None
    source_url: str | None = Field(default=None, max_length=2000)
    evidence_url: str | None = Field(default=None, max_length=2000)
    quantity: int | None = Field(default=None, gt=0, strict=True)
    importer_role: str | None = Field(default=None, max_length=500)
    operator_role: str | None = Field(default=None, max_length=500)
    purpose: str | None = Field(default=None, max_length=1000)
    personal_use: bool | None = None
    natural_person: bool | None = None
    category: str | None = Field(default=None, max_length=200)


class NtmFrequencyRangeFacts(BaseModel):
    """One explicitly bounded operating-frequency range in MHz."""

    model_config = ConfigDict(extra="forbid")

    min: float = Field(ge=0)
    max: float = Field(ge=0)


NtmFrequencyFactsList = Annotated[
    list[float | NtmFrequencyRangeFacts],
    Field(max_length=100),
]


class NtmTransactionFacts(BaseModel):
    """User- or document-supplied facts used by exact NTM evaluators.

    Every field is optional.  An omitted fact is unknown and therefore cannot
    promote an ``из``/prefix candidate to ``definite``.
    """

    model_config = ConfigDict(extra="forbid")

    direction: Literal["import", "export", "transit"] | None = None
    transit_route: Literal[
        "border_to_border",
        "arrival_to_internal",
        "internal_to_exit",
    ] | None = None
    origin_country: IsoCountryCode | None = None
    destination_country: IsoCountryCode | None = None
    intended_use: str | None = Field(default=None, max_length=1000)
    end_user: str | None = Field(default=None, max_length=1000)
    composition: list[str] = Field(default_factory=list, max_length=100)
    cas_numbers: list[str] = Field(default_factory=list, max_length=100)
    product_name_matches_official_row: bool | None = None
    manufacturer_documents_verified: bool | None = None
    official_list_item: str | None = Field(default=None, max_length=200)
    evidence_documents: list[str] = Field(default_factory=list, max_length=30)

    # Decision 299 / sanitary registration.
    first_import: bool | None = None
    food_contact: bool | None = None
    drinking_water_contact: bool | None = None
    disinfectant_use: bool | None = None
    personal_hygiene_use: bool | None = None

    # Decisions 317, 318 and 157.
    animal_origin: bool | None = None
    feed_use: bool | None = None
    veterinary_use: bool | None = None
    used_animal_equipment: bool | None = None
    processing_method: str | None = Field(default=None, max_length=500)
    packaging: str | None = Field(default=None, max_length=500)
    phytosanitary_risk_tier: Literal["high", "low", "not_listed"] | None = None

    # Decision 30 waste/cultural/chemical conditions.
    is_waste: bool | None = None
    hazardous_waste: bool | None = None
    waste_class: str | None = Field(default=None, max_length=200)
    contamination: list[str] = Field(default_factory=list, max_length=100)
    cultural_age_years: int | None = Field(default=None, ge=0, le=100_000)
    declared_value: float | None = Field(default=None, ge=0)
    sealed_container: bool | None = None
    package_volume_ml: float | None = Field(default=None, ge=0)
    package_mass_g: float | None = Field(default=None, ge=0)
    substance_purity_percent: float | None = Field(default=None, ge=0, le=100)

    # Sections 2.16 and 2.19.
    embedded_radio: bool | None = None
    radio_technology: list[str] = Field(default_factory=list, max_length=50)
    frequency_mhz: (
        float
        | NtmFrequencyRangeFacts
        | NtmFrequencyFactsList
        | None
    ) = None
    transmitter_power_mw: float | None = Field(default=None, ge=0)
    radio_registry_exemption: bool | NtmRegistryMatchFacts | None = None
    radio_registry_evidence_url: str | None = Field(default=None, max_length=2000)
    cryptography_present: bool | None = None
    crypto_functions: list[str] = Field(default_factory=list, max_length=100)
    mass_market: bool | None = None
    notification_registry_number: str | None = Field(default=None, max_length=200)
    notification_registry_verified: bool | NtmRegistryMatchFacts | None = None
    crypto_exemption: bool | NtmCryptoExemptionFacts | None = None
    registry_evidence_url: str | None = Field(default=None, max_length=2000)

    # Russian export control and transaction-level catch-all review.
    export_control_list_item: str | None = Field(default=None, max_length=200)
    technical_parameters_confirmed: bool | None = None
    catch_all_risk: (
        Literal["none", "unknown", "indicators_present", "confirmed"] | None
    ) = None
    military_end_use: bool | None = None
    wmd_end_use: bool | None = None
    sanctioned_end_user: bool | None = None


def dump_ntm_transaction_facts(facts: NtmTransactionFacts | None) -> dict[str, object]:
    """Return only facts explicitly supplied by the caller."""

    if facts is None:
        return {}
    return facts.model_dump(exclude_none=True, exclude_defaults=True)
