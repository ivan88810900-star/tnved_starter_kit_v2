"""Conservative exact advisory for EAEU radio and cryptography measures.

This module is deliberately isolated from the non-tariff broker.  It turns
structured product facts into *shadow-only* rows for sections 2.16 and 2.19 of
the Unified list attached to EEC Board Decision No. 30.  A code or a word such
as ``Wi-Fi``, ``AES``, ``TLS`` or ``VPN`` is only a candidate signal.  A row is
``definite`` only when one of the small, source-backed rules below can be
proved from structured facts or from an exact, verified official-registry
result.

Trust boundary
--------------
The evaluator does not query a registry.  Public ``*_verified`` fields are a
caller-supplied assertion, not proof that a trusted adapter performed a lookup.
Together with an official-host evidence URL they may produce a manual-review
``definite`` advisory row, which the UI labels as unverified by the service.
Trusted adapter provenance is a separate broker-bridge field and is never
derived from the public request.  Free text and unverified registry hints never
create a ``definite`` result.

Every row has ``used_for_missing_check=False`` and
``enforcement_eligible=False``.  Integration with broker enforcement requires
a separate source-policy decision.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import urlparse

from .hs_matching import normalize_hs_code

SOURCE_KIND = "official_ntm_exact_devices_shadow"

DECISION_30_SECTION_216_URL = (
    "https://eec.eaeunion.org/upload/files/catr/EP.pdf/2.16.pdf"
)
DECISION_30_SECTION_219_URL = (
    "https://eec.eaeunion.org/upload/files/catr/EP.pdf/2.19_137.pdf"
)
DECISION_30_RADIO_PROCEDURE_URL = (
    "https://eec.eaeunion.org/upload/files/catr/EP.pdf/PR15.pdf"
)
DECISION_30_CRYPTO_PROCEDURE_URL = (
    "https://eec.eaeunion.org/upload/files/catr/EP.pdf/pr9.pdf"
)
EAEU_REGISTRY_PORTAL_URL = "https://portal.eaeunion.org/"


# The section itself contains only ``из`` ranges.  They are candidates and
# cannot prove applicability without the item name and technical facts.
SECTION_216_PREFIXES: tuple[str, ...] = (
    "8419",
    "8514",
    "8540",
    "8543",
    "9018",
    "9027",
    "8470",
    "8471",
    "8517",
    "8518",
    "8519",
    "8521",
    "8525",
    "8526",
    "8527",
    "8528",
    "8531",
    "90",
)

SECTION_219_PREFIXES: tuple[str, ...] = tuple(
    """
    844331 8443321009 8443323000 8443991000 8470100000 8471300000
    8471410000 8471490000 8471500000 8471900000 8473302008
    8471705000 8471709800 8471800000 8473211000 8473219000
    8473308000 8517110000 8517130000 8517140000 8517180000
    8517610001 8517610002 8517610008 851762000 8517693900
    8517699000 851779000 8523293101 8523293102 852329330 852329390
    8523492500 8523493100 8523493900 8523494500 8523499101
    8523499300 8523519101 8523519300 852352 8523599101 8523599300
    8523809101 8523809300 370400 370500 3706 482110 4901100000
    4901990000 4911990000 8523210000 8525500000 852560000
    8529902002 852990650 8529909600 8526912000 8526918000
    852692000 8528711500 8542319010 8542319090 8542329000
    8543708000 8543900000 852329310 8523299000 8523495100
    8523495900 8523499900 8523519900 8523599900 8523809900
    """.split()  # noqa: SIM905 - auditable source table
)


# Exact, bounded Appendix 2 rules.  These are not general keyword heuristics:
# technology, complete frequency information and maximum transmitter power
# must all agree with the official rule before an exclusion is emitted.
RADIO_TECHNICAL_EXEMPTION_ALLOWLIST: tuple[dict[str, Any], ...] = (
    {
        "rule_id": "radio.app15.annex2.3.5.ieee_802_15",
        "technologies": frozenset({"ieee_802.15", "ieee802.15", "bluetooth", "zigbee"}),
        "bands_mhz": ((2400.0, 2483.5),),
        "max_power_mw": 100.0,
        "label": "IEEE 802.15, 2400–2483.5 MHz, up to 100 mW",
    },
    {
        "rule_id": "radio.app15.annex2.3.6_7.ieee_802_11",
        "technologies": frozenset(
            {"ieee_802.11", "ieee802.11", "wifi", "wi-fi", "wlan"}
        ),
        "bands_mhz": (
            (2400.0, 2483.5),
            (5150.0, 5350.0),
            (5650.0, 5850.0),
            (57000.0, 66000.0),
        ),
        "max_power_mw": 100.0,
        "label": "IEEE 802.11 in listed bands, up to 100 mW",
    },
    {
        "rule_id": "radio.app15.annex2.3.10.dect",
        "technologies": frozenset({"dect"}),
        "bands_mhz": ((1880.0, 1900.0),),
        "max_power_mw": 10.0,
        "label": "DECT, 1880–1900 MHz, up to 10 mW",
    },
)

RADIO_CATEGORY_EXEMPTION_ALLOWLIST: tuple[dict[str, Any], ...] = (
    {
        "rule_id": "radio.app15.annex2.3.1.cellular_terminal",
        "technologies": frozenset(
            {
                "cellular_terminal",
                "cellular_modem",
                "mobile_phone",
                "gsm_terminal",
                "lte_terminal",
                "5g_terminal",
            }
        ),
        "label": "cellular subscriber terminal or cellular modem",
    },
    {
        "rule_id": "radio.app15.annex2.3.9.receive_only",
        "technologies": frozenset(
            {"receive_only", "radio_receiver_only", "receiver_without_transmitter"}
        ),
        "label": "receive-only equipment without a radio-emitting device",
    },
)

CRYPTO_EXEMPTION_ALLOWLIST = frozenset(
    {
        "crypto.app9.p6.test_sim_cards",
        "crypto.app9.annex5.personal_use",
    }
)


_RADIO_MARKERS = (
    "wi-fi",
    "wifi",
    "wlan",
    "bluetooth",
    "zigbee",
    "радиопередат",
    "радиоприем",
    "радиоприём",
    "радиомодул",
    "беспровод",
    "rfid",
    "lte",
    "5g",
    "gsm",
    "dect",
)
_CRYPTO_MARKERS = (
    "шифрован",
    "криптограф",
    "криптомодул",
    " aes",
    "aes-",
    "tls",
    "vpn",
    "ipsec",
    "электронная подпись",
)


def _normal_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().replace("ё", "е").split())


def _is_true(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return _normal_text(value) in {
            "true",
            "yes",
            "да",
            "verified",
            "active",
            "действует",
        }
    return False


def _is_false(value: Any) -> bool:
    if value is False:
        return True
    if isinstance(value, str):
        return _normal_text(value) in {"false", "no", "нет", "absent", "none"}
    return False


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _official_eaeu_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    try:
        parsed = urlparse(raw)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        return None
    if host == "eaeunion.org" or host.endswith(".eaeunion.org"):
        return raw
    return None


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _technologies(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        raw_values = [
            part for part in value.replace(";", ",").split(",") if part.strip()
        ]
    elif isinstance(value, Iterable) and not isinstance(
        value, (bytes, bytearray, Mapping)
    ):
        raw_values = list(value)
    else:
        raw_values = [value]
    return {
        _normal_text(item).replace(" ", "_")
        for item in raw_values
        if _normal_text(item)
    }


def _crypto_functions(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_values = [
            part for part in value.replace(";", ",").split(",") if part.strip()
        ]
    elif isinstance(value, Iterable) and not isinstance(
        value, (bytes, bytearray, Mapping)
    ):
        raw_values = list(value)
    else:
        raw_values = [value]
    return _unique(_normal_text(item) for item in raw_values if _normal_text(item))


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().replace(",", "."))
        except ValueError:
            return None
    return None


def _frequency_ranges_mhz(value: Any) -> tuple[tuple[float, float], ...]:
    """Normalize a MHz scalar/range/list without guessing other units."""

    if value is None:
        return ()
    if isinstance(value, Mapping):
        if "ranges" in value:
            return _frequency_ranges_mhz(value["ranges"])
        low = _to_float(_first(value, "min", "low", "from", "start"))
        high = _to_float(_first(value, "max", "high", "to", "end"))
        if low is None and high is None:
            point = _to_float(_first(value, "value", "frequency"))
            return ((point, point),) if point is not None else ()
        if low is None or high is None or low > high:
            return ()
        return ((low, high),)
    point = _to_float(value)
    if point is not None:
        return ((point, point),)
    if isinstance(value, tuple) and len(value) == 2:
        low, high = _to_float(value[0]), _to_float(value[1])
        if low is not None and high is not None and low <= high:
            return ((low, high),)
    if isinstance(value, list):
        ranges: list[tuple[float, float]] = []
        for item in value:
            ranges.extend(_frequency_ranges_mhz(item))
        return tuple(ranges)
    return ()


def _power_mw(value: Any) -> float | None:
    if isinstance(value, Mapping):
        number = _to_float(_first(value, "max", "value", "power"))
        unit = _normal_text(_first(value, "unit", "units") or "mw")
        if number is None:
            return None
        if unit in {"w", "watt", "watts", "вт"}:
            return number * 1000.0
        if unit in {"mw", "milliwatt", "milliwatts", "мвт"}:
            return number
        return None
    return _to_float(value)


def _matches_prefix(code: str, prefixes: Iterable[str]) -> bool:
    return bool(code) and any(code.startswith(prefix) for prefix in prefixes)


def _direction(value: Any) -> str | None:
    normalized = _normal_text(value).replace(" ", "_")
    aliases = {
        "import": "import",
        "in": "import",
        "ввоз": "import",
        "export": "export",
        "out": "export",
        "вывоз": "export",
        "both": "both",
        "import_export": "both",
        "ввоз_вывоз": "both",
        "transit": "transit",
        "транзит": "transit",
    }
    return aliases.get(normalized)


def _transit_route(value: Any) -> str | None:
    normalized = _normal_text(value).replace(" ", "_")
    aliases = {
        "border_to_border": "border_to_border",
        "arrival_to_internal": "arrival_to_internal",
        "internal_to_exit": "internal_to_exit",
    }
    return aliases.get(normalized)


def _base_row(
    *,
    family: str,
    section: str,
    permit_type: str,
    direction: str | None,
    hs_code: str,
    hs_scope: bool,
) -> dict[str, Any]:
    return {
        "source_kind": SOURCE_KIND,
        "family": family,
        "section": section,
        "permit_type": permit_type,
        "direction": direction,
        "hs_code": hs_code,
        "hs_scope": hs_scope,
        "applicability": "needs_clarification",
        "decision": "needs_clarification",
        "requirement_applicable": None,
        "required_document": None,
        "missing_facts": [],
        "exclusion": None,
        "evidence": [],
        "source_urls": [],
        "curated_exact": False,
        "shadow_ready": False,
        "used_for_missing_check": False,
        "enforcement_eligible": False,
    }


def _set_definite(
    row: dict[str, Any],
    *,
    decision: str,
    requirement_applicable: bool,
    required_document: str | None = None,
) -> dict[str, Any]:
    row.update(
        applicability="definite",
        decision=decision,
        requirement_applicable=requirement_applicable,
        required_document=required_document,
        missing_facts=[],
        curated_exact=True,
        shadow_ready=True,
    )
    return row


def _registry_result(
    value: Any,
    *,
    fallback_url: Any,
) -> tuple[bool, str | None, dict[str, Any]]:
    details = _as_mapping(value)
    if details:
        verified = _is_true(_first(details, "verified", "exact_match", "matched"))
        if "active" in details and not _is_true(details["active"]):
            verified = False
        if "exact_model_match" in details and not _is_true(
            details["exact_model_match"]
        ):
            verified = False
        url = _official_eaeu_url(
            _first(details, "source_url", "evidence_url", "registry_url")
            or fallback_url
        )
        evidence = {
            "type": "official_registry_match",
            "verified": verified,
            "registration_number": _first(
                details, "registration_number", "number", "registry_number"
            ),
            "source_url": url,
        }
        return verified and url is not None, url, evidence
    verified = _is_true(value)
    url = _official_eaeu_url(fallback_url)
    return (
        verified and url is not None,
        url,
        {
            "type": "official_registry_match",
            "verified": verified,
            "source_url": url,
        },
    )


def _find_radio_technical_exemption(
    technologies: set[str],
    frequencies: tuple[tuple[float, float], ...],
    power_mw: float | None,
) -> Mapping[str, Any] | None:
    if not technologies or not frequencies or power_mw is None:
        return None
    for rule in RADIO_TECHNICAL_EXEMPTION_ALLOWLIST:
        if not technologies.intersection(rule["technologies"]):
            continue
        if power_mw > float(rule["max_power_mw"]):
            continue
        allowed_bands = rule["bands_mhz"]
        if all(
            any(
                allowed_low <= actual_low and actual_high <= allowed_high
                for allowed_low, allowed_high in allowed_bands
            )
            for actual_low, actual_high in frequencies
        ):
            return rule
    return None


def _find_radio_category_exemption(
    technologies: set[str],
) -> Mapping[str, Any] | None:
    for rule in RADIO_CATEGORY_EXEMPTION_ALLOWLIST:
        if technologies.intersection(rule["technologies"]):
            return rule
    return None


def evaluate_exact_radio_requirement(
    hs_code: str | None,
    description: str | None,
    facts: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Evaluate section 2.16 from structured facts, without broker effects."""

    data: Mapping[str, Any] = facts or {}
    code = normalize_hs_code(hs_code)
    desc = f" {_normal_text(description)} "
    direction = _direction(data.get("direction"))
    hs_scope = _matches_prefix(code, SECTION_216_PREFIXES)
    embedded = data.get("embedded_radio")
    technologies = _technologies(data.get("radio_technology"))
    frequencies = _frequency_ranges_mhz(data.get("frequency_mhz"))
    power_mw = _power_mw(data.get("transmitter_power_mw"))
    registry_value = data.get("radio_registry_exemption")
    registry_requested = _is_true(registry_value) or bool(_as_mapping(registry_value))
    text_signal = any(marker in desc for marker in _RADIO_MARKERS)
    candidate = (
        hs_scope
        or embedded is True
        or bool(technologies)
        or bool(frequencies)
        or registry_requested
        or text_signal
    )
    if not candidate:
        return None

    row = _base_row(
        family="radio_frequency",
        section="2.16",
        permit_type="РЭВЧУ",
        direction=direction,
        hs_code=code,
        hs_scope=hs_scope,
    )
    row["source_urls"] = [
        DECISION_30_SECTION_216_URL,
        DECISION_30_RADIO_PROCEDURE_URL,
    ]
    row["evidence"] = [
        {"type": "hs_scope", "matched": hs_scope},
        {"type": "structured_fact", "field": "embedded_radio", "value": embedded},
        {
            "type": "structured_fact",
            "field": "radio_technology",
            "value": sorted(technologies),
        },
        {
            "type": "structured_fact",
            "field": "frequency_mhz",
            "value": [list(item) for item in frequencies],
        },
        {
            "type": "structured_fact",
            "field": "transmitter_power_mw",
            "value": power_mw,
        },
    ]

    # Section 2.16 is import-only.  A known export transaction is an exact
    # negative irrespective of the product's radio characteristics.
    if direction in {"export", "transit"}:
        row["exclusion"] = {
            "rule_id": "radio.section_2_16.import_only",
            "reason": "Section 2.16 applies to import, not the supplied movement direction.",
            "source_url": DECISION_30_SECTION_216_URL,
        }
        return _set_definite(
            row,
            decision="not_applicable",
            requirement_applicable=False,
        )

    registry_exact, registry_url, registry_evidence = _registry_result(
        registry_value,
        fallback_url=data.get("radio_registry_evidence_url"),
    )
    row["evidence"].append(registry_evidence)
    if registry_url and registry_url not in row["source_urls"]:
        row["source_urls"].append(registry_url)
    if direction in {"import", "both"} and registry_exact:
        row["exclusion"] = {
            "rule_id": "radio.app15.unified_registry.exemption",
            "reason": (
                "An exact active product/model match in the official unified radio "
                "registry means a licence or conclusion is not required."
            ),
            "source_url": registry_url,
        }
        return _set_definite(
            row,
            decision="excluded_by_registry",
            requirement_applicable=False,
        )

    category_rule = _find_radio_category_exemption(technologies)
    technical_rule = _find_radio_technical_exemption(
        technologies, frequencies, power_mw
    )
    exact_rule = category_rule or technical_rule
    if direction in {"import", "both"} and exact_rule is not None:
        row["exclusion"] = {
            "rule_id": exact_rule["rule_id"],
            "reason": (
                "Structured technology, frequency and power facts match the curated "
                f"Appendix 2 exclusion: {exact_rule['label']}."
                if technical_rule is not None
                else "Structured product facts match the curated Appendix 2 exclusion: "
                f"{exact_rule['label']}."
            ),
            "source_url": DECISION_30_RADIO_PROCEDURE_URL,
        }
        return _set_definite(
            row,
            decision="excluded_by_exact_rule",
            requirement_applicable=False,
        )

    missing: list[str] = []
    if direction is None:
        missing.append("direction")
    if not hs_scope and embedded is not True and not technologies:
        missing.extend(("embedded_radio", "radio_technology"))
    if technologies.intersection(
        set().union(
            *(rule["technologies"] for rule in RADIO_TECHNICAL_EXEMPTION_ALLOWLIST)
        )
    ):
        if not frequencies:
            missing.append("frequency_mhz")
        if power_mw is None:
            missing.append("transmitter_power_mw")
    if registry_requested and not registry_exact:
        missing.append("radio_registry_evidence_url")
    # Outside a proven Appendix 2/registry exclusion, absence from the dynamic
    # registry and national technical conformity still need verification.
    if direction in {"import", "both"} and not registry_exact:
        missing.append("verified_current_radio_registry_result")
    row["missing_facts"] = _unique(missing)
    return row


