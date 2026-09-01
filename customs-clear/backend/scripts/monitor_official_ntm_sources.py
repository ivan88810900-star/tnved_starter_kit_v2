#!/usr/bin/env python3
"""Проверка доступности и изменений всех официальных источников.

Скрипт ничего не импортирует в БД и не меняет правила. Его JSON-отчёт пригоден
для хранения как CI artifact и ручного сравнения при изменении документа.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.official_ntm_contours import (  # noqa: E402
    DECISION_30_216_URL,
    DECISION_30_219_URL,
    DECISION_30_UNIFIED_LIST_URL,
    DECISION_299_LIST_URL,
    PP_2425_URL,
    TR_EAEU_036_URL,
    TR_EAEU_050_URL,
    TR_EAEU_051_URL,
    TR_EAEU_052_URL,
    TR_GENERAL_URL,
    TR_TS_007_URL,
    TR_TS_015_URL,
)
from app.services.official_export_control import FSTEC_IDENTIFICATION_URL, PP_1299_URL  # noqa: E402
from app.services.regulatory_source_registry import (  # noqa: E402
    REGULATORY_SOURCE_REGISTRY,
    SOURCE_OF_TRUTH_LEVELS,
)
from app.services.regulatory_source_updates import UPDATE_POLICIES  # noqa: E402

SOURCES = {
    "eec_decision30_unified_list": DECISION_30_UNIFIED_LIST_URL,
    "eec_decision30_section_2_16": DECISION_30_216_URL,
    "eec_decision30_section_2_19": DECISION_30_219_URL,
    "eec_decision299_sgr_list": DECISION_299_LIST_URL,
    "eec_decision317_veterinary_list": "https://eec.eaeunion.org/upload/medialibrary/89f/Pr.1-Edinyy-perechen-tov.pdf",
    "eec_decision318_phytosanitary_list": "https://eec.eaeunion.org/upload/medialibrary/60f/x9vhmm3gi76102uwhqlv7iffol64r6lo/Perechen-produktsii.pdf",
    "eec_decision157_phytosanitary_requirements": "https://eec.eaeunion.org/upload/medialibrary/e83/ne3jhyoymc2i57nx91wzn5fihnoi28ap/EKFT-v-red.-Resh.-_80.pdf",
    "rf_pp1299_dual_use": PP_1299_URL,
    "rf_pp1284_chemical_control": "https://publication.pravo.gov.ru/Document/View/0001202207190026",
    "rf_pp1285_nuclear_control": "https://publication.pravo.gov.ru/Document/View/0001202207190029",
    "rf_pp1286_nuclear_dual_use": "https://publication.pravo.gov.ru/Document/View/0001202207190018",
    "rf_pp1287_biological_control": "https://publication.pravo.gov.ru/Document/View/0001202207190030",
    "rf_pp1288_missile_control": "https://publication.pravo.gov.ru/Document/View/0001202207190036",
    "fstec_identification_expertise": FSTEC_IDENTIFICATION_URL,
    "rf_pp_2425": PP_2425_URL,
    "eec_tr_ts_007": TR_TS_007_URL,
    "eec_tr_ts_015": TR_TS_015_URL,
    "eec_tr_eaeu_036": TR_EAEU_036_URL,
    "eec_tr_eaeu_050": TR_EAEU_050_URL,
    "eec_tr_eaeu_051": TR_EAEU_051_URL,
    "eec_tr_eaeu_052": TR_EAEU_052_URL,
    "eec_technical_regulations": TR_GENERAL_URL,
    "eec_sanitary_measures": "https://eec.eaeunion.org/comission/department/depsanmer/regulation/sanitarnye-mery.php",
    "eec_veterinary_measures": "https://eec.eaeunion.org/comission/department/depsanmer/regulation/veterinarno-sanitarnye-mery.php",
    "eec_phytosanitary_measures": "https://eec.eaeunion.org/comission/department/depsanmer/regulation/karantinnye-fitosanitarnye-mery.php",
}
SOURCE_MODES: dict[str, str] = {source_id: "legal_drift" for source_id in SOURCES}

# Реестр является основным каталогом. Точные URL отдельных приложений к НПА
# выше сохраняются дополнительно, потому что одна карточка источника может
# содержать несколько юридически значимых документов.
_policy_by_source = {policy.source_id: policy for policy in UPDATE_POLICIES}
_registered_urls = set(SOURCES.values())


def _looks_machine_artifact_url(url: str) -> bool:
    lowered = (url or "").lower()
    return any(token in lowered for token in (".xml", ".csv", ".xlsx", ".json", "xml_daily"))


for _entry in REGULATORY_SOURCE_REGISTRY:
    if _entry.authority_level not in SOURCE_OF_TRUTH_LEVELS:
        continue
    _policy = _policy_by_source.get(_entry.source_id)
    _artifact_mode = (
        "structured_freshness"
        if _policy and _policy.strategy == "automatic_structured"
        else "legal_drift"
    )
    _artifact_number = 0
    for _url in dict.fromkeys(_entry.monitor_urls):
        if not _url or _url in _registered_urls:
            continue
        _artifact_number += 1
        _source_id = (
            _entry.source_id
            if _artifact_number == 1
            else f"{_entry.source_id}__artifact_{_artifact_number}"
        )
        SOURCES[_source_id] = _url
        SOURCE_MODES[_source_id] = (
            "availability"
            if _artifact_mode == "structured_freshness"
            and _url == _entry.official_url
            and not _looks_machine_artifact_url(_url)
            else _artifact_mode
        )
        _registered_urls.add(_url)
    # A portal/landing page proves availability only.  Its HTML checksum is not
    # a revision signal for a structured feed and must not create update noise.
    if _entry.official_url and _entry.official_url not in _registered_urls:
        _source_id = _entry.source_id if not _artifact_number else f"{_entry.source_id}__landing"
        SOURCES[_source_id] = _entry.official_url
        SOURCE_MODES[_source_id] = (
            "availability" if _artifact_mode == "structured_freshness" else "legal_drift"
        )
        _registered_urls.add(_entry.official_url)

_BLOCK_PAGE_MARKERS = (
    b"captcha",
    b"access denied",
    b"forbidden",
    b"cloudflare ray id",
    b"temporarily unavailable",
    "доступ ограничен".encode("utf-8"),
    "технические работы".encode("utf-8"),
)
_MAX_MONITOR_BYTES = 64 * 1024 * 1024
STATE_SCHEMA_VERSION = 3
_REVALIDATABLE_STATE_SCHEMA_VERSION = 2
_OFAC_DOWNLOAD_HOST = "www.treasury.gov"
_OFAC_GOVCLOUD_REDIRECT_HOST = (
    "wc2h-sls-prod-public-published.s3.us-gov-west-1.amazonaws.com"
)
_OFAC_XML_NAMESPACE = (
    "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/XML"
)
_EU_SANCTIONS_HOST = "webgate.ec.europa.eu"
_EU_SANCTIONS_XML_NAMESPACE = "http://eu.europa.ec/fpi/fsd/export"
_OFAC_MIN_ROWS = 1000
_EU_SANCTIONS_MIN_ROWS = 500


def _expected_content_kind(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.lower()
    filename_hint = f"{path}?{parsed.query.lower()}"
    if ".pdf" in filename_hint:
        return "pdf"
    if (
        ".xml" in filename_hint
        or "xml" in path.rsplit("/", 1)[-1].lower()
        or "xmlfullsanctionslist" in path
    ):
        return "xml"
    if ".xlsx" in filename_hint:
        return "xlsx"
    if ".csv" in filename_hint:
        return "csv"
    return "html_or_document"


def _redirect_host_allowed(original_url: str, final_url: str) -> bool:
    original_url_parts = urlparse(original_url)
    final_url_parts = urlparse(final_url)
    original = (original_url_parts.hostname or "").lower()
    final = (final_url_parts.hostname or "").lower()
    if not original or not final:
        return False
    if original_url_parts.scheme.lower() == "https" and final_url_parts.scheme.lower() != "https":
        return False
    if original == _OFAC_DOWNLOAD_HOST:
        return (
            final_url_parts.scheme.lower() == "https"
            and final_url_parts.port in {None, 443}
            and final in {_OFAC_DOWNLOAD_HOST, _OFAC_GOVCLOUD_REDIRECT_HOST}
        )
    if original == _EU_SANCTIONS_HOST:
        return (
            final_url_parts.scheme.lower() == "https"
            and final_url_parts.port in {None, 443}
            and final == _EU_SANCTIONS_HOST
        )
    return original == final or original.endswith("." + final) or final.endswith("." + original)


def _xml_namespace(tag: Any) -> str:
    value = str(tag or "")
    if value.startswith("{") and "}" in value:
        return value[1:].split("}", 1)[0]
    return ""


def _xml_local_name(tag: Any) -> str:
    return str(tag or "").rsplit("}", 1)[-1]


def _xml_child_text(node: ET.Element, name: str) -> str:
    return next(
        (
            str(child.text or "").strip()
            for child in list(node)
            if _xml_local_name(child.tag) == name
        ),
        "",
    )


def _source_date_valid(value: str, *, ofac_format: bool = False) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    try:
        if ofac_format:
            parsed = datetime.strptime(raw, "%m/%d/%Y")
        else:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    return 2000 <= parsed.year <= datetime.now(timezone.utc).year + 1


def _official_xml_schema_valid(url: str, root: ET.Element) -> bool:
    """Validate identity markers for the two enforcement-sensitive XML feeds."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold()
    path = parsed.path.casefold()
    if host == _OFAC_DOWNLOAD_HOST and path.endswith("/sdn.xml"):
        if _xml_local_name(root.tag) != "sdnList" or _xml_namespace(root.tag) != _OFAC_XML_NAMESPACE:
            return False
        publication = next(
            (node for node in list(root) if _xml_local_name(node.tag) == "publshInformation"),
            None,
        )
        if publication is None:
            return False
        metadata = {
            _xml_local_name(node.tag): str(node.text or "").strip()
            for node in list(publication)
        }
        entries = [node for node in root.iter() if _xml_local_name(node.tag) == "sdnEntry"]
        try:
            declared_count = int(metadata.get("Record_Count") or "")
        except ValueError:
            return False
        if not (
            _source_date_valid(metadata.get("Publish_Date") or "", ofac_format=True)
            and declared_count >= _OFAC_MIN_ROWS
            and declared_count == len(entries)
            and all(_xml_namespace(node.tag) == _OFAC_XML_NAMESPACE for node in entries)
        ):
            return False
        for entry in entries:
            if not _xml_child_text(entry, "uid") or not _xml_child_text(entry, "sdnType"):
                return False
            name = " ".join(
                value
                for value in (
                    _xml_child_text(entry, "firstName"),
                    _xml_child_text(entry, "lastName"),
                )
                if value
            ).strip()
            if not name:
                name = next(
                    (
                        str(node.text or "").strip()
                        for node in entry.iter()
                        if _xml_local_name(node.tag) == "sdnName"
                    ),
                    "",
                )
            if not name:
                return False
        return True
    if host == _EU_SANCTIONS_HOST and "xmlfullsanctionslist" in path:
        if _xml_local_name(root.tag) != "export" or _xml_namespace(root.tag) != _EU_SANCTIONS_XML_NAMESPACE:
            return False
        if not _source_date_valid(str(root.attrib.get("generationDate") or "")) or not str(
            root.attrib.get("globalFileId") or ""
        ).strip():
            return False
        entities = [node for node in root.iter() if _xml_local_name(node.tag) == "sanctionEntity"]
        if len(entities) < _EU_SANCTIONS_MIN_ROWS:
            return False
        for entity in entities:
            if _xml_namespace(entity.tag) != _EU_SANCTIONS_XML_NAMESPACE:
                return False
            if not str(entity.attrib.get("euReferenceNumber") or "").strip():
                return False
            aliases = [
                node
                for node in entity.iter()
                if _xml_local_name(node.tag) == "nameAlias"
                and _xml_namespace(node.tag) == _EU_SANCTIONS_XML_NAMESPACE
                and str(node.attrib.get("wholeName") or node.attrib.get("name") or "").strip()
            ]
            if not aliases:
                return False
    return True


