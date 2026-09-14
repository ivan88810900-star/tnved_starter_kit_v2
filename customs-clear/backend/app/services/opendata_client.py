"""HTTP-клиент и парсеры метаданных официальных наборов открытых данных (ФТС, ФСА)."""

from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urljoin, urlparse

import httpx
from loguru import logger

from .source_http import CHUNK_SIZE, bounded_chunks, read_httpx_body, validate_body_headers

USER_AGENT = os.getenv(
    "OPENDATA_USER_AGENT",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
)
FSA_USER_AGENT = os.getenv("OPENDATA_FSA_USER_AGENT", USER_AGENT)
VERIFY_SSL = os.getenv("OPENDATA_VERIFY_SSL", "true").lower() not in ("0", "false", "no")
DEFAULT_TIMEOUT = float(os.getenv("OPENDATA_HTTP_TIMEOUT", "120") or "120")

FTS_BASE = "https://customs.gov.ru"
FSA_BASE = "https://fsa.gov.ru"

_TRUE_VALUES = {"1", "true", "yes", "on"}
_REGULATORY_ADAPTER_MODE = (
    (os.getenv("CUSTOMSCLEAR_REGULATORY_ADAPTER_MODE") or "").strip().lower()
    in _TRUE_VALUES
)

# Scheduled source adapters are an official-data trust boundary.  An operator
# may disable certificate validation for a one-off legacy/manual tool, but that
# escape hatch must never weaken an automatic regulatory update subprocess.
if _REGULATORY_ADAPTER_MODE:
    VERIFY_SSL = True

_OFFICIAL_HOSTS_BY_AGENCY: dict[str, frozenset[str]] = {
    "fts": frozenset({"customs.gov.ru"}),
    "fsa": frozenset({"fsa.gov.ru"}),
}
_FTS_DATASET_IDS = frozenset({"7730176610-trois", "7730176610-mask44"})
_FSA_DATASET_IDS = frozenset({"7736638268-rss", "7736638268-rds"})
_SEVEN_Z_SIGNATURE = b"7z\xbc\xaf'\x1c"

ContentKind = Literal["csv", "xml", "7z"]

