"""Immutable schema-v2 ETT candidate contract (Decision Memo #188, Option A).

Validation establishes structural consistency, never authenticity, legal completeness
or approval. Raw artifacts must independently be hash-verified and a trusted reviewer
must bind their decision to ``manifest_sha256`` before any serving transition.
This module does not read/write a database, fetch documents, approve a candidate or
derive VAT. Dates are supplied explicitly from retained legal evidence.
"""
from __future__ import annotations

import hashlib
from html import unescape
import json
import re
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated, Any, Literal
from urllib.parse import quote, unquote, urljoin, urlsplit

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator, model_serializer, model_validator

EXPECTED_CHAPTERS = tuple(f"{number:02d}" for number in range(1, 98) if number != 77)
EAEU_DESTINATIONS = frozenset({"AM", "BY", "KZ", "KG", "RU"})
SINGLETON_ROLES = frozenset({"index", "nomenclature_notes", "tariff_notes", "amendment_inventory"})
MAX_MANIFEST_BYTES = 64 * 1024 * 1024
_ID = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
_HASH = r"^[0-9a-f]{64}$"
_NUMBER = re.compile(r"^-?(?:0|[1-9][0-9]{0,23})(?:\.[0-9]{1,12})?$")

Identifier = Annotated[StrictStr, Field(pattern=_ID)]
SHA256 = Annotated[StrictStr, Field(pattern=_HASH)]
Code = Annotated[StrictStr, Field(pattern=r"^[0-9]{10}$")]
Text = Annotated[StrictStr, Field(min_length=1, max_length=100_000)]
Destination = Literal["AM", "BY", "KZ", "KG", "RU"]


def _date(value: Any) -> date:
    if type(value) is date:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return date.fromisoformat(value)
    raise ValueError("an explicit ISO calendar date is required; timestamps are not dates")


def _instant(value: Any) -> datetime:
    if isinstance(value, str):
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|\+00:00)", value):
            raise ValueError("an explicit UTC ISO timestamp is required")
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError("an explicit UTC timestamp is required")
    return value.astimezone(timezone.utc)


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if type(value) not in (str, int, Decimal):
        raise ValueError("decimal quantities require an exact string, integer or Decimal, never float/bool")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("decimal quantities must be finite")
        components = value.as_tuple()
        if len(components.digits) > 36 or components.exponent < -12 or components.exponent > 24 or value.adjusted() > 23:
            raise ValueError("decimal quantity exceeds the bounded precision or exponent")
        value = format(value, "f")
    else:
        if isinstance(value, int) and value.bit_length() > 80:
            raise ValueError("integer quantity exceeds the bounded precision")
        value = str(value)
    if not _NUMBER.fullmatch(value):
        raise ValueError("decimal quantities require at most 24 integral and 12 fractional digits")
    return Decimal(value)


def _nonempty(value: str) -> str:
    if not value.strip() or "\x00" in value:
        raise ValueError("text must be nonempty and contain no NUL")
    return value


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True, revalidate_instances="always")


class ETTParserIdentity(_Frozen):
    name: Identifier
    version: Identifier
    sha256: SHA256


class ETTDerivedAmendmentInventory(_Frozen):
    """Derived bytes bind an original index; they have no invented source URL."""
    derivation_kind: Literal["eec_index_amendment_inventory_v1"]
    source_artifact_id: Identifier
    source_artifact_sha256: SHA256
    report_sha256: SHA256
    report_size_bytes: Annotated[StrictInt, Field(gt=0, le=16 * 1024 * 1024)]
    parser: ETTParserIdentity


