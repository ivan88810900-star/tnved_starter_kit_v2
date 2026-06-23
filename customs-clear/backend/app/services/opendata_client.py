"""HTTP-клиент и парсеры метаданных официальных наборов открытых данных (ФТС, ФСА)."""

from __future__ import annotations

import csv
import io
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
from loguru import logger

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


def _http_client(*, referer: str = "", for_fsa: bool = False) -> httpx.Client:
    ua = FSA_USER_AGENT if for_fsa else USER_AGENT
    headers = {"User-Agent": ua, "Accept": "*/*"}
    if referer:
        headers["Referer"] = referer
    return httpx.Client(
        timeout=DEFAULT_TIMEOUT,
        follow_redirects=True,
        verify=VERIFY_SSL,
        headers=headers,
    )


def download_bytes(url: str, *, referer: str = "", dest: Path | None = None, for_fsa: bool = False) -> bytes:
    """Скачать файл по официальной ссылке opendata (без обхода защиты)."""
    url = url.strip()
    with _http_client(referer=referer, for_fsa=for_fsa) as client:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.content
    if dest is not None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        logger.info("opendata: saved {} ({} bytes)", dest, len(data))
    return data


def parse_fts_meta_csv(text: str) -> OpendataMeta:
    """Паспорт набора ФТС: property,value (meta.csv)."""
    rows = list(csv.reader(io.StringIO(text)))
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
        data_format=props.get("format", "CSV"),
        versions=versions,
    )


def fetch_fts_meta(dataset_id: str) -> OpendataMeta:
    url = f"{FTS_BASE}/{dataset_id}/meta.csv"
    text = download_bytes(url).decode("utf-8-sig", errors="replace")
    meta = parse_fts_meta_csv(text)
    if not meta.identifier:
        meta = OpendataMeta(
            identifier=dataset_id,
            title=meta.title,
            modified=meta.modified,
            data_format=meta.data_format,
            versions=meta.versions,
        )
    return meta


def parse_fsa_meta_xml(text: str) -> OpendataMeta:
    root = ET.fromstring(text)
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
        data_format=(root.findtext("format") or "7Z").strip(),
        versions=versions,
    )


def fetch_fsa_meta(dataset_id: str) -> OpendataMeta:
    url = f"{FSA_BASE}/opendata/{dataset_id}/meta.xml"
    referer = f"{FSA_BASE}/opendata/{dataset_id}/"
    text = download_bytes(url, referer=referer, for_fsa=True).decode("utf-8", errors="replace")
    return parse_fsa_meta_xml(text)


def latest_version(meta: OpendataMeta) -> OpendataVersion | None:
    if not meta.versions:
        return None
    return meta.versions[0]


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
