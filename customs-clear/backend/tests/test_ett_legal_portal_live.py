"""Replay retained official responses offline; never request or execute pages."""
from collections import Counter
import hashlib
import json
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from app.services.ett_legal_attachments import parse_legal_attachments

FIXTURES = Path(__file__).parent / "fixtures/ett_legal_portal"
HOST = "https://docs.eaeunion.org"
CASES = [
    {
        "stem": "collegium_66_run_34240219765",
        "url": HOST + "/documents/399/6620/",
        "identity": "Решение Коллегии ЕЭК № 66",
        "sha256": "68161af0fb45bf6a420a47c92f4b459df1fb5d9b382df5c1c0cb2d539d327fa7",
        "size_bytes": 54256,
        "pdf": HOST + "/upload/iblock/393/f3ak35ptlhz2u9paqn79dontu4r2kj8h/err_28042022_66_doc.pdf",
        "unsupported": {
            HOST + "/upload/iblock/6cb/gfvjhw7yfs6prab1gtl0zzrh8rzg97xr/err_28042022_doc.docx",
            HOST + "/upload/iblock/f88/8q7g6xj03agjbs25m2km9g0rff02y7z2/err_28042022_66_doc.doc",
            HOST + "/upload/iblock/6a2/079pkmu7rny0r7jl5pyxf234rvbxk2pi/err_28042022_66_doc.doc",
            HOST + "/upload/iblock/89e/glj9sgxn5m3tm0o3gun59us7fshhicg6/err_28042022_66_doc.docx",
            HOST + "/upload/iblock/30f/1ejbrxx8u338qjf970tal0715afq9li8/err_28042022_66_att.zip",
            HOST + "/upload/iblock/69b/5d1mepn2ab9o2j8s9kbc5345rps6txkv/err_28042022_76_att.docx",
        },
    },
    {
        "stem": "council_76_run_34240219765",
        "url": HOST + "/documents/401/6619/",
        "identity": "Решение Совета ЕЭК № 76",
        "sha256": "5511dadc71d651aad14926fb84aac9efe674248e2be41cb1c9495f3b85c4ff76",
        "size_bytes": 53278,
        "pdf": HOST + "/upload/iblock/82b/1h7ofr72qrt3q86uvgi7kwy36d0l66m6/err_28042022_76_doc.pdf",
        "unsupported": {
            HOST + "/upload/iblock/f78/b5m629phjj7o4a7kn0zxofhj5m8w5r73/err_28042022_doc.docx",
            HOST + "/upload/iblock/91c/i0sk3s5mrm01bsgkgsvio3e8l2tjx0vm/err_28042022_76_doc.docx",
            HOST + "/upload/iblock/966/6vx377j0u8g0k709lf9f4wib2bp3121j/err_28042022_76_doc.doc",
            HOST + "/upload/iblock/23a/zifcty1ropjh1acn1c2befcdmhrg7ap9/err_28042022_76_doc.docx",
            HOST + "/upload/iblock/69b/5d1mepn2ab9o2j8s9kbc5345rps6txkv/err_28042022_76_att.docx",
            HOST + "/upload/iblock/f8b/4n8tf0bp9hkvrg1mwvd3o992yckghgn3/err_28042022_76_att.zip",
        },
    },
]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["stem"])
def test_original_source_bytes_and_observed_metadata_identity(case):
    raw = (FIXTURES / (case["stem"] + ".html")).read_bytes()
    metadata = json.loads((FIXTURES / (case["stem"] + ".metadata.json")).read_bytes())
    record = metadata["capture_record"]
    assert hashlib.sha256(raw).hexdigest() == case["sha256"] == record["sha256"]
    assert len(raw) == case["size_bytes"] == record["size_bytes"]
    assert record["requested_url"] == record["response_url"] == case["url"]
    assert record["status"] == "captured"
    assert record["redirect_chain"] == []
    assert metadata["github_actions_run_id"] == "34240219765"
    result = parse_legal_attachments(raw, case["url"])
    assert result.source_sha256 == case["sha256"]
    assert result.document_identity == case["identity"]
    assert result.identity_sha256 == hashlib.sha256(case["identity"].encode()).hexdigest()
    assert result.legal_inventory_complete is result.semantic_verified is False
    assert metadata["amendment_inventory_complete"] is metadata["legal_applicability_verified"] is metadata["production_ready"] is False


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["stem"])
def test_all_observed_pdf_and_unsupported_attachment_urls_remain_distinct(case):
    raw = (FIXTURES / (case["stem"] + ".html")).read_bytes()
    result = parse_legal_attachments(raw, case["url"])
    assert Counter(ref.url for ref in result.documents) == {case["pdf"]: 3}
    assert {ref.url for ref in result.unsupported_references} == case["unsupported"]
    assert len(case["unsupported"]) == 6
    assert all(ref.media_type == "application/pdf" for ref in result.documents)
    assert all(ref.media_type != "application/pdf" for ref in result.unsupported_references)
    assert {ref.role for ref in result.unsupported_references} == {"unsupported_legal_attachment"}
    assert result.legal_inventory_complete is False


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["stem"])
def test_each_attachment_locator_points_to_an_original_anchor(case):
    raw = (FIXTURES / (case["stem"] + ".html")).read_bytes()
    result = parse_legal_attachments(raw, case["url"])
    soup = BeautifulSoup(raw.decode("utf-8"), "html.parser")
    anchors = soup.body.find_all("a")
    refs = result.documents + result.unsupported_references
    assert len({ref.locator for ref in refs}) == len(refs)
    for ref in refs:
        locator = ref.locator.split(":")
        original = anchors[int(locator[2]) - 1]
        assert int(locator[4]) == original.sourceline
        assert int(locator[6]) == original.sourcepos
        assert ref.href == original["href"]
        assert ref.raw_href in str(original)
