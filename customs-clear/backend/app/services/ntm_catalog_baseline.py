"""Reproducible fingerprints for the full TN VED catalog used by the NTM gate."""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable


BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = BACKEND_ROOT.parent.parent
DEFAULT_BASELINE_PATH = BACKEND_ROOT / "data" / "ntm_full_catalog_baseline.json"
DEFAULT_ETT_PATH = BACKEND_ROOT / "data" / "raw_normative" / "eec_ett_normative_bundle.json"
DEFAULT_PDF_SOURCE_DIR = REPOSITORY_ROOT / "backend" / "app" / "services" / "source_sync" / "data"
DEFAULT_PARSER_PATH = BACKEND_ROOT / "scripts" / "tnved_pdf_parser.py"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_lines(lines: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for line in lines:
        digest.update(line.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def canonical_duty_rate(value: Any) -> str:
    """Canonical comparison value for a duty string.

    The pinned ETT bundle contains equivalent ad-valorem values in both
    ``5%`` and ``5.0`` form.  Treat only plain numeric/percent values as
    equivalent; compound and specific-duty formulas remain exact normalized
    text so this helper cannot silently reinterpret a legal formula.
    """
    raw = " ".join(("" if value is None else str(value)).split())
    numeric_candidate = raw.replace(",", ".")
    match = re.fullmatch(
        r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*%?",
        numeric_candidate,
    )
    if match:
        try:
            number = Decimal(match.group(1)).normalize()
        except InvalidOperation:
            pass
        else:
            if number == 0:
                number = Decimal(0)
            return f"ad_valorem_percent:{format(number, 'f')}"
    return f"text:{raw.casefold()}"


def duty_rate_content_sha256(rows: Iterable[tuple[Any, Any]]) -> str:
    """Fingerprint exact code/rate content after canonical value comparison."""
    normalized = sorted(
        (str(code or "").strip(), canonical_duty_rate(duty_rate))
        for code, duty_rate in rows
    )
    return _sha256_lines(
        f"{code}\t{canonical_rate}" for code, canonical_rate in normalized
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def normalize_catalog_description(value: Any) -> str:
    return " ".join(str(value or "").split())


def catalog_fingerprint(rows: Iterable[tuple[Any, Any]]) -> dict[str, Any]:
    normalized = sorted(
        (str(code or "").strip(), normalize_catalog_description(description))
        for code, description in rows
    )
    codes = [code for code, _ in normalized]
    blank_codes = [code for code, description in normalized if not description]
    return {
        "rows": len(normalized),
        "unique_codes": len(set(codes)),
        "description_rows": len(normalized) - len(blank_codes),
        "blank_description_codes": blank_codes,
        "code_set_sha256": _sha256_lines(sorted(set(codes))),
        "code_description_sha256": _sha256_lines(
            f"{code}\t{description}" for code, description in normalized
        ),
    }


def pdf_source_manifest(data_dir: Path = DEFAULT_PDF_SOURCE_DIR) -> dict[str, Any]:
    files = sorted(data_dir.glob("ru.*.pdf"), key=lambda path: path.name)
    manifest_rows: list[dict[str, Any]] = []
    chapter_codes: list[str] = []
    for path in files:
        match = re.match(r"ru\.(\d{2})_", path.name)
        if match:
            chapter_codes.append(match.group(1))
        manifest_rows.append({
            "name": path.name,
            "size_bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        })
    return {
        "source_dir": "backend/app/services/source_sync/data",
        "file_count": len(manifest_rows),
        "total_size_bytes": sum(int(row["size_bytes"]) for row in manifest_rows),
        "chapter_codes": sorted(chapter_codes),
        "manifest_sha256": _sha256_lines(
            f"{row['name']}\t{row['size_bytes']}\t{row['sha256']}"
            for row in manifest_rows
        ),
        "files": manifest_rows,
    }


def parser_fingerprint(path: Path = DEFAULT_PARSER_PATH) -> dict[str, Any]:
    return {
        "path": "customs-clear/backend/scripts/tnved_pdf_parser.py",
        "sha256": _sha256_file(path),
    }


def active_ett_fingerprint(path: Path = DEFAULT_ETT_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rates = payload.get("rates")
    if not isinstance(rates, list):
        raise ValueError("official ETT bundle has no rates array")
    raw_codes = [
        str(row.get("hs_code") or "").strip() if isinstance(row, dict) else ""
        for row in rates
    ]
    valid_codes = [code for code in raw_codes if code.isdigit() and len(code) == 10]
    unique_codes = sorted(set(valid_codes))
    rows_by_code: dict[str, list[dict[str, Any]]] = {}
    for row, code in zip(rates, raw_codes, strict=True):
        if isinstance(row, dict) and code.isdigit() and len(code) == 10:
            rows_by_code.setdefault(code, []).append(row)
    duplicate_codes = sorted(
        code for code, rows in rows_by_code.items() if len(rows) > 1
    )
    material_conflict_codes = sorted(
        code
        for code, rows in rows_by_code.items()
        if len({canonical_duty_rate(row.get("duty_rate")) for row in rows}) > 1
    )
    return {
        "revision": payload.get("revision"),
        "effective_from": payload.get("effective_from"),
        "source_url": payload.get("official_ett_url") or payload.get("source_url"),
        "raw_rows": len(rates),
        "unique_codes": len(unique_codes),
        "duplicate_rows": len(valid_codes) - len(unique_codes),
        "duplicate_code_count": len(duplicate_codes),
        "duplicate_codes": duplicate_codes,
        "material_conflict_code_count": len(material_conflict_codes),
        "material_conflict_codes": material_conflict_codes,
        "invalid_code_rows": len(rates) - len(valid_codes),
        "code_set_sha256": _sha256_lines(unique_codes),
        "active_duty_rate_sha256": duty_rate_content_sha256(
            (code, row.get("duty_rate"))
            for row, code in zip(rates, raw_codes, strict=True)
            if isinstance(row, dict) and code.isdigit() and len(code) == 10
        ),
        "artifact_sha256": _sha256_file(path),
        "rate_rows_sha256": _sha256_lines(
            sorted(_canonical_json(row) for row in rates)
        ),
        "structurally_publishable": not (
            len(rates) - len(valid_codes)
            or len(valid_codes) - len(unique_codes)
            or material_conflict_codes
        ),
    }


def load_catalog_baseline(path: Path = DEFAULT_BASELINE_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "1":
        raise ValueError("unsupported NTM full-catalog baseline schema")
    if payload.get("validation_mode") != "quarantine_only":
        raise ValueError("NTM baseline schema v1 must remain quarantine-only")
    if not isinstance(payload.get("pdf_source"), dict):
        raise ValueError("NTM full-catalog baseline has no pdf_source")
    if not isinstance(payload.get("catalog"), dict):
        raise ValueError("NTM full-catalog baseline has no catalog")
    if not isinstance(payload.get("active_ett"), dict):
        raise ValueError("NTM full-catalog baseline has no active_ett")
    return payload


def compare_source_baseline(
    baseline: dict[str, Any],
    *,
    pdf_source: dict[str, Any],
    active_ett: dict[str, Any],
    parser: dict[str, Any] | None = None,
) -> dict[str, bool]:
    expected_pdf = baseline["pdf_source"]
    expected_ett = baseline["active_ett"]
    current_parser = parser or parser_fingerprint()
    return {
        "pdf_source_manifest_match": (
            pdf_source.get("manifest_sha256") == expected_pdf.get("manifest_sha256")
            and pdf_source.get("file_count") == expected_pdf.get("file_count")
            and pdf_source.get("chapter_codes") == expected_pdf.get("chapter_codes")
        ),
        "active_ett_snapshot_match": all(
            active_ett.get(field) == expected_ett.get(field)
            for field in (
                "revision",
                "effective_from",
                "source_url",
                "raw_rows",
                "unique_codes",
                "duplicate_rows",
                "duplicate_code_count",
                "duplicate_codes",
                "material_conflict_code_count",
                "material_conflict_codes",
                "invalid_code_rows",
                "code_set_sha256",
                "active_duty_rate_sha256",
                "artifact_sha256",
                "rate_rows_sha256",
                "structurally_publishable",
            )
        ),
        "catalog_parser_match": current_parser == baseline.get("parser"),
    }
