#!/usr/bin/env python3
"""Проверка доступности и изменений всех официальных источников.

Скрипт ничего не импортирует в БД и не меняет правила. Его JSON-отчёт пригоден
для хранения как CI artifact и ручного сравнения при изменении документа.
"""

from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urljoin, urlparse

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
from app.services.ett_artifacts import LocalArtifactStore  # noqa: E402
from app.services.regulatory_source_capture import capture_original, url_identity  # noqa: E402

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


def _secure_monitor_url(url: str) -> str:
    """Canonicalize legacy official HTTP citations to their TLS endpoint."""
    value = str(url or "").strip()
    parsed = urlparse(value)
    if parsed.scheme.casefold() == "http":
        return parsed._replace(scheme="https").geturl()
    return value


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
    for _raw_url in dict.fromkeys(_entry.monitor_urls):
        _url = _secure_monitor_url(_raw_url)
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
    _official_url = _secure_monitor_url(_entry.official_url)
    if _official_url and _official_url not in _registered_urls:
        _source_id = _entry.source_id if not _artifact_number else f"{_entry.source_id}__landing"
        SOURCES[_source_id] = _official_url
        SOURCE_MODES[_source_id] = (
            "availability" if _artifact_mode == "structured_freshness" else "legal_drift"
        )
        _registered_urls.add(_official_url)

_BLOCK_PAGE_MARKERS = (
    b"captcha",
    b"access denied",
    b"forbidden",
    b"cloudflare ray id",
    b"temporarily unavailable",
    "доступ ограничен".encode("utf-8"),
    "технические работы".encode("utf-8"),
)
_SOFT_NOT_FOUND_MARKERS = (
    b"<title>404",
    b"page not found",
    b"document not found",
    "страница не найдена".encode("utf-8"),
    "документ не найден".encode("utf-8"),
    "запрашиваемая страница не существует".encode("utf-8"),
)
_MAX_MONITOR_BYTES = 64 * 1024 * 1024
STATE_SCHEMA_VERSION = 4
_REVALIDATABLE_STATE_SCHEMA_VERSIONS = frozenset({2, 3})
_OFAC_DOWNLOAD_HOST = "www.treasury.gov"
_OFAC_GOVCLOUD_REDIRECT_HOST = (
    "wc2h-sls-prod-public-published.s3.us-gov-west-1.amazonaws.com"
)
_OFAC_GOVCLOUD_ARTIFACT_PATH_RE = re.compile(
    r"^/Published/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/"
    r"\d{4}-\d{2}-\d{2}/"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/SDN\.XML$"
)
_OFAC_GOVCLOUD_QUERY_KEYS = frozenset(
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
    try:
        original_port = original_url_parts.port
        final_port = final_url_parts.port
    except ValueError:
        return False
    if (
        original_url_parts.scheme.casefold() != "https"
        or final_url_parts.scheme.casefold() != "https"
        or original_port not in {None, 443}
        or final_port not in {None, 443}
        or original_url_parts.username is not None
        or original_url_parts.password is not None
        or final_url_parts.username is not None
        or final_url_parts.password is not None
    ):
        return False
    if original == _OFAC_DOWNLOAD_HOST:
        return (
            final_url_parts.scheme.lower() == "https"
            and final_port in {None, 443}
            and final in {_OFAC_DOWNLOAD_HOST, _OFAC_GOVCLOUD_REDIRECT_HOST}
        )
    if original == _EU_SANCTIONS_HOST:
        return (
            final_url_parts.scheme.lower() == "https"
            and final_url_parts.port in {None, 443}
            and final == _EU_SANCTIONS_HOST
        )
    # Every other legal source is pinned to its exact origin.  Parent/public
    # suffix and arbitrary child-host matching are not provenance checks.
    return original == final


def _same_request_url(left: str, right: str) -> bool:
    try:
        return httpx.URL(left) == httpx.URL(right)
    except (TypeError, ValueError):
        return False


def _is_ofac_canonical_url(url: str) -> bool:
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme.casefold() == "https"
        and (parsed.hostname or "").casefold() == _OFAC_DOWNLOAD_HOST
        and port in {None, 443}
        and parsed.username is None
        and parsed.password is None
        and parsed.path == "/ofac/downloads/sdn.xml"
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
    )


