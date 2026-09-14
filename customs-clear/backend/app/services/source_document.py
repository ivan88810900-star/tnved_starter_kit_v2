"""Decoded text with immutable downloaded bytes for source evidence."""

from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree as ET

XML_MEDIA_TYPES = frozenset({"text/xml", "application/xml"})
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class SourceDocument(str):
    def __new__(cls, raw: bytes, content_type: str = ""):
        if not isinstance(raw, bytes) or not raw:
            raise ValueError("source document requires nonempty downloaded bytes")
        encoding_match = re.search(br'<\?xml[^>]*encoding=[\'"]([A-Za-z0-9_-]+)[\'"]', raw[:256])
        charset = re.search(r"charset=([A-Za-z0-9_-]+)", content_type, re.I)
        encoding = (encoding_match.group(1).decode("ascii") if encoding_match else
                    charset.group(1) if charset else "utf-8-sig")
        if encoding.casefold() not in {"utf-8", "utf-8-sig", "windows-1251", "cp1251", "iso-8859-1"}:
            raise ValueError("source document has an unsupported text encoding")
        value = super().__new__(cls, raw.decode(encoding))
        value.raw = raw
        return value


def original_source_bytes(document: SourceDocument) -> bytes:
    if not isinstance(document, SourceDocument):
        raise ValueError("source evidence requires original downloaded bytes")
    return document.raw


def parse_source_xml(document: str | bytes) -> ET.Element:
    raw = document.raw if isinstance(document, SourceDocument) else document
    check = raw.encode("utf-8") if isinstance(raw, str) else raw
    if b"\x00" in check or b"<!doctype" in check.lower() or b"<!entity" in check.lower():
        raise ValueError("source XML must not contain DTD/entities or unsupported encoding")
    return ET.fromstring(raw)


def validate_xlsx_archive(blob: bytes) -> None:
    """Validate bounded OOXML members before any workbook library is invoked."""
    if not blob.startswith(b"PK\x03\x04") or len(blob) > 32 * 1024**2:
        raise ValueError("EU correlation artifact is not a bounded XLSX ZIP")
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        members = archive.infolist()
        if not members or len(members) > 512:
            raise ValueError("EU workbook has an invalid ZIP member count")
        names: set[str] = set()
        total = 0
        expected_roots = {
            "[Content_Types].xml": "{http://schemas.openxmlformats.org/package/2006/content-types}Types",
            "xl/workbook.xml": "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}workbook",
            "xl/_rels/workbook.xml.rels": "{http://schemas.openxmlformats.org/package/2006/relationships}Relationships",
            "_rels/.rels": "{http://schemas.openxmlformats.org/package/2006/relationships}Relationships",
        }
        for member in members:
            name = member.filename
            key = name.casefold()
            if (key in names or len(name) > 256 or "\\" in name or ":" in name
                    or any(part in {"", ".", ".."} for part in name.rstrip("/").split("/"))
                    or member.flag_bits & 1 or (member.external_attr >> 16) & 0o170000 == 0o120000
                    or member.file_size < 0 or member.file_size > 16 * 1024**2
                    or "vbaproject" in key or "/embeddings/" in key or "/externallinks/" in key):
                raise ValueError("EU workbook contains unsafe ZIP members")
            names.add(key)
            total += member.file_size
            if total > 128 * 1024**2:
                raise ValueError("EU workbook exceeds expanded size limit")
            if name.endswith((".xml", ".rels")):
                root = parse_source_xml(archive.read(member))
                if name in expected_roots and root.tag != expected_roots[name]:
                    raise ValueError("EU workbook has an unexpected OOXML namespace/root")
                if any(node.attrib.get("TargetMode", "").casefold() == "external" for node in root.iter()):
                    raise ValueError("EU workbook must not contain external relationships")
        if not {name.casefold() for name in expected_roots}.issubset(names):
            raise ValueError("EU workbook is missing required OOXML members")
