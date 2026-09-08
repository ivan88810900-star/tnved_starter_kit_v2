"""Synthetic portal pages exercise discovery, never official acquisition proof."""
from dataclasses import FrozenInstanceError, asdict
import hashlib
import html

import pytest

from app.services.ett_legal_attachments import (
    ETTLegalAttachmentError, MAX_ATTACHMENT_REFERENCES, parse_legal_attachments,
    validate_attachment_url,
)

PAGE = "https://docs.eaeunion.org/documents/399/6620/"
PDF = "/upload/iblock/393/opaque/err_28042022_66_doc.pdf"
DOCX = "/upload/iblock/69b/opaque/clarification.docx"


def portal(links=None, *, extra=""):
    if links is None:
        links = f'<a href="{PDF}">Рус</a><a href="{PDF}">Скачать</a><a href="{DOCX}">Разъяснение</a>'
    return (
        '<!doctype html><html><head><title>Legal portal fixture</title></head><body>'
        '<div>Правовой портал</div><div>Информация о документе</div>'
        '<div>Полный заголовок документа</div><p>Синтетический пример</p>'
        '<div>Номер документа</div><div>66</div>'
        '<div>Короткий заголовок документа</div><div>Решение Коллегии ЕЭК № 66</div>'
        '<div>Вид документа</div><div>Решения</div>'
        '<div>Дата принятия документа</div><div>19.04.2022</div>'
        '<div>Дата опубликования</div><div>28.04.2022</div>'
        '<div>Дата вступления в силу</div><div>08.05.2022</div>'
        f'<div>{links}</div>{extra}</body></html>'
    ).encode()


def test_preserves_original_hash_repeated_links_unsupported_files_and_no_dates():
    raw = portal()
    result = parse_legal_attachments(raw, PAGE)
    assert result.source_sha256 == hashlib.sha256(raw).hexdigest()
    assert result.size_bytes == len(raw)
    assert len(result.documents) == 2
    assert result.documents[0].url == "https://docs.eaeunion.org" + PDF
    assert result.documents[0].href == result.documents[0].raw_href == PDF
    assert result.documents[0].text == "Рус"
    assert result.documents[0].locator.startswith("html:a:1:line:")
    assert result.documents[0].locator != result.documents[1].locator
    assert result.documents[0].role == "legal_attachment_pdf"
    assert len(result.unsupported_references) == 1
    assert result.unsupported_references[0].url.endswith(".docx")
    assert result.unsupported_references[0].role == "unsupported_legal_attachment"
    assert result.legal_inventory_complete is result.semantic_verified is False
    assert not any("date" in key or "valid" in key for key in asdict(result))


def test_empty_attachments_are_explicitly_incomplete_and_never_guessed():
    result = parse_legal_attachments(portal(""), PAGE)
    assert result.documents == result.unsupported_references == ()
    assert result.legal_inventory_complete is False


def test_metadata_identity_ignores_titles_of_related_decisions():
    result = parse_legal_attachments(portal(extra="<p>Решение Совета ЕЭК № 99</p>"), PAGE)
    assert result.document_identity == "Решение Коллегии ЕЭК № 66"
    assert result.identity_sha256 == hashlib.sha256(result.document_identity.encode()).hexdigest()


def test_full_council_identity_and_old_portal_path_are_supported_without_dates():
    raw = portal().replace("Решение Коллегии ЕЭК № 66".encode(), "Решение Совета Евразийской экономической комиссии № 66".encode())
    result = parse_legal_attachments(raw, "https://docs.eaeunion.org/docs/ru-ru/01232481/err_28042022_66")
    assert result.document_identity.startswith("Решение Совета")


def test_reference_and_result_are_frozen():
    result = parse_legal_attachments(portal(), PAGE)
    with pytest.raises(FrozenInstanceError):
        result.legal_inventory_complete = True
    with pytest.raises(FrozenInstanceError):
        result.documents[0].url = "https://example.com/"


def test_literal_href_is_not_confused_with_text_inside_another_attribute():
    href = PDF.replace("opaque", "opaque&#x2d;name")
    raw = portal(f'<a data-note=" href=\'fake.pdf\' " href="{href}">Document</a>')
    result = parse_legal_attachments(raw, PAGE)
    ref = result.documents[0]
    assert ref.raw_href == href
    assert ref.href == html.unescape(href)
    assert "opaque-name" in ref.url


@pytest.mark.parametrize("href", [PDF, "https://docs.eaeunion.org" + PDF, "//docs.eaeunion.org" + PDF])
def test_observed_absolute_root_and_protocol_relative_links(href):
    assert parse_legal_attachments(portal(f"<a href='{href}'>PDF</a>"), PAGE).documents[0].url.endswith(PDF)


def test_spaces_unicode_extension_case_and_unquoted_href():
    href = "/upload/iblock/abc/name/Акт с приложением.PDF"
    ref = parse_legal_attachments(portal(f'<a href="{href}">PDF</a>'), PAGE).documents[0]
    assert "%20" in ref.url and "%D0%90" in ref.url
    assert ref.media_type == "application/pdf"
    assert parse_legal_attachments(portal(f"<a href={PDF}>PDF</a>"), PAGE).documents[0].raw_href == PDF


def test_encoded_dot_does_not_hide_supported_file_type():
    href = PDF.replace(".pdf", "%2epdf")
    ref = parse_legal_attachments(portal(f'<a href="{href}">PDF</a>'), PAGE).documents[0]
    assert ref.url.endswith("%2epdf")


