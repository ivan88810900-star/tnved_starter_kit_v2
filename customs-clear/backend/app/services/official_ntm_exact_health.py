"""Fail-closed exact health-measure evaluator (not wired to the broker).

The existing full official contour is intentionally broad and advisory.  This
module is a much smaller, transaction-aware allowlist for sanitary
registration, veterinary control and phytosanitary control.  A positive
``definite`` result is possible only when all of the following agree:

* one enumerated ten-digit TN VED code;
* the product identity in ``description``;
* the structured transaction/product facts required by that exact rule.

An ``iz`` row or a heading prefix is never promoted by itself.  Negative rows
are also deliberately narrow: they exclude only the named curated rule and do
not assert that no other regulation can apply.  Every row remains outside the
production missing-document/broker calculation until a separate rollout
decision integrates it.

Official artifacts pinned while curating this module (observed 2026-08-15):

* KTS Decision 299 PDF, ETag ``6239a9b4-66d16``;
* KTS Decision 317 PDF, ETag ``63aea335-3ba5f``;
* KTS Decision 318 PDF, ETag ``694e2d91-49113``;
* EEC Council Decision 157 PDF, ETag ``6932c0d2-e1858``.

The allowlist is not a substitute for checking the current consolidated act,
the exact consignment, epidemiological/epizootic conditions or a certificate
registry.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from .hs_matching import normalize_hs_code

OFFICIAL_NTM_EXACT_HEALTH_SOURCE_KIND = "official_ntm_exact_health"
OFFICIAL_NTM_EXACT_HEALTH_SOURCE_LABEL = (
    "Точные санитарные, ветеринарные и фитосанитарные правила ЕЭК"
)

DECISION_299_URL = (
    "https://eec.eaeunion.org/upload/medialibrary/f52/EdpertovarovEEU.pdf"
)
DECISION_317_URL = (
    "https://eec.eaeunion.org/upload/medialibrary/89f/Pr.1-Edinyy-perechen-tov.pdf"
)
DECISION_318_URL = (
    "https://eec.eaeunion.org/upload/medialibrary/60f/"
    "x9vhmm3gi76102uwhqlv7iffol64r6lo/Perechen-produktsii.pdf"
)
DECISION_157_URL = (
    "https://eec.eaeunion.org/upload/medialibrary/e83/"
    "ne3jhyoymc2i57nx91wzn5fihnoi28ap/EKFT-v-red.-Resh.-_80.pdf"
)

DECISION_299_REVISION = (
    "KTS-299|official-eec-pdf-etag:6239a9b4-66d16|observed:2026-08-15"
)
DECISION_317_REVISION = (
    "KTS-317|official-eec-pdf-etag:63aea335-3ba5f|observed:2026-08-15"
)
DECISION_318_157_REVISION = (
    "KTS-318|official-eec-pdf-etag:694e2d91-49113;"
    "EEC-Council-157|official-eec-pdf-etag:6932c0d2-e1858|observed:2026-08-15"
)


# Enumerated codes are intentional.  Do not replace them with startswith rules.
_SGR_DISINFECTANT_CODES = frozenset({"3808941000", "3808943000", "3808948000"})
_SGR_LEGACY_DISINFECTANT_CODES = frozenset({"3808990000"})
_VET_FISH_MEAL_CODES = frozenset(
    {
        "0309100000",
        "0309900001",
        "0309900004",
        "0309900005",
        "0309900007",
        "0309900008",
        "0309900009",
    }
)
_VET_STALE_NEGATIVE_CODES = frozenset({"0508000000", "2305000000", "5104000000"})
_PHYTO_LOW_ROASTED_COFFEE_CODES = frozenset(
    {"0901210001", "0901210002", "0901210008", "0901210009"}
)
_PHYTO_FROZEN_EXCLUSION_CODES = frozenset(
    {
        "0710801000",
        "0710805100",
        "0710805900",
        "0710806100",
        "0710806900",
        "0710807000",
        "0710808000",
        "0710808500",
        "0710809500",
        "0811101100",
        "0811101900",
        "0811109000",
    }
)


# Public, reviewable allowlist metadata.  It is data for shadow evaluation only;
# no caller should infer broker authorization from its presence here.
CURATED_EXACT_HEALTH_ALLOWLIST: tuple[Mapping[str, Any], ...] = (
    {
        "rule_id": "sgr-299-disinfectant-exact",
        "family": "sanitary_registration",
        "exact_hs_codes": tuple(sorted(_SGR_DISINFECTANT_CODES)),
        "decision": "KTS-299",
    },
    {
        "rule_id": "sgr-299-child-cosmetics-3304990000",
        "family": "sanitary_registration",
        "exact_hs_codes": ("3304990000",),
        "decision": "KTS-299",
    },
    {
        "rule_id": "sgr-299-infant-food-1901100000",
        "family": "sanitary_registration",
        "exact_hs_codes": ("1901100000",),
        "decision": "KTS-299",
    },
    {
        "rule_id": "vet-317-live-purebred-horses-0101210000",
        "family": "veterinary_control",
        "exact_hs_codes": ("0101210000",),
        "decision": "KTS-317",
    },
    {
        "rule_id": "vet-317-fish-meal-0309-exact",
        "family": "veterinary_control",
        "exact_hs_codes": tuple(sorted(_VET_FISH_MEAL_CODES)),
        "decision": "KTS-317",
    },
    {
        "rule_id": "vet-317-feed-wheat-1001990000",
        "family": "veterinary_control",
        "exact_hs_codes": ("1001990000",),
        "decision": "KTS-317",
    },
    {
        "rule_id": "phyto-318-high-sowing-corn-0712901100",
        "family": "phytosanitary_control",
        "exact_hs_codes": ("0712901100",),
        "decision": "KTS-318/EEC-Council-157",
    },
    {
        "rule_id": "phyto-318-low-roasted-coffee-exclusion",
        "family": "phytosanitary_control",
        "exact_hs_codes": tuple(sorted(_PHYTO_LOW_ROASTED_COFFEE_CODES)),
        "decision": "KTS-318/EEC-Council-157",
    },
)


_EAEU_COUNTRIES = frozenset(
    {
        "am",
        "arm",
        "armenia",
        "армения",
        "by",
        "blr",
        "belarus",
        "беларусь",
        "белоруссия",
        "kg",
        "kgz",
        "kyrgyzstan",
        "кыргызстан",
        "киргизия",
        "kz",
        "kaz",
        "kazakhstan",
        "казахстан",
        "ru",
        "rus",
        "russia",
        "россия",
        "российская федерация",
    }
)

_IMPORT_TOKENS = frozenset({"import", "ввоз", "импорт", "inbound"})
_CHILD_TOKENS = ("детск", "для детей", "младен", "baby", "infant", "child")
_ADULT_TOKENS = ("взросл", "adult")
_SPECIAL_COSMETICS_TOKENS = (
    "интим",
    "тату",
    "перманент",
    "осветлен",
    "осветлён",
    "отбелив",
    "выпаден",
)
_DISINFECTANT_TOKENS = (
    "дезинфиц",
    "дезинфект",
    "дезинсек",
    "дератизац",
    "disinfect",
)
_INFANT_FOOD_TOKENS = (
    "детское питание",
    "питание для детей",
    "молочная смесь",
    "infant formula",
)
_FISH_MEAL_TOKENS = (
    "мука из рыб",
    "мука рыб",
    "гранул из рыб",
    "мука и гранулы из рыб",
    "ракообраз",
    "моллюск",
    "fish meal",
)
_FEED_TOKENS = ("корм", "фураж", "для животных", "feed")
_SOWING_CORN_TOKENS = (
    "кукуруза сахарная",
    "sweet corn",
    "zea mays",
    "гибридная для посева",
)
_ROASTED_COFFEE_TOKENS = ("кофе жарен", "жареный кофе", "roasted coffee")
_FROZEN_TOKENS = ("заморож", "frozen")


def _normal_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def _fact_text(facts: Mapping[str, Any], key: str) -> str:
    value = facts.get(key)
    if isinstance(value, Mapping):
        return " ".join(f"{k} {v}" for k, v in value.items()).casefold()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return " ".join(str(item) for item in value).casefold()
    return _normal_text(value)


def _contains_any(text: str, tokens: Sequence[str]) -> bool:
    normalized = _normal_text(text)
    return any(token.casefold() in normalized for token in tokens)


def _bool_fact(facts: Mapping[str, Any], key: str) -> bool | None:
    if key not in facts or facts.get(key) is None:
        return None
    value = facts.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    normalized = _normal_text(value)
    if normalized in {"1", "true", "yes", "on", "да"}:
        return True
    if normalized in {"0", "false", "no", "off", "нет"}:
        return False
    return None


def _has_fact(facts: Mapping[str, Any], key: str) -> bool:
    if key not in facts:
        return False
    value = facts.get(key)
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (Sequence, Mapping)):
        return bool(value)
    return True


def _country_key(value: Any) -> str:
    return re.sub(r"[^a-zа-яё]+", " ", _normal_text(value)).strip()


def _is_eaeu_country(value: Any) -> bool:
    return _country_key(value) in _EAEU_COUNTRIES


def _direction(facts: Mapping[str, Any]) -> str:
    value = _normal_text(facts.get("direction"))
    if value in _IMPORT_TOKENS:
        return "import"
    return value


def _transaction_missing(
    facts: Mapping[str, Any],
    *,
    require_origin: bool,
    allow_transit: bool = False,
) -> list[str]:
    missing: list[str] = []
    direction = _direction(facts)
    transit = allow_transit and direction == "transit"
    if not direction:
        missing.append("direction")
    if not _has_fact(facts, "destination_country"):
        missing.append("destination_country")
    elif not transit and not _is_eaeu_country(facts.get("destination_country")):
        missing.append("destination_country:eaeu_member")
    if require_origin and not _has_fact(facts, "origin_country"):
        missing.append("origin_country")
    if transit:
        # The curated rows do not model the border route, control point or the
        # exact transit permit/certificate.  Transit therefore remains
        # advisory even when all import-oriented product facts are present.
        missing.append("transit_route_and_control_documents")
    return missing


def _is_outside_import_scope(
    facts: Mapping[str, Any],
    *,
    allow_transit: bool = False,
) -> str | None:
    direction = _direction(facts)
    transit = allow_transit and direction == "transit"
    if direction and direction != "import" and not transit:
        return "Правило в этом модуле относится к ввозу; указано иное направление перемещения."
    if (
        not transit
        and _has_fact(facts, "destination_country")
        and not _is_eaeu_country(facts.get("destination_country"))
    ):
        return "Страна назначения не распознана как государство — член ЕАЭС."
    return None


def _row(
    *,
    family: str,
    permit_type: str,
    applicability: str,
    outcome: str,
    rule_id: str,
    rule_name: str,
    matched_hs_scope: str,
    source_url: str,
    source_revision: str,
    reason: str,
    missing_facts: Sequence[str] = (),
    exclusion_reason: str | None = None,
    requirements_source_url: str | None = None,
    certificate_required: bool | None = None,
    risk_level: str | None = None,
) -> dict[str, Any]:
    definite_positive = applicability == "definite" and outcome in {
        "required",
        "control_required",
        "certificate_required",
    }
    result: dict[str, Any] = {
        "source": OFFICIAL_NTM_EXACT_HEALTH_SOURCE_KIND,
        "source_kind": OFFICIAL_NTM_EXACT_HEALTH_SOURCE_KIND,
        "source_label": OFFICIAL_NTM_EXACT_HEALTH_SOURCE_LABEL,
        "family": family,
        "permit_type": permit_type,
        "applicability": applicability,
        "outcome": outcome,
        "matched_rule": rule_id,
        "matched_rule_name": rule_name,
        "matched_hs_scope": matched_hs_scope,
        "hs_scope_mode": "exact",
        "missing_facts": list(dict.fromkeys(missing_facts)),
        "exclusion_reason": exclusion_reason,
        "reason": reason,
        "source_url": source_url,
        "source_revision": source_revision,
        "used_for_missing_check": False,
        "requires_manual_review": applicability != "definite",
        "eligible_for_curated_enforcement": definite_positive,
    }
    if requirements_source_url:
        result["requirements_source_url"] = requirements_source_url
    if certificate_required is not None:
        result["certificate_required"] = certificate_required
    if risk_level:
        result["risk_level"] = risk_level
    return result


def _excluded_for_transaction(
    *,
    family: str,
    permit_type: str,
    rule_id: str,
    rule_name: str,
    code: str,
    source_url: str,
    source_revision: str,
    exclusion_reason: str,
    requirements_source_url: str | None = None,
    certificate_required: bool | None = None,
    risk_level: str | None = None,
) -> dict[str, Any]:
    return _row(
        family=family,
        permit_type=permit_type,
        applicability="definite",
        outcome="excluded",
        rule_id=rule_id,
        rule_name=rule_name,
        matched_hs_scope=code,
        source_url=source_url,
        source_revision=source_revision,
        exclusion_reason=exclusion_reason,
        reason=(
            "Точный отрицательный вывод относится только к указанному правилу; "
            "другие санитарные, ветеринарные или фитосанитарные основания не исключены."
        ),
        requirements_source_url=requirements_source_url,
        certificate_required=certificate_required,
        risk_level=risk_level,
    )


def _evaluate_sgr(
    code: str, description: str, facts: Mapping[str, Any]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    if code == "9503007500":
        rows.append(
            _excluded_for_transaction(
                family="sanitary_registration",
                permit_type="СГР",
                rule_id="sgr-299-toy-9503007500-negative",
                rule_name="Раздел II Решения КТС №299 — точная игрушка не является строкой СГР",
                code=code,
                source_url=DECISION_299_URL,
                source_revision=DECISION_299_REVISION,
                exclusion_reason=(
                    "Код 9503007500 исключён только из curated-контура СГР Решения №299; "
                    "оценка соответствия игрушки по техническому регламенту проверяется отдельно."
                ),
            )
        )

    if code == "3304990000":
        description_child = _contains_any(description, _CHILD_TOKENS)
        intended_use = _fact_text(facts, "intended_use")
        intended_child = _contains_any(intended_use, _CHILD_TOKENS)
        adult = _contains_any(description, _ADULT_TOKENS) or _contains_any(
            intended_use, _ADULT_TOKENS
        )
        special = _contains_any(
            description, _SPECIAL_COSMETICS_TOKENS
        ) or _contains_any(intended_use, _SPECIAL_COSMETICS_TOKENS)
        if adult and not special and not (description_child or intended_child):
            rows.append(
                _excluded_for_transaction(
                    family="sanitary_registration",
                    permit_type="СГР",
                    rule_id="sgr-299-child-cosmetics-3304990000",
                    rule_name="Детская/специальная косметика 3304990000",
                    code=code,
                    source_url=DECISION_299_URL,
                    source_revision=DECISION_299_REVISION,
                    exclusion_reason=(
                        "Подтверждено взрослое, не специальное назначение; исключён только "
                        "curated-позитив для детской косметики."
                    ),
                )
            )
        elif description_child or intended_child or special:
            missing = _transaction_missing(facts, require_origin=False)
            if not description_child:
                missing.append("description:child_cosmetics_identity")
            if not intended_child:
                missing.append("intended_use:children")
            if not _has_fact(facts, "composition") and not _has_fact(
                facts, "cas_numbers"
            ):
                missing.append("composition_or_cas_numbers")
            if _bool_fact(facts, "first_import") is None:
                missing.append("first_import")
            outside = _is_outside_import_scope(facts)
            if outside:
                rows.append(
                    _excluded_for_transaction(
                        family="sanitary_registration",
                        permit_type="СГР",
                        rule_id="sgr-299-child-cosmetics-3304990000",
                        rule_name="Детская/специальная косметика 3304990000",
                        code=code,
                        source_url=DECISION_299_URL,
                        source_revision=DECISION_299_REVISION,
                        exclusion_reason=outside,
                    )
                )
            else:
                rows.append(
                    _row(
                        family="sanitary_registration",
                        permit_type="СГР",
                        applicability="definite"
                        if not missing
                        else "needs_clarification",
                        outcome="required" if not missing else "pending_facts",
                        rule_id="sgr-299-child-cosmetics-3304990000",
                        rule_name="Детская косметика, точный код 3304990000",
                        matched_hs_scope=code,
                        source_url=DECISION_299_URL,
                        source_revision=DECISION_299_REVISION,
                        missing_facts=missing,
                        reason=(
                            "Точный код, детское назначение и состав подтверждены структурированными "
                            "данными. first_import определяет необходимость первичного оформления; "
                            "при повторном ввозе проверяется действующий документ."
                            if not missing
                            else "Код/наименование дают кандидата, но для точного вывода не хватает обязательных фактов."
                        ),
                    )
                )

    if code == "1901100000" and _contains_any(description, _INFANT_FOOD_TOKENS):
        intended_use = _fact_text(facts, "intended_use")
        missing = _transaction_missing(facts, require_origin=False)
        if not _contains_any(intended_use, _CHILD_TOKENS):
            missing.append("intended_use:infant_or_children")
        if not _has_fact(facts, "composition"):
            missing.append("composition")
        if _bool_fact(facts, "first_import") is None:
            missing.append("first_import")
        outside = _is_outside_import_scope(facts)
        if outside:
            rows.append(
                _excluded_for_transaction(
                    family="sanitary_registration",
                    permit_type="СГР",
                    rule_id="sgr-299-infant-food-1901100000",
                    rule_name="Детское питание, точный код 1901100000",
                    code=code,
                    source_url=DECISION_299_URL,
                    source_revision=DECISION_299_REVISION,
                    exclusion_reason=outside,
                )
            )
        else:
            rows.append(
                _row(
                    family="sanitary_registration",
                    permit_type="СГР",
                    applicability="definite" if not missing else "needs_clarification",
                    outcome="required" if not missing else "pending_facts",
                    rule_id="sgr-299-infant-food-1901100000",
                    rule_name="Детское питание, точный код 1901100000",
                    matched_hs_scope=code,
                    source_url=DECISION_299_URL,
                    source_revision=DECISION_299_REVISION,
                    missing_facts=missing,
                    reason=(
                        "Точный код, наименование детского питания, назначение и состав совпали."
                        if not missing
                        else "Не все обязательные свойства специализированного детского питания подтверждены."
                    ),
                )
            )

    if code in _SGR_DISINFECTANT_CODES or code in _SGR_LEGACY_DISINFECTANT_CODES:
        indicated = (
            _contains_any(description, _DISINFECTANT_TOKENS)
            or _bool_fact(facts, "disinfectant_use") is True
        )
        if indicated:
            if _bool_fact(facts, "veterinary_use") is True:
                rows.append(
                    _excluded_for_transaction(
                        family="sanitary_registration",
                        permit_type="СГР",
                        rule_id="sgr-299-disinfectant-exact",
                        rule_name="Дезинфицирующее средство, точные коды 380894",
                        code=code,
                        source_url=DECISION_299_URL,
                        source_revision=DECISION_299_REVISION,
                        exclusion_reason=(
                            "Подтверждено ветеринарное назначение; оно исключено только из этого "
                            "санитарного правила и требует отдельной ветеринарной оценки."
                        ),
                    )
                )
            else:
                missing = _transaction_missing(facts, require_origin=False)
                if code in _SGR_LEGACY_DISINFECTANT_CODES:
                    missing.append("active_tnved_code:380894xxxx")
                if not _contains_any(description, _DISINFECTANT_TOKENS):
                    missing.append("description:disinfectant_identity")
                if _bool_fact(facts, "disinfectant_use") is not True:
                    missing.append("disinfectant_use:true")
                intended_use = _fact_text(facts, "intended_use")
                if not intended_use:
                    missing.append("intended_use")
                if not _has_fact(facts, "composition") and not _has_fact(
                    facts, "cas_numbers"
                ):
                    missing.append("composition_or_cas_numbers")
                if _bool_fact(facts, "first_import") is None:
                    missing.append("first_import")
                if _bool_fact(facts, "veterinary_use") is None:
                    missing.append("veterinary_use:false")
                outside = _is_outside_import_scope(facts)
                if outside:
                    rows.append(
                        _excluded_for_transaction(
                            family="sanitary_registration",
                            permit_type="СГР",
                            rule_id="sgr-299-disinfectant-exact",
                            rule_name="Дезинфицирующее средство, точные коды 380894",
                            code=code,
                            source_url=DECISION_299_URL,
                            source_revision=DECISION_299_REVISION,
                            exclusion_reason=outside,
                        )
                    )
                else:
                    rows.append(
                        _row(
                            family="sanitary_registration",
                            permit_type="СГР",
                            applicability="definite"
                            if not missing
                            else "needs_clarification",
                            outcome="required" if not missing else "pending_facts",
                            rule_id="sgr-299-disinfectant-exact",
                            rule_name="Дезинфицирующее средство, точные коды 380894",
                            matched_hs_scope=code,
                            source_url=DECISION_299_URL,
                            source_revision=DECISION_299_REVISION,
                            missing_facts=missing,
                            reason=(
                                "Точная товарная подсубпозиция дезинфицирующих средств и обязательные "
                                "характеристики подтверждены."
                                if not missing
                                else "Широкое/устаревшее кодовое совпадение или неполные свойства не позволяют definite-вывод."
                            ),
                        )
                    )
    return rows


def _evaluate_veterinary(
    code: str, description: str, facts: Mapping[str, Any]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    if code in _VET_STALE_NEGATIVE_CODES:
        rows.append(
            _excluded_for_transaction(
                family="veterinary_control",
                permit_type="ВЕТКОНТРОЛЬ",
                rule_id=f"vet-317-curated-negative-{code}",
                rule_name="Точный код отсутствует в curated exact-строках Решения КТС №317",
                code=code,
                source_url=DECISION_317_URL,
                source_revision=DECISION_317_REVISION,
                exclusion_reason=(
                    f"Код {code} не повышается по устаревшему широкому префиксу; "
                    "отрицательный вывод ограничен перечнем №317 и этой редакцией."
                ),
            )
        )

    if code == "0101210000":
        missing = _transaction_missing(
            facts,
            require_origin=True,
            allow_transit=True,
        )
        if not _contains_any(description, ("лошад", "horse")):
            missing.append("description:live_horse_identity")
        if _bool_fact(facts, "animal_origin") is not True:
            missing.append("animal_origin:true")
        if not _contains_any(_fact_text(facts, "processing_method"), ("жив", "live")):
            missing.append("processing_method:live")
        if not _contains_any(
            _fact_text(facts, "intended_use"), ("плем", "развед", "breeding")
        ):
            missing.append("intended_use:breeding")
        outside = _is_outside_import_scope(facts, allow_transit=True)
        if outside:
            rows.append(
                _excluded_for_transaction(
                    family="veterinary_control",
                    permit_type="ВЕТКОНТРОЛЬ",
                    rule_id="vet-317-live-purebred-horses-0101210000",
                    rule_name="Живые чистопородные племенные лошади 0101210000",
                    code=code,
                    source_url=DECISION_317_URL,
                    source_revision=DECISION_317_REVISION,
                    exclusion_reason=outside,
                )
            )
        else:
            rows.append(
                _row(
                    family="veterinary_control",
                    permit_type="ВЕТКОНТРОЛЬ",
                    applicability="definite" if not missing else "needs_clarification",
                    outcome="control_required" if not missing else "pending_facts",
                    rule_id="vet-317-live-purebred-horses-0101210000",
                    rule_name="Живые чистопородные племенные лошади 0101210000",
                    matched_hs_scope=code,
                    source_url=DECISION_317_URL,
                    source_revision=DECISION_317_REVISION,
                    missing_facts=missing,
                    reason=(
                        "Точная строка живых животных и факты партии подтверждены; вид ветеринарного "
                        "документа всё равно определяется отдельными едиными требованиями."
                        if not missing
                        else "Для точного ветеринарного вывода не подтверждены все свойства живого племенного животного/сделки."
                    ),
                )
            )

    fish_candidate = code in _VET_FISH_MEAL_CODES or code == "0309000000"
    if fish_candidate and _contains_any(description, _FISH_MEAL_TOKENS):
        missing = _transaction_missing(
            facts,
            require_origin=True,
            allow_transit=True,
        )
        if code == "0309000000":
            missing.append("active_tnved_code:0309xxxxxxxx")
        if _bool_fact(facts, "animal_origin") is not True:
            missing.append("animal_origin:true")
        if not _has_fact(facts, "composition"):
            missing.append("composition")
        if not _has_fact(facts, "processing_method"):
            missing.append("processing_method")
        outside = _is_outside_import_scope(facts, allow_transit=True)
        if outside:
            rows.append(
                _excluded_for_transaction(
                    family="veterinary_control",
                    permit_type="ВЕТКОНТРОЛЬ",
                    rule_id="vet-317-fish-meal-0309-exact",
                    rule_name="Мука/гранулы из рыбы и водных животных, точные коды 0309",
                    code=code,
                    source_url=DECISION_317_URL,
                    source_revision=DECISION_317_REVISION,
                    exclusion_reason=outside,
                )
            )
        else:
            rows.append(
                _row(
                    family="veterinary_control",
                    permit_type="ВЕТКОНТРОЛЬ",
                    applicability="definite" if not missing else "needs_clarification",
                    outcome="control_required" if not missing else "pending_facts",
                    rule_id="vet-317-fish-meal-0309-exact",
                    rule_name="Мука/гранулы из рыбы и водных животных, точные коды 0309",
                    matched_hs_scope=code,
                    source_url=DECISION_317_URL,
                    source_revision=DECISION_317_REVISION,
                    missing_facts=missing,
                    reason=(
                        "Точный действующий код, животное происхождение, состав и обработка подтверждены."
                        if not missing
                        else "Агрегированный/устаревший код либо неполные сведения о происхождении и обработке."
                    ),
                )
            )

    if code == "1001990000":
        feed_use = _bool_fact(facts, "feed_use")
        intended_use = _fact_text(facts, "intended_use")
        feed_description = _contains_any(description, _FEED_TOKENS)
        feed_intended = _contains_any(intended_use, _FEED_TOKENS)
        if feed_use is False or (
            _has_fact(facts, "intended_use") and not feed_intended
        ):
            rows.append(
                _excluded_for_transaction(
                    family="veterinary_control",
                    permit_type="ВЕТКОНТРОЛЬ",
                    rule_id="vet-317-feed-wheat-1001990000",
                    rule_name="Пшеница кормового назначения 1001990000",
                    code=code,
                    source_url=DECISION_317_URL,
                    source_revision=DECISION_317_REVISION,
                    exclusion_reason=(
                        "Документами подтверждено некормовое назначение; исключена только условная "
                        "ветеринарная строка кормовой пшеницы."
                    ),
                )
            )
        elif feed_description or feed_use is True or feed_intended:
            missing = _transaction_missing(
                facts,
                require_origin=True,
                allow_transit=True,
            )
            if not feed_description:
                missing.append("description:feed_identity")
            if feed_use is not True:
                missing.append("feed_use:true")
            if not feed_intended:
                missing.append("intended_use:animal_feed")
            if not _has_fact(facts, "processing_method"):
                missing.append("processing_method")
            outside = _is_outside_import_scope(facts, allow_transit=True)
            if outside:
                rows.append(
                    _excluded_for_transaction(
                        family="veterinary_control",
                        permit_type="ВЕТКОНТРОЛЬ",
                        rule_id="vet-317-feed-wheat-1001990000",
                        rule_name="Пшеница кормового назначения 1001990000",
                        code=code,
                        source_url=DECISION_317_URL,
                        source_revision=DECISION_317_REVISION,
                        exclusion_reason=outside,
                    )
                )
            else:
                rows.append(
                    _row(
                        family="veterinary_control",
                        permit_type="ВЕТКОНТРОЛЬ",
                        applicability="definite"
                        if not missing
                        else "needs_clarification",
                        outcome="control_required" if not missing else "pending_facts",
                        rule_id="vet-317-feed-wheat-1001990000",
                        rule_name="Пшеница кормового назначения 1001990000",
                        matched_hs_scope=code,
                        source_url=DECISION_317_URL,
                        source_revision=DECISION_317_REVISION,
                        missing_facts=missing,
                        reason=(
                            "Условная строка Решения №317 подтверждена кодом, наименованием и кормовым назначением."
                            if not missing
                            else "Код 1001990000 сам по себе не доказывает кормовое назначение."
                        ),
                    )
                )
    return rows


def _evaluate_phytosanitary(
    code: str, description: str, facts: Mapping[str, Any]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    if code == "0712901100":
        missing = _transaction_missing(
            facts,
            require_origin=True,
            allow_transit=True,
        )
        if not _contains_any(description, _SOWING_CORN_TOKENS):
            missing.append("description:sowing_sweet_corn_identity")
        if not _contains_any(
            _fact_text(facts, "intended_use"), ("посев", "sowing", "seed")
        ):
            missing.append("intended_use:sowing")
        if _fact_text(facts, "phytosanitary_risk_tier") not in {
            "high",
            "высокий",
            "высокого риска",
        }:
            missing.append("phytosanitary_risk_tier:high")
        if not _contains_any(
            _fact_text(facts, "processing_method"),
            ("семен", "seed", "суш", "dried", "необработ"),
        ):
            missing.append("processing_method:seed_or_dried_unprocessed")
        if not _has_fact(facts, "packaging"):
            missing.append("packaging")
        outside = _is_outside_import_scope(facts, allow_transit=True)
        if outside:
            rows.append(
                _excluded_for_transaction(
                    family="phytosanitary_control",
                    permit_type="ФСС",
                    rule_id="phyto-318-high-sowing-corn-0712901100",
                    rule_name="Гибридная сахарная кукуруза для посева 0712901100 — высокий риск",
                    code=code,
                    source_url=DECISION_318_URL,
                    source_revision=DECISION_318_157_REVISION,
                    requirements_source_url=DECISION_157_URL,
                    certificate_required=False,
                    risk_level="high",
                    exclusion_reason=outside,
                )
            )
        else:
            rows.append(
                _row(
                    family="phytosanitary_control",
                    permit_type="ФСС",
                    applicability="definite" if not missing else "needs_clarification",
                    outcome="certificate_required" if not missing else "pending_facts",
                    rule_id="phyto-318-high-sowing-corn-0712901100",
                    rule_name="Гибридная сахарная кукуруза для посева 0712901100 — высокий риск",
                    matched_hs_scope=code,
                    source_url=DECISION_318_URL,
                    source_revision=DECISION_318_157_REVISION,
                    requirements_source_url=DECISION_157_URL,
                    missing_facts=missing,
                    certificate_required=True if not missing else None,
                    risk_level="high",
                    reason=(
                        "Точная высокорисковая строка, посевное назначение, обработка и сведения партии подтверждены."
                        if not missing
                        else "Высокорисковый код требует одновременного подтверждения наименования и параметров партии."
                    ),
                )
            )

    if code in _PHYTO_LOW_ROASTED_COFFEE_CODES or code == "0901210000":
        indicated = _contains_any(description, _ROASTED_COFFEE_TOKENS)
        if indicated:
            missing = _transaction_missing(
                facts,
                require_origin=True,
                allow_transit=True,
            )
            if code == "0901210000":
                missing.append("active_tnved_code:090121000x")
            if _fact_text(facts, "phytosanitary_risk_tier") not in {
                "low",
                "низкий",
                "низкого риска",
            }:
                missing.append("phytosanitary_risk_tier:low")
            if not _contains_any(
                _fact_text(facts, "processing_method"), ("жар", "roast")
            ):
                missing.append("processing_method:roasted")
            if not _has_fact(facts, "packaging"):
                missing.append("packaging")
            outside = _is_outside_import_scope(facts, allow_transit=True)
            if outside:
                rows.append(
                    _excluded_for_transaction(
                        family="phytosanitary_control",
                        permit_type="ФСС",
                        rule_id="phyto-318-low-roasted-coffee-exclusion",
                        rule_name="Жареный кофе 090121000x — низкий фитосанитарный риск",
                        code=code,
                        source_url=DECISION_318_URL,
                        source_revision=DECISION_318_157_REVISION,
                        requirements_source_url=DECISION_157_URL,
                        certificate_required=False,
                        risk_level="low",
                        exclusion_reason=outside,
                    )
                )
            elif missing:
                rows.append(
                    _row(
                        family="phytosanitary_control",
                        permit_type="ФСС",
                        applicability="needs_clarification",
                        outcome="pending_facts",
                        rule_id="phyto-318-low-roasted-coffee-exclusion",
                        rule_name="Жареный кофе 090121000x — низкий фитосанитарный риск",
                        matched_hs_scope=code,
                        source_url=DECISION_318_URL,
                        source_revision=DECISION_318_157_REVISION,
                        requirements_source_url=DECISION_157_URL,
                        missing_facts=missing,
                        risk_level="low",
                        reason="Низкорисковое исключение из ФСС нельзя применить без точного действующего кода и обработки.",
                    )
                )
            else:
                rows.append(
                    _excluded_for_transaction(
                        family="phytosanitary_control",
                        permit_type="ФСС",
                        rule_id="phyto-318-low-roasted-coffee-exclusion",
                        rule_name="Жареный кофе 090121000x — низкий фитосанитарный риск",
                        code=code,
                        source_url=DECISION_318_URL,
                        source_revision=DECISION_318_157_REVISION,
                        requirements_source_url=DECISION_157_URL,
                        certificate_required=False,
                        risk_level="low",
                        exclusion_reason=(
                            "Точная строка низкого фитосанитарного риска перемещается без "
                            "фитосанитарного сертификата; контроль иных объектов/упаковки не исключён."
                        ),
                    )
                )

    frozen_current = code in _PHYTO_FROZEN_EXCLUSION_CODES
    frozen_legacy_aggregate = code in {"0710800000", "0811100000"}
    if (frozen_current or frozen_legacy_aggregate) and _contains_any(
        description, _FROZEN_TOKENS
    ):
        processing_frozen = _contains_any(
            _fact_text(facts, "processing_method"), _FROZEN_TOKENS
        )
        missing: list[str] = []
        if frozen_legacy_aggregate:
            missing.append("active_tnved_code:exact_frozen_subposition")
        if not processing_frozen:
            missing.append("processing_method:frozen")
        if missing:
            rows.append(
                _row(
                    family="phytosanitary_control",
                    permit_type="ФСС",
                    applicability="needs_clarification",
                    outcome="pending_facts",
                    rule_id="phyto-318-frozen-produce-curated-negative",
                    rule_name="Замороженные овощи/клубника — exact negative against broad 07/08 prefix",
                    matched_hs_scope=code,
                    source_url=DECISION_318_URL,
                    source_revision=DECISION_318_157_REVISION,
                    requirements_source_url=DECISION_157_URL,
                    missing_facts=missing,
                    reason="Агрегированный код или неподтверждённая заморозка не дают точного отрицательного вывода.",
                )
            )
        else:
            rows.append(
                _excluded_for_transaction(
                    family="phytosanitary_control",
                    permit_type="ФСС",
                    rule_id="phyto-318-frozen-produce-curated-negative",
                    rule_name="Замороженные овощи/клубника — exact negative against broad 07/08 prefix",
                    code=code,
                    source_url=DECISION_318_URL,
                    source_revision=DECISION_318_157_REVISION,
                    requirements_source_url=DECISION_157_URL,
                    certificate_required=False,
                    exclusion_reason=(
                        "Этот точный код замороженного продукта отсутствует в curated-строках "
                        "высокого/низкого риска; упаковка и иные подкарантинные объекты проверяются отдельно."
                    ),
                )
            )
    return rows


def evaluate_exact_health_measures(
    hs_code: str,
    description: str,
    facts: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Evaluate the bounded exact health allowlist.

    ``facts`` accepts the canonical keys used by the NTM API and tolerates
    additional keys.  The evaluator never mutates the mapping.  Unknown codes
    return an empty list rather than a false global negative.
    """

    code = normalize_hs_code(hs_code)
    if len(code) != 10:
        return []
    structured_facts: Mapping[str, Any] = facts or {}
    return [
        *_evaluate_sgr(code, description or "", structured_facts),
        *_evaluate_veterinary(code, description or "", structured_facts),
        *_evaluate_phytosanitary(code, description or "", structured_facts),
    ]


# Descriptive alias for integration callers.
evaluate_official_ntm_exact_health = evaluate_exact_health_measures
