from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass
import hashlib
import math
import os
import re
import xml.etree.ElementTree as ET

import httpx

from ..datetime_util import utc_now_naive
from ..db import SessionLocal
from ..models.core import ExchangeRate, SourceStatus, SyncLog
from .opendata_snapshot_evidence import acquire_opendata_write_lock
from .source_http import read_async_body, read_httpx_body, validate_body_headers

CBR_DAILY_URL = "https://www.cbr.ru/scripts/XML_daily.asp"
CBRF_SOURCE_CODE = "CBRF"
CBRF_SOURCE_NAME = "Курсы валют ЦБ РФ (XML daily)"
TRACKED = ("USD", "EUR", "CNY", "BYN", "KZT")

_CBR_OFFICIAL_URL = "https://www.cbr.ru/scripts/XML_daily.asp"
_CBR_SOURCE_CODES = (CBRF_SOURCE_CODE, "cbr_exchange_rates", "CBR", "EXCHANGE_RATES")
_CBR_XML_MEDIA_TYPES = frozenset({"application/xml", "text/xml"})
_CBR_XML_MAX_BYTES = 1024 * 1024
_CBR_XML_MAX_VALUTES = 256
_CBR_REVISION_RE = re.compile(r"^cbrf:(\d{4}-\d{2}-\d{2})(?::sha256:([0-9a-f]{64}))?$", re.IGNORECASE)
_CBR_CODE_RE = re.compile(r"^[A-Z]{3}$")
_CBR_POSITIVE_DECIMAL_RE = re.compile(r"^(?:0|[1-9]\d*)(?:[.,]\d+)?$")
_CBR_POSITIVE_INTEGER_RE = re.compile(r"^[1-9]\d*$")


class CBRRateRollbackError(RuntimeError):
    """A candidate rate date is older than persisted official CBR state."""


@dataclass(frozen=True)
class CBRRateSnapshot:
    date_key: str
    rows: dict[str, tuple[float, float]]
    sha256: str

    def __iter__(self):
        # Existing read-only consumers may continue unpacking date and rates.
        yield self.date_key
        yield self.rows


def _configured_cbr_max_rate_age_days() -> int:
    try:
        value = int(os.getenv("CBR_MAX_RATE_AGE_DAYS", "14") or "14")
    except ValueError:
        value = 14
    return max(1, min(31, value))


CBR_MAX_RATE_AGE_DAYS = _configured_cbr_max_rate_age_days()
FALLBACK: dict[str, float] = {
    "USD": 92.0,
    "EUR": 100.0,
    "CNY": 12.7,
    "BYN": 28.0,
    "KZT": 0.19,
    "RUB": 1.0,
}


def _require_exact_cbr_url(value: object, *, label: str) -> str:
    """Accept only the one canonical HTTPS CBR daily-rate endpoint."""
    candidate = str(value or "")
    if candidate != _CBR_OFFICIAL_URL:
        raise RuntimeError(f"unexpected CBR {label} URL: {candidate!r}")
    return candidate


def _cbr_xml_media_type(content_type: object) -> str:
    return str(content_type or "").split(";", 1)[0].strip().casefold()


def _validate_cbr_response_headers(response: httpx.Response) -> None:
    _require_exact_cbr_url(response.url, label="response")
    if 300 <= response.status_code < 400:
        raise RuntimeError(f"CBR redirects are not allowed: HTTP {response.status_code}")
    response.raise_for_status()
    if response.status_code != 200:
        raise RuntimeError("CBR requires a complete HTTP 200 snapshot")

    media_type = _cbr_xml_media_type(response.headers.get("content-type"))
    if media_type not in _CBR_XML_MEDIA_TYPES:
        raise RuntimeError(
            f"CBR returned non-XML Content-Type: {media_type or 'missing'}"
        )

    validate_body_headers(response.headers, max_bytes=_CBR_XML_MAX_BYTES)


def _validate_cbr_body(body: bytes) -> bytes:
    if not body:
        raise RuntimeError("CBR returned an empty XML response")
    if len(body) > _CBR_XML_MAX_BYTES:
        raise RuntimeError("CBR XML response exceeds the size limit")
    if b"\x00" in body:
        raise ValueError("CBR XML uses an unsupported encoding")
    stripped = body.lstrip(b"\xef\xbb\xbf \t\r\n")
    if not stripped.startswith((b"<?xml", b"<ValCurs")):
        raise ValueError("CBR response body is not the expected XML document")
    lowered = body.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise ValueError("CBR XML must not contain DTD or entity declarations")
    return body