class ETTArtifact(_Frozen):
    artifact_id: Identifier
    role: Literal["index", "chapter", "nomenclature_notes", "tariff_notes", "amendment_inventory", "amendment"]
    url: Annotated[StrictStr, Field(max_length=4096)]
    sha256: SHA256
    size_bytes: Annotated[StrictInt, Field(gt=0, le=64 * 1024 * 1024)]
    media_type: Literal["application/pdf", "text/html", "application/json", "application/xml", "text/xml"]
    retrieved_at: datetime
    chapter: Annotated[StrictStr, Field(pattern=r"^[0-9]{2}$")] | None = None

    @field_validator("retrieved_at", mode="before")
    @classmethod
    def explicit_instant(cls, value: Any) -> datetime:
        return _instant(value)

    @field_validator("url")
    @classmethod
    def official_url(cls, value: str) -> str:
        if any(ord(char) < 33 or ord(char) == 127 for char in value) or "\\" in value or "?" in value or "#" in value:
            raise ValueError("official URL must have no whitespace, query, fragment or backslash")
        parsed = urlsplit(value)
        if parsed.scheme != "https" or parsed.netloc not in {"eec.eaeunion.org", "docs.eaeunion.org"} or not parsed.path.startswith("/"):
            raise ValueError("official URL must use exact HTTPS EEC/document hosts without credentials or ports")
        if re.search(r"%(?:00|0[ad]|2f|5c)", value, re.IGNORECASE):
            raise ValueError("encoded path separators or controls are forbidden")
        return value

    @model_validator(mode="after")
    def chapter_role(self) -> ETTArtifact:
        if self.role == "chapter":
            if self.chapter not in EXPECTED_CHAPTERS or self.media_type != "application/pdf":
                raise ValueError("a chapter artifact requires a valid chapter and PDF media type")
        elif self.chapter is not None:
            raise ValueError("only chapter artifacts may declare a chapter")
        return self


class ETTEvidence(_Frozen):
    artifact_id: Identifier
    artifact_sha256: SHA256
    page: Annotated[StrictInt, Field(ge=1, le=100_000)]
    row: Annotated[StrictStr, Field(min_length=1, max_length=256)]
    raw_text: Text
    raw_text_sha256: SHA256

    @field_validator("raw_text", "row")
    @classmethod
    def nonempty(cls, value: str) -> str:
        return _nonempty(value)

    @model_validator(mode="after")
    def digest_matches(self) -> ETTEvidence:
        if hashlib.sha256(self.raw_text.encode("utf-8")).hexdigest() != self.raw_text_sha256:
            raise ValueError("raw_text_sha256 does not bind the exact retained UTF-8 text")
        return self


Evidence = Annotated[tuple[ETTEvidence, ...], Field(min_length=1, max_length=128)]


_PORTAL_LABELS = {
    "publication_date": "Дата опубликования",
    "entry_into_force_date_metadata": "Дата вступления в силу",
    "comment": "Комментарий",
}
_PORTAL_MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
    "мая": 5, "июня": 6, "июля": 7, "августа": 8,
    "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}
_PORTAL_DESCRIPTION = re.compile(
    r"Решение (Коллегии|Совета) (?:(?:ЕЭК|Евразийской экономической комиссии) )?"
    r"№\s*([1-9][0-9]{0,5}) от "
    r"([0-9]{2}\.[0-9]{2}\.[0-9]{4}|[0-9]{1,2} (?:" + "|".join(_PORTAL_MONTHS) +
    r") [0-9]{4})(?: (?:г\.?|года))?\Z"
)


def _portal_locator(value: str, role: str) -> tuple[int, int, int]:
    pattern = rf"html:{role}:([1-9][0-9]{{0,5}}):line:([1-9][0-9]{{0,6}}):column:(0|[1-9][0-9]{{0,6}})"
    match = re.fullmatch(pattern, value)
    if match is None:
        raise ValueError("a bounded original legal-portal HTML locator is required")
    position, line, column = map(int, match.groups())
    if position > 256 or line > 4 * 1024 * 1024 or column > 4 * 1024 * 1024:
        raise ValueError("legal-portal HTML locator exceeds source bounds")
    return position, line, column


def _portal_pdf_url(value: str) -> str:
    ETTArtifact.official_url(value)
    parsed = urlsplit(value)
    path = unquote(parsed.path, encoding="utf-8", errors="strict")
    if (parsed.netloc != "docs.eaeunion.org"
            or re.fullmatch(r"/upload/iblock/[^/]+/(?:[^/]+/)*[^/]+\.[pP][dD][fF]", path) is None
            or any(part in {"", ".", ".."} for part in path.split("/")[1:])
            or any(ord(char) < 32 or ord(char) == 127 for char in path)):
        raise ValueError("primary PDF binding requires an exact official legal-portal attachment URL")
    return value


class ETTLegalActIdentity(_Frozen):
    """An asserted identity to replay against originals; never legal approval."""
    issuing_body: Literal["collegium", "council"]
    adoption_date: date
    number: Annotated[StrictStr, Field(pattern=r"^[1-9][0-9]{0,5}$")]

    @field_validator("adoption_date", mode="before")
    @classmethod
    def explicit_adoption_date(cls, value: Any) -> date:
        return _date(value)


