"""Synthetic archive fixtures exercise bounded parsing, never execute members."""
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
import hashlib
import io
import stat
import struct
import warnings
import zipfile
import zlib
import json
from pathlib import Path

import pytest
import httpx

from app.services import ett_legal_archives as subject
from app.services.ett_artifacts import LocalArtifactStore
from app.services import ett_transport
from app.services.ett_transport import OfficialTransportError, OfficialResponse
from scripts import probe_ett_legal_archives as cli

PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
DOC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"candidate"
CONTENT_TYPES = b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'
RELS = b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'
DOCUMENT = b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body/></w:document>'


def make_zip(members, *, compression=zipfile.ZIP_STORED):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as archive:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            for name, payload in members:
                archive.writestr(name, payload)
    return buffer.getvalue()


def make_docx(*, types=CONTENT_TYPES, rels=RELS, document=DOCUMENT, extra=()):
    return make_zip([("[Content_Types].xml", types), ("_rels/.rels", rels), ("word/document.xml", document), *extra])


def alter_sizes(raw, size, crc):
    result = bytearray(raw)
    central = result.index(b"PK\x01\x02")
    struct.pack_into("<I", result, 14, crc)
    struct.pack_into("<I", result, 22, size)
    struct.pack_into("<I", result, central + 16, crc)
    struct.pack_into("<I", result, central + 24, size)
    return bytes(result)


def test_inventory_preserves_candidate_bytes_hashes_and_types():
    docx = make_docx()
    raw = make_zip([("Приложения/", b""), ("Приложения/акт.pdf", PDF), ("act.doc", DOC), ("act.docx", docx), ("readme.txt", b"text")])
    result = subject.inspect_legal_archive(raw)
    assert result.archive_sha256 == hashlib.sha256(raw).hexdigest()
    assert result.size_bytes == len(raw)
    assert [item.kind for item in result.members] == ["directory", "pdf_candidate", "ole_doc_candidate", "ooxml_docx_candidate", "unknown"]
    assert dict(result._selected_payloads) == {"Приложения/акт.pdf": PDF, "act.doc": DOC, "act.docx": docx}
    assert result.expanded_size_bytes == len(PDF) + len(DOC) + len(docx) + 4 + len(CONTENT_TYPES) + len(RELS) + len(DOCUMENT)
    assert result.members[1].sha256 == hashlib.sha256(PDF).hexdigest()
    with pytest.raises(FrozenInstanceError):
        result.members[1].kind = "verified"
    assert "_selected_payloads" not in repr(result)


def test_observed_legacy_filename_bytes_survive_without_guessing_identity():
    metadata = json.loads((Path(__file__).parent / "fixtures/ett_archives/legacy_filenames.metadata.json").read_text())
    assert metadata["fixture_kind"] == "observed_filename_metadata_with_synthetic_document_payloads"
    for archive in metadata["archives"]:
        synthetic_members = []
        for index, member in enumerate(archive["members"]):
            filename_bytes = bytes.fromhex(member["raw_filename_hex"])
            # Reproduce the literal observed filename bytes and flag, while
            # keeping the fixture payload tiny and explicitly synthetic.
            placeholder = str(index) + "x" * (len(filename_bytes) - 1)
            payload = make_docx() if member["kind"] == "ooxml_docx_candidate" else DOC
            synthetic_members.append((placeholder, payload))
        raw = make_zip(synthetic_members)
        for (placeholder, _), member in zip(synthetic_members, archive["members"]):
            raw = raw.replace(placeholder.encode("ascii"), bytes.fromhex(member["raw_filename_hex"]))
        inspected = subject.inspect_legal_archive(raw)
        assert len(inspected.members) == len(archive["members"])
        for actual, expected in zip(inspected.members, archive["members"]):
            filename_bytes = bytes.fromhex(expected["raw_filename_hex"])
            assert actual.path == filename_bytes.decode("cp437")
            assert actual.raw_filename_hex == expected["raw_filename_hex"]
            assert actual.filename_encoding == "cp437_zip_convention"
            assert actual.utf8_filename_declared is False
            assert actual.unverified_display_path == expected["unverified_cp866_display"]
            assert actual.unverified_display_encoding == "cp866"
            assert actual.kind == expected["kind"] and actual.selected