def _validated_cbr_response_body(response: httpx.Response) -> bytes:
    _validate_cbr_response_headers(response)
    return _validate_cbr_body(read_httpx_body(response, max_bytes=_CBR_XML_MAX_BYTES))


def _required_scalar_text(element: ET.Element, field: str, *, code: str = "?") -> str:
    matches = [child for child in element if child.tag == field]
    if len(matches) != 1:
        raise ValueError(
            f"CBR Valute {code!r} must contain exactly one {field} element"
        )
    node = matches[0]
    if list(node):
        raise ValueError(f"CBR Valute {code!r} {field} must be scalar")
    value = (node.text or "").strip()
    if not value:
        raise ValueError(f"CBR Valute {code!r} has an empty {field}")
    return value


def _positive_cbr_decimal(raw: str, *, field: str, code: str) -> Decimal:
    if len(raw) > 64 or not _CBR_POSITIVE_DECIMAL_RE.fullmatch(raw):
        raise ValueError(f"CBR Valute {code!r} has an invalid {field}")
    try:
        value = Decimal(raw.replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError(f"CBR Valute {code!r} has an invalid {field}") from exc
    if not value.is_finite() or value <= 0:
        raise ValueError(f"CBR Valute {code!r} has a non-positive {field}")
    return value


def _parse_cbr_xml(xml_text: str | bytes) -> tuple[str, dict[str, tuple[float, float]]]:
    raw_for_checks = xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text
    lowered = raw_for_checks.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise ValueError("CBR XML must not contain DTD or entity declarations")
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError("CBR response is not well-formed XML") from exc
    if root.tag != "ValCurs":
        raise ValueError(f"CBR XML root must be ValCurs, got {root.tag!r}")

    date_raw = (root.attrib.get("Date") or "").strip()
    if not date_raw:
        raise ValueError("CBR XML is missing its Date attribute")
    try:
        date_key = datetime.strptime(date_raw, "%d.%m.%Y").strftime("%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"CBR XML has an invalid Date attribute: {date_raw!r}") from exc

    valutes = list(root)
    if not valutes:
        raise ValueError("CBR XML contains no Valute records")
    if len(valutes) > _CBR_XML_MAX_VALUTES:
        raise ValueError("CBR XML contains too many Valute records")

    out: dict[str, tuple[float, float]] = {}
    seen_codes: set[str] = set()
    for valute in valutes:
        if valute.tag != "Valute":
            raise ValueError(f"CBR XML has an unexpected root child: {valute.tag!r}")
        if any(not isinstance(field.tag, str) or list(field) for field in valute):
            raise ValueError("CBR Valute fields must be unnamespaced scalar elements")
        code = _required_scalar_text(valute, "CharCode").strip()
        if not _CBR_CODE_RE.fullmatch(code):
            raise ValueError(f"CBR Valute has an invalid CharCode: {code!r}")
        if code in seen_codes:
            raise ValueError(f"CBR XML contains duplicate CharCode: {code}")
        seen_codes.add(code)

        nominal_raw = _required_scalar_text(valute, "Nominal", code=code)
        if not _CBR_POSITIVE_INTEGER_RE.fullmatch(nominal_raw):
            raise ValueError(f"CBR Valute {code!r} has an invalid Nominal")
        nominal = _positive_cbr_decimal(nominal_raw, field="Nominal", code=code)
        value = _positive_cbr_decimal(
            _required_scalar_text(valute, "Value", code=code),
            field="Value",
            code=code,
        )
        if code in TRACKED:
            rate = float(value / nominal)
            nominal_float = float(nominal)
            if not math.isfinite(rate) or not math.isfinite(nominal_float):
                raise ValueError(f"CBR Valute {code!r} is outside numeric limits")
            out[code] = (rate, nominal_float)
    return date_key, out


async def fetch_cbr_rates() -> CBRRateSnapshot:
    request_url = _require_exact_cbr_url(CBR_DAILY_URL, label="request")
    async with httpx.AsyncClient(
        timeout=20.0,
        follow_redirects=False,
        trust_env=False,
        verify=True,
    ) as client:
        async with client.stream(
            "GET", request_url,
            headers={"Accept": "application/xml, text/xml;q=0.9", "Accept-Encoding": "identity"},
        ) as response:
            _validate_cbr_response_headers(response)
            body = _validate_cbr_body(await read_async_body(response, max_bytes=_CBR_XML_MAX_BYTES))
    date_key, rows = _parse_cbr_xml(body)
    return CBRRateSnapshot(date_key, rows, hashlib.sha256(body).hexdigest())


def _validate_cbr_rate_date(date_key: str, *, now: datetime | None = None) -> None:
    """Reject cached or future-dated XML even when its shape looks canonical."""
    rate_date = datetime.strptime(str(date_key or ""), "%Y-%m-%d").date()
    reference = (now or datetime.now(timezone.utc)).date()
    age_days = (reference - rate_date).days
    if age_days < -1:
        raise ValueError(f"CBR rate date is in the future: {rate_date.isoformat()}")
    if age_days > CBR_MAX_RATE_AGE_DAYS:
        raise ValueError(
            f"CBR rate date is stale: {rate_date.isoformat()} "
            f"(age_days={age_days}, max={CBR_MAX_RATE_AGE_DAYS})"
        )


async def validate_cbr_rates_source() -> dict[str, object]:
    """Fetch and validate the canonical CBR payload without mutating the database."""
    try:
        date_key, rows = await fetch_cbr_rates()
        _validate_cbr_rate_date(date_key)
    except Exception as exc:
        return {
            "status": "ERROR",
            "source": "unavailable",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "validated": 0,
            "error": str(exc),
        }
    missing = _missing_tracked_currencies(rows)
    if missing:
        return {
            "status": "ERROR",
            "source": "incomplete",
            "date": date_key,
            "validated": len(rows),
            "missing_currencies": missing,
        }
    return {
        "status": "OK",
        "source": "CBRF",
        "date": date_key,
        "validated": len(rows),
        "updated": 0,
    }


def _missing_tracked_currencies(rows: dict[str, tuple[float, float]]) -> list[str]:
    """Валюты TRACKED, отсутствующие в ответе CBR XML (до добивки FALLBACK в upsert)."""
    return [code for code in TRACKED if code not in rows]


def _official_cbr_revision_date(revision: object) -> date | None:
    value = str(revision or "").strip()
    match = _CBR_REVISION_RE.fullmatch(value)
    if match is None:
        if value.casefold().startswith("cbrf:"):
            raise RuntimeError(
                f"cannot prove CBR monotonicity from persisted revision {value!r}"
            )
        return None
    try:
        parsed = date.fromisoformat(match.group(1))
    except ValueError as exc:
        raise RuntimeError(
            f"cannot prove CBR monotonicity from persisted revision {value!r}"
        ) from exc
    if parsed.isoformat() != match.group(1):
        raise RuntimeError(
            f"cannot prove CBR monotonicity from persisted revision {value!r}"
        )
    return parsed


def _persisted_official_cbr_revisions(db, *, lock: bool = False) -> list[str]:
    """Read the durable CBR high-water mark from status and successful logs."""
    status_query = (
        db.query(SourceStatus)
        .filter(SourceStatus.source_code.in_(_CBR_SOURCE_CODES))
        .order_by(SourceStatus.source_code.asc())
    )
    if lock:
        status_query = status_query.with_for_update()
    revisions = []
    for row in status_query.all():
        value = str(row.revision or "").strip()
        if not row.is_stale and _CBR_REVISION_RE.fullmatch(value) is None:
            raise RuntimeError("cannot prove CBR monotonicity from successful source status")
        if value.casefold().startswith("cbrf:"):
            _official_cbr_revision_date(value)
            revisions.append(value)
    for revision, status in db.query(SyncLog.revision, SyncLog.status).filter(
        SyncLog.source_code.in_(_CBR_SOURCE_CODES)
    ).all():
        if str(status or "").strip().upper() == "OK":
            value = str(revision or "").strip()
            if _CBR_REVISION_RE.fullmatch(value) is None:
                raise RuntimeError("cannot prove CBR monotonicity from successful sync log")
            _official_cbr_revision_date(value)
            revisions.append(value)
    return revisions


def _newest_persisted_official_cbr_date(db, *, lock: bool = False) -> date | None:
    revisions = _persisted_official_cbr_revisions(db, lock=lock)
    dates = [
        parsed
        for revision in revisions
        if (parsed := _official_cbr_revision_date(revision)) is not None
    ]
    return max(dates, default=None)


def _require_no_cbr_rate_rollback(db, date_key: str) -> date:
    try:
        candidate = date.fromisoformat(str(date_key or ""))
    except ValueError as exc:
        raise ValueError(f"invalid CBR rate date: {date_key!r}") from exc
    if candidate.isoformat() != str(date_key or ""):
        raise ValueError(f"invalid CBR rate date: {date_key!r}")
    persisted = _newest_persisted_official_cbr_date(db, lock=True)
    if persisted is not None and candidate < persisted:
        raise CBRRateRollbackError(
            "refusing CBR rate rollback from "
            f"{persisted.isoformat()} to {candidate.isoformat()}"
        )
    return candidate


def _write_source_status(db, *, revision: str, now: datetime, stale: bool, note: str) -> None:
    status = (
        db.query(SourceStatus)
        .filter(SourceStatus.source_code == CBRF_SOURCE_CODE)
        .first()
    )
    if status is None:
        db.add(
            SourceStatus(
                source_code=CBRF_SOURCE_CODE,
                source_name=CBRF_SOURCE_NAME,
                source_url=_CBR_OFFICIAL_URL,
                revision=revision,
                synced_at=now,
                is_stale=stale,
                note=note,
            )
        )
        return
    status.source_name = CBRF_SOURCE_NAME
    status.source_url = _CBR_OFFICIAL_URL
    status.revision = revision
    status.synced_at = now
    status.is_stale = stale
    status.note = note


def _upsert_rates(
    rows: dict[str, tuple[float, float]],
    *,
    official_date_key: str | None = None,
    artifact_sha256: str | None = None,
) -> int:
    changed = 0
    with SessionLocal() as db:
        acquire_opendata_write_lock(db, source_key="CBRF", dataset_id="XML_daily")
        now = utc_now_naive()
        if official_date_key is not None:
            _require_no_cbr_rate_rollback(db, official_date_key)
            if not re.fullmatch(r"[0-9a-f]{64}", str(artifact_sha256 or "")):
                raise RuntimeError("CBR update requires the original artifact SHA-256")
            if _missing_tracked_currencies(rows):
                raise RuntimeError("CBR official snapshot is incomplete")
            revisions = _persisted_official_cbr_revisions(db)
            same_date = [r for r in revisions if _official_cbr_revision_date(r).isoformat() == official_date_key]
            digests = {_CBR_REVISION_RE.fullmatch(r).group(2) for r in same_date}
            if any(digest and digest != artifact_sha256 for digest in digests):
                raise RuntimeError("CBR immutable same-date artifact changed; stored rates preserved")
            if None in digests:
                existing = {r.currency_code: (float(r.rate), float(r.nominal))
                            for r in db.query(ExchangeRate).filter(ExchangeRate.currency_code.in_(TRACKED)).all()}
                if existing != rows:
                    raise RuntimeError("CBR legacy same-date rates do not match candidate artifact")
        for code in TRACKED:
            rate, nominal = rows.get(code, (FALLBACK[code], 1.0))
            obj = db.query(ExchangeRate).filter(ExchangeRate.currency_code == code).first()
            if obj is None:
                db.add(
                    ExchangeRate(
                        currency_code=code,
                        rate=float(rate),
                        nominal=float(nominal),
                        updated_at=now,
                    )
                )
                changed += 1
            else:
                obj.rate = float(rate)
                obj.nominal = float(nominal)
                obj.updated_at = now
                changed += 1
        if official_date_key is not None:
            _record_cbrf_sync_success(db, official_date_key, changed,
                                      artifact_sha256=artifact_sha256, now=now)
        db.commit()
    return changed


def _stored_tracked_rate_count() -> int:
    """Число уже сохранённых курсов, которые нельзя затирать fallback-константами."""
    with SessionLocal() as db:
        return int(
            db.query(ExchangeRate)
            .filter(ExchangeRate.currency_code.in_(TRACKED))
            .count()
        )


def _record_cbrf_sync_success(
    db, date_key: str, rows_updated: int, *, artifact_sha256: str, now: datetime,
) -> None:
    """The rate rows, high-water mark and success evidence share ONE commit."""
    revision = f"cbrf:{date_key}:sha256:{artifact_sha256}"
    note = f"CBRF XML sync OK, currencies={len(TRACKED)}, updated={rows_updated}"
    _write_source_status(db, revision=revision, now=now, stale=False, note=note)
    db.add(SyncLog(source_code=CBRF_SOURCE_CODE, synced_at=now, status="OK",
                   revision=revision, rows_affected=rows_updated, note=note))


def _handle_cbr_failure(
    error: str, *, allow_fallback: bool, attempt_started_at: datetime,
) -> dict[str, object]:
    """Serialize empty-DB fallback and failure provenance with successful writers."""
    with SessionLocal() as db:
        acquire_opendata_write_lock(db, source_key="CBRF", dataset_id="XML_daily")
        existing = db.query(ExchangeRate).filter(ExchangeRate.currency_code.in_(TRACKED)).count()
        status = db.query(SourceStatus).filter_by(source_code=CBRF_SOURCE_CODE).first()
        # A failed request started before a successful writer must not downgrade it.
        superseded = bool(status and status.synced_at and status.synced_at > attempt_started_at)
        changed = 0
        now = utc_now_naive()
        if not superseded:
            try:
                revisions = _persisted_official_cbr_revisions(db)
                revision = max(revisions, key=lambda value: (_official_cbr_revision_date(value), len(value))) if revisions else "fallback"
            except RuntimeError:
                # Preserve corrupt high-water evidence for investigation, not fallback.
                revision = str(status.revision or "unavailable") if status else "unavailable"
                allow_fallback = False
            if allow_fallback and not existing and revision == "fallback":
                for code in TRACKED:
                    db.add(ExchangeRate(currency_code=code, rate=FALLBACK[code],
                                        nominal=1.0, updated_at=now))
                changed = len(TRACKED)
            action = "seeded FALLBACK constants" if changed else "preserved stored rates"
            note = f"CBRF sync failed, {action}: {error[:200]}"
            _write_source_status(db, revision=revision, now=now, stale=True, note=note)
            db.add(SyncLog(source_code=CBRF_SOURCE_CODE, synced_at=now, status="ERROR",
                           revision="fallback", rows_affected=changed, note=note))
            db.commit()
    return {
        "status": "OK" if changed else "ERROR",
        "source": "fallback" if changed else "preserved_last_good" if existing else "unavailable",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "updated": changed, "preserved_rows": existing,
        "error": error, "superseded": superseded,
    }


def _record_cbrf_sync_fallback(error: str, rows_updated: int = 0) -> None:
    # Compatibility for callers recording an unsuccessful attempt; never seed here.
    _handle_cbr_failure(error, allow_fallback=False, attempt_started_at=utc_now_naive())


async def update_exchange_rates_from_cbrf(*, allow_fallback: bool = False) -> dict[str, object]:
    started = utc_now_naive()
    date_key = datetime.now().strftime("%Y-%m-%d")
    missing: list[str] = []
    fetched = False
    try:
        snapshot = await fetch_cbr_rates()
        date_key, rows = snapshot
        fetched = True
        _validate_cbr_rate_date(date_key)
        missing = _missing_tracked_currencies(rows)
        if missing:
            raise ValueError(f"CBRF XML incomplete, missing tracked currencies: {', '.join(missing)}")
        if not isinstance(snapshot, CBRRateSnapshot):
            raise RuntimeError("CBR update requires a byte-bound source snapshot")
        changed = _upsert_rates(rows, official_date_key=date_key, artifact_sha256=snapshot.sha256)
        return {"status": "OK", "source": "CBRF", "date": date_key,
                "updated": changed, "provenance_recorded": True}
    except Exception as exc:
        try:
            result = _handle_cbr_failure(
                str(exc), allow_fallback=allow_fallback and not fetched,
                attempt_started_at=started,
            )
        except Exception as provenance_exc:
            result = {"status": "ERROR", "source": "unavailable", "updated": 0,
                      "error": str(exc), "provenance_error": str(provenance_exc)}
        result["date"] = date_key
        if missing:
            result["missing_currencies"] = missing
            if not result.get("preserved_rows"):
                result["source"] = "incomplete"
        if isinstance(exc, CBRRateRollbackError):
            result["rollback_rejected"] = True
        return result


def get_rates_map() -> dict[str, float]:
    with SessionLocal() as db:
        rows = db.query(ExchangeRate).all()
        rates = {r.currency_code: float(r.rate) for r in rows}
    for code, value in FALLBACK.items():
        rates.setdefault(code, value)
    rates["RUB"] = 1.0
    return rates


def get_rates_payload() -> dict[str, object]:
    with SessionLocal() as db:
        rows = db.query(ExchangeRate).order_by(ExchangeRate.currency_code.asc()).all()
        items = [
            {
                "currency_code": r.currency_code,
                "rate": float(r.rate),
                "nominal": float(r.nominal),
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]
    if not items:
        items = [
            {"currency_code": c, "rate": v, "nominal": 1.0, "updated_at": None}
            for c, v in FALLBACK.items()
            if c in TRACKED
        ]
    map_data = {i["currency_code"]: i["rate"] for i in items}
    map_data["RUB"] = 1.0
    latest = max((i["updated_at"] or "" for i in items), default=None)
    return {
        "status": "OK",
        "base": "RUB",
        "updated_at": latest,
        "rates": items,
        "map": map_data,
    }