def _validate_observation(
    *,
    url: str,
    final_url: str,
    status_code: int,
    content_type: str,
    body: bytes,
) -> tuple[bool, str | None]:
    if not _redirect_host_allowed(url, final_url):
        return False, "unexpected_redirect_host"
    if status_code != 200:
        return False, f"unexpected_http_status:{status_code}"
    if len(body) <= 100:
        return False, "content_too_small"
    if len(body) > _MAX_MONITOR_BYTES:
        return False, "content_too_large"
    lowered = body[:200_000].lower()
    if any(marker in lowered for marker in _BLOCK_PAGE_MARKERS):
        return False, "block_or_error_page_detected"
    kind = _expected_content_kind(url)
    ctype = (content_type or "").lower()
    stripped = body.lstrip()
    if kind == "pdf" and (not stripped.startswith(b"%PDF-") or "pdf" not in ctype):
        return False, "invalid_pdf_content"
    if kind == "xml":
        if "xml" not in ctype or not stripped.startswith(b"<"):
            return False, "invalid_xml_content"
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            return False, "invalid_xml_content"
        root_name = _xml_local_name(root.tag).casefold()
        if root_name in {"html", "error", "errors"}:
            return False, "invalid_xml_content"
        if not _official_xml_schema_valid(url, root):
            return False, "invalid_xml_content"
    if kind == "xlsx" and not body.startswith(b"PK"):
        return False, "invalid_xlsx_content"
    if kind == "csv" and (b"<html" in lowered[:1000] or b"<!doctype html" in lowered[:1000]):
        return False, "invalid_csv_content"
    return True, None


