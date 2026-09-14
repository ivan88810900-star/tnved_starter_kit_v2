#!/usr/bin/env python3
"""Validate OFAC SDN and explicitly promote reviewed snapshots.

The fail-safe default is validation-only.  Replacing ``ofac_sdn_list`` requires
the affirmative ``--apply`` flag.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urljoin, urlparse
from xml.etree import ElementTree as ET

import httpx
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.source_http import read_httpx_body
from app.services.source_document import SourceDocument, XML_MEDIA_TYPES, XLSX_MEDIA_TYPE, original_source_bytes, parse_source_xml
from app.db import SessionLocal
from app.models.core import OfacSdnList
from app.services.normative_store import (
    append_sync_log,
    stage_source_status,
    stage_sync_log,
    upsert_source_status,
)
from app.services.preview_cache_revision import bump_preview_cache_revision
from app.services.snapshot_safety import configured_minimum_rows, validate_full_snapshot

OFAC_DEFAULT_URL = "https://www.treasury.gov/ofac/downloads/sdn.xml"
OFAC_CURRENT_XML_NAMESPACE = (
    "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/XML"
)
OFAC_GOVCLOUD_REDIRECT_HOST = (
    "wc2h-sls-prod-public-published.s3.us-gov-west-1.amazonaws.com"
)
OFAC_GOVCLOUD_ARTIFACT_PATH_RE = re.compile(
    r"^/Published/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/"
    r"\d{4}-\d{2}-\d{2}/"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/SDN\.XML$"
)
OFAC_GOVCLOUD_QUERY_KEYS = frozenset(
    {
        "X-Amz-Algorithm",
        "X-Amz-Credential",
        "X-Amz-Date",
        "X-Amz-Expires",
        "X-Amz-Security-Token",
        "X-Amz-Signature",
        "X-Amz-SignedHeaders",
        "response-content-disposition",
        "response-content-type",
    }
)
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
UA = "customs-clear-ofac-sync/1.0"


def _local_name(tag: Any) -> str:
    t = str(tag or "")
    return t.split("}", 1)[-1] if "}" in t else t


def _namespace(tag: Any) -> str:
    value = str(tag or "")
    if value.startswith("{") and "}" in value:
        return value[1:].split("}", 1)[0]
    return ""


def _safe_https_parts(url: str):
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.casefold() != "https"
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.hostname
        or bool(parsed.fragment)
    ):
        return None
    return parsed


def _is_ofac_canonical_url(url: str) -> bool:
    parsed = _safe_https_parts(url)
    return bool(
        parsed is not None
        and (parsed.hostname or "").casefold() == "www.treasury.gov"
        and parsed.path == "/ofac/downloads/sdn.xml"
        and not parsed.params
        and not parsed.query
    )


def _is_ofac_govcloud_artifact_url(url: str) -> bool:
    parsed = _safe_https_parts(url)
    if (
        parsed is None
        or (parsed.hostname or "").casefold() != OFAC_GOVCLOUD_REDIRECT_HOST
        or parsed.params
        or OFAC_GOVCLOUD_ARTIFACT_PATH_RE.fullmatch(parsed.path) is None
    ):
        return False
    try:
        pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return False
    if len(pairs) != len(OFAC_GOVCLOUD_QUERY_KEYS):
        return False
    query = dict(pairs)
    if set(query) != OFAC_GOVCLOUD_QUERY_KEYS:
        return False
    credential = query["X-Amz-Credential"]
    request_date = query["X-Amz-Date"]
    credential_match = re.fullmatch(
        r"[A-Z0-9]{16,32}/(\d{8})/us-gov-west-1/s3/aws4_request",
        credential,
    )
    return bool(
        query["X-Amz-Algorithm"] == "AWS4-HMAC-SHA256"
        and credential_match is not None
        and re.fullmatch(r"\d{8}T\d{6}Z", request_date)
        and credential_match.group(1) == request_date[:8]
        and query["X-Amz-Expires"].isdigit()
        and 1 <= int(query["X-Amz-Expires"]) <= 86400
        and bool(query["X-Amz-Security-Token"])
        and re.fullmatch(r"[0-9a-fA-F]{64}", query["X-Amz-Signature"])
        and query["X-Amz-SignedHeaders"] == "host"
        and query["response-content-disposition"] == 'attachment; filename="sdn.xml"'
        and query["response-content-type"] == "text/xml"
    )


def _same_request_url(left: str, right: str) -> bool:
    try:
        return httpx.URL(left) == httpx.URL(right)
    except (TypeError, ValueError):
        return False


def _redirect_url_allowed(original_url: str, target_url: str) -> bool:
    """Allow only the canonical feed or its exact signed GovCloud artifact."""
    if _is_ofac_canonical_url(original_url):
        return _is_ofac_canonical_url(target_url) or _is_ofac_govcloud_artifact_url(
            target_url
        )
    # Operator-provided, non-scheduled sources may be fetched, but they cannot
    # redirect.  Their initial URL must still use verified HTTPS transport.
    return _safe_https_parts(original_url) is not None and _same_request_url(
        original_url, target_url
    )


def _get_with_verified_redirects(
    client: httpx.Client,
    url: str,
    *,
    headers: dict[str, str],
) -> httpx.Response:
    """Validate every URL before a network request is issued."""
    if not _redirect_url_allowed(url, url):
        raise RuntimeError(f"untrusted OFAC source URL: {url!r}")
    current_url = url
    for redirect_count in range(2):
        if not _redirect_url_allowed(url, current_url):
            raise RuntimeError(f"unexpected OFAC redirect target: {current_url}")
        response = client.send(client.build_request("GET", current_url,
            headers={**headers, "Accept-Encoding": "identity"}), stream=True, follow_redirects=False)
        handed_off = False
        try:
            if not _same_request_url(current_url, str(response.url)):
                raise RuntimeError(f"unexpected OFAC response URL: {response.url}")
            if response.status_code not in _REDIRECT_STATUSES:
                handed_off = True
                return response
            location = str(response.headers.get("location") or "").strip()
            if not location:
                raise RuntimeError("OFAC redirect is missing Location")
            next_url = urljoin(current_url, location)
            # The only approved official transition is canonical Treasury -> the
            # exact signed SDN.XML object.  Reject before contacting the target.
            if (
                redirect_count > 0
                or not _is_ofac_canonical_url(current_url)
                or not _is_ofac_govcloud_artifact_url(next_url)
            ):
                raise RuntimeError(f"unexpected OFAC redirect target: {next_url}")
            current_url = next_url
        finally:
            if not handed_off:
                response.close()
    raise RuntimeError("OFAC redirect limit exceeded")  # pragma: no cover


def _child_text(node: ET.Element, name: str) -> str:
    for ch in list(node):
        if _local_name(ch.tag) == name:
            return _clean(ch.text)
    return ""


def _desc_text(node: ET.Element, name: str) -> str:
    for ch in node.iter():
        if _local_name(ch.tag) == name:
            return _clean(ch.text)
    return ""


def _http_get(url: str, *, timeout_sec: float = 45.0, retries: int = 4) -> tuple[str, str]:
    err: Exception | None = None
    with httpx.Client(timeout=timeout_sec, follow_redirects=False, trust_env=False, verify=True) as client:
        for attempt in range(1, max(1, retries) + 1):
            try:
                with closing(_get_with_verified_redirects(client, url, headers={"User-Agent": UA})) as response:
                    response.raise_for_status()
                    if response.status_code != 200:
                        raise RuntimeError("OFAC requires a complete HTTP 200 snapshot")
                    ctype = str(response.headers.get("content-type") or "").lower()
                    if ctype.split(";", 1)[0].strip() not in XML_MEDIA_TYPES:
                        raise ValueError("OFAC source returned non-XML Content-Type")
                    raw = read_httpx_body(response, max_bytes=128 * 1024**2)
                    document = SourceDocument(raw, ctype)
                    parse_source_xml(document)
                    return document, ctype
            except Exception as exc:
                err = exc
                if attempt >= max(1, retries):
                    break
            time.sleep(min(1.2 * attempt, 8.0))
    raise RuntimeError(f"OFAC download failed: {err!r}")


def _clean(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip())


def _guess_type(raw: str) -> str:
    t = _clean(raw).lower()
    if "individual" in t:
        return "individual"
    if "entity" in t or "organization" in t:
        return "entity"
    if "vessel" in t:
        return "vessel"
    if "aircraft" in t:
        return "aircraft"
    return "other"


def _extract_rows_from_xml(
    xml_text: str,
    *,
    require_official_schema: bool = False,
) -> list[dict[str, str]]:
    root = parse_source_xml(xml_text)
    if require_official_schema:
        if _local_name(root.tag) != "sdnList":
            raise ValueError("official OFAC XML root must be sdnList")
        if _namespace(root.tag) != OFAC_CURRENT_XML_NAMESPACE:
            raise ValueError("official OFAC XML namespace is not the current SLS namespace")
        publish_nodes = [
            node for node in list(root) if _local_name(node.tag) == "publshInformation"
        ]
        if len(publish_nodes) != 1:
            raise ValueError("official OFAC XML is missing publshInformation")
        publish = publish_nodes[0]
        record_count_raw = _child_text(publish, "Record_Count")
        publish_date = _child_text(publish, "Publish_Date")
        if not record_count_raw or not publish_date:
            raise ValueError("official OFAC XML is missing publication metadata")
        try:
            declared_count = int(record_count_raw)
        except ValueError as exc:
            raise ValueError("official OFAC XML Record_Count is invalid") from exc
        try:
            parsed_publish_date = datetime.strptime(publish_date, "%m/%d/%Y")
        except ValueError as exc:
            raise ValueError("official OFAC XML Publish_Date is invalid") from exc
        if not 2000 <= parsed_publish_date.year <= datetime.now().year + 1:
            raise ValueError("official OFAC XML Publish_Date is implausible")

    rows: list[dict[str, str]] = []
    entries = [e for e in root.iter() if _local_name(e.tag) == "sdnEntry"]
    if require_official_schema:
        if not entries or declared_count != len(entries):
            raise ValueError("official OFAC XML record count does not match sdnEntry rows")
        expected_tag = f"{{{OFAC_CURRENT_XML_NAMESPACE}}}sdnEntry"
        if any(str(entry.tag) != expected_tag for entry in entries):
            raise ValueError("official OFAC XML contains an unexpected sdnEntry namespace")
    for entry in entries:
        if require_official_schema and (
            not _child_text(entry, "uid") or not _child_text(entry, "sdnType")
        ):
            raise ValueError("official OFAC sdnEntry is missing uid or sdnType")
        first = _child_text(entry, "firstName")
        last = _child_text(entry, "lastName")
        whole = _clean(f"{first} {last}")
        if not whole:
            whole = _child_text(entry, "sdnName") or _desc_text(entry, "sdnName")
        if not whole:
            if require_official_schema:
                raise ValueError("official OFAC sdnEntry is missing a name")
            continue

        sdn_type = _guess_type(_child_text(entry, "sdnType") or _desc_text(entry, "sdnType"))
        countries: set[str] = set()
        for c in entry.iter():
            if _local_name(c.tag) != "country":
                continue
            cc = _clean(c.text).upper()[:8]
            if cc:
                countries.add(cc)
        origin_country = sorted(countries)[0] if countries else ""

        aliases: list[str] = []
        for aka in entry.iter():
            if _local_name(aka.tag) != "aka":
                continue
            af = _desc_text(aka, "firstName")
            al = _desc_text(aka, "lastName")
            nm = _clean(f"{af} {al}")
            if nm and nm not in aliases:
                aliases.append(nm)
        aliases_json = json.dumps(aliases, ensure_ascii=False)

        rows.append(
            {
                "name": whole[:1024],
                "type": sdn_type[:64],
                "origin_country": origin_country[:8],
                "aliases": aliases_json[:12000],
            }
        )
    return rows


def _extract_rows_from_csv(csv_text: str) -> list[dict[str, str]]:
    sample = csv_text[:4096]
    try:
        import csv

        dialect = csv.Sniffer().sniff(sample, delimiters=";,")
    except Exception:
        import csv

        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(csv_text), dialect=dialect)
    rows: list[dict[str, str]] = []
    for r in reader:
        low = {str(k or "").strip().lower(): str(v or "").strip() for k, v in r.items() if k}
        nm = _clean(low.get("name") or low.get("sdn_name") or low.get("full_name") or "")
        if not nm:
            continue
        typ = _guess_type(low.get("type") or low.get("sdn_type") or "other")
        country = _clean(low.get("country") or low.get("origin_country") or "").upper()[:8]
        aliases = _clean(low.get("aliases") or low.get("aka") or "")
        aliases_json = json.dumps([x.strip() for x in re.split(r"[;|,]+", aliases) if x.strip()], ensure_ascii=False)
        rows.append(
            {
                "name": nm[:1024],
                "type": typ[:64],
                "origin_country": country[:8],
                "aliases": aliases_json[:12000],
            }
        )
    return rows


def _is_sqlite(db) -> bool:
    return db.bind.dialect.name == "sqlite"


def _snapshot_candidates(
    rows: list[dict[str, str]],
) -> dict[tuple[str, str, str], dict[str, str]]:
    candidates: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in rows:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        payload = {
            "name": name,
            "type": str(row.get("type") or "other"),
            "origin_country": str(row.get("origin_country") or ""),
            "aliases": str(row.get("aliases") or ""),
        }
        candidates[(payload["name"], payload["type"], payload["origin_country"])] = payload
    return candidates


def _validate_rows(
    rows: list[dict[str, str]],
    *,
    minimum_rows: int = 1,
) -> int:
    """Validate a complete candidate snapshot without changing enforcement data."""
    candidates = _snapshot_candidates(rows)
    with SessionLocal() as db:
        existing_count = db.query(OfacSdnList).count()
        validate_full_snapshot(
            source_id="ofac_sdn_list",
            candidate_count=len(candidates),
            existing_count=existing_count,
            minimum_rows=minimum_rows,
        )
    return len(candidates)


def _replace_rows(
    rows: list[dict[str, str]],
    *,
    source_url: str,
    revision: str,
    note: str,
    minimum_rows: int = 1,
) -> int:
    """Atomically replace the full snapshot and its success provenance."""
    candidates = _snapshot_candidates(rows)
    if not candidates:
        return 0
    if not revision.strip():
        raise ValueError("OFAC replacement requires a non-empty evidence revision")
    n = 0
    with SessionLocal() as db:
        try:
            existing_count = db.query(OfacSdnList).count()
            validate_full_snapshot(
                source_id="ofac_sdn_list",
                candidate_count=len(candidates),
                existing_count=existing_count,
                minimum_rows=minimum_rows,
            )
            db.query(OfacSdnList).delete(synchronize_session=False)
            for payload in candidates.values():
                if _is_sqlite(db):
                    stmt = sqlite_insert(OfacSdnList.__table__).values(**payload)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["name", "type", "origin_country"],
                        set_={"aliases": stmt.excluded.aliases},
                    )
                    db.execute(stmt)
                else:
                    db.add(OfacSdnList(**payload))
                n += 1
            stage_source_status(
                db,
                source_code="OFAC_SDN",
                source_name="OFAC SDN official bulk feed",
                source_url=source_url,
                revision=revision,
                is_stale=False,
                note=note[:2000],
            )
            stage_sync_log(
                db,
                source_code="OFAC_SDN",
                status="OK",
                revision=revision,
                rows_affected=n,
                note=note[:2000],
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description="Синхронизация OFAC SDN -> ofac_sdn_list")
    ap.add_argument("--url", type=str, default=OFAC_DEFAULT_URL, help="URL XML/CSV OFAC SDN")
    ap.add_argument(
        "--official-only",
        action="store_true",
        help="Ignore an operator-provided URL and use the pinned OFAC bulk feed",
    )
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Explicitly replace the blocking table with this reviewed full snapshot",
    )
    mode.add_argument(
        "--validate-only",
        action="store_true",
        help="Fetch, parse and validate without changing the blocking table (default)",
    )
    ap.add_argument("--timeout", type=float, default=45.0)
    ap.add_argument("--retries", type=int, default=4)
    ap.add_argument("--strict", action="store_true", help="Fail on an empty parsed official snapshot")
    ap.add_argument("--json", action="store_true", help="Emit the adapter result contract")
    args = ap.parse_args()

    apply_changes = bool(args.apply)
    source_url = OFAC_DEFAULT_URL if args.official_only else args.url
    official_source = bool(args.official_only and source_url == OFAC_DEFAULT_URL)
    operation = "apply" if apply_changes else "validation_only"
    source_code = "OFAC_SDN" if apply_changes else "OFAC_SDN_VALIDATION"
    try:
        text, ctype = _http_get(
            source_url,
            timeout_sec=float(args.timeout),
            retries=max(1, int(args.retries)),
        )
    except Exception as exc:
        note = f"download_failed={exc!r}; url={source_url}"
        upsert_source_status(
            source_code=source_code,
            source_name="OFAC SDN official bulk feed",
            source_url=source_url,
            revision="unavailable",
            is_stale=True,
            note=note[:2000],
        )
        append_sync_log(source_code, "ERROR", "unavailable", 0, note[:2000])
        print(f"ofac_sdn_list download failed: {exc}")
        if args.json:
            print("REGULATORY_SYNC_RESULT=" + json.dumps({
                "status": "error",
                "source_ids": ["ofac_sdn_list"],
                "official_source": official_source,
                "operation": operation,
                "enforcement_changed": False,
                "rows_applied": 0,
                "error": str(exc),
            }, ensure_ascii=False, separators=(",", ":")))
        return 1
    try:
        stripped = text.lstrip()
        original_source_bytes(text)
        if args.official_only:
            if ctype.split(";", 1)[0].strip().casefold() not in XML_MEDIA_TYPES or not stripped.startswith("<"):
                raise ValueError("official OFAC bulk feed is not XML")
            rows = _extract_rows_from_xml(text, require_official_schema=True)
        elif "csv" in ctype or (stripped and not stripped.startswith("<")):
            rows = _extract_rows_from_csv(text)
        else:
            rows = _extract_rows_from_xml(text)
    except Exception as exc:
        note = f"parse_failed={exc!r}; url={source_url}; content_type={ctype}"
        upsert_source_status(
            source_code=source_code,
            source_name="OFAC SDN official bulk feed",
            source_url=source_url,
            revision="unavailable",
            is_stale=True,
            note=note[:2000],
        )
        append_sync_log(source_code, "ERROR", "unavailable", 0, note[:2000])
        print(f"ofac_sdn_list parse failed: {exc}")
        if args.json:
            print("REGULATORY_SYNC_RESULT=" + json.dumps({
                "status": "error",
                "source_ids": ["ofac_sdn_list"],
                "official_source": official_source,
                "operation": operation,
                "enforcement_changed": False,
                "rows_applied": 0,
                "error": str(exc),
            }, ensure_ascii=False, separators=(",", ":")))
        return 1
    minimum_rows = configured_minimum_rows("ofac_sdn_list", 1000)
    digest = hashlib.sha256(original_source_bytes(text)).hexdigest()
    revision = f"sha256:{digest}"
    try:
        if not apply_changes:
            validated = _validate_rows(rows, minimum_rows=minimum_rows)
            saved = 0
        else:
            validated = len(_snapshot_candidates(rows))
            success_note = (
                f"url={source_url}; content_type={ctype}; parsed={len(rows)}; "
                f"validated={validated}; saved={validated}; operation={operation}; sha256={digest}"
            )
            saved = _replace_rows(
                rows,
                minimum_rows=minimum_rows,
                source_url=source_url,
                revision=revision,
                note=success_note,
            )
            if saved <= 0:
                raise RuntimeError("official OFAC snapshot contained no valid rows")
    except Exception as exc:
        note = f"snapshot_rejected={exc!s}; url={source_url}; parsed={len(rows)}"
        upsert_source_status(
            source_code=source_code,
            source_name="OFAC SDN official bulk feed",
            source_url=source_url,
            revision="unavailable",
            is_stale=True,
            note=note[:2000],
        )
        append_sync_log(source_code, "ERROR", "unavailable", 0, note[:2000])
        print(f"ofac_sdn_list snapshot rejected: {exc}")
        if args.json:
            print("REGULATORY_SYNC_RESULT=" + json.dumps({
                "status": "error",
                "source_ids": ["ofac_sdn_list"],
                "official_source": official_source,
                "operation": operation,
                "enforcement_changed": False,
                "rows_validated": 0,
                "rows_applied": 0,
                "error": str(exc),
            }, ensure_ascii=False, separators=(",", ":")))
        return 1

    sync_ok = validated > 0 if not apply_changes else saved > 0
    note = (
        f"url={source_url}; content_type={ctype}; parsed={len(rows)}; "
        f"validated={validated}; saved={saved}; operation={operation}; sha256={digest}"
    )
    if not apply_changes:
        upsert_source_status(
            source_code=source_code,
            source_name="OFAC SDN official bulk feed",
            source_url=source_url,
            revision=revision,
            is_stale=not sync_ok,
            note=note[:2000],
        )
        append_sync_log(
            source_code,
            "OK" if sync_ok else "ERROR",
            revision,
            0,
            note[:2000],
        )
    if saved and apply_changes:
        try:
            bump_preview_cache_revision("sync_ofac_sanctions")
        except Exception:
            pass
    print(f"ofac_sdn_list parsed={len(rows)} saved={saved}")
    if args.json:
        payload = {
            "status": "ok" if sync_ok else "error",
            "source_ids": ["ofac_sdn_list"],
            "official_source": official_source,
            "operation": operation,
            "enforcement_changed": bool(saved) and apply_changes,
            "snapshot_kind": "full",
            "rows_parsed": len(rows),
            "rows_validated": validated,
            "rows_applied": saved,
            "sha256": digest,
        }
        print("REGULATORY_SYNC_RESULT=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0 if sync_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