def test_utf8_russian_numero_is_safe_without_normalization_alias():
    name = "Решение №66.doc"
    member = subject.inspect_legal_archive(make_zip([(name, DOC)])).members[0]
    assert member.path == name and member.utf8_filename_declared is True
    assert member.filename_encoding == "utf-8"
    assert member.raw_filename_hex == name.encode("utf-8").hex()
    assert member.unverified_display_path is None


@pytest.mark.parametrize("compression", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_accepts_bounded_stored_and_deflated(compression):
    assert subject.inspect_legal_archive(make_zip([("act.pdf", PDF)], compression=compression)).members[0].selected


@pytest.mark.parametrize("path", ["../act.pdf", "/act.pdf", "a//act.pdf", "a/./act.pdf", "a/../act.pdf", "C:/act.pdf", "a\\act.pdf", "a. /act.pdf", "con.pdf", "a\x01.pdf", "a/" * 17 + "act.pdf", "a／act.pdf", "a：act.pdf", "．．/act.pdf", "ｃｏｎ.pdf", "a．/act.pdf", "a\u00a0/act.pdf"])
def test_rejects_unsafe_paths(path):
    with pytest.raises(subject.LegalArchiveError):
        subject.inspect_legal_archive(make_zip([(path, PDF)]))


@pytest.mark.parametrize("members", [
    [("act.pdf", PDF), ("act.pdf", PDF)],
    [("act.pdf", PDF), ("ACT.pdf", PDF)],
    [("A/one.txt", b"x"), ("a/two.txt", b"x")],
    [("a", b"x"), ("a/act.pdf", PDF)],
    [("№66.doc", DOC), ("No66.doc", DOC)],
    [("ａｃｔ.pdf", PDF), ("act.pdf", PDF)],
    [("№/one.txt", b"x"), ("No/two.txt", b"x")],
    [("№", b"x"), ("No/act.pdf", PDF)],
])
def test_rejects_duplicate_alias_and_file_directory_conflicts(members):
    with pytest.raises(subject.LegalArchiveError):
        subject.inspect_legal_archive(make_zip(members))


@pytest.mark.parametrize("mode", [stat.S_IFLNK, stat.S_IFIFO, stat.S_IFSOCK, stat.S_IFCHR])
def test_rejects_nonregular_members(mode):
    info = zipfile.ZipInfo("act.pdf")
    info.create_system = 3
    info.external_attr = (mode | 0o600) << 16
    with pytest.raises(subject.LegalArchiveError):
        subject.inspect_legal_archive(make_zip([(info, PDF)]))


@pytest.mark.parametrize("flag", [1, 64, 0x2000])
def test_rejects_encryption_and_unsupported_flags(flag):
    raw = bytearray(make_zip([("act.pdf", PDF)]))
    central = raw.index(b"PK\x01\x02")
    struct.pack_into("<H", raw, 6, flag)
    struct.pack_into("<H", raw, central + 8, flag)
    with pytest.raises(subject.LegalArchiveError):
        subject.inspect_legal_archive(bytes(raw))


def test_rejects_nul_original_path_even_when_zipinfo_truncates_it():
    raw = make_zip([("aX.pdf", PDF)]).replace(b"aX.pdf", b"a\x00.pdf")
    with pytest.raises(subject.LegalArchiveError, match="unsafe_member_path"):
        subject.inspect_legal_archive(raw)


@pytest.mark.parametrize("suffix", [b"trailing", b"PK\x05\x06"])
def test_rejects_trailing_archive_bytes(suffix):
    with pytest.raises(subject.LegalArchiveError):
        subject.inspect_legal_archive(make_zip([("act.pdf", PDF)]) + suffix)


def test_rejects_bad_crc_in_unselected_member_after_document():
    raw = make_zip([("act.pdf", PDF), ("unknown.bin", b"crc-test-value")]).replace(b"crc-test-value", b"crc-TEST-value")
    with pytest.raises(subject.LegalArchiveError):
        subject.inspect_legal_archive(raw)


def test_reads_true_deflate_size_instead_of_truncated_declared_size():
    payload = DOC[:8] + b"A" * 1048576
    raw = make_zip([("act.doc", payload)], compression=zipfile.ZIP_DEFLATED)
    forged = alter_sizes(raw, 8, zlib.crc32(DOC[:8]))
    with pytest.raises(subject.LegalArchiveError, match="member_actual_size_mismatch"):
        subject.inspect_legal_archive(forged)


def test_central_record_limit_checked_before_zipfile_allocation(monkeypatch):
    raw = bytearray(make_zip([(f"member-{index}.txt", b"x") for index in range(257)]))
    end = raw.rfind(b"PK\x05\x06")
    struct.pack_into("<HH", raw, end + 8, 1, 1)
    def must_not_construct(*args, **kwargs):
        pytest.fail("ZipFile must not parse excessive central records")
    monkeypatch.setattr(zipfile, "ZipFile", must_not_construct)
    with pytest.raises(subject.LegalArchiveError, match="central_records"):
        subject.inspect_legal_archive(bytes(raw))


@pytest.mark.parametrize("xml", [b"<broken>", b'<!DOCTYPE x [<!ENTITY y "z">]><x/>', b"<wrong/>"])
def test_malformed_or_wrong_docx_xml_cannot_be_selected(xml):
    raw = make_zip([("act.docx", make_docx(types=xml))])
    try:
        result = subject.inspect_legal_archive(raw)
    except subject.LegalArchiveError:
        return
    assert not result.members[0].selected


def test_invalid_deflate_is_sanitized():
    raw = bytearray(make_zip([("act.doc", DOC)], compression=zipfile.ZIP_DEFLATED))
    raw[30 + len("act.doc")] = 0xff
    with pytest.raises(subject.LegalArchiveError, match="invalid_zip_or_document_container"):
        subject.inspect_legal_archive(bytes(raw))


@pytest.mark.parametrize("extra", [[("word/vbaProject.bin", b"x")], [("word/embeddings/other.bin", b"x")]])
def test_docx_active_content_is_rejected(extra):
    with pytest.raises(subject.LegalArchiveError, match="unsupported_active_container"):
        subject.inspect_legal_archive(make_zip([("act.docx", make_docx(extra=extra))]))


def test_docx_external_relationship_is_rejected():
    rels = RELS.replace(b'</Relationships>', b'<Relationship TargetMode="External" Target="https://example.invalid/"/></Relationships>')
    with pytest.raises(subject.LegalArchiveError, match="unsupported_external_relationship"):
        subject.inspect_legal_archive(make_zip([("act.docx", make_docx(rels=rels))]))


def test_nested_docx_reads_share_expansion_budget(monkeypatch):
    docx = make_docx()
    monkeypatch.setattr(subject, "MAX_EXPANDED_BYTES", len(docx) + len(CONTENT_TYPES))
    with pytest.raises(subject.LegalArchiveError, match="archive_expansion_limit"):
        subject.inspect_legal_archive(make_zip([("act.docx", docx)]))


def test_rejects_declared_compression_bomb_before_reading():
    raw = make_zip([("many.txt", b"a" * 100000)], compression=zipfile.ZIP_DEFLATED)
    with pytest.raises(subject.LegalArchiveError, match="compression_limit"):
        subject.inspect_legal_archive(raw)


def replace_compressed_region(raw, replacement):
    original = bytearray(raw)
    central = original.index(b"PK\x01\x02")
    name_size, extra_size = struct.unpack_from("<HH", original, 26)
    start = 30 + name_size + extra_size
    result = original[:start] + replacement + original[central:]
    new_central = start + len(replacement)
    struct.pack_into("<I", result, 18, len(replacement))
    struct.pack_into("<I", result, new_central + 20, len(replacement))
    end = result.rfind(b"PK\x05\x06")
    struct.pack_into("<I", result, end + 16, new_central)
    return bytes(result)


@pytest.mark.parametrize("change", [lambda compressed: compressed + b"junk", lambda compressed: compressed[:-1]])
def test_rejects_trailing_or_unterminated_deflate_stream(change):
    raw = make_zip([("act.doc", DOC)], compression=zipfile.ZIP_DEFLATED)
    central = raw.index(b"PK\x01\x02")
    compressed = raw[30 + len("act.doc"):central]
    with pytest.raises(subject.LegalArchiveError):
        subject.inspect_legal_archive(replace_compressed_region(raw, change(compressed)))


def test_inspection_has_time_bound(monkeypatch):
    ticks = iter([0, subject.MAX_INSPECTION_SECONDS + 1])
    monkeypatch.setattr(subject.time, "monotonic", lambda: next(ticks))
    with pytest.raises(subject.LegalArchiveError, match="time_limit"):
        subject.inspect_legal_archive(make_zip([("act.pdf", PDF)]))


def test_source_size_bound_checked_before_zipfile(monkeypatch):
    monkeypatch.setattr(subject, "MAX_ARCHIVE_BYTES", 8)
    with pytest.raises(subject.LegalArchiveError, match="oversized"):
        subject.inspect_legal_archive(make_zip([("act.pdf", PDF)]))


def test_nested_central_count_preflight_precedes_nested_zipfile(monkeypatch):
    nested = bytearray(make_zip([(f"member-{index}.txt", b"x") for index in range(257)]))
    end = nested.rfind(b"PK\x05\x06")
    struct.pack_into("<HH", nested, end + 8, 1, 1)
    raw = make_zip([("act.docx", bytes(nested))])
    original = zipfile.ZipFile
    count = 0
    def counted(*args, **kwargs):
        nonlocal count
        count += 1
        assert count == 1, "Only the outer ZIP may reach ZipFile"
        return original(*args, **kwargs)
    monkeypatch.setattr(zipfile, "ZipFile", counted)
    with pytest.raises(subject.LegalArchiveError, match="central_records"):
        subject.inspect_legal_archive(raw)
    assert count == 1


def response_for(url, content, media="application/zip"):
    return subject.ArchiveResponse(url=url, requested_url=url, content=content, media_type=media,
                                   retrieved_at=datetime.now(timezone.utc), redirect_chain=(), http_content_type=media)


def test_capture_both_literal_sources_and_store_only_selected_members(tmp_path):
    raw = make_zip([("act.pdf", PDF), ("readme.txt", b"unselected")])
    requested = []
    def fetch(url):
        requested.append(url)
        return response_for(url, raw, "application/octet-stream")
    store = LocalArtifactStore(tmp_path / "objects")
    report = subject.capture_legal_archives(store, fetch=fetch)
    assert requested == [url for _, url in subject.ARCHIVE_SOURCES]
    assert report["all_selected_archives_inspected"] is True
    assert report["inspected_sources"] == 2
    assert {path.stem for path in (tmp_path / "objects").glob("*.blob")} == {hashlib.sha256(raw).hexdigest(), hashlib.sha256(PDF).hexdigest()}
    assert report["results"][0]["observed_media_type"] == "application/octet-stream"
    assert report["results"][0]["archive_validation_passed"] is True
    assert report["results"][0]["members"][1]["selected"] is False
    for key in ("source_identity_verified", "adoption_dates_verified", "effective_dates_verified", "legal_text_verified", "amendment_inventory_complete", "production_ready", "active_rates_written", "pdf_acquisition_receipt_created"):
        assert report[key] is False
    json.dumps(report)


def test_rejected_archive_retains_original_without_member_objects_and_continues(tmp_path):
    raw = make_zip([("act.pdf", PDF), ("unknown.bin", b"crc-test-value")]).replace(b"crc-test-value", b"crc-TEST-value")
    store = LocalArtifactStore(tmp_path / "objects")
    calls = []
    def fetch(url):
        calls.append(url)
        return response_for(url, raw)
    report = subject.capture_legal_archives(store, fetch=fetch)
    assert len(calls) == 2
    assert report["all_selected_archives_inspected"] is False
    assert report["failed_sources"] == 2
    assert all(item["original_archive_retained"] and not item["archive_validation_passed"] for item in report["results"])
    assert {path.stem for path in (tmp_path / "objects").glob("*.blob")} == {hashlib.sha256(raw).hexdigest()}
    assert all("members" not in item for item in report["results"])


def test_transport_failure_is_sanitized_and_does_not_stop_second_source(tmp_path):
    calls = []
    raw = make_zip([("act.pdf", PDF)])
    def fetch(url):
        calls.append(url)
        if len(calls) == 1:
            raise OfficialTransportError("private upstream body must not appear")
        return response_for(url, raw)
    report = subject.capture_legal_archives(LocalArtifactStore(tmp_path / "objects"), fetch=fetch)
    assert len(calls) == 2 and report["inspected_sources"] == 1
    assert report["results"][0]["reason"] == "archive_transport_failed"
    assert "private upstream" not in json.dumps(report)


def test_invalid_response_seam_cannot_publish(tmp_path):
    raw = make_zip([("act.pdf", PDF)])
    report = subject.capture_legal_archives(LocalArtifactStore(tmp_path / "objects"), fetch=lambda url: response_for(url, raw, "text/html"))
    assert report["failed_sources"] == 2
    assert not list((tmp_path / "objects").glob("*.blob"))


@pytest.mark.parametrize("succeed", [True, False])
def test_cli_writes_all_attempted_results_to_new_report(tmp_path, succeed):
    raw = make_zip([("act.pdf", PDF)]) if succeed else b"not a ZIP"
    path = tmp_path / "report.json"
    result = cli.main(["--store-root", str(tmp_path / "objects"), "--output", str(path)], fetch=lambda url: response_for(url, raw))
    assert result == (0 if succeed else 2)
    report = json.loads(path.read_text())
    assert report["attempted_sources"] == 2
    assert report["all_selected_archives_inspected"] is succeed
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_cli_never_overwrites_report_or_fetches_with_existing_output(tmp_path):
    path = tmp_path / "report.json"
    path.write_text("existing")
    def forbidden(url):
        pytest.fail("existing report must reject before acquisition")
    assert cli.main(["--store-root", str(tmp_path / "objects"), "--output", str(path)], fetch=forbidden) == 2
    assert path.read_text() == "existing"


@pytest.mark.parametrize("media", sorted(subject.ARCHIVE_MEDIA_TYPES))
def test_archive_transport_keeps_observed_media_and_separate_response_type(media):
    raw = make_zip([("act.pdf", PDF)])
    def handler(request):
        assert request.headers["Accept"] == "application/zip"
        assert request.headers["Accept-Encoding"] == "identity"
        return httpx.Response(200, headers={"content-type": media + "; name=attachment.zip"}, stream=httpx.ByteStream(raw))
    result = subject.fetch_legal_archive(subject.ARCHIVE_SOURCES[0][1], _transport=httpx.MockTransport(handler))
    assert type(result) is subject.ArchiveResponse and not isinstance(result, OfficialResponse)
    assert result.media_type == media
    assert result.http_content_type == media + "; name=attachment.zip"
    assert result.content == raw
    assert result.requested_url == result.url == subject.ARCHIVE_SOURCES[0][1]
    assert not hasattr(result, "archive_validation_passed")


def test_raw_transport_candidate_is_not_successful_archive_inspection(tmp_path):
    raw = b"<html>This is not a ZIP attachment</html>"
    transport = httpx.MockTransport(lambda request: httpx.Response(200, headers={"content-type": "application/zip"}, stream=httpx.ByteStream(raw)))
    report = subject.capture_legal_archives(LocalArtifactStore(tmp_path / "objects"), fetch=lambda url: subject.fetch_legal_archive(url, _transport=transport))
    assert report["failed_sources"] == 2 and not report["all_selected_archives_inspected"]
    assert all(item["original_archive_retained"] and not item["archive_validation_passed"] for item in report["results"])


@pytest.mark.parametrize("headers", [
    {"content-type": "text/html"}, {"content-type": "application/pdf"}, {},
    [("content-type", "application/zip"), ("content-type", "application/zip")],
    {"content-type": "application/zip", "content-encoding": "gzip"},
    {"content-type": "application/zip", "content-length": "1", "transfer-encoding": "chunked"},
])
def test_archive_transport_rejects_unapproved_media_and_body_framing(headers):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, headers=headers, stream=httpx.ByteStream(b"private response")))
    with pytest.raises(OfficialTransportError) as error:
        subject.fetch_legal_archive(subject.ARCHIVE_SOURCES[0][1], _transport=transport)
    assert "private response" not in str(error.value)