def _notification_number(value: Any) -> str | None:
    if value is None:
        return None
    compact = "".join(str(value).strip().upper().split())
    if len(compact) != 12:
        return None
    if compact[:2] not in {"AM", "BY", "KZ", "KG", "RU"}:
        return None
    if not compact[2:].isdigit():
        return None
    return compact


def _exact_crypto_exemption(
    value: Any,
    *,
    direction: str | None,
) -> tuple[Mapping[str, Any] | None, list[str]]:
    details = _as_mapping(value)
    if not details:
        return None, ["crypto_exemption.rule_id"] if _is_true(value) else []
    rule_id = _normal_text(_first(details, "rule_id", "id")).replace(" ", "_")
    aliases = {
        "test_sim_cards": "crypto.app9.p6.test_sim_cards",
        "crypto.app9.p6.test_sim_cards": "crypto.app9.p6.test_sim_cards",
        "personal_use": "crypto.app9.annex5.personal_use",
        "personal_use_appendix_5": "crypto.app9.annex5.personal_use",
        "crypto.app9.annex5.personal_use": "crypto.app9.annex5.personal_use",
    }
    canonical = aliases.get(rule_id)
    missing: list[str] = []
    if canonical not in CRYPTO_EXEMPTION_ALLOWLIST:
        return None, ["crypto_exemption.rule_id"]
    if not _is_true(_first(details, "verified", "exact_match")):
        missing.append("crypto_exemption.verified")
    source_url = _official_eaeu_url(
        _first(details, "source_url", "evidence_url")
        or DECISION_30_CRYPTO_PROCEDURE_URL
    )
    if source_url is None:
        missing.append("crypto_exemption.evidence_url")

    if canonical == "crypto.app9.p6.test_sim_cards":
        raw_quantity = details.get("quantity")
        quantity = (
            raw_quantity
            if isinstance(raw_quantity, int) and not isinstance(raw_quantity, bool)
            else None
        )
        role = _normal_text(_first(details, "importer_role", "operator_role"))
        purpose = _normal_text(details.get("purpose"))
        if quantity is None or quantity <= 0 or quantity > 20:
            missing.append("crypto_exemption.quantity_at_most_20")
        if "cellular" not in role and "сотов" not in role:
            missing.append("crypto_exemption.cellular_operator")
        if "international" not in purpose and "международ" not in purpose:
            missing.append("crypto_exemption.international_exchange_purpose")
    elif canonical == "crypto.app9.annex5.personal_use":
        if not _is_true(details.get("personal_use")):
            missing.append("crypto_exemption.personal_use")
        if not _is_true(details.get("natural_person")):
            missing.append("crypto_exemption.natural_person")
        category = _normal_text(details.get("category")).replace(" ", "_")
        allowed_categories = {
            "mass_market_software",
            "electronic_signature",
            "computer",
            "smartphone",
            "smart_watch",
            "bank_or_sim_card",
        }
        if category not in allowed_categories:
            missing.append("crypto_exemption.appendix_5_category")
    if direction is None:
        missing.append("direction")
    if missing:
        return None, _unique(missing)
    return {
        "rule_id": canonical,
        "reason": (
            "Exact structured facts match the test-SIM-card exception in point 6."
            if canonical == "crypto.app9.p6.test_sim_cards"
            else "Exact structured facts match the personal-use list in Appendix 5."
        ),
        "source_url": source_url,
    }, []


