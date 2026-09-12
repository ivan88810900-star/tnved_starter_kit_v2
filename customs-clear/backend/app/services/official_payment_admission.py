"""Legacy payment metadata cannot authorize legal rate application.

There is no supported trusted manifest-bound review/release record for legacy
bundles. This module intentionally has no positive branch or payload override.
Pure parsing and isolated versioned ETT candidate previews remain available.
"""

LEGACY_OFFICIAL_PAYMENT_DOMAINS = frozenset({
    "import_duty", "vat", "excise", "anti_dumping", "special_safeguard", "countervailing",
})

LEGAL_REVIEW_BLOCKER = (
    "manifest_bound_legal_review_required: исходные артефакты, их хранение и "
    "юридическое решение по точному manifest не подтверждены. URL, revision, "
    "checksum локального JSON и SourceStatus не заменяют эту проверку."
)
LEGACY_ETT_QUARANTINE_BLOCKER = (
    "versioned_manifest_review_required: legacy DB-derived ЕТТ остаётся в "
    "карантине; требуется отдельный версионный официальный manifest и review."
)


def payment_admission_blocker(domain: str) -> str:
    if domain not in LEGACY_OFFICIAL_PAYMENT_DOMAINS:
        raise ValueError("unsupported payment domain")
    return LEGACY_ETT_QUARANTINE_BLOCKER if domain == "import_duty" else LEGAL_REVIEW_BLOCKER


def blocked_payment_import(*, source: str, domain: str = "vat") -> dict:
    return {
        "status": "manual_review_required", "source": source,
        "db_mutated": False, "active_rates_written": False,
        "source_evidence_verified": False, "legal_review_verified": False,
        "retention_verified": False, "imported": 0,
        "blockers": [payment_admission_blocker(domain)],
    }