@pytest.mark.parametrize("url", [
    "https://docs.eaeunion.org/upload/guessed.zip",
    subject.ARCHIVE_SOURCES[0][1] + "?x=1",
    subject.ARCHIVE_SOURCES[0][1].replace("docs.eaeunion.org", "docs.eaeunion.org:443"),
    subject.ARCHIVE_SOURCES[0][1].replace("https://", "http://"),
])
def test_only_two_literal_sources_can_start_archive_requests(url):
    def forbidden(request):
        pytest.fail("Unobserved initial URL must reject before network")
    with pytest.raises(OfficialTransportError):
        subject.fetch_legal_archive(url, _transport=httpx.MockTransport(forbidden))


def test_archive_redirect_default_https_port_keeps_original_and_final_url_without_cookies():
    raw = make_zip([("act.pdf", PDF)])
    requests = []
    def handler(request):
        requests.append(request)
        assert "cookie" not in request.headers and "authorization" not in request.headers
        if len(requests) == 1:
            return httpx.Response(302, headers={"location": "https://docs.eaeunion.org:443/actual-attachment.zip", "set-cookie": "session=private"})
        return httpx.Response(200, headers={"content-type": "application/zip"}, stream=httpx.ByteStream(raw))
    result = subject.fetch_legal_archive(subject.ARCHIVE_SOURCES[0][1], _transport=httpx.MockTransport(handler))
    assert result.requested_url == subject.ARCHIVE_SOURCES[0][1]
    assert result.url == "https://docs.eaeunion.org/actual-attachment.zip"
    assert result.redirect_chain == (result.url,)
    assert len(requests) == 2