class ETTLegalPortalLiteral(_Frozen):
    """Exact visible DOM text projection, including retained source whitespace."""
    locator: Annotated[StrictStr, Field(min_length=1, max_length=256)]
    raw_text: Text
    raw_text_sha256: SHA256

    @model_validator(mode="after")
    def literal_matches(self) -> ETTLegalPortalLiteral:
        _nonempty(self.raw_text)
        _nonempty(self.locator)
        if hashlib.sha256(self.raw_text.encode("utf-8")).hexdigest() != self.raw_text_sha256:
            raise ValueError("portal literal SHA256 must bind the exact retained UTF-8 text")
        return self


class ETTLegalPortalPDFBinding(_Frozen):
    """One observed descriptive PDF anchor; its source occurrence needs replay."""
    artifact_id: Identifier
    artifact_sha256: SHA256
    url: Annotated[StrictStr, Field(min_length=1, max_length=4096)]
    href: Annotated[StrictStr, Field(min_length=1, max_length=4096)]
    raw_href: Annotated[StrictStr, Field(min_length=1, max_length=4096)]
    text: Annotated[StrictStr, Field(min_length=1, max_length=8192)]
    text_sha256: SHA256
    locator: Annotated[StrictStr, Field(min_length=1, max_length=256)]

    @model_validator(mode="after")
    def observed_anchor_is_consistent(self) -> ETTLegalPortalPDFBinding:
        _portal_pdf_url(self.url)
        _portal_locator(self.locator, "a")
        if unescape(self.raw_href) != self.href:
            raise ValueError("raw_href must decode to the exact observed href")
        if (any(ord(char) < 32 or ord(char) == 127 for char in self.href)
                or any(char in self.href for char in "\\?#")
                or not self.href.strip().startswith(("/upload/iblock/", "https://docs.eaeunion.org/upload/iblock/"))):
            raise ValueError("PDF href must be an observed official attachment path")
        original_path = unquote(urlsplit(self.href.strip()).path, encoding="utf-8", errors="strict")
        if any(part in {"", ".", ".."} for part in original_path.split("/")[1:]):
            raise ValueError("PDF href cannot normalize traversal or empty source path segments")
        target = urlsplit(urljoin("https://docs.eaeunion.org/", self.href.strip()))
        resolved = target._replace(path=quote(target.path, safe="/%:@!$&'()*+,;=-._~")).geturl()
        if _portal_pdf_url(resolved) != self.url:
            raise ValueError("observed href does not resolve to the bound primary PDF URL")
        _nonempty(self.text)
        if self.text != " ".join(self.text.split()):
            raise ValueError("PDF anchor text requires its exact normalized visible-text projection")
        if hashlib.sha256(self.text.encode("utf-8")).hexdigest() != self.text_sha256:
            raise ValueError("PDF anchor SHA256 must bind the exact retained text")
        self.described_identity()
        return self

    def described_identity(self) -> ETTLegalActIdentity:
        match = _PORTAL_DESCRIPTION.fullmatch(self.text)
        if match is None:
            raise ValueError("a descriptive PDF anchor with an exact act identity is required")
        literal = match[3]
        if "." in literal:
            day, month, year = map(int, literal.split("."))
        else:
            day_raw, month_raw, year_raw = literal.split()
            day, month, year = int(day_raw), _PORTAL_MONTHS[month_raw], int(year_raw)
        return ETTLegalActIdentity(
            issuing_body="collegium" if match[1] == "Коллегии" else "council",
            adoption_date=date(year, month, day), number=match[2],
        )


