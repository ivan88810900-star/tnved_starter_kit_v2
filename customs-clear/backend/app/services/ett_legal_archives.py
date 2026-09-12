"""Bounded inspection of observed official ZIP attachments; no path extraction.

Original archives and selected document members are evidence candidates only.
Nothing here executes documents, supplies approved legal text, creates a normal
PDF acquisition receipt or changes rates. Nested DOCX checks establish only a
bounded OOXML container, never legal identity or document authenticity.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import io
import re
import stat
import struct
import time
import unicodedata
import zipfile
import zlib
from xml.etree import ElementTree as ET
from urllib.parse import urlsplit

from app.services.ett_artifacts import ArtifactIntegrityError, LocalArtifactStore
from app.services.ett_transport import (
    MAX_REDIRECTS, OfficialTransportError, _validate_document,
    sanitize_transport_diagnostics, validate_official_url,
)
from app.services.source_document import parse_source_xml

MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 256
MAX_EXPANDED_BYTES = 128 * 1024 * 1024
MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200
MAX_INSPECTION_SECONDS = 60
MAX_CONTENT_TYPES_BYTES = 1024 * 1024
ARCHIVE_SOURCES = (
    ("collegium_66_zip", "https://docs.eaeunion.org/upload/iblock/30f/1ejbrxx8u338qjf970tal0715afq9li8/err_28042022_66_att.zip"),
    ("council_76_zip", "https://docs.eaeunion.org/upload/iblock/f8b/4n8tf0bp9hkvrg1mwvd3o992yckghgn3/err_28042022_76_att.zip"),
)
# Literal hrefs verified in the retained primary HTML of this runner capture.
# This attests locator provenance only, never act identity or adoption dates.
ARCHIVE_LOCATOR_PROVENANCE = {
    "collegium_66_zip": {
        "page_url": "https://docs.eaeunion.org/documents/399/6620/",
        "page_sha256": "e63bdf745f82084b6775d9be006bfa895a790f29ba216d4e063d48bdca42af2f",
        "observed_href": "/upload/iblock/30f/1ejbrxx8u338qjf970tal0715afq9li8/err_28042022_66_att.zip",
        "capture_run_id": "34241158561",
    },
    "council_76_zip": {
        "page_url": "https://docs.eaeunion.org/documents/401/6619/",
        "page_sha256": "cc29e2ccd4eda95aa365d50cb86e3e2949735532fd4f2edb76f44d764c2ec087",
        "observed_href": "/upload/iblock/f8b/4n8tf0bp9hkvrg1mwvd3o992yckghgn3/err_28042022_76_att.zip",
        "capture_run_id": "34241158561",
    },
}
ARCHIVE_MEDIA_TYPES = frozenset({"application/zip", "application/x-zip-compressed", "application/octet-stream"})


class LegalArchiveError(ValueError):
    """A static failure code; source member names/bodies are never interpolated."""


@dataclass(frozen=True)
class ArchiveMember:
    path: str
    raw_filename_hex: str
    filename_encoding: str
    utf8_filename_declared: bool
    unverified_display_path: str | None
    unverified_display_encoding: str | None
    size_bytes: int
    compressed_size_bytes: int
    sha256: str | None
    kind: str
    selected: bool


@dataclass(frozen=True)
class ArchiveInspection:
    archive_sha256: str
    size_bytes: int
    expanded_size_bytes: int
    members: tuple[ArchiveMember, ...]
    # Kept separate from the public inventory; never serialized into a report.
    _selected_payloads: tuple[tuple[str, bytes], ...] = field(repr=False)


@dataclass(frozen=True)
class ArchiveResponse:
    """Bounded HTTP bytes awaiting archive validation, never OfficialResponse."""
    url: str
    requested_url: str
    content: bytes = field(repr=False)
    media_type: str
    retrieved_at: datetime
    redirect_chain: tuple[str, ...]
    http_content_type: str


def _path(value: str, *, directory: bool) -> str:
    if type(value) is not str or not 1 <= len(value) <= 1024:
        raise LegalArchiveError("unsafe_member_path")
    name = value[:-1] if directory and value.endswith("/") else value
    parts = name.split("/")
    # Compatibility characters occur in ordinary legacy ZIP filenames (and in
    # Russian №). Check both spellings; use normalization-aware collision keys
    # below, without changing identity or silently guessing a legacy code page.
    if (len(parts) > 16
            or any(not part or part in {".", ".."} or part[-1:] in {" ", "."}
                   or any(char in part for char in "/\\:")
                   or any(unicodedata.category(char).startswith("C") for char in part)
                   or re.fullmatch(r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part, re.I)
                   for original in parts for part in (original, unicodedata.normalize("NFKC", original)))):
        raise LegalArchiveError("unsafe_member_path")
    return name


def _path_key(name: str) -> str:
    return unicodedata.normalize("NFKC", unicodedata.normalize("NFKC", name).casefold())


def _raw_filename(raw: bytes, member: zipfile.ZipInfo) -> bytes:
    name_size = struct.unpack_from("<H", raw, member.header_offset + 26)[0]
    return raw[member.header_offset + 30:member.header_offset + 30 + name_size]


def _extra_fields(extra: bytes) -> None:
    cursor = 0
    while cursor < len(extra):
        if cursor + 4 > len(extra):
            raise LegalArchiveError("invalid_zip_extra_fields")
        field_id, size = struct.unpack_from("<HH", extra, cursor)
        cursor += 4
        if field_id == 1 or cursor + size > len(extra):
            raise LegalArchiveError("unsupported_zip64_or_extra_fields")
        cursor += size


def _preflight_zip(raw: bytes) -> tuple[int, int]:
    # Bound central-directory records before ZipFile eagerly allocates ZipInfo
    # objects. The EOCD count alone is untrusted and is not Python's loop bound.
    end_offset = raw.rfind(b"PK\x05\x06", max(0, len(raw) - 65557))
    if end_offset < 0 or end_offset + 22 > len(raw):
        raise LegalArchiveError("invalid_zip_end_record")
    _, disk, central_disk, disk_count, count, central_size, central_offset, comment_size = struct.unpack_from("<4s4H2IH", raw, end_offset)
    if (disk or central_disk or count != disk_count or not 1 <= count <= MAX_ARCHIVE_MEMBERS
            or end_offset + 22 + comment_size != len(raw) or central_offset + central_size != end_offset):
        raise LegalArchiveError("unsupported_zip_layout")
    cursor = central_offset
    actual_count = 0
    while cursor < end_offset:
        actual_count += 1
        if (actual_count > MAX_ARCHIVE_MEMBERS or cursor + 46 > end_offset
                or raw[cursor:cursor + 4] != b"PK\x01\x02"):
            raise LegalArchiveError("invalid_or_excessive_central_records")
        name_size, extra_size, comment_size = struct.unpack_from("<3H", raw, cursor + 28)
        cursor += 46 + name_size + extra_size + comment_size
    if cursor != end_offset or actual_count != count:
        raise LegalArchiveError("zip_member_count_mismatch")
    return central_offset, count


def _zip_layout(raw: bytes, archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    central_offset, count = _preflight_zip(raw)
    members = archive.infolist()
    if len(members) != count:
        raise LegalArchiveError("zip_member_count_mismatch")
    names: dict[str, tuple[str, bool]] = {}
    implicit_directories: dict[str, str] = {}
    intervals = []
    expanded = 0
    for member in members:
        directory = member.is_dir()
        name = _path(member.orig_filename, directory=directory)
        key = _path_key(name)
        if key in names:
            raise LegalArchiveError("duplicate_or_alias_member_path")
        names[key] = (name, directory)
        parts = name.split("/")
        for length in range(1, len(parts) + int(directory)):
            prefix = "/".join(parts[:length])
            previous = implicit_directories.setdefault(_path_key(prefix), prefix)
            if previous != prefix:
                raise LegalArchiveError("directory_case_alias")
        mode = stat.S_IFMT(member.external_attr >> 16)
        if (member.flag_bits & ~(0x800 | 8 | 6) or member.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                or mode not in {0, stat.S_IFDIR if directory else stat.S_IFREG}
                or bool(member.external_attr & 0x10) and not directory):
            raise LegalArchiveError("encrypted_or_nonregular_member")
        if (not 0 <= member.file_size <= MAX_MEMBER_BYTES or not 0 <= member.compress_size <= len(raw)
                or directory and member.file_size or member.volume != 0
                or member.file_size > max(1, member.compress_size) * MAX_COMPRESSION_RATIO):
            raise LegalArchiveError("member_size_or_compression_limit")
        expanded += member.file_size
        if expanded > MAX_EXPANDED_BYTES:
            raise LegalArchiveError("archive_expansion_limit")
        _extra_fields(member.extra)
        offset = member.header_offset
        if not 0 <= offset <= central_offset - 30:
            raise LegalArchiveError("invalid_local_header_offset")
        header = struct.unpack_from("<4s5H3I2H", raw, offset)
        signature, _, flags, method, _, _, crc, compressed, uncompressed, name_size, extra_size = header
        if signature != b"PK\x03\x04" or flags != member.flag_bits or method != member.compress_type:
            raise LegalArchiveError("local_central_header_mismatch")
        filename = raw[offset + 30:offset + 30 + name_size].decode("utf-8" if flags & 0x800 else "cp437")
        if filename != member.orig_filename:
            raise LegalArchiveError("local_central_filename_mismatch")
        data_start = offset + 30 + name_size + extra_size
        data_end = data_start + member.compress_size
        if data_start > central_offset or data_end > central_offset:
            raise LegalArchiveError("member_data_outside_archive")
        _extra_fields(raw[offset + 30 + name_size:data_start])
        if flags & 8:
            descriptor_size = 16 if raw[data_end:data_end + 4] == b"PK\x07\x08" else 12
            descriptor_start = data_end + (4 if descriptor_size == 16 else 0)
            if data_end + descriptor_size > central_offset:
                raise LegalArchiveError("invalid_data_descriptor")
            if struct.unpack_from("<III", raw, descriptor_start) != (member.CRC, member.compress_size, member.file_size):
                raise LegalArchiveError("invalid_data_descriptor")
            data_end += descriptor_size
        elif (crc, compressed, uncompressed) != (member.CRC, member.compress_size, member.file_size):
            raise LegalArchiveError("local_central_size_mismatch")
        intervals.append((offset, data_end))
    for key, (_, directory) in names.items():
        parts = key.split("/")
        for length in range(1, len(parts)):
            parent = names.get("/".join(parts[:length]))
            if parent is not None and not parent[1]:
                raise LegalArchiveError("file_directory_conflict")
    intervals.sort()
    if intervals[0][0] != 0 or intervals[-1][1] != central_offset or any(left[1] != right[0] for left, right in zip(intervals, intervals[1:])):
        raise LegalArchiveError("overlapping_or_unaccounted_zip_records")
    return members


def _read_member(raw: bytes, member: zipfile.ZipInfo, budget: list[int], deadline: float) -> bytes:
    # ZipExtFile truncates output at attacker-declared file_size and then checks
    # CRC over that prefix. Decode the entire bounded compressed region ourselves.
    chunks = []
    size = 0
    crc = 0
    name_size, extra_size = struct.unpack_from("<HH", raw, member.header_offset + 26)
    start = member.header_offset + 30 + name_size + extra_size
    end = start + member.compress_size
    decoder = zlib.decompressobj(-15) if member.compress_type == zipfile.ZIP_DEFLATED else None
    if decoder is None and member.compress_size != member.file_size:
        raise LegalArchiveError("stored_member_size_mismatch")
    for offset in range(start, end, 65536):
        pending = raw[offset:min(offset + 65536, end)]
        while pending:
            if time.monotonic() > deadline:
                raise LegalArchiveError("archive_inspection_time_limit")
            chunk = decoder.decompress(pending, 65536) if decoder else pending
            pending = decoder.unconsumed_tail if decoder else b""
            size += len(chunk)
            budget[0] += len(chunk)
            if size > MAX_MEMBER_BYTES or budget[0] > MAX_EXPANDED_BYTES:
                raise LegalArchiveError("archive_expansion_limit")
            if size > member.file_size:
                raise LegalArchiveError("member_actual_size_mismatch")
            crc = zlib.crc32(chunk, crc)
            chunks.append(chunk)
            if decoder and decoder.unused_data:
                raise LegalArchiveError("trailing_compressed_member_data")
    if decoder and not decoder.eof:
        raise LegalArchiveError("incomplete_compressed_member")
    if size != member.file_size or crc != member.CRC:
        raise LegalArchiveError("member_actual_size_mismatch")
    return b"".join(chunks)


def _docx_container(payload: bytes, budget: list[int], deadline: float) -> bool:
    _preflight_zip(payload)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = _zip_layout(payload, archive)
        names = {member.filename for member in members}
        required = {"[Content_Types].xml", "_rels/.rels", "word/document.xml"}
        complete = required.issubset(names)
        content_types = None
        main_relationship = False
        for member in members:
            lowered = member.filename.casefold()
            if any(part in lowered for part in ("vbaproject", "/embeddings/", "/externallinks/")):
                raise LegalArchiveError("unsupported_active_container")
            raw = _read_member(payload, member, budget, deadline)
            if member.filename in required or lowered.endswith(".rels"):
                if len(raw) > MAX_CONTENT_TYPES_BYTES:
                    raise LegalArchiveError("docx_xml_inspection_limit")
                root = parse_source_xml(raw)
                if member.filename == "[Content_Types].xml":
                    content_types = root
                elif lowered.endswith(".rels"):
                    if root.tag != "{http://schemas.openxmlformats.org/package/2006/relationships}Relationships":
                        raise LegalArchiveError("invalid_docx_relationships")
                    if any(node.attrib.get("TargetMode", "").casefold() == "external" for node in root.iter()):
                        raise LegalArchiveError("unsupported_external_relationship")
                    if member.filename == "_rels/.rels":
                        main_relationship = any(
                            node.tag == "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"
                            and node.attrib.get("Type") == "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
                            and node.attrib.get("Target") in {"word/document.xml", "/word/document.xml"}
                            for node in root
                        )
                elif root.tag != "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}document":
                    raise LegalArchiveError("invalid_docx_document_root")
        namespace = "{http://schemas.openxmlformats.org/package/2006/content-types}"
        return (complete and main_relationship and content_types is not None and content_types.tag == namespace + "Types"
                and any(node.tag == namespace + "Override" and node.attrib.get("PartName") == "/word/document.xml"
                        and node.attrib.get("ContentType") == "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
                        for node in content_types))


def inspect_legal_archive(raw: bytes) -> ArchiveInspection:
    """CRC-read every safe member; return candidates only after all checks pass."""
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_ARCHIVE_BYTES or not raw.startswith(b"PK\x03\x04"):
        raise LegalArchiveError("invalid_or_oversized_zip_source")
    try:
        budget = [0]
        deadline = time.monotonic() + MAX_INSPECTION_SECONDS
        inventory = []
        selected = []
        _preflight_zip(raw)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            for member in _zip_layout(raw, archive):
                payload = _read_member(raw, member, budget, deadline)
                name = member.orig_filename
                kind = "directory" if member.is_dir() else "unknown"
                if not member.is_dir():
                    suffix = name.casefold().rsplit(".", 1)[-1]
                    if suffix == "pdf" and payload.startswith(b"%PDF-"):
                        _validate_document(payload, "application/pdf")
                        kind = "pdf_candidate"
                    elif suffix == "doc" and payload.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
                        kind = "ole_doc_candidate"
                    elif payload.startswith(b"PK\x03\x04"):
                        kind = "ooxml_docx_candidate" if suffix == "docx" and _docx_container(payload, budget, deadline) else "zip_other"
                retain = kind in {"pdf_candidate", "ole_doc_candidate", "ooxml_docx_candidate"}
                if retain:
                    selected.append((name, payload))
                filename_bytes = _raw_filename(raw, member)
                declared_utf8 = bool(member.flag_bits & 0x800)
                # Raw bytes + flag remain authoritative. CP866 is an explicitly
                # unverified display candidate for these Russian attachments;
                # it never changes validation, path identity or member lookup.
                display = filename_bytes.decode("cp866") if not declared_utf8 and any(byte >= 128 for byte in filename_bytes) else None
                inventory.append(ArchiveMember(name, filename_bytes.hex(), "utf-8" if declared_utf8 else "cp437_zip_convention",
                                               declared_utf8, display, "cp866" if display is not None else None,
                                               len(payload), member.compress_size,
                                               None if member.is_dir() else hashlib.sha256(payload).hexdigest(), kind, retain))
        return ArchiveInspection(hashlib.sha256(raw).hexdigest(), len(raw), budget[0], tuple(inventory), tuple(selected))
    except LegalArchiveError:
        raise
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OfficialTransportError, OSError, RuntimeError, ValueError, EOFError, NotImplementedError, struct.error, ET.ParseError, zlib.error):
        raise LegalArchiveError("invalid_zip_or_document_container") from None


def _instant(value: datetime) -> str:
    if (type(value) is not datetime or value.tzinfo is None
            or value.utcoffset() != timezone.utc.utcoffset(value)):
        raise ValueError("invalid archive response instant")
    return value.isoformat()


def fetch_legal_archive(url: str, *, _transport=None) -> ArchiveResponse:
    """Capture bounded transport bytes from one of the two observed ZIP URLs.

    The separate ArchiveResponse deliberately precedes archive validation, so
    rejected originals remain retainable. Only capture_legal_archives can mark
    inspection success, after PK structure and every member check have passed.
    """
    # Loaded here to keep the archive inspector independent of this private
    # transport extension and avoid widening the normal PDF/HTML entry point.
    from app.services.ett_transport import _BodyPolicy, _fetch_bounded, _official_redirect_target

    if url not in {source_url for _, source_url in ARCHIVE_SOURCES}:
        raise OfficialTransportError("invalid official source URL")
    validate_official_url(url)

    def nonempty(content: bytes) -> None:
        if not content:
            raise OfficialTransportError("official archive response is empty")

    return _fetch_bounded(
        url, expected_media="application/zip", url_validator=validate_official_url,
        redirect_target=_official_redirect_target, _transport=_transport,
        _body_policy=_BodyPolicy(allowed_media=ARCHIVE_MEDIA_TYPES, max_bytes=MAX_ARCHIVE_BYTES,
                                 validate=nonempty, response_factory=ArchiveResponse),
    )


def _response_metadata(response: ArchiveResponse, requested_url: str) -> dict:
    if (type(response) is not ArchiveResponse or response.requested_url != requested_url
            or response.media_type not in ARCHIVE_MEDIA_TYPES
            or type(response.content) is not bytes or not 1 <= len(response.content) <= MAX_ARCHIVE_BYTES
            or type(response.http_content_type) is not str or not 1 <= len(response.http_content_type) <= 256
            or any(not 32 <= ord(char) <= 126 for char in response.http_content_type)
            or response.http_content_type.split(";", 1)[0].strip().lower() != response.media_type
            or type(response.redirect_chain) is not tuple or len(response.redirect_chain) > MAX_REDIRECTS):
        raise ValueError("invalid archive response identity")
    for url in (response.url, *response.redirect_chain):
        validate_official_url(url)
        if urlsplit(url).netloc != urlsplit(requested_url).netloc:
            raise ValueError("invalid archive response origin")
    if ((response.redirect_chain and response.redirect_chain[-1] != response.url)
            or (not response.redirect_chain and response.url != requested_url)):
        raise ValueError("invalid archive response final URL")
    return {
        "response_url": response.url, "requested_url": response.requested_url,
        "redirect_chain": list(response.redirect_chain), "archive_sha256": hashlib.sha256(response.content).hexdigest(),
        "size_bytes": len(response.content), "observed_media_type": response.media_type,
        "observed_http_content_type": response.http_content_type, "retrieved_at": _instant(response.retrieved_at),
    }


def capture_legal_archives(store: LocalArtifactStore, *, fetch=None) -> dict:
    """Capture both observed archives; original bytes survive inspection failure.

    Selected member objects are written only after every member's compressed
    stream, size, CRC and applicable nested DOCX checks pass. These separately
    identified objects are candidates; presence never establishes legal proof.
    """
    if fetch is None:
        fetch = fetch_legal_archive
    started_at = _instant(datetime.now(timezone.utc))
    results = []
    for source_id, url in ARCHIVE_SOURCES:
        record = {"source_id": source_id, "requested_url": url, "source_kind": "observed_official_zip_attachment",
                  "locator_provenance": dict(ARCHIVE_LOCATOR_PROVENANCE[source_id]),
                  "attempted_at": _instant(datetime.now(timezone.utc)), "archive_validation_passed": False,
                  "source_identity_verified": False, "legal_text_verified": False}
        try:
            response = fetch(url)
            metadata = _response_metadata(response, url)
            digest = store.put(response.content)
            if digest != metadata["archive_sha256"]:
                raise ArtifactIntegrityError("archive digest mismatch")
            record.update(original_archive_retained=True, **metadata)
            inspected = inspect_legal_archive(response.content)
            record["archive_validation_passed"] = True
            retained = {}
            for path, payload in inspected._selected_payloads:
                digest = store.put(payload)
                if digest != hashlib.sha256(payload).hexdigest():
                    raise ArtifactIntegrityError("member digest mismatch")
                retained[path] = digest
            members = [{"path": member.path, "raw_filename_hex": member.raw_filename_hex,
                        "filename_encoding": member.filename_encoding, "utf8_filename_declared": member.utf8_filename_declared,
                        "unverified_display_path": member.unverified_display_path,
                        "unverified_display_encoding": member.unverified_display_encoding,
                        "size_bytes": member.size_bytes,
                        "compressed_size_bytes": member.compressed_size_bytes, "sha256": member.sha256,
                        "kind": member.kind, "selected": member.selected,
                        **({"stored_member_sha256": retained[member.path]} if member.selected else {})}
                       for member in inspected.members]
            record.update(status="inspected", member_count=len(members), selected_member_count=len(retained),
                          expanded_size_bytes=inspected.expanded_size_bytes, members=members)
        except OfficialTransportError as exc:
            record.update(status="failed", reason="archive_transport_failed")
            diagnostics = sanitize_transport_diagnostics(exc.diagnostics)
            if diagnostics:
                record["diagnostics"] = diagnostics
        except LegalArchiveError:
            record.update(status="failed", reason="archive_validation_failed")
        except ArtifactIntegrityError:
            record.update(status="failed", reason="archive_storage_integrity_failure")
        except Exception:
            record.update(status="failed", reason="archive_operation_failed")
        results.append(record)
    inspected_count = sum(record["status"] == "inspected" for record in results)
    return {
        "schema_version": 1, "probe_kind": "observed_official_archive_inspection",
        "started_at": started_at, "finished_at": _instant(datetime.now(timezone.utc)),
        "selected_source_ids": [source_id for source_id, _ in ARCHIVE_SOURCES],
        "attempted_sources": len(results), "inspected_sources": inspected_count,
        "failed_sources": len(results) - inspected_count,
        "all_selected_archives_inspected": inspected_count == len(ARCHIVE_SOURCES),
        "source_identity_verified": False, "adoption_dates_verified": False, "effective_dates_verified": False,
        "legal_text_verified": False, "amendment_inventory_complete": False,
        "production_ready": False, "active_rates_written": False, "pdf_acquisition_receipt_created": False,
        "storage_kind": "local_development", "durable_legal_retention_attested": False,
        "results": results,
    }