@pytest.mark.parametrize("location", [
    "https://eec.eaeunion.org/actual.zip", "https://docs.eaeunion.org:444/actual.zip",
    "/%2e%2e/actual.zip", "/actual.zip?key=1", "/actual.zip#fragment", "https://user@docs.eaeunion.org/actual.zip",
])
def test_archive_redirects_cannot_weaken_official_url_policy(location):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": location})
    with pytest.raises(OfficialTransportError):
        subject.fetch_legal_archive(subject.ARCHIVE_SOURCES[0][1], _transport=httpx.MockTransport(handler))
    assert len(requests) == 1


def test_archive_transport_inherits_size_bound(monkeypatch):
    monkeypatch.setattr(subject, "MAX_ARCHIVE_BYTES", 4)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, headers={"content-type": "application/zip"}, stream=httpx.ByteStream(b"12345")))
    with pytest.raises(OfficialTransportError):
        subject.fetch_legal_archive(subject.ARCHIVE_SOURCES[0][1], _transport=transport)


def test_private_body_policy_cannot_exceed_global_transport_cap():
    policy = ett_transport._BodyPolicy(allowed_media=frozenset({"application/zip"}), max_bytes=ett_transport.MAX_PDF_BYTES + 1,
                                       validate=lambda content: None, response_factory=subject.ArchiveResponse)
    with pytest.raises(OfficialTransportError):
        ett_transport._fetch_bounded(subject.ARCHIVE_SOURCES[0][1], expected_media="application/zip",
                                     url_validator=ett_transport.validate_official_url,
                                     redirect_target=ett_transport._official_redirect_target,
                                     _body_policy=policy, _transport=httpx.MockTransport(lambda request: pytest.fail("No request permitted")))


def test_public_official_transport_still_rejects_zip_expected_media():
    with pytest.raises(OfficialTransportError, match="unsupported official source media type"):
        ett_transport.fetch_official(subject.ARCHIVE_SOURCES[0][1], expected_media="application/zip",
                                     _transport=httpx.MockTransport(lambda request: pytest.fail("No request permitted")))