class ETTLegalPortalMetadataEvidence(_Frozen):
    """Replayable HTML metadata assertion, allowed only as effective evidence.

    HTML has no fabricated physical ``page``. The exact row, label, value and
    descriptive PDF anchor must independently replay from the included originals.
    An observed portal date is not a verified legal date, and this model never
    computes a commencement date or infers a code-version validity interval.
    """
    kind: Literal["legal_portal_metadata_v1"]
    artifact_id: Identifier
    artifact_sha256: SHA256
    field: Literal["publication_date", "entry_into_force_date_metadata", "comment"]
    locator: Annotated[StrictStr, Field(min_length=1, max_length=256)]
    raw_text: Text
    raw_text_sha256: SHA256
    label: ETTLegalPortalLiteral
    value: ETTLegalPortalLiteral
    parser: ETTParserIdentity
    expected_identity: ETTLegalActIdentity
    pdf_binding: ETTLegalPortalPDFBinding

    @model_validator(mode="after")
    def metadata_assertion_is_consistent(self) -> ETTLegalPortalMetadataEvidence:
        _, row_line, row_column = _portal_locator(self.locator, "metadata-row")
        label_position, label_line, label_column = _portal_locator(self.label.locator, "metadata-label")
        value_position, value_line, value_column = _portal_locator(self.value.locator, "metadata-value")
        if (label_position != 1 or value_position != 1
                or not ((row_line, row_column) <= (label_line, label_column) <= (value_line, value_column))):
            raise ValueError("metadata requires a single ordered label/value pair in its source row")
        _nonempty(self.raw_text)
        if hashlib.sha256(self.raw_text.encode("utf-8")).hexdigest() != self.raw_text_sha256:
            raise ValueError("metadata row SHA256 must bind the exact retained UTF-8 text")
        label, value = " ".join(self.label.raw_text.split()), " ".join(self.value.raw_text.split())
        if label != _PORTAL_LABELS[self.field]:
            raise ValueError("metadata field and its exact official label disagree")
        label_start = self.raw_text.find(self.label.raw_text)
        value_start = self.raw_text.find(self.value.raw_text, label_start + len(self.label.raw_text))
        if (label_start < 0 or value_start < 0
                or " ".join(self.raw_text.split()) != f"{label} {value}"):
            raise ValueError("metadata label and value must bind the exact retained row projection")
        if self.field != "comment":
            if re.fullmatch(r"[0-9]{2}\.[0-9]{2}\.[0-9]{4}", value) is None:
                raise ValueError("metadata date requires one literal DD.MM.YYYY calendar date")
            day, month, year = map(int, value.split("."))
            date(year, month, day)  # Validate only; never derive a legal date.
        if self.parser.name != "ett_legal_metadata" or self.parser.version != "1":
            raise ValueError("unsupported legal-portal metadata parser identity")
        if self.expected_identity != self.pdf_binding.described_identity():
            raise ValueError("expected act identity contradicts the descriptive PDF anchor")
        return self


EffectiveEvidenceItem = ETTEvidence | ETTLegalPortalMetadataEvidence
EffectiveEvidence = Annotated[tuple[EffectiveEvidenceItem, ...], Field(min_length=1, max_length=128)]


class ETTCondition(_Frozen):
    """A conjunction term; numeric facts are compared in the field's named unit.

    Field names are an explicit vocabulary. No expressions, regex, code evaluation,
    inferred units, or synonym/substring matching are supported.
    """
    field: Literal[
        "origin_country", "purpose", "material", "processing", "packaging", "quota_id",
        "composition", "is_organic", "is_used", "product_age_days", "mass_kg",
        "engine_displacement_cm3", "alcohol_percent", "sugar_percent", "fat_percent",
        "power_kw", "length_m",
    ]
    op: Literal["eq", "numeric_interval"]
    value: StrictStr | StrictBool | None = None
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    minimum_inclusive: StrictBool = True
    maximum_inclusive: StrictBool = True

    @field_validator("minimum", "maximum", mode="before")
    @classmethod
    def exact_decimal(cls, value: Any) -> Decimal | None:
        return _decimal(value)

    @model_validator(mode="after")
    def bounded_expression(self) -> ETTCondition:
        numeric = self.field in {"product_age_days", "mass_kg", "engine_displacement_cm3", "alcohol_percent", "sugar_percent", "fat_percent", "power_kw", "length_m"}
        boolean = self.field in {"is_organic", "is_used"}
        if self.op == "eq":
            if numeric or self.value is None or self.minimum is not None or self.maximum is not None:
                raise ValueError("eq supports only exact string/boolean fields with a value")
            if boolean != (type(self.value) is bool):
                raise ValueError("equality value type must match the field")
            if isinstance(self.value, str):
                _nonempty(self.value)
                if len(self.value) > 512:
                    raise ValueError("equality value is too long")
                if self.field == "origin_country" and not re.fullmatch(r"[A-Z]{2}", self.value):
                    raise ValueError("origin_country requires a two-letter uppercase country code")
            if not self.minimum_inclusive or not self.maximum_inclusive:
                raise ValueError("interval flags have no meaning for equality")
        else:
            if not numeric or self.value is not None or (self.minimum is None and self.maximum is None):
                raise ValueError("numeric_interval needs a numeric field and at least one explicit bound")
            if self.minimum is not None and self.minimum < 0 or self.maximum is not None and self.maximum < 0:
                raise ValueError("this schema supports nonnegative product quantities only")
            if self.minimum is None and not self.minimum_inclusive or self.maximum is None and not self.maximum_inclusive:
                raise ValueError("an absent bound cannot declare an exclusion")
            if self.minimum is not None and self.maximum is not None:
                if self.minimum > self.maximum or (self.minimum == self.maximum and not (self.minimum_inclusive and self.maximum_inclusive)):
                    raise ValueError("numeric interval is empty")
        return self