_SNAPSHOT_ID_RE = re.compile(
    r"^data-(?P<data_date>\d{8})(?:T(?P<data_time>\d{4}(?:\d{2})?))?"
    r"(?:-structure-(?P<structure_date>\d{8})"
    r"(?:T(?P<structure_time>\d{4}(?:\d{2})?))?)?"
    r"\.(?:csv|7z)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class OpendataVersion:
    snapshot_id: str
    url: str
    structure_url: str = ""


@dataclass(frozen=True)
class OpendataMeta:
    identifier: str
    title: str
    modified: str
    data_format: str
    versions: list[OpendataVersion]
    provenance_verified: bool = False


def snapshot_revision_key(snapshot_id: str) -> tuple[str, str, str]:
    """Return a stable chronological key for an official snapshot filename.

    Both managed agencies encode the data publication date in ``data-*`` and
    may additionally encode a structure revision.  Treating the metadata list
    order as authoritative would let a reordered or rolled-back passport
    replace a newer live table.
    """
    value = str(snapshot_id or "").strip()
    match = _SNAPSHOT_ID_RE.fullmatch(value)
    if match is None:
        raise ValueError(f"opendata snapshot id has no sortable revision: {value!r}")

    def normalized_timestamp(date_value: str, time_value: str | None) -> str:
        raw_time = str(time_value or "").ljust(6, "0")
        try:
            datetime.strptime(f"{date_value}{raw_time}", "%Y%m%d%H%M%S")
        except ValueError as exc:
            raise ValueError(
                f"opendata snapshot id contains an invalid revision date: {value!r}"
            ) from exc
        return f"{date_value}{raw_time}"

    data_revision = normalized_timestamp(
        match.group("data_date"),
        match.group("data_time"),
    )
    structure_date = match.group("structure_date")
    structure_revision = (
        normalized_timestamp(structure_date, match.group("structure_time"))
        if structure_date
        else "00000000000000"
    )
    return data_revision, structure_revision, value.casefold()


def ordered_versions(
    versions: list[OpendataVersion],
    *,
    oldest_first: bool = False,
) -> list[OpendataVersion]:
    """Order official versions from their filename revision, not XML/CSV order."""
    return sorted(
        versions,
        key=lambda version: snapshot_revision_key(version.snapshot_id),
        reverse=not oldest_first,
    )


def require_no_snapshot_rollback(
    candidate_snapshot_id: str,
    persisted_snapshot_ids: list[str] | tuple[str, ...] | set[str],
    *,
    source_key: str,
) -> None:
    """Reject a candidate older than any successful persisted revision."""
    candidate_key = snapshot_revision_key(candidate_snapshot_id)
    prior_ids = {
        str(snapshot_id or "").strip()
        for snapshot_id in persisted_snapshot_ids
        if str(snapshot_id or "").strip()
    }
    if not prior_ids:
        return
    try:
        newest_persisted = max(prior_ids, key=snapshot_revision_key)
        newest_key = snapshot_revision_key(newest_persisted)
    except ValueError as exc:
        raise RuntimeError(
            f"{source_key}: cannot prove monotonic update because a persisted "
            "successful snapshot has no sortable revision"
        ) from exc
    if candidate_key < newest_key:
        raise RuntimeError(
            f"{source_key}: refusing snapshot rollback from "
            f"{newest_persisted!r} to {candidate_snapshot_id!r}"
        )


def _normalized_host(url: str) -> str:
    return (urlparse(str(url or "").strip()).hostname or "").casefold()


def _validate_official_url(
    url: str,
    *,
    agency: Literal["fts", "fsa"],
    dataset_id: str | None = None,
    expected_suffix: str | None = None,
    expected_path: str | None = None,
) -> str:
    """Return a verified official HTTPS URL or fail closed.

    Host comparisons are exact.  Suffix/parent-domain matching would turn a
    redirect to a public suffix (for example ``https://ru``) into an apparent
    official response.
    """
    value = str(url or "").strip()
    parsed = urlparse(value)
    allowed_hosts = _OFFICIAL_HOSTS_BY_AGENCY[agency]
    try:
        port = parsed.port
    except ValueError as exc:
        raise RuntimeError(f"untrusted {agency.upper()} opendata URL: {value!r}") from exc
    if (
        parsed.scheme.casefold() != "https"
        or port not in {None, 443}
        or _normalized_host(value) not in allowed_hosts
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.query
        or parsed.params
    ):
        raise RuntimeError(f"untrusted {agency.upper()} opendata URL: {value!r}")
    path = parsed.path or ""
    decoded_path = unquote(path)
    if (
        decoded_path != path
        or "\\" in path
        or any(part in {".", ".."} for part in path.split("/"))
    ):
        raise RuntimeError(f"unsafe {agency.upper()} opendata URL path: {value!r}")
    if expected_path and path != expected_path:
        raise RuntimeError(
            f"{agency.upper()} opendata URL has an unexpected path: {value!r}"
        )
    if dataset_id:
        managed_dataset_ids = _FTS_DATASET_IDS if agency == "fts" else _FSA_DATASET_IDS
        if dataset_id not in managed_dataset_ids:
            raise RuntimeError(
                f"unsupported {agency.upper()} opendata dataset: {dataset_id!r}"
            )
        allowed_prefixes = (
            (f"/{dataset_id}/", f"/storage/opendata/{dataset_id}/")
            if agency == "fts"
            else (f"/opendata/{dataset_id}/",)
        )
        if not path.startswith(allowed_prefixes):
            raise RuntimeError(
                f"{agency.upper()} opendata URL is outside dataset {dataset_id!r}: "
                f"{value!r}"
            )
    if expected_suffix and not path.casefold().endswith(expected_suffix.casefold()):
        raise RuntimeError(
            f"{agency.upper()} opendata URL has an unexpected artifact type: {value!r}"
        )
    return value


def _validate_download_body(
    data: bytes,
    *,
    expected_kind: ContentKind | None,
    content_type: str = "",
) -> None:
    if expected_kind is None:
        return
    if not data:
        raise RuntimeError(f"official opendata {expected_kind} response is empty")
    stripped = data[3:] if data.startswith(b"\xef\xbb\xbf") else data
    stripped = stripped.lstrip()
    lowered = stripped[:2_000].lower()
    media_type = str(content_type or "").split(";", 1)[0].strip().casefold()
    if media_type in {
        "text/html",
        "application/xhtml+xml",
        "application/json",
        "application/problem+json",
    }:
        raise RuntimeError(
            f"official opendata {expected_kind} endpoint returned {media_type}"
        )
    if expected_kind == "7z":
        if not data.startswith(_SEVEN_Z_SIGNATURE):
            raise RuntimeError("official opendata response is not a 7z archive")
        return
    if (
        lowered.startswith(b"<!doctype html")
        or lowered.startswith(b"<html")
        or lowered.startswith(b"{")
        or lowered.startswith(b"[")
    ):
        raise RuntimeError(
            f"official opendata {expected_kind} endpoint returned an error/document payload"
        )
    if expected_kind == "xml":
        if b"\x00" in data or b"<!doctype" in data.lower() or b"<!entity" in data.lower():
            raise RuntimeError("official opendata XML has unsafe encoding/declarations")
        if not stripped.startswith(b"<"):
            raise RuntimeError("official opendata response is not XML")
        try:
            ET.fromstring(data)
        except ET.ParseError as exc:
            raise RuntimeError("official opendata response contains invalid XML") from exc
    elif expected_kind == "csv":
        # Do not require a server-specific Content-Type: both agencies have
        # historically served CSV as text/plain or application/octet-stream.
        first_line = stripped.splitlines()[0] if stripped.splitlines() else b""
        if not any(delimiter in first_line for delimiter in (b",", b";", b"\t")):
            raise RuntimeError("official opendata response is not a recognizable CSV")


def _http_client(*, referer: str = "", for_fsa: bool = False) -> httpx.Client:
    ua = FSA_USER_AGENT if for_fsa else USER_AGENT
    headers = {"User-Agent": ua, "Accept": "*/*", "Accept-Encoding": "identity"}
    if referer:
        headers["Referer"] = referer
    return httpx.Client(
        timeout=DEFAULT_TIMEOUT,
        # Redirect targets are validated before the next request in
        # ``download_bytes``.  Letting httpx follow first would still send a
        # request to an attacker-controlled Location before provenance failed.
        follow_redirects=False,
        verify=VERIFY_SSL,
        headers=headers,
        trust_env=not _REGULATORY_ADAPTER_MODE,
    )


def _agency_for_url(url: str) -> Literal["fts", "fsa"]:
    host = _normalized_host(url)
    for agency, allowed_hosts in _OFFICIAL_HOSTS_BY_AGENCY.items():
        if host in allowed_hosts:
            return agency  # type: ignore[return-value]
    raise RuntimeError(f"untrusted official opendata host: {host or 'missing'}")


@contextmanager
def _download_response(
    url: str,
    *,
    referer: str = "",
    for_fsa: bool = False,
    expected_kind: ContentKind | None = None,
    dataset_id: str | None = None,
    expected_suffix: str | None = None,
    expected_path: str | None = None,
):
    """Download one verified official FTS/FSA artifact.

    Both the requested and final redirect URL must remain on the same exact
    pinned agency host over TLS.  Validation happens before a file is persisted.
    """
    url = str(url or "").strip()
    agency = _agency_for_url(url)
    pinned_artifact_path = expected_path or (urlparse(url).path if dataset_id else None)
    if for_fsa and agency != "fsa":
        raise RuntimeError(f"FSA download requested for a non-FSA URL: {url!r}")
    _validate_official_url(
        url,
        agency=agency,
        dataset_id=dataset_id,
        expected_suffix=expected_suffix,
        expected_path=pinned_artifact_path,
    )
    if referer:
        _validate_official_url(referer, agency=agency, dataset_id=dataset_id)
    with _http_client(referer=referer, for_fsa=for_fsa) as client:
        current_url = url
        for redirect_count in range(6):
            with client.stream("GET", current_url, headers={"Accept-Encoding": "identity"}) as resp:
                if resp.status_code in {301, 302, 303, 307, 308}:
                    location = str(resp.headers.get("location") or "").strip()
                    if not location:
                        raise RuntimeError("official opendata redirect is missing Location")
                    if redirect_count >= 5:
                        raise RuntimeError("official opendata redirect limit exceeded")
                    next_url = urljoin(current_url, location)
                    _validate_official_url(
                        next_url, agency=agency, dataset_id=dataset_id,
                        expected_suffix=expected_suffix, expected_path=pinned_artifact_path,
                    )
                    current_url = next_url
                    continue
                resp.raise_for_status()
                if resp.status_code != 200:
                    raise RuntimeError("official opendata requires a complete HTTP 200 snapshot")
                _validate_official_url(
                    str(resp.url), agency=agency, dataset_id=dataset_id,
                    expected_suffix=expected_suffix, expected_path=pinned_artifact_path,
                )
                allowed_types = {
                    "7z": {"application/x-7z-compressed", "application/octet-stream"},
                    "xml": {"application/xml", "text/xml"},
                    "csv": {"text/csv", "application/csv", "text/plain", "application/octet-stream", "application/vnd.ms-excel"},
                }
                media_type = resp.headers.get("content-type", "").split(";", 1)[0].strip().casefold()
                if expected_kind is not None and media_type not in allowed_types[expected_kind]:
                    raise RuntimeError(f"official opendata returned unexpected Content-Type: {media_type or 'missing'}")
                yield resp
                return
        else:  # pragma: no cover - loop exits by return/break or explicit limit
            raise RuntimeError("official opendata redirect limit exceeded")


def download_bytes(
    url: str, *, dest: Path | None = None, expected_kind: ContentKind | None = None,
    max_bytes: int | None = None, **kwargs: Any,
) -> bytes:
    path = urlparse(url).path
    limit = max_bytes or (8 * 1024**2 if "/meta." in path else 64 * 1024**2
                          if "/structure-" in path else 256 * 1024**2)
    with _download_response(url, expected_kind=expected_kind, **kwargs) as resp:
        data = read_httpx_body(resp, max_bytes=limit)
        _validate_download_body(data, expected_kind=expected_kind,
                                content_type=str(resp.headers.get("content-type") or ""))
    if dest is not None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        logger.info("opendata: saved {} ({} bytes)", dest, len(data))
    return data


@dataclass(frozen=True)
class DownloadedArtifact:
    path: Path
    sha256: str
    size_bytes: int


def download_file(
    url: str, *, dest: Path, expected_kind: ContentKind = "7z",
    max_bytes: int = 4 * 1024**3, **kwargs: Any,
) -> DownloadedArtifact:
    """Stream a large archive to a private file; promote only a complete body."""
    if expected_kind != "7z":
        raise ValueError("file streaming currently supports only 7z artifacts")
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial: Path | None = None
    digest = hashlib.sha256()
    size = 0
    prefix = bytearray()
    try:
        with _download_response(url, expected_kind=expected_kind, **kwargs) as resp:
            declared = validate_body_headers(resp.headers, max_bytes=max_bytes)
            with tempfile.NamedTemporaryFile(dir=dest.parent, prefix=".download-", delete=False) as stream:
                partial = Path(stream.name)
                for chunk in bounded_chunks(resp.iter_bytes(chunk_size=CHUNK_SIZE),
                                            max_bytes=max_bytes, declared=declared):
                    if len(prefix) < 2000:
                        prefix.extend(chunk[:2000 - len(prefix)])
                        _validate_download_body(bytes(prefix), expected_kind=expected_kind,
                                                content_type=resp.headers.get("content-type", ""))
                    digest.update(chunk)
                    size += len(chunk)
                    stream.write(chunk)
        partial.replace(dest)
        return DownloadedArtifact(dest, digest.hexdigest(), size)
    finally:
        if partial is not None:
            partial.unlink(missing_ok=True)


def parse_fts_meta_csv(text: str) -> OpendataMeta:
    """Паспорт набора ФТС: property,value (meta.csv)."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or [cell.strip().casefold() for cell in rows[0][:2]] != [
        "property",
        "value",
    ]:
        raise ValueError("FTS metadata CSV is missing the property,value header")
    props: dict[str, str] = {}
    versions: list[OpendataVersion] = []
    for row in rows:
        if len(row) < 2:
            continue
        key, val = row[0].strip(), row[1].strip()
        if key.startswith("data-"):
            versions.append(OpendataVersion(snapshot_id=key, url=val.strip()))
        else:
            props[key] = val
    return OpendataMeta(
        identifier=props.get("identifier", ""),
        title=props.get("title", ""),
        modified=props.get("modified", ""),
        data_format=props.get("format", ""),
        versions=versions,
    )


def fetch_fts_meta(dataset_id: str) -> OpendataMeta:
    if dataset_id not in _FTS_DATASET_IDS:
        raise RuntimeError(f"unsupported FTS opendata dataset: {dataset_id!r}")
    url = f"{FTS_BASE}/{dataset_id}/meta.csv"
    _validate_official_url(url, agency="fts", dataset_id=dataset_id, expected_suffix=".csv")
    text = download_bytes(
        url,
        expected_kind="csv",
        dataset_id=dataset_id,
        expected_suffix=".csv",
    ).decode("utf-8-sig", errors="replace")
    meta = parse_fts_meta_csv(text)
    if meta.identifier != dataset_id:
        raise RuntimeError(
            f"FTS metadata identifier mismatch: expected={dataset_id!r}, "
            f"observed={meta.identifier!r}"
        )
    if meta.data_format.strip().casefold() != "csv":
        raise RuntimeError(f"FTS {dataset_id} metadata has unexpected format: {meta.data_format!r}")
    if not meta.versions:
        raise RuntimeError(f"FTS {dataset_id} metadata contains no data versions")
    seen: set[str] = set()
    for version in meta.versions:
        if (
            not re.fullmatch(r"data-[A-Za-z0-9][A-Za-z0-9_-]*\.csv", version.snapshot_id)
            or version.snapshot_id in seen
        ):
            raise RuntimeError(
                f"FTS {dataset_id} metadata has an invalid/duplicate snapshot id: "
                f"{version.snapshot_id!r}"
            )
        seen.add(version.snapshot_id)
        try:
            snapshot_revision_key(version.snapshot_id)
        except ValueError as exc:
            raise RuntimeError(
                f"FTS {dataset_id} metadata has an unsortable snapshot id: "
                f"{version.snapshot_id!r}"
            ) from exc
        _validate_official_url(
            version.url,
            agency="fts",
            dataset_id=dataset_id,
            expected_suffix=".csv",
        )
        if Path(urlparse(version.url).path).name != version.snapshot_id:
            raise RuntimeError(
                f"FTS {dataset_id} snapshot id does not match its URL basename: "
                f"{version.snapshot_id!r}"
            )
    return replace(meta, provenance_verified=True)


def parse_fsa_meta_xml(text: str) -> OpendataMeta:
    root = ET.fromstring(text)
    if str(root.tag).rsplit("}", 1)[-1].casefold() != "meta":
        raise ValueError("FSA metadata XML root must be meta")
    versions: list[OpendataVersion] = []
    for dv in root.findall(".//dataversion"):
        src = (dv.findtext("source") or "").strip()
        struct = (dv.findtext("structure") or "").strip()
        if not src:
            continue
        name = src.rsplit("/", 1)[-1].split("?", 1)[0]
        versions.append(OpendataVersion(snapshot_id=name, url=src, structure_url=struct))
    return OpendataMeta(
        identifier=(root.findtext("identifier") or "").strip(),
        title=(root.findtext("title") or "").strip(),
        modified=(root.findtext("modified") or "").strip(),
        data_format=(root.findtext("format") or "").strip(),
        versions=versions,
    )


def fetch_fsa_meta(dataset_id: str) -> OpendataMeta:
    if dataset_id not in _FSA_DATASET_IDS:
        raise RuntimeError(f"unsupported FSA opendata dataset: {dataset_id!r}")
    url = f"{FSA_BASE}/opendata/{dataset_id}/meta.xml"
    referer = f"{FSA_BASE}/opendata/{dataset_id}/"
    _validate_official_url(url, agency="fsa", dataset_id=dataset_id, expected_suffix=".xml")
    text = download_bytes(
        url,
        referer=referer,
        for_fsa=True,
        expected_kind="xml",
        dataset_id=dataset_id,
        expected_suffix=".xml",
    ).decode("utf-8", errors="replace")
    meta = parse_fsa_meta_xml(text)
    if meta.identifier != dataset_id:
        raise RuntimeError(
            f"FSA metadata identifier mismatch: expected={dataset_id!r}, "
            f"observed={meta.identifier!r}"
        )
    if meta.data_format.strip().casefold() not in {"7z", "7zip", "7-zip"}:
        raise RuntimeError(f"FSA {dataset_id} metadata has unexpected format: {meta.data_format!r}")
    if not meta.versions:
        raise RuntimeError(f"FSA {dataset_id} metadata contains no data versions")
    seen: set[str] = set()
    for version in meta.versions:
        if (
            not re.fullmatch(r"data-[A-Za-z0-9][A-Za-z0-9_-]*\.7z", version.snapshot_id)
            or version.snapshot_id in seen
        ):
            raise RuntimeError(
                f"FSA {dataset_id} metadata has an invalid/duplicate snapshot id: "
                f"{version.snapshot_id!r}"
            )
        seen.add(version.snapshot_id)
        try:
            snapshot_revision_key(version.snapshot_id)
        except ValueError as exc:
            raise RuntimeError(
                f"FSA {dataset_id} metadata has an unsortable snapshot id: "
                f"{version.snapshot_id!r}"
            ) from exc
        _validate_official_url(
            version.url,
            agency="fsa",
            dataset_id=dataset_id,
            expected_suffix=".7z",
        )
        if Path(urlparse(version.url).path).name != version.snapshot_id:
            raise RuntimeError(
                f"FSA {dataset_id} snapshot id does not match its URL basename: "
                f"{version.snapshot_id!r}"
            )
        if not version.structure_url:
            raise RuntimeError(
                f"FSA {dataset_id} snapshot is missing its structure URL: "
                f"{version.snapshot_id!r}"
            )
        _validate_official_url(
            version.structure_url,
            agency="fsa",
            dataset_id=dataset_id,
            expected_suffix=".csv",
        )
        structure_name = Path(urlparse(version.structure_url).path).name
        if not re.fullmatch(
            r"(?:data-)?structure-[A-Za-z0-9][A-Za-z0-9_-]*\.csv",
            structure_name,
        ):
            raise RuntimeError(
                f"FSA {dataset_id} metadata has an invalid structure artifact: "
                f"{structure_name!r}"
            )
    return replace(meta, provenance_verified=True)


def latest_version(meta: OpendataMeta) -> OpendataVersion | None:
    if not meta.versions:
        return None
    return ordered_versions(meta.versions)[0]


def snapshot_date_from_id(snapshot_id: str) -> str:
    m = re.search(r"data-(\d{8})", snapshot_id)
    if m:
        d = m.group(1)
        return f"{d[6:8]}.{d[4:6]}.{d[0:4]}"
    m = re.search(r"(\d{8})", snapshot_id)
    if m:
        d = m.group(1)
        return f"{d[6:8]}.{d[4:6]}.{d[0:4]}"
    return ""


def backend_opendata_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "opendata"
