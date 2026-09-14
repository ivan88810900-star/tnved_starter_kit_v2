"""Quarantined compatibility entry points for the retired ETT PDF importer.

Decision #188 requires immutable, versioned official artifacts and manifest-bound
review before applying rates. Flattened PDF text cannot establish a duty cell,
its footnotes or effective dates. ETT is not a VAT source. These helpers may
identify unreviewed code candidates, but never produce active tariff records.
"""
from __future__ import annotations

from decimal import Decimal
import re
from typing import Any

EEC_ETT_INDEX = "https://eec.eaeunion.org/comission/department/catr/ett/"
EEC_ETT_BASE = "https://eec.eaeunion.org"
ETT_REVIEW_DECISION = (
    "https://github.com/ivan88810900-star/tnved_starter_kit_v2/issues/188"
)


def _normalize_hs(code: str) -> str | None:
    """Accept exact ten-digit codes; never pad headings into invented leaves."""
    if not isinstance(code, str):
        return None
    digits = re.sub(r"[ \t\r\n]+", "", code)
    return digits if re.fullmatch(r"[0-9]{10}", digits) else None


def _extract_duty_from_line(line: str) -> str | None:
    """Read only an isolated, explicit percentage cell, not a flattened row.

    This lexical helper does not establish applicability or approve a rate.
    Combined/specific duties, footnotes and bare numbers require the versioned
    parser. A description's final number is never a rate; failure is not zero.
    """
    match = re.fullmatch(r"[ \t]*([0-9]+(?:[.,][0-9]+)?)[ \t]*%[ \t]*", line)
    if match is None:
        return None
    number = Decimal(match.group(1).replace(",", "."))
    # Fixed-point formatting avoids context-sensitive normalize() rounding.
    value = format(number, "f")
    if "." in value:
        value = value.rstrip("0").rstrip(".")
    return f"{value}%"


def _extract_vat_from_line(line: str) -> None:
    """Compatibility helper: no text in ETT establishes a VAT rate."""
    return None


def _parse_pdf_text(text: str) -> list[dict[str, Any]]:
    """Retain unreviewed code candidates, without inferred duties or VAT.

    Duplicate candidates stay visible: a later reviewed parser must resolve
    conflicting rows, footnotes and validity intervals explicitly. A candidate
    is not an hs_rates import payload.
    """
    records: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        match = re.match(
            r"^([0-9]{10}|[0-9]{4}[ \t]+[0-9]{2}[ \t]+[0-9]{3}[ \t]+[0-9])(?=\s|$)",
            line,
        )
        if match is None:
            continue
        code = _normalize_hs(match.group(1))
        if code is not None:
            records.append({
                "hs_code": code,
                "raw_text": raw_line,
                "candidate_only": True,
                "review_status": "REVIEW_REQUIRED",
            })
    return records


def _parse_table_to_records(table: list[list[str]]) -> list[dict[str, Any]]:
    """Unknown table columns cannot establish a rate cell or an effective date."""
    records: list[dict[str, Any]] = []
    for row in table:
        records.extend(_parse_pdf_text(" ".join(str(cell or "") for cell in row)))
    return records


async def _fetch_pdf_links() -> list[str]:
    """Retired discovery path; acquisition belongs to the versioned pipeline."""
    return []


async def parse_ett_pdf_from_url(pdf_url: str) -> list[dict[str, Any]]:
    """Retired URL parser, retained for compatibility without network access.

    The old downloader had neither artifact identity nor a versioned manifest.
    Callers must use the reviewed snapshot pipeline. Returning no records must
    not be interpreted as zero duty.
    """
    return []


async def sync_ett_from_pdfs(max_groups: int = 5) -> dict[str, Any]:
    """Report the review boundary without downloads or database side effects.

    max_groups remains accepted for existing API/scheduler callers. It cannot
    enable the retired partial-corpus importer, even when set to zero.
    """
    return {
        "status": "REVIEW_REQUIRED",
        "source": "ETT_PDF",
        "rows": 0,
        "files": 0,
        "quarantined": True,
        "reason": "versioned_manifest_review_required",
        "decision_url": ETT_REVIEW_DECISION,
        "note": (
            "Прямой импорт ЕТТ из PDF отключён. Требуется версия официального "
            "снимка с подтверждёнными источниками, датами действия и утверждением "
            "точной контрольной суммы перед применением ставок."
        ),
    }
