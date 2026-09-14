from app.services.ntm_catalog_baseline import (
    active_ett_fingerprint,
    compare_source_baseline,
    load_catalog_baseline,
    pdf_source_manifest,
)


def test_pinned_pdf_catalog_and_active_ett_manifests_are_current() -> None:
    baseline = load_catalog_baseline()
    comparison = compare_source_baseline(
        baseline,
        pdf_source=pdf_source_manifest(),
        active_ett=active_ett_fingerprint(),
    )

    assert comparison == {
        "pdf_source_manifest_match": True,
        "active_ett_snapshot_match": True,
        "catalog_parser_match": True,
    }
    assert baseline["pdf_source"]["file_count"] == 96
    assert baseline["pdf_source"]["chapter_codes"] == [
        *(f"{value:02d}" for value in range(1, 77)),
        *(f"{value:02d}" for value in range(78, 98)),
    ]
    assert baseline["catalog"]["section_count"] == 21
    assert baseline["catalog"]["chapter_count"] == 96
    assert baseline["catalog"]["rows"] == 17_809
    assert baseline["catalog"]["unique_codes"] == 17_809
    assert baseline["catalog"]["description_rows"] == 17_774
    assert len(baseline["catalog"]["blank_description_codes"]) == 35
    assert baseline["active_ett"]["unique_codes"] == 13_290


def test_blank_reference_codes_do_not_overlap_active_ett_snapshot() -> None:
    baseline = load_catalog_baseline()
    active = active_ett_fingerprint()
    # The exact code-set digest is pinned; the full list need not be copied into
    # the aggregate-only evidence report.
    assert active["code_set_sha256"] == baseline["active_ett"]["code_set_sha256"]

    import json
    from app.services.ntm_catalog_baseline import DEFAULT_ETT_PATH

    payload = json.loads(DEFAULT_ETT_PATH.read_text(encoding="utf-8"))
    active_codes = {
        str(row.get("hs_code") or "")
        for row in payload["rates"]
        if isinstance(row, dict)
    }
    assert set(baseline["catalog"]["blank_description_codes"]).isdisjoint(active_codes)