class ETTDuty(_Frozen):
    """A bounded duty expression; percentages use 5 == five percent, not 0.05.

    Specific duty is amount in currency per ``unit_quantity`` units. Combined
    expressions apply max or sum to the ad-valorem and specific components.
    ``engine_displacement_cm3`` is explicitly engine cylinder displacement,
    never a conversion of generic cargo cubic metres.

    ``capped_combined_max`` represents exactly
    min(cap_percent / 100 * customs_value,
        max(ad_valorem_percent / 100 * customs_value,
            specific_amount * engine_displacement_cm3 / unit_quantity)).
    The specific amount must first be expressed in the same currency as customs
    value when a separate calculator evaluates it. This model does not evaluate
    money or assume exchange rates. This bounded kind requires an engine unit
    and a nonnegative cap at least as high as its inner ad-valorem percentage.
    Unrepresented legal formulas must remain outside a valid candidate.
    """
    kind: Literal["ad_valorem", "specific", "combined_max", "combined_sum", "capped_combined_max"]
    ad_valorem_percent: Decimal | None = None
    specific_amount: Decimal | None = None
    currency: Literal["EUR", "USD", "RUB"] | None = None
    unit: Literal["kg", "g", "tonne", "litre", "m3", "m2", "m", "unit", "pair", "kwh", "engine_displacement_cm3"] | None = None
    unit_quantity: Decimal | None = None
    ad_valorem_cap_percent: Decimal | None = None

    @field_validator("ad_valorem_percent", "specific_amount", "unit_quantity", "ad_valorem_cap_percent", mode="before")
    @classmethod
    def exact_decimal(cls, value: Any) -> Decimal | None:
        return _decimal(value)

    @model_validator(mode="after")
    def valid_components(self) -> ETTDuty:
        ad = self.kind in {"ad_valorem", "combined_max", "combined_sum", "capped_combined_max"}
        specific = self.kind in {"specific", "combined_max", "combined_sum", "capped_combined_max"}
        if ad != (self.ad_valorem_percent is not None):
            raise ValueError("the duty kind must explicitly match its ad-valorem component")
        components = (self.specific_amount, self.currency, self.unit, self.unit_quantity)
        if specific and any(value is None for value in components) or not specific and any(value is not None for value in components):
            raise ValueError("the duty kind must explicitly match all specific-duty components")
        if self.ad_valorem_percent is not None and self.ad_valorem_percent < 0:
            raise ValueError("ad-valorem duty cannot be negative")
        if self.specific_amount is not None and self.specific_amount < 0:
            raise ValueError("specific duty cannot be negative")
        if self.unit_quantity is not None and self.unit_quantity <= 0:
            raise ValueError("unit_quantity must be positive")
        capped = self.kind == "capped_combined_max"
        if capped != (self.ad_valorem_cap_percent is not None):
            raise ValueError("only capped_combined_max requires an explicit ad-valorem cap")
        if capped and (self.unit != "engine_displacement_cm3" or self.ad_valorem_cap_percent < self.ad_valorem_percent):
            raise ValueError("capped_combined_max requires an engine-displacement unit and cap at least the inner percentage")
        return self

    @model_serializer(mode="wrap")
    def preserve_existing_wire_shape(self, handler: Any) -> dict[str, Any]:
        # Adding the optional field must not alter previously retained schema-v2
        # manifest bytes, immutable digests or child payloads for old duty kinds.
        result = handler(self)
        if self.ad_valorem_cap_percent is None:
            result.pop("ad_valorem_cap_percent", None)
        return result