def evaluate_exact_crypto_requirement(
    hs_code: str | None,
    description: str | None,
    facts: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Evaluate section 2.19; generic algorithm/protocol words stay advisory."""

    data: Mapping[str, Any] = facts or {}
    code = normalize_hs_code(hs_code)
    desc = f" {_normal_text(description)} "
    direction = _direction(data.get("direction"))
    hs_scope = _matches_prefix(code, SECTION_219_PREFIXES)
    present = data.get("cryptography_present")
    functions = _crypto_functions(data.get("crypto_functions"))
    text_signal = any(marker in desc for marker in _CRYPTO_MARKERS)
    notification_number = _notification_number(data.get("notification_registry_number"))
    notification_hint = _is_true(data.get("notification_registry_verified"))
    exemption_hint = _is_true(data.get("crypto_exemption")) or bool(
        _as_mapping(data.get("crypto_exemption"))
    )
    candidate = (
        hs_scope
        or present is True
        or bool(functions)
        or text_signal
        or notification_number is not None
        or notification_hint
        or exemption_hint
    )
    if not candidate:
        return None

    row = _base_row(
        family="cryptography",
        section="2.19",
        permit_type="НФ/ЛЗ",
        direction=direction,
        hs_code=code,
        hs_scope=hs_scope,
    )
    row["source_urls"] = [
        DECISION_30_SECTION_219_URL,
        DECISION_30_CRYPTO_PROCEDURE_URL,
    ]
    row["evidence"] = [
        {"type": "hs_scope", "matched": hs_scope},
        {
            "type": "structured_fact",
            "field": "cryptography_present",
            "value": present,
        },
        {
            "type": "structured_fact",
            "field": "crypto_functions",
            "value": functions,
        },
        {
            "type": "structured_fact",
            "field": "mass_market",
            "value": data.get("mass_market"),
            "note": "Mass-market status is a notification category, not a general exemption.",
        },
    ]

    registry_details = _as_mapping(data.get("notification_registry_verified"))
    registry_value: Any = (
        registry_details
        if registry_details
        else data.get("notification_registry_verified")
    )
    registry_exact, registry_url, registry_evidence = _registry_result(
        registry_value,
        fallback_url=data.get("registry_evidence_url"),
    )
    if registry_details and notification_number is None:
        notification_number = _notification_number(
            _first(registry_details, "registration_number", "number", "registry_number")
        )
    registry_evidence["registration_number"] = notification_number
    row["evidence"].append(registry_evidence)
    if registry_url and registry_url not in row["source_urls"]:
        row["source_urls"].append(registry_url)
    if direction == "transit":
        transit_route = _transit_route(data.get("transit_route"))
        row["evidence"].append(
            {
                "type": "structured_fact",
                "field": "transit_route",
                "value": transit_route,
            }
        )
        if transit_route == "border_to_border":
            row["exclusion"] = {
                "rule_id": "crypto.app9.p8.through_transit_no_documents",
                "reason": (
                    "Caller-supplied route facts identify through transit from the "
                    "place of arrival to the place of departure under Appendix 9, point 8."
                ),
                "source_url": DECISION_30_CRYPTO_PROCEDURE_URL,
            }
            return _set_definite(
                row,
                decision="not_applicable",
                requirement_applicable=False,
            )
        row["missing_facts"] = [
            "transit_route"
            if transit_route is None
            else "crypto_transit_authorization_or_notification"
        ]
        return row

    conflicting_absence = _is_false(present) and (
        bool(functions) or registry_exact or notification_number is not None
    )
    if (
        direction in {"import", "export", "both"}
        and hs_scope
        and registry_exact
        and notification_number is not None
        and not conflicting_absence
    ):
        row["permit_type"] = "НФ"
        return _set_definite(
            row,
            decision="covered_by_verified_notification",
            requirement_applicable=True,
            required_document=f"Сведения о нотификации {notification_number}",
        )

    exact_exemption, exemption_missing = _exact_crypto_exemption(
        data.get("crypto_exemption"),
        direction=direction,
    )
    if hs_scope and exact_exemption is not None and not conflicting_absence:
        row["exclusion"] = dict(exact_exemption)
        source_url = exact_exemption.get("source_url")
        if source_url and source_url not in row["source_urls"]:
            row["source_urls"].append(source_url)
        return _set_definite(
            row,
            decision="excluded_by_exact_rule",
            requirement_applicable=False,
        )

    missing: list[str] = []
    if direction is None:
        missing.append("direction")
    if not hs_scope:
        missing.append("section_2_19_hs_scope")
    if present is not True and not registry_exact:
        missing.append("cryptography_present")
    if present is True and not functions:
        missing.append("crypto_functions")
    if conflicting_absence:
        missing.append("resolve_conflicting_crypto_facts")
    if notification_hint or notification_number is not None:
        if notification_number is None:
            missing.append("notification_registry_number")
        if not registry_exact:
            missing.append("official_active_notification_registry_evidence")
    missing.extend(exemption_missing)
    # AES/TLS/VPN and mass-market status deliberately do not close these facts.
    if functions and not registry_exact and exact_exemption is None:
        missing.append("notification_or_exact_legal_exemption")
    row["missing_facts"] = _unique(missing)
    return row


def evaluate_official_ntm_exact_devices(
    hs_code: str | None,
    description: str | None,
    facts: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return deterministic radio/crypto shadow rows in section order."""

    rows = (
        evaluate_exact_radio_requirement(hs_code, description, facts),
        evaluate_exact_crypto_requirement(hs_code, description, facts),
    )
    return [row for row in rows if row is not None]


# Short integration-friendly alias.
evaluate_exact_device_requirements = evaluate_official_ntm_exact_devices


__all__ = [
    "CRYPTO_EXEMPTION_ALLOWLIST",
    "DECISION_30_CRYPTO_PROCEDURE_URL",
    "DECISION_30_RADIO_PROCEDURE_URL",
    "DECISION_30_SECTION_216_URL",
    "DECISION_30_SECTION_219_URL",
    "EAEU_REGISTRY_PORTAL_URL",
    "RADIO_CATEGORY_EXEMPTION_ALLOWLIST",
    "RADIO_TECHNICAL_EXEMPTION_ALLOWLIST",
    "SECTION_216_PREFIXES",
    "SECTION_219_PREFIXES",
    "SOURCE_KIND",
    "evaluate_exact_crypto_requirement",
    "evaluate_exact_device_requirements",
    "evaluate_exact_radio_requirement",
    "evaluate_official_ntm_exact_devices",
]