def _is_ofac_govcloud_artifact_url(url: str) -> bool:
    parsed = urlparse(url)
    try:
        port = parsed.port
        pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    except (ValueError, TypeError):
        return False
    if not (
        parsed.scheme.casefold() == "https"
        and (parsed.hostname or "").casefold() == _OFAC_GOVCLOUD_REDIRECT_HOST
        and port in {None, 443}
        and parsed.username is None
        and parsed.password is None
        and not parsed.params
        and not parsed.fragment
        and _OFAC_GOVCLOUD_ARTIFACT_PATH_RE.fullmatch(parsed.path)
        and len(pairs) == len(_OFAC_GOVCLOUD_QUERY_KEYS)
    ):
        return False
    query = dict(pairs)
    if set(query) != _OFAC_GOVCLOUD_QUERY_KEYS:
        return False
    credential_match = re.fullmatch(
        r"[A-Z0-9]{16,32}/(\d{8})/us-gov-west-1/s3/aws4_request",
        query["X-Amz-Credential"],
    )
    request_date = query["X-Amz-Date"]
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


def _redirect_target_allowed(original_url: str, target_url: str) -> bool:
    """Bind every request to the configured official artifact identity."""
    if not _redirect_host_allowed(original_url, target_url):
        return False
    if _is_ofac_canonical_url(original_url):
        return _is_ofac_canonical_url(target_url) or _is_ofac_govcloud_artifact_url(
            target_url
        )
    if _same_request_url(original_url, target_url):
        return True
    # The publication portal has two canonical spellings for the same immutable
    # publication number.  No other same-host path change is provenance-safe.
    requested_document_id = _pravo_document_id(original_url)
    original = urlparse(original_url)
    target = urlparse(target_url)
    return bool(
        requested_document_id
        and requested_document_id == _pravo_document_id(target_url)
        and not original.params
        and not original.query
        and not original.fragment
        and not target.params
        and not target.query
        and not target.fragment
    )


_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


def _get_with_verified_redirects(
    client: httpx.Client, url: str, *, headers: dict[str, str],
) -> httpx.Response:
    """Read bounded snapshots; close streams before caching or following redirects."""
    from app.services.source_http import read_httpx_body, validate_body_headers

    if not _redirect_target_allowed(url, url):
        raise RuntimeError(f"untrusted monitor source URL: {url!r}")
    current_url = url
    redirect_chain = [url]
    for redirect_count in range(6):
        if not _redirect_target_allowed(url, current_url):
            raise RuntimeError("unexpected_redirect_target")
        with client.stream("GET", current_url, headers={**headers, "Accept-Encoding": "identity"}) as response:
            if not _same_request_url(current_url, str(response.url)):
                raise RuntimeError("unexpected_response_url")
            if response.status_code not in _REDIRECT_STATUSES:
                if response.status_code == 304:
                    validate_body_headers(response.headers, max_bytes=64 * 1024**2)
                    body = b""
                else:
                    response.raise_for_status()
                    body = read_httpx_body(response, max_bytes=64 * 1024**2)
                return httpx.Response(
                    response.status_code, content=body,
                    headers=response.headers, request=response.request,
                    extensions={
                        "official_redirect_chain": tuple(redirect_chain),
                        "official_retrieved_at": datetime.now(timezone.utc),
                    },
                )
            location = str(response.headers.get("location") or "").strip()
            if not location:
                raise RuntimeError("official source redirect is missing Location")
            if redirect_count >= 5:
                raise RuntimeError("official source redirect limit exceeded")
            next_url = urljoin(current_url, location)
            if not _redirect_target_allowed(url, next_url) or _is_ofac_govcloud_artifact_url(current_url):
                raise RuntimeError("unexpected_redirect_target")
            current_url = next_url
            redirect_chain.append(next_url)
    raise RuntimeError("official source redirect limit exceeded")


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