class ETTCodeVersion(_Frozen):
    code: Code
    description: Text
    valid_from: date
    valid_to: date
    evidence: Evidence
    effective_evidence: EffectiveEvidence

    @field_validator("valid_from", "valid_to", mode="before")
    @classmethod
    def explicit_date(cls, value: Any) -> date:
        return _date(value)

    @field_validator("description")
    @classmethod
    def nonempty(cls, value: str) -> str:
        return _nonempty(value)

    @model_validator(mode="after")
    def nonempty_interval(self) -> ETTCodeVersion:
        if self.valid_from >= self.valid_to:
            raise ValueError("code validity is [valid_from, valid_to) and must be nonempty")
        return self


class ETTRateRule(_Frozen):
    rule_id: Identifier
    code: Code
    valid_from: date
    valid_to: date
    destinations: Annotated[tuple[Destination, ...], Field(min_length=1, max_length=5)]
    conditions: Annotated[tuple[ETTCondition, ...], Field(max_length=32)] = ()
    duty: ETTDuty
    footnote_ids: Annotated[tuple[Identifier, ...], Field(max_length=128)] = ()
    evidence: Evidence
    effective_evidence: EffectiveEvidence

    @field_validator("valid_from", "valid_to", mode="before")
    @classmethod
    def explicit_date(cls, value: Any) -> date:
        return _date(value)

    @model_validator(mode="after")
    def nonempty_unique(self) -> ETTRateRule:
        if self.valid_from >= self.valid_to:
            raise ValueError("rate validity is [valid_from, valid_to) and must be nonempty")
        if len(set(self.destinations)) != len(self.destinations) or len(set(self.footnote_ids)) != len(self.footnote_ids):
            raise ValueError("destinations and footnote references must be unique")
        if len({condition.field for condition in self.conditions}) != len(self.conditions):
            raise ValueError("use one condition per product field")
        return self


class ETTFootnote(_Frozen):
    footnote_id: Identifier
    text: Text
    evidence: Evidence
    resolution: Literal["rate_rule", "informational"]
    rule_ids: Annotated[tuple[Identifier, ...], Field(max_length=100_000)] = ()
    rationale: Text

    @field_validator("text", "rationale")
    @classmethod
    def nonempty(cls, value: str) -> str:
        return _nonempty(value)

    @model_validator(mode="after")
    def resolution_has_target(self) -> ETTFootnote:
        if len(set(self.rule_ids)) != len(self.rule_ids):
            raise ValueError("footnote rule references must be unique")
        if self.resolution == "rate_rule" and not self.rule_ids:
            raise ValueError("a rate footnote must resolve to explicit normalized rate rules")
        return self


def conditions_provably_disjoint(left: tuple[ETTCondition, ...], right: tuple[ETTCondition, ...]) -> bool:
    """Conservative contradiction proof for conjunctions in the supported grammar."""
    other = {condition.field: condition for condition in right}
    for condition in left:
        candidate = other.get(condition.field)
        if candidate is None or condition.op != candidate.op:
            continue
        if condition.op == "eq":
            if type(condition.value) is not type(candidate.value) or condition.value != candidate.value:
                return True
        else:
            for low, high in ((condition, candidate), (candidate, condition)):
                if low.minimum is not None and high.maximum is not None:
                    if low.minimum > high.maximum or (low.minimum == high.maximum and not (low.minimum_inclusive and high.maximum_inclusive)):
                        return True
    return False