def _load_state(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {"version": STATE_SCHEMA_VERSION, "sources": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("sources"), dict):
            if data.get("version") == STATE_SCHEMA_VERSION:
                return data
            if data.get("version") == _REVALIDATABLE_STATE_SCHEMA_VERSION:
                # v3 tightened sanctions schema/cardinality/date validation.
                # Preserve approved digests but remove conditional validators so
                # the first v3 run must download and revalidate every body.
                migrated_sources: dict[str, Any] = {}
                for source_id, raw in data["sources"].items():
                    if not isinstance(raw, dict):
                        continue
                    source_state = dict(raw)
                    source_state.pop("etag", None)
                    source_state.pop("last_modified", None)
                    migrated_sources[str(source_id)] = source_state
                migrated = dict(data)
                migrated["version"] = STATE_SCHEMA_VERSION
                migrated["sources"] = migrated_sources
                return migrated
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read source monitor state: {exc}") from exc
    raise RuntimeError(
        f"unsupported source monitor state schema; expected version={STATE_SCHEMA_VERSION}"
    )


def monitor_sources(
    timeout: float = 15.0,
    *,
    previous_state: dict[str, Any] | None = None,
    accept_changes: bool = False,
    approval_ref: str = "",
) -> dict[str, Any]:
    if accept_changes and not approval_ref.strip():
        raise ValueError("approval_ref is required when accepting a source baseline")
    rows: list[dict[str, Any]] = []
    previous_sources = (previous_state or {}).get("sources") or {}
    has_previous_baseline = any(
        isinstance(value, dict) and bool(value.get("sha256"))
        for value in previous_sources.values()
    )
    headers = {"User-Agent": "Tariff-regulatory-source-monitor/2.0"}
    next_sources = dict(previous_sources)
    response_cache: dict[tuple[str, str, str], Any] = {}
    with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers, trust_env=False) as client:
        for source_id, url in SOURCES.items():
            previous = previous_sources.get(source_id) or {}
            monitor_mode = SOURCE_MODES.get(source_id, "legal_drift")
            request_headers: dict[str, str] = {}
            # A pending legal digest must be observed again with a full body so
            # approval can prove that the reviewed bytes are still current.
            # Reusing the approved ETag here could yield 304 and accidentally
            # hide the pending review from the run report.
            has_pending_review = bool(previous.get("pending_sha256"))
            if previous.get("etag") and not has_pending_review:
                request_headers["If-None-Match"] = str(previous["etag"])
            if previous.get("last_modified") and not has_pending_review:
                request_headers["If-Modified-Since"] = str(previous["last_modified"])
            try:
                cache_key = (
                    url,
                    request_headers.get("If-None-Match", ""),
                    request_headers.get("If-Modified-Since", ""),
                )
                response = response_cache.get(cache_key)
                if response is None:
                    response = client.get(url, headers=request_headers)
                    response_cache[cache_key] = response
                if (
                    response.status_code == 304
                    and previous.get("sha256")
                    and bool(request_headers)
                    and _redirect_host_allowed(url, str(response.url))
                ):
                    pending_review = bool(
                        monitor_mode == "legal_drift" and previous.get("pending_sha256")
                    )
                    row = {
                        "source_id": source_id,
                        "url": url,
                        "monitor_mode": monitor_mode,
                        "final_url": str(response.url),
                        "status_code": 304,
                        "ok": True,
                        "not_modified": True,
                        "changed": False,
                        "new_source": False,
                        "content_type": previous.get("content_type"),
                        "content_length": previous.get("content_length"),
                        "etag": response.headers.get("etag") or previous.get("etag"),
                        "last_modified": response.headers.get("last-modified") or previous.get("last_modified"),
                        "sha256": previous.get("sha256"),
                        "previous_sha256": previous.get("sha256"),
                        "observed_sha256": (
                            previous.get("pending_sha256")
                            if pending_review
                            else previous.get("sha256")
                        ),
                        "validation_error": None,
                        "baseline_advanced": False,
                        "requires_approval": pending_review,
                        "approval_digest_mismatch": bool(
                            accept_changes and pending_review
                        ),
                    }
                    rows.append(row)
                    continue
                body = response.content
                digest = hashlib.sha256(body).hexdigest()
                content_type = str(response.headers.get("content-type") or "")
                final_url = str(response.url)
                ok, validation_error = _validate_observation(
                    url=url,
                    final_url=final_url,
                    status_code=response.status_code,
                    content_type=content_type,
                    body=body,
                )
                digest_is_new = ok and not bool(previous.get("sha256"))
                digest_changed = ok and bool(previous.get("sha256")) and previous.get("sha256") != digest
                is_new = digest_is_new and monitor_mode != "availability"
                changed = digest_changed and monitor_mode != "availability"
                requires_approval = monitor_mode == "legal_drift" and (is_new or changed)
                pending_digest_matches = bool(
                    requires_approval
                    and previous.get("pending_sha256")
                    and previous.get("pending_sha256") == digest
                )
                approval_authorized = bool(
                    accept_changes and requires_approval and pending_digest_matches
                )
                baseline_advanced = bool(
                    ok
                    and (
                        monitor_mode != "legal_drift"
                        or not requires_approval
                        or approval_authorized
                    )
                )
                row = {
                    "source_id": source_id,
                    "url": url,
                    "monitor_mode": monitor_mode,
                    "final_url": final_url,
                    "status_code": response.status_code,
                    "ok": ok,
                    "not_modified": False,
                    "changed": changed,
                    "new_source": is_new,
                    "content_type": content_type,
                    "content_length": len(body),
                    "etag": response.headers.get("etag"),
                    "last_modified": response.headers.get("last-modified"),
                    "sha256": digest,
                    "previous_sha256": previous.get("sha256"),
                    "observed_sha256": digest,
                    "validation_error": validation_error,
                    "requires_approval": requires_approval and not approval_authorized,
                    "approval_digest_mismatch": bool(
                        accept_changes and requires_approval and not pending_digest_matches
                    ),
                    "baseline_advanced": baseline_advanced,
                }
                rows.append(row)
                if ok and baseline_advanced:
                    next_sources[source_id] = {
                        key: row.get(key)
                        for key in (
                            "url",
                            "final_url",
                            "content_type",
                            "content_length",
                            "etag",
                            "last_modified",
                            "sha256",
                        )
                    }
                    next_sources[source_id]["monitor_mode"] = monitor_mode
                    if monitor_mode == "legal_drift" and approval_authorized:
                        next_sources[source_id]["approved_at"] = datetime.now(timezone.utc).isoformat()
                        next_sources[source_id]["approval_ref"] = approval_ref.strip()
                elif ok and requires_approval:
                    pending = dict(previous)
                    pending.update(
                        {
                            "url": url,
                            "monitor_mode": monitor_mode,
                            "pending_sha256": digest,
                            "pending_observed_at": datetime.now(timezone.utc).isoformat(),
                            "pending_content_type": content_type,
                            "pending_content_length": len(body),
                            "pending_final_url": final_url,
                        }
                    )
                    next_sources[source_id] = pending
            except Exception as exc:
                rows.append(
                    {
                        "source_id": source_id,
                        "url": url,
                        "monitor_mode": monitor_mode,
                        "ok": False,
                        "changed": False,
                        "new_source": False,
                        "previous_sha256": previous.get("sha256"),
                        "observed_sha256": None,
                        "baseline_advanced": False,
                        "error": str(exc),
                    }
                )
    changed_ids = [row["source_id"] for row in rows if row.get("changed")]
    new_ids = [row["source_id"] for row in rows if row.get("new_source")]
    pending_ids = [row["source_id"] for row in rows if row.get("requires_approval")]
    accepted_ids = [
        row["source_id"]
        for row in rows
        if row.get("baseline_advanced") and row.get("monitor_mode") == "legal_drift" and (row.get("changed") or row.get("new_source"))
    ]
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "all_available": all(row.get("ok") is True for row in rows),
        "had_previous_baseline": has_previous_baseline,
        "changed_source_ids": changed_ids,
        "new_source_ids": new_ids,
        "pending_review_source_ids": pending_ids,
        "accepted_source_ids": accepted_ids,
        "review_required": bool(pending_ids),
        "sources": rows,
        "next_state": {
            "version": STATE_SCHEMA_VERSION,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "last_approval_ref": approval_ref.strip() if accept_changes else (previous_state or {}).get("last_approval_ref"),
            "sources": next_sources,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--state", type=Path, help="Persisted checksum/ETag baseline")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if a source is unavailable or legal drift awaits review",
    )
    parser.add_argument("--accept-changes", action="store_true", help="Advance legal baselines after explicit review")
    parser.add_argument("--approval-ref", default="", help="Required issue/PR/reference for --accept-changes")
    args = parser.parse_args()
    previous_state = _load_state(args.state)
    if args.accept_changes and not args.approval_ref.strip():
        parser.error("--approval-ref is required with --accept-changes")
    report = monitor_sources(
        args.timeout,
        previous_state=previous_state,
        accept_changes=args.accept_changes,
        approval_ref=args.approval_ref,
    )
    next_state = report.pop("next_state")
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        output_tmp = args.output.with_suffix(args.output.suffix + ".tmp")
        output_tmp.write_text(text + "\n", encoding="utf-8")
        output_tmp.replace(args.output)
    if args.state:
        args.state.parent.mkdir(parents=True, exist_ok=True)
        state_tmp = args.state.with_suffix(args.state.suffix + ".tmp")
        state_tmp.write_text(json.dumps(next_state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        state_tmp.replace(args.state)
    gate_ok = report["all_available"] and not report["review_required"]
    return 0 if gate_ok or not args.strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