class _LegalIdentityHTMLParser(HTMLParser):
    """Extract stable headings and official legal-artifact links only."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.headings: list[str] = []
        self.visible_text: list[str] = []
        self._heading_depth = 0
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.casefold()
        if lowered in {"script", "style", "noscript", "template"}:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if lowered in {"title", "h1", "h2", "h3"}:
            self._heading_depth += 1
        if lowered == "a":
            href = next(
                (str(value or "").strip() for key, value in attrs if key.casefold() == "href"),
                "",
            )
            if href:
                self.links.append(href)
        if lowered == "link":
            normalized_attrs = {
                key.casefold(): str(value or "").strip()
                for key, value in attrs
            }
            rel = {
                token.casefold()
                for token in normalized_attrs.get("rel", "").split()
            }
            href = normalized_attrs.get("href", "")
            if href and rel.intersection({"canonical", "alternate"}):
                self.links.append(href)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if lowered in {"script", "style", "noscript", "template"}:
            if self._ignored_depth:
                self._ignored_depth -= 1
            return
        if not self._ignored_depth and lowered in {"title", "h1", "h2", "h3"}:
            self._heading_depth = max(0, self._heading_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        normalized = " ".join(str(data or "").split())
        if not normalized:
            return
        self.visible_text.append(normalized)
        if self._heading_depth:
            self.headings.append(normalized)


_LEGAL_ARTIFACT_EXTENSIONS = (
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".xml",
    ".csv",
    ".json",
    ".zip",
    ".7z",
)
_LEGAL_REFERENCE_RE = re.compile(
    r"(?:решени(?:е|я)|постановлени(?:е|я)|приказ|распоряжени(?:е|я)|"
    r"тр\s+(?:тс|еаэс)|федеральн(?:ый|ого)\s+закон)"
    r"[^\n\r<>]{0,100}?(?:№|n)\s*[0-9][0-9a-zа-я./-]{0,30}",
    re.IGNORECASE,
)


def _pravo_document_id(url: str) -> str:
    parsed = urlparse(url)
    if (parsed.hostname or "").casefold() != "publication.pravo.gov.ru":
        return ""
    match = re.fullmatch(
        r"/(?:document/)?(?:view/)?([0-9]{16,})/?",
        parsed.path,
        flags=re.IGNORECASE,
    )
    return match.group(1) if match else ""


def _same_legal_resource_identity(requested_url: str, final_url: str) -> bool:
    if not _redirect_host_allowed(requested_url, final_url):
        return False
    requested = urlparse(requested_url)
    final = urlparse(final_url)
    requested_path = requested.path.rstrip("/") or "/"
    final_path = final.path.rstrip("/") or "/"
    if requested_path == final_path:
        return True
    requested_document_id = _pravo_document_id(requested_url)
    return bool(
        requested_document_id
        and requested_document_id == _pravo_document_id(final_url)
    )


def _canonical_legal_html_revision(
    url: str,
    final_url: str,
    body: bytes,
) -> tuple[bytes | None, str]:
    """Build a stable legal-identity payload, excluding template/nonces.

    A raw HTML checksum is not a legal revision signal.  Only an immutable
    publication identifier, same-origin legal attachments, or explicit legal
    act references can establish a reviewable identity.
    """
    if not _same_legal_resource_identity(url, final_url):
        return None, "legal_resource_identity_mismatch"
    parser = _LegalIdentityHTMLParser()
    try:
        parser.feed(body.decode("utf-8", errors="replace"))
        parser.close()
    except Exception:
        return None, "html_identity_parse_failed"

    signals: set[str] = set()
    parsed_source = urlparse(final_url)
    requested_document_id = _pravo_document_id(url)
    document_identity_confirmed = False

    for raw_link in parser.links:
        absolute = urljoin(url, raw_link)
        if not _redirect_host_allowed(url, absolute):
            continue
        parsed_link = urlparse(absolute)
        path = parsed_link.path or "/"
        lowered_path = path.casefold()
        is_legal_artifact = lowered_path.endswith(_LEGAL_ARTIFACT_EXTENSIONS)
        is_document_identity = bool(
            re.search(r"/(?:document|docs?|files?|upload)/", lowered_path)
            or re.search(r"/[0-9]{16,}/?$", lowered_path)
        )
        if not (is_legal_artifact or is_document_identity):
            continue
        # Query strings commonly carry expiring signatures/nonces.  The exact
        # same-origin path is the durable identity monitored for legal drift.
        canonical_link = parsed_link._replace(query="", fragment="").geturl()
        signals.add(f"official_link:{canonical_link}")
        if requested_document_id and _pravo_document_id(canonical_link) == requested_document_id:
            document_identity_confirmed = True

    visible = " ".join(parser.visible_text)
    for reference in _LEGAL_REFERENCE_RE.findall(visible):
        normalized = " ".join(reference.casefold().split())
        signals.add(f"legal_reference:{normalized}")

    if requested_document_id and requested_document_id in visible:
        signals.add(f"publication_document_id:{requested_document_id}")
        document_identity_confirmed = True
    if requested_document_id and not document_identity_confirmed:
        return None, "publication_document_identity_unconfirmed"

    identity_signals = sorted(signals)
    if not identity_signals:
        return None, "legal_revision_identity_unverified"
    payload = json.dumps(
        {
            "source_origin": (
                parsed_source.scheme.casefold(),
                (parsed_source.hostname or "").casefold(),
                parsed_source.path,
            ),
            "identity_signals": identity_signals,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return payload, "canonical_html_legal_identity"


def _revision_material(
    *,
    url: str,
    final_url: str,
    monitor_mode: str,
    content_type: str,
    body: bytes,
) -> tuple[bytes, bool, bool, str]:
    kind = _expected_content_kind(url)
    if kind != "html_or_document":
        return body, True, True, kind
    stripped = body.lstrip()
    if stripped.startswith(b"%PDF-"):
        return body, True, True, "pdf_magic"
    if monitor_mode == "availability":
        return body, False, False, "availability_only"
    canonical, identity_kind = _canonical_legal_html_revision(url, final_url, body)
    if canonical is None:
        return body, False, False, identity_kind
    # An HTML card can identify a source but cannot prove the current legal
    # revision.  Only direct mutable artifacts/structured feeds (or a future
    # explicitly validated host-specific manifest) satisfy revision coverage.
    return canonical, True, False, identity_kind


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
    if not _redirect_target_allowed(url, final_url):
        return False, "unexpected_redirect_target"
    if status_code != 200:
        return False, f"unexpected_http_status:{status_code}"
    if len(body) <= 100:
        return False, "content_too_small"
    if len(body) > _MAX_MONITOR_BYTES:
        return False, "content_too_large"
    lowered = body[:200_000].lower()
    if any(marker in lowered for marker in _BLOCK_PAGE_MARKERS):
        return False, "block_or_error_page_detected"
    if any(marker in lowered[:50_000] for marker in _SOFT_NOT_FOUND_MARKERS):
        return False, "soft_not_found_page_detected"
    kind = _expected_content_kind(url)
    from app.services.source_document import XML_MEDIA_TYPES, XLSX_MEDIA_TYPE, parse_source_xml, validate_xlsx_archive

    ctype = (content_type or "").split(";", 1)[0].strip().lower()
    stripped = body.lstrip()
    if kind == "pdf" and (not stripped.startswith(b"%PDF-") or ctype != "application/pdf"):
        return False, "invalid_pdf_content"
    if kind == "xml":
        if ctype not in XML_MEDIA_TYPES or not stripped.startswith(b"<"):
            return False, "invalid_xml_content"
        try:
            root = parse_source_xml(body)
        except (ET.ParseError, ValueError):
            return False, "invalid_xml_content"
        root_name = _xml_local_name(root.tag).casefold()
        if root_name in {"html", "error", "errors"}:
            return False, "invalid_xml_content"
        if not _official_xml_schema_valid(url, root):
            return False, "invalid_xml_content"
    if kind == "xlsx":
        if ctype != XLSX_MEDIA_TYPE:
            return False, "invalid_xlsx_content"
        try:
            validate_xlsx_archive(body)
        except Exception:
            return False, "invalid_xlsx_content"
    if kind == "csv" and (b"<html" in lowered[:1000] or b"<!doctype html" in lowered[:1000]):
        return False, "invalid_csv_content"
    if kind == "html_or_document" and not (
        "html" in ctype
        or stripped.startswith(b"<!DOCTYPE html")
        or stripped[:100].lower().startswith(b"<html")
        or stripped.startswith(b"%PDF-")
    ):
        return False, "invalid_html_or_document_content"
    return True, None


def _load_state(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {"version": STATE_SCHEMA_VERSION, "sources": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("sources"), dict):
            if data.get("version") == STATE_SCHEMA_VERSION:
                return data
            if data.get("version") in _REVALIDATABLE_STATE_SCHEMA_VERSIONS:
                previous_version = int(data["version"])
                # v4 adds exact redirect provenance and separates an HTML
                # card's identity from legal-revision coverage.  Direct
                # artifact digests can be revalidated, but legacy raw-HTML
                # digests are not compatible and must not remain approved.
                migrated_sources: dict[str, Any] = {}
                for source_id, raw in data["sources"].items():
                    if not isinstance(raw, dict):
                        continue
                    source_state = dict(raw)
                    source_state.pop("etag", None)
                    source_state.pop("last_modified", None)
                    source_url = str(source_state.get("url") or "")
                    if (
                        previous_version == 3
                        and _expected_content_kind(source_url) == "html_or_document"
                    ):
                        for key in (
                            "sha256",
                            "pending_sha256",
                            "pending_observed_at",
                            "pending_content_type",
                            "pending_content_length",
                            "pending_final_url",
                            "approved_at",
                            "approval_ref",
                        ):
                            source_state.pop(key, None)
                        source_state["artifact_identity_verified"] = False
                        source_state["revision_covered"] = False
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


def _selected_sources(source_ids: list[str] | tuple[str, ...] | None) -> dict[str, str]:
    if source_ids is None:
        return dict(SOURCES)
    if (
        not isinstance(source_ids, (list, tuple))
        or not source_ids
        or any(not isinstance(key, str) or not key or key not in SOURCES for key in source_ids)
    ):
        raise ValueError("source_ids must be a nonempty list of existing monitor source IDs")
    selected = set(source_ids)
    return {key: url for key, url in SOURCES.items() if key in selected}


def monitor_sources(
    timeout: float = 15.0,
    *,
    previous_state: dict[str, Any] | None = None,
    accept_changes: bool = False,
    approval_ref: str = "",
    original_store: LocalArtifactStore | None = None,
    source_ids: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    selected_sources = _selected_sources(source_ids)
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
    original_captures: dict[tuple[str, str, str], dict] = {}
    cached_bytes = 0
    with httpx.Client(
        follow_redirects=False,
        timeout=timeout,
        headers=headers,
        trust_env=False,
        verify=True,
    ) as client:
        for source_id, url in selected_sources.items():
            previous = previous_sources.get(source_id) or {}
            monitor_mode = SOURCE_MODES.get(source_id, "legal_drift")
            request_headers: dict[str, str] = {}
            # A pending legal digest must be observed again with a full body so
            # approval can prove that the reviewed bytes are still current.
            # Reusing the approved ETag here could yield 304 and accidentally
            # hide the pending review from the run report.
            has_pending_review = bool(previous.get("pending_sha256"))
            if previous.get("etag") and not has_pending_review and original_store is None:
                request_headers["If-None-Match"] = str(previous["etag"])
            if previous.get("last_modified") and not has_pending_review and original_store is None:
                request_headers["If-Modified-Since"] = str(previous["last_modified"])
            try:
                cache_key = (
                    url,
                    request_headers.get("If-None-Match", ""),
                    request_headers.get("If-Modified-Since", ""),
                )
                response = response_cache.get(cache_key)
                if response is None:
                    response = _get_with_verified_redirects(
                        client,
                        url,
                        headers=request_headers,
                    )
                    if cached_bytes + len(response.content) > 256 * 1024**2:
                        raise RuntimeError("official monitor response cache exceeds size limit")
                    cached_bytes += len(response.content)
                    response_cache[cache_key] = response
                if (
                    response.status_code == 304
                    and previous.get("sha256")
                    and bool(request_headers)
                    and _redirect_host_allowed(url, str(response.url))
                ):
                    inferred_revision_covered = bool(
                        previous.get("revision_covered") is True
                        or _expected_content_kind(url) != "html_or_document"
                    )
                    inferred_identity_verified = bool(
                        previous.get("artifact_identity_verified") is True
                        or inferred_revision_covered
                    )
                    pending_review = bool(
                        monitor_mode == "legal_drift"
                        and inferred_revision_covered
                        and previous.get("pending_sha256")
                    )
                    revision_gap = bool(
                        monitor_mode == "legal_drift" and not inferred_revision_covered
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
                        "artifact_identity_verified": inferred_identity_verified,
                        "revision_covered": inferred_revision_covered,
                        "revision_identity_kind": previous.get("revision_identity_kind"),
                        "revision_gap": revision_gap,
                        "revision_gap_reason": (
                            previous.get("revision_gap_reason")
                            or previous.get("revision_identity_kind")
                            if revision_gap
                            else None
                        ),
                        "effective_monitor_mode": (
                            "availability_only"
                            if revision_gap or monitor_mode == "availability"
                            else monitor_mode
                        ),
                        "approval_allowed": inferred_revision_covered,
                        "baseline_advanced": False,
                        "requires_approval": pending_review,
                        "approval_digest_mismatch": bool(
                            accept_changes and pending_review
                        ),
                    }
                    rows.append(row)
                    continue
                body = response.content
                content_type = str(response.headers.get("content-type") or "")
                final_url = str(response.url)
                ok, validation_error = _validate_observation(
                    url=url,
                    final_url=final_url,
                    status_code=response.status_code,
                    content_type=content_type,
                    body=body,
                )
                original_capture = None
                if original_store is not None and ok:
                    try:
                        original_capture = original_captures.get(cache_key)
                        if original_capture is None:
                            # Registry entries can share a request. Keep every
                            # source identity on one immutable observation.
                            capture_source_ids = {
                                key for key, target in SOURCES.items() if target == url
                            }
                            capture_source_ids.update(
                                entry.source_id
                                for entry in REGULATORY_SOURCE_REGISTRY
                                if entry.authority_level in SOURCE_OF_TRUTH_LEVELS
                                and url in {
                                    _secure_monitor_url(target)
                                    for target in (entry.official_url, *entry.monitor_urls)
                                    if target
                                }
                            )
                            original_capture = capture_original(
                                original_store, body=body, source_ids=sorted(capture_source_ids),
                                requested_url=url, final_url=final_url,
                                redirect_chain=list(response.extensions["official_redirect_chain"]),
                                retrieved_at=response.extensions["official_retrieved_at"],
                                status_code=response.status_code, content_type=content_type,
                            )
                            original_captures[cache_key] = original_capture
                    except Exception:
                        raise RuntimeError("original_capture_failed") from None
                (
                    revision_body,
                    artifact_identity_verified,
                    revision_covered,
                    revision_identity_kind,
                ) = _revision_material(
                    url=url,
                    final_url=final_url,
                    monitor_mode=monitor_mode,
                    content_type=content_type,
                    body=body,
                )
                digest = hashlib.sha256(revision_body).hexdigest()
                digest_is_new = ok and not bool(previous.get("sha256"))
                digest_changed = ok and bool(previous.get("sha256")) and previous.get("sha256") != digest
                revision_gap = bool(
                    ok and monitor_mode == "legal_drift" and not revision_covered
                )
                coverage_regressed = bool(
                    revision_gap and previous.get("revision_covered") is True
                )
                hard_identity_failure = bool(
                    revision_gap
                    and revision_identity_kind
                    in {
                        "html_identity_parse_failed",
                        "legal_resource_identity_mismatch",
                        "publication_document_identity_unconfirmed",
                    }
                )
                if coverage_regressed or hard_identity_failure:
                    ok = False
                    validation_error = (
                        "legal_revision_coverage_regressed"
                        if coverage_regressed
                        else revision_identity_kind
                    )
                is_new = bool(
                    digest_is_new
                    and monitor_mode != "availability"
                    and revision_covered
                )
                changed = bool(
                    digest_changed
                    and monitor_mode != "availability"
                    and revision_covered
                )
                identity_new = bool(digest_is_new and revision_gap)
                identity_changed = bool(digest_changed and revision_gap)
                requires_approval = bool(
                    monitor_mode == "legal_drift"
                    and revision_covered
                    and (is_new or changed)
                )
                pending_digest_matches = bool(
                    requires_approval
                    and previous.get("pending_sha256")
                    and previous.get("pending_sha256") == digest
                )
                approval_authorized = bool(
                    accept_changes
                    and requires_approval
                    and pending_digest_matches
                    and revision_covered
                )
                baseline_advanced = bool(
                    ok
                    and (
                        monitor_mode != "legal_drift"
                        or (revision_gap and not previous.get("pending_sha256"))
                        or not requires_approval
                        or approval_authorized
                    )
                    # A legacy/persisted pending digest is never silently
                    # discarded merely because the endpoint now exposes only
                    # an HTML identity.  It remains visible as a coverage gap
                    # until the state is deliberately migrated/rebuilt.
                    and not (revision_gap and previous.get("pending_sha256"))
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
                    "identity_changed": identity_changed,
                    "identity_new": identity_new,
                    "content_type": content_type,
                    "content_length": len(body),
                    "etag": response.headers.get("etag"),
                    "last_modified": response.headers.get("last-modified"),
                    "sha256": digest,
                    "previous_sha256": previous.get("sha256"),
                    "observed_sha256": digest,
                    "validation_error": validation_error,
                    "artifact_identity_verified": artifact_identity_verified,
                    "revision_covered": revision_covered,
                    "revision_identity_kind": revision_identity_kind,
                    "revision_gap": revision_gap,
                    "revision_gap_reason": revision_identity_kind if revision_gap else None,
                    "effective_monitor_mode": (
                        "availability_only"
                        if revision_gap or monitor_mode == "availability"
                        else monitor_mode
                    ),
                    "approval_allowed": revision_covered,
                    "requires_approval": requires_approval and not approval_authorized,
                    "approval_digest_mismatch": bool(
                        accept_changes and requires_approval and not pending_digest_matches
                    ),
                    "baseline_advanced": baseline_advanced,
                }
                if original_store is not None:
                    row["original_capture"] = original_capture
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
                            "artifact_identity_verified",
                            "revision_covered",
                            "revision_identity_kind",
                            "revision_gap_reason",
                        )
                    }
                    next_sources[source_id]["monitor_mode"] = monitor_mode
                    if original_capture is not None:
                        next_sources[source_id]["original_capture"] = original_capture
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
                    if original_capture is not None:
                        pending["pending_original_capture"] = original_capture
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
                        "artifact_identity_verified": False,
                        "revision_covered": False,
                        "revision_identity_kind": "fetch_failed",
                        "revision_gap": False,
                        "revision_gap_reason": None,
                        "effective_monitor_mode": monitor_mode,
                        "approval_allowed": False,
                        "validation_error": (
                            str(exc)
                            if str(exc) in {
                                "unexpected_redirect_host",
                                "unexpected_redirect_target",
                                "unexpected_response_url",
                                "official source redirect is missing Location",
                                "official source redirect limit exceeded",
                                "original_capture_failed",
                            }
                            else "source_fetch_failed"
                        ),
                        # A transport exception can contain signed redirect
                        # URLs. Optional capture reports never copy that text.
                        "error": type(exc).__name__ if original_store is not None else str(exc),
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
    revision_candidate_rows = [
        row
        for row in rows
        if row.get("monitor_mode") != "availability"
    ]
    revision_rows = [
        row for row in revision_candidate_rows if row.get("revision_covered") is True
    ]
    revision_gap_rows = [
        row
        for row in revision_candidate_rows
        if row.get("revision_covered") is not True and row.get("ok") is True
    ]
    revision_unavailable_rows = [
        row
        for row in revision_candidate_rows
        if row.get("ok") is not True
    ]
    explicit_availability_rows = [
        row for row in rows if row.get("monitor_mode") == "availability"
    ]
    unverified_revision_ids = [
        row["source_id"]
        for row in revision_gap_rows
    ]
    unapprovable_ids = [
        row["source_id"]
        for row in rows
        if row.get("requires_approval") and row.get("approval_allowed") is not True
    ]
    selected_coverage_complete = (
        bool(revision_candidate_rows)
        and not revision_gap_rows
        and len(revision_rows) == len(revision_candidate_rows)
    )
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "monitor_scope": "selected_sources" if source_ids is not None else "all_registered_monitor_sources",
        "selected_source_ids": list(selected_sources),
        "selected_source_count": len(selected_sources),
        "registered_monitor_source_count": len(SOURCES),
        "full_registry_checked": source_ids is None,
        "selected_revision_coverage_complete": selected_coverage_complete,
        # Availability and the operational gate refer to the explicit scope
        # above. Selecting sources never establishes full-registry coverage.
        "all_available": all(row.get("ok") is True for row in rows),
        "had_previous_baseline": has_previous_baseline,
        "changed_source_ids": changed_ids,
        "new_source_ids": new_ids,
        "pending_review_source_ids": pending_ids,
        "accepted_source_ids": accepted_ids,
        "unverified_revision_source_ids": unverified_revision_ids,
        "unapprovable_source_ids": unapprovable_ids,
        "monitored_url_count": len(rows),
        "revision_candidate_source_count": len(revision_candidate_rows),
        "revision_covered_source_count": len(revision_rows),
        "revision_gap_source_count": len(revision_gap_rows),
        "revision_gap_source_ids": [row["source_id"] for row in revision_gap_rows],
        "revision_unavailable_source_count": len(revision_unavailable_rows),
        "revision_unavailable_source_ids": [
            row["source_id"] for row in revision_unavailable_rows
        ],
        "explicit_availability_source_count": len(explicit_availability_rows),
        "availability_only_source_count": (
            len(explicit_availability_rows) + len(revision_gap_rows)
        ),
        "revision_coverage_complete": source_ids is None and selected_coverage_complete,
        # Availability-only sources are reported as coverage gaps but cannot
        # make the operational gate impossible.  The covered subset remains
        # fail-closed; ``all([])`` is intentional for an availability-only
        # monitor universe.
        "revision_monitor_gate_ok": all(
            row.get("ok") is True
            for row in revision_candidate_rows
            if row not in revision_gap_rows
        ),
        "review_required": bool(pending_ids),
        "sources": rows,
        "next_state": {
            "version": STATE_SCHEMA_VERSION,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "last_approval_ref": approval_ref.strip() if accept_changes else (previous_state or {}).get("last_approval_ref"),
            "sources": next_sources,
        },
    }
    if original_store is not None:
        report["original_capture_requested"] = True
        report["original_capture_complete"] = bool(rows) and all(
            row.get("ok") is True and row.get("original_capture") is not None
            for row in rows
        )
        report["original_capture_count"] = len(original_captures)
        # Keep signed transport URLs out of both reports and persisted state.
        # Exact URL hashes remain bound in the original receipt.
        def safe_url(value):
            try:
                return url_identity(value)["url"]
            except ValueError:
                return "redacted_invalid_source_url"

        def safe_urls(value):
            if isinstance(value, dict):
                return {
                    key: (
                        safe_url(item)
                        if key in {"url", "final_url", "pending_final_url"}
                        and isinstance(item, str)
                        else safe_urls(item)
                    )
                    for key, item in value.items()
                }
            if isinstance(value, list):
                return [safe_urls(item) for item in value]
            return value
        state = report.pop("next_state")
        report = safe_urls(report)
        # Unselected or failed source baselines are caller-owned historical
        # data and must remain unchanged, including their existing metadata.
        state["sources"] = {
            key: safe_urls(value)
            if key in selected_sources and value is not previous_sources.get(key)
            else value
            for key, value in state["sources"].items()
        }
        report["next_state"] = state
    return report


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
    parser.add_argument("--capture-originals", action="store_true", help="Retain original response bytes and receipts; no legal approval")
    parser.add_argument("--store-root", type=Path, help="Private local CAS directory; requires --capture-originals")
    parser.add_argument("--source-id", action="append", help="Select an exact monitor source ID; repeat for multiple sources")
    args = parser.parse_args()
    if args.accept_changes and not args.approval_ref.strip():
        parser.error("--approval-ref is required with --accept-changes")
    if args.capture_originals != (args.store_root is not None):
        parser.error("--capture-originals and --store-root must be supplied together")
    try:
        _selected_sources(args.source_id)
    except ValueError as exc:
        parser.error(str(exc))
    previous_state = _load_state(args.state)
    report = monitor_sources(
        args.timeout,
        previous_state=previous_state,
        accept_changes=args.accept_changes,
        approval_ref=args.approval_ref,
        original_store=LocalArtifactStore(args.store_root) if args.capture_originals else None,
        source_ids=args.source_id,
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
    gate_ok = (
        report["all_available"]
        and report["revision_monitor_gate_ok"]
        and not report["review_required"]
    )
    if args.capture_originals and not report["original_capture_complete"]:
        return 1
    return 0 if gate_ok or not args.strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