class ETTManifest(_Frozen):
    schema_version: Literal[2] = 2
    source_kind: Literal["official_eec_ett"] = "official_eec_ett"
    snapshot_id: Identifier
    created_at: datetime
    coverage_from: date
    coverage_to: date
    parser: ETTParserIdentity
    artifacts: Annotated[tuple[ETTArtifact, ...], Field(min_length=99, max_length=2048)]
    derived_amendment_inventory: ETTDerivedAmendmentInventory | None = None
    codes: Annotated[tuple[ETTCodeVersion, ...], Field(min_length=1, max_length=100_000)]
    footnotes: Annotated[tuple[ETTFootnote, ...], Field(max_length=100_000)] = ()
    rate_rules: Annotated[tuple[ETTRateRule, ...], Field(min_length=1, max_length=200_000)]

    @model_serializer(mode="wrap")
    def preserve_legacy_serialization(self, handler):
        result = handler(self)
        # Adding an optional descriptor must not add a null field to existing
        # schema-v2 bytes, model dumps or manifest identities.
        if self.derived_amendment_inventory is None:
            result.pop("derived_amendment_inventory", None)
        return result

    @field_validator("created_at", mode="before")
    @classmethod
    def explicit_instant(cls, value: Any) -> datetime:
        return _instant(value)

    @field_validator("coverage_from", "coverage_to", mode="before")
    @classmethod
    def explicit_date(cls, value: Any) -> date:
        return _date(value)

    @field_validator("schema_version", mode="before")
    @classmethod
    def strict_version(cls, value: Any) -> int:
        if type(value) is not int or value != 2:
            raise ValueError("only integer schema_version 2 is supported")
        return value

    @model_validator(mode="after")
    def complete_consistent_candidate(self) -> ETTManifest:
        if self.coverage_from >= self.coverage_to:
            raise ValueError("snapshot coverage is finite [coverage_from, coverage_to)")
        artifacts = {artifact.artifact_id: artifact for artifact in self.artifacts}
        if len(artifacts) != len(self.artifacts):
            raise ValueError("artifact IDs must be unique")
        if len({artifact.url for artifact in self.artifacts}) != len(self.artifacts):
            raise ValueError("one immutable artifact per official URL is allowed in a snapshot")
        chapters = [artifact.chapter for artifact in self.artifacts if artifact.role == "chapter"]
        if sorted(chapters) != list(EXPECTED_CHAPTERS):
            raise ValueError("exactly all 96 ETT chapters are required")
        for role in SINGLETON_ROLES:
            if role == "amendment_inventory" and self.derived_amendment_inventory is not None:
                if any(artifact.role == role for artifact in self.artifacts):
                    raise ValueError("official and derived amendment inventories are mutually exclusive")
                continue
            if sum(artifact.role == role for artifact in self.artifacts) != 1:
                raise ValueError(f"exactly one {role} artifact is required")
        if self.derived_amendment_inventory is not None:
            binding = self.derived_amendment_inventory
            source = artifacts.get(binding.source_artifact_id)
            if (source is None or source.role != "index" or source.media_type != "text/html"
                    or source.sha256 != binding.source_artifact_sha256):
                raise ValueError("derived amendment inventory must bind the sole HTML index artifact and its exact SHA256")
        if any(artifact.retrieved_at > self.created_at for artifact in self.artifacts):
            raise ValueError("artifact retrieval must not postdate snapshot creation")

        def evidence_is_bound(items: tuple[EffectiveEvidenceItem, ...], code: str | None = None) -> None:
            for item in items:
                artifact = artifacts.get(item.artifact_id)
                if artifact is None or artifact.sha256 != item.artifact_sha256:
                    raise ValueError("evidence must bind an included artifact's exact SHA256")
                if artifact.role == "chapter" and code is not None and artifact.chapter != code[:2]:
                    raise ValueError("code evidence cannot refer to a different chapter")
                if artifact.role in {"index", "amendment_inventory"}:
                    raise ValueError("landing/index inventories cannot establish normalized legal rows or dates")
                if isinstance(item, ETTLegalPortalMetadataEvidence):
                    parsed = urlsplit(artifact.url)
                    if (artifact.role != "amendment" or artifact.media_type != "text/html"
                            or parsed.netloc != "docs.eaeunion.org"
                            or re.fullmatch(r"/documents/[1-9][0-9]*/[1-9][0-9]*/", parsed.path) is None):
                        raise ValueError("portal metadata requires an official amendment HTML detail artifact")
                    binding = item.pdf_binding
                    pdf = artifacts.get(binding.artifact_id)
                    if (pdf is None or pdf.sha256 != binding.artifact_sha256
                            or pdf.role != "amendment" or pdf.media_type != "application/pdf"
                            or pdf.url != binding.url):
                        raise ValueError("portal metadata must bind the included primary amendment PDF and its exact URL/SHA256")

        by_code: dict[str, list[ETTCodeVersion]] = defaultdict(list)
        for code in self.codes:
            if code.code[:2] not in EXPECTED_CHAPTERS:
                raise ValueError("code must belong to an existing ETT chapter")
            if code.valid_from >= self.coverage_to or code.valid_to <= self.coverage_from:
                raise ValueError("code validity must intersect the snapshot coverage")
            evidence_is_bound(code.evidence, code.code)
            evidence_is_bound(code.effective_evidence, code.code)
            by_code[code.code].append(code)
        for versions in by_code.values():
            if len(versions) > 128:
                raise ValueError("at most 128 versions per code are supported in one snapshot")
            ordered = sorted(versions, key=lambda item: item.valid_from)
            if any(left.valid_to > right.valid_from for left, right in zip(ordered, ordered[1:])):
                raise ValueError("duplicate or overlapping code validity")

        rules = {rule.rule_id: rule for rule in self.rate_rules}
        footnotes = {footnote.footnote_id: footnote for footnote in self.footnotes}
        if len(rules) != len(self.rate_rules) or len(footnotes) != len(self.footnotes):
            raise ValueError("rate and footnote IDs must be unique")
        by_rule_code: dict[str, list[ETTRateRule]] = defaultdict(list)
        for rule in self.rate_rules:
            if rule.valid_from >= self.coverage_to or rule.valid_to <= self.coverage_from:
                raise ValueError("rule validity must intersect snapshot coverage")
            if not any(code.valid_from <= rule.valid_from and rule.valid_to <= code.valid_to for code in by_code.get(rule.code, ())):
                raise ValueError("every rate must fit a declared code validity interval")
            evidence_is_bound(rule.evidence, rule.code)
            evidence_is_bound(rule.effective_evidence, rule.code)
            for footnote_id in rule.footnote_ids:
                if footnote_id not in footnotes or rule.rule_id not in footnotes[footnote_id].rule_ids:
                    raise ValueError("unresolved or unbound rate footnote")
            by_rule_code[rule.code].append(rule)
            if len(by_rule_code[rule.code]) > 256:
                raise ValueError("at most 256 rules per code are supported in one snapshot")
        for code in self.codes:
            if not any(code.valid_from <= rule.valid_from and rule.valid_to <= code.valid_to for rule in by_rule_code.get(code.code, ())):
                raise ValueError("every code version must have an explicit rate, never an implicit zero")
        for footnote in self.footnotes:
            evidence_is_bound(footnote.evidence)
            for rule_id in footnote.rule_ids:
                if rule_id not in rules or footnote.footnote_id not in rules[rule_id].footnote_ids:
                    raise ValueError("footnote resolution must be bidirectionally bound to existing rate rules")
        for candidates in by_rule_code.values():
            candidates.sort(key=lambda item: item.valid_from)
            for index, left in enumerate(candidates):
                for right in candidates[index + 1:]:
                    if right.valid_from >= left.valid_to:
                        break
                    if left.valid_from >= right.valid_to:
                        continue
                    if set(left.destinations).isdisjoint(right.destinations):
                        continue
                    if not conditions_provably_disjoint(left.conditions, right.conditions):
                        raise ValueError(f"unresolved overlapping rate rules: {left.rule_id}, {right.rule_id}")
        return self


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def validate_manifest(value: ETTManifest | dict[str, Any] | bytes | str) -> ETTManifest:
    """Revalidate even existing model instances; never trust ``model_construct``."""
    if isinstance(value, (bytes, str)):
        if len(value if isinstance(value, bytes) else value.encode("utf-8")) > MAX_MANIFEST_BYTES:
            raise ValueError("manifest exceeds the bounded input size")
        value = json.loads(value, object_pairs_hook=_unique_object, parse_constant=lambda constant: (_ for _ in ()).throw(ValueError(f"non-finite JSON number: {constant}")))
    return ETTManifest.model_validate(value)


def _canonical(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value == 0:
            return "0"
        result = format(value, "f")
        return result.rstrip("0").rstrip(".") if "." in result else result
    if type(value) is datetime:
        return value.isoformat().replace("+00:00", "Z")
    if type(value) is date:
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    return value


def canonical_manifest_bytes(manifest: ETTManifest | dict[str, Any] | bytes | str) -> bytes:
    validated = validate_manifest(manifest)
    return json.dumps(_canonical(validated.model_dump(mode="python")), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def manifest_sha256(manifest: ETTManifest | dict[str, Any] | bytes | str) -> str:
    return hashlib.sha256(canonical_manifest_bytes(manifest)).hexdigest()