@pytest.mark.parametrize("extension", ["doc", "docx", "zip", "xls", "xlsx", "rtf", "unknown"])
def test_non_pdf_attachments_remain_unsupported(extension):
    raw = portal(f'<a href="/upload/iblock/abc/name/file.{extension}">Attachment</a>')
    result = parse_legal_attachments(raw, PAGE)
    assert result.documents == ()
    assert len(result.unsupported_references) == 1
    assert result.legal_inventory_complete is False


@pytest.mark.parametrize("hidden", ["hidden", 'aria-hidden="true"', 'style="display:none"', 'style="visibility:hidden"'])
def test_hidden_references_do_not_become_visible_documents(hidden):
    result = parse_legal_attachments(portal(f'<div {hidden}><a href="{PDF}">PDF</a></div>'), PAGE)
    assert result.documents == ()


@pytest.mark.parametrize("tag", ["script", "template", "noscript", "style"])
def test_inert_markup_does_not_supply_attachment_or_identity(tag):
    raw = portal(f'<{tag}><a href="{PDF}">PDF</a></{tag}>')
    assert parse_legal_attachments(raw, PAGE).documents == ()
    raw = portal().replace(b'<div>66</div>', b'<div>66</div>')
    raw = raw.replace("Решение Коллегии ЕЭК № 66".encode(), f'<{tag}>Решение Коллегии ЕЭК № 66</{tag}>'.encode())
    with pytest.raises(ETTLegalAttachmentError):
        parse_legal_attachments(raw, PAGE)


@pytest.mark.parametrize("href", [
    "https://example.com/a.pdf", "http://docs.eaeunion.org" + PDF,
    "https://docs.eaeunion.org:443" + PDF, "https://user@docs.eaeunion.org" + PDF,
    "https://eec.eaeunion.org" + PDF, PDF + "?download=1", PDF + "#page=1",
    PDF.replace("opaque", ".."), PDF.replace("opaque", "%2e%2e"),
    PDF.replace("opaque", "a%2fb"), PDF.replace("opaque", "a%5cb"),
    PDF.replace("opaque", "a%252fb"), PDF.replace("opaque", "a%00b"),
    PDF.replace("opaque", "a\\b"), PDF.replace("opaque", "a\nb"),
    PDF.replace("opaque", "a%ffb"), PDF.replace("opaque", "a%b"),
    PDF.replace("opaque", "/opaque"), "/admin/secret.pdf",
    "file:///tmp/a.pdf", "../a.pdf", "javascript:a.pdf",
    "\n" + PDF, PDF + "\n", " https://example.com/a.pdf ",
])
def test_unsafe_attachment_is_not_silently_omitted(href):
    with pytest.raises(ETTLegalAttachmentError):
        parse_legal_attachments(portal(f'<a href="{href}">PDF</a>'), PAGE)


@pytest.mark.parametrize("page", [
    "https://eec.eaeunion.org/comission/department/catr/ett/",
    "https://docs.eaeunion.org/", "https://docs.eaeunion.org/upload/iblock/a/a.pdf",
    PAGE + "?a=1", "http://docs.eaeunion.org/documents/399/6620/",
])
def test_invalid_source_document_urls(page):
    with pytest.raises(ETTLegalAttachmentError):
        parse_legal_attachments(portal(), page)


@pytest.mark.parametrize("raw", [b"", b"\xff", b"x" * (4 * 1024 * 1024 + 1), portal().decode()])
def test_invalid_input_bytes(raw):
    with pytest.raises(ETTLegalAttachmentError):
        parse_legal_attachments(raw, PAGE)


@pytest.mark.parametrize("old,new", [
    (b"</html>", b""), (b"</body>", b""), (b"</a>", b""),
    (b"<body>", b'<base href="https://example.com/"><body>'),
    (b"<!doctype html>", b'<!DOCTYPE html [<!ENTITY x SYSTEM "file:///etc/passwd">]>'),
    (b"<body>", b"<body>\x00"),
    ("Правовой портал".encode(), b"Challenge"),
    ("Короткий заголовок документа".encode(), b"Missing identity"),
    (b'<a href="', b'<a href="x.pdf" href="'),
])
def test_malformed_or_wrong_identity_html(old, new):
    with pytest.raises(ETTLegalAttachmentError):
        parse_legal_attachments(portal().replace(old, new), PAGE)


def test_duplicate_identity_metadata_is_ambiguous():
    duplicate = '<p>Короткий заголовок документа</p><p>Решение Совета ЕЭК № 2</p><p>Вид документа</p>'
    with pytest.raises(ETTLegalAttachmentError, match="identity"):
        parse_legal_attachments(portal(extra=duplicate), PAGE)


def test_html_and_attachment_budgets():
    with pytest.raises(ETTLegalAttachmentError, match="structure"):
        parse_legal_attachments(portal(extra="<div>" * 300 + "x" + "</div>" * 300), PAGE)
    links = f'<a href="{PDF}">PDF</a>' * (MAX_ATTACHMENT_REFERENCES + 1)
    with pytest.raises(ETTLegalAttachmentError, match="count"):
        parse_legal_attachments(portal(links), PAGE)
    with pytest.raises(ETTLegalAttachmentError, match="label"):
        parse_legal_attachments(portal(f'<a href="{PDF}">{"x" * 8193}</a>'), PAGE)


def test_standalone_url_validator_does_not_accept_page_as_attachment():
    assert validate_attachment_url("https://docs.eaeunion.org" + PDF)
    with pytest.raises(ETTLegalAttachmentError):
        validate_attachment_url(PAGE)
