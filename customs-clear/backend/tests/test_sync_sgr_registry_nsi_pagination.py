from __future__ import annotations

from typing import Any

import pytest

from scripts import sync_sgr_registry as sync


def _nsi_item(index: int) -> dict[str, Any]:
    return {
        "data": {
            "NUMB_DOC": f"RU.00.00.00.000.E.{index:06d}.00.00",
            "NAME_PROD": f"Product {index}",
        }
    }


def test_nsi_pagination_continues_after_short_nonempty_page(monkeypatch: pytest.MonkeyPatch) -> None:
    offsets: list[int] = []
    page_sizes = {0: 1000, 1000: 998, 1998: 1000}

    def fake_post(url: str, payload: dict[str, Any], **_: Any) -> Any:
        if url.endswith("get-list-data-total"):
            return {"byFilterCount": 2998}
        offset = payload["offset"]
        offsets.append(offset)
        return [_nsi_item(offset + i) for i in range(page_sizes[offset])]

    monkeypatch.setattr(sync, "_http_post_json", fake_post)

    rows, total, is_partial = sync._nsi_sgr_rows(
        code=sync.NSI_SGR_CODE,
        date_iso="2026-10-13",
        batch_size=1000,
    )

    assert sync.NSI_SGR_CODE == "1995"
    assert total == 2998
    assert is_partial is False
    assert len(rows) == 2998
    assert offsets == [0, 1000, 1998]


def test_nsi_batch_size_is_capped_at_official_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    requested_limits: list[int] = []

    def fake_post(url: str, payload: dict[str, Any], **_: Any) -> Any:
        if url.endswith("get-list-data-total"):
            return {"byFilterCount": 1600}
        requested_limits.append(payload["limit"])
        return [_nsi_item(payload["offset"] + i) for i in range(payload["limit"])]

    monkeypatch.setattr(sync, "_http_post_json", fake_post)

    rows, total, is_partial = sync._nsi_sgr_rows(
        code=sync.NSI_SGR_CODE,
        date_iso="2026-10-13",
        batch_size=2000,
    )

    assert total == 1600
    assert is_partial is False
    assert len(rows) == 1600
    assert requested_limits == [1500, 100]
    assert all(limit <= sync.NSI_SGR_MAX_BATCH_SIZE for limit in requested_limits)


def test_nsi_pagination_fails_on_premature_empty_page(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(url: str, payload: dict[str, Any], **_: Any) -> Any:
        if url.endswith("get-list-data-total"):
            return {"totalCount": 3}
        return [_nsi_item(0), _nsi_item(1)] if payload["offset"] == 0 else []

    monkeypatch.setattr(sync, "_http_post_json", fake_post)

    with pytest.raises(RuntimeError, match="exhausted at offset 2 before target 3"):
        sync._nsi_sgr_rows(code=sync.NSI_SGR_CODE, date_iso="2026-10-13", batch_size=3)


def test_drift_safe_resume_requires_matching_overlap_and_dedupes_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior_tail = [_nsi_item(80 + i) for i in range(20)]
    next_rows = [_nsi_item(100 + i) for i in range(100)]
    expected_overlap = sync._nsi_overlap_sha256(prior_tail)
    totals = iter([778350, 778404])
    monkeypatch.setattr(sync, "_nsi_sgr_total", lambda **_kwargs: next(totals))

    def fake_page(_url: str, payload: dict[str, Any], **_kwargs: Any) -> list[dict[str, Any]]:
        assert payload["offset"] == 80
        assert payload["limit"] == 120
        return prior_tail + next_rows

    monkeypatch.setattr(sync, "_http_post_json", fake_page)

    rows, manifest = sync.fetch_nsi_sgr_drift_safe_page(
        code=sync.NSI_SGR_CODE,
        date_iso="2026-10-16",
        offset=100,
        limit=100,
        overlap_rows=20,
        expected_overlap_sha256=expected_overlap,
    )

    assert rows == next_rows
    assert manifest["overlap_sha256"] == expected_overlap
    assert manifest["new_count"] == 100
    assert manifest["next_offset"] == 200
    assert manifest["total_before"] == 778350
    assert manifest["total_after"] == 778404
    assert manifest["total_drift"] == 54
    assert manifest["drift_detected"] is True
    assert manifest["terminal_total_reconciled"] is False


def test_drift_safe_resume_fails_closed_on_overlap_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sync, "_nsi_sgr_total", lambda **_kwargs: 200)
    monkeypatch.setattr(
        sync,
        "_http_post_json",
        lambda *_args, **_kwargs: [_nsi_item(81 + i) for i in range(120)],
    )

    with pytest.raises(RuntimeError, match="overlap mismatch"):
        sync.fetch_nsi_sgr_drift_safe_page(
            code=sync.NSI_SGR_CODE,
            date_iso="2026-10-16",
            offset=100,
            limit=100,
            overlap_rows=20,
            expected_overlap_sha256=sync._nsi_overlap_sha256(
                [_nsi_item(80 + i) for i in range(20)]
            ),
        )


def test_drift_safe_terminal_reconciliation_requires_stable_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = [_nsi_item(i) for i in range(5)]
    monkeypatch.setattr(sync, "_nsi_sgr_total", lambda **_kwargs: 5)
    monkeypatch.setattr(sync, "_http_post_json", lambda *_args, **_kwargs: page)

    rows, manifest = sync.fetch_nsi_sgr_drift_safe_page(
        code=sync.NSI_SGR_CODE,
        date_iso="2026-10-16",
        offset=0,
        limit=10,
    )

    assert rows == page
    assert manifest["page_sha256"] == sync.hashlib.sha256(
        sync._canonical_json(page).encode("utf-8")
    ).hexdigest()
    assert manifest["terminal_candidate"] is True
    assert manifest["terminal_total_reconciled"] is True


def test_drift_safe_cursor_advances_by_source_rows_after_dedupe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    overlap = [_nsi_item(8), _nsi_item(9)]
    duplicate = _nsi_item(10)
    page = overlap + [duplicate, duplicate, _nsi_item(11)]
    monkeypatch.setattr(sync, "_nsi_sgr_total", lambda **_kwargs: 20)
    monkeypatch.setattr(sync, "_http_post_json", lambda *_args, **_kwargs: page)

    rows, manifest = sync.fetch_nsi_sgr_drift_safe_page(
        code=sync.NSI_SGR_CODE,
        date_iso="2026-10-16",
        offset=10,
        limit=3,
        overlap_rows=2,
        expected_overlap_sha256=sync._nsi_overlap_sha256(overlap),
    )

    assert rows == [duplicate, _nsi_item(11)]
    assert manifest["new_count"] == 2
    assert manifest["source_advance"] == 3
    assert manifest["next_offset"] == 13


def test_drift_safe_nonterminal_empty_page_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sync, "_nsi_sgr_total", lambda **_kwargs: 3)
    monkeypatch.setattr(sync, "_http_post_json", lambda *_args, **_kwargs: [])

    with pytest.raises(RuntimeError, match="exhausted at offset 0 before observed total 3"):
        sync.fetch_nsi_sgr_drift_safe_page(
            code=sync.NSI_SGR_CODE,
            date_iso="2026-10-16",
            offset=0,
            limit=3,
        )


def test_drift_safe_page_exceeding_stable_total_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sync, "_nsi_sgr_total", lambda **_kwargs: 5)
    monkeypatch.setattr(
        sync,
        "_http_post_json",
        lambda *_args, **_kwargs: [_nsi_item(index) for index in range(6)],
    )

    with pytest.raises(RuntimeError, match="exceeds the stable official total"):
        sync.fetch_nsi_sgr_drift_safe_page(
            code=sync.NSI_SGR_CODE,
            date_iso="2026-10-16",
            offset=0,
            limit=10,
        )


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"offset": 100, "limit": 100}, "positive overlap"),
        ({"offset": 100, "limit": 100, "overlap_rows": 20}, "expected overlap"),
        ({"offset": -1, "limit": 100}, "non-negative"),
        ({"offset": 0, "limit": 0}, "must be positive"),
    ],
)
def test_drift_safe_page_rejects_unsafe_resume(
    kwargs: dict[str, int],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        sync.fetch_nsi_sgr_drift_safe_page(
            code=sync.NSI_SGR_CODE,
            date_iso="2026-10-16",
            **kwargs,
        )


@pytest.mark.parametrize(
    "response",
    [
        [],
        {},
        {"byFilterCount": "not-an-integer"},
        {"byFilterCount": -1},
        {"byFilterCount": 1.5},
        {"byFilterCount": True},
    ],
)
def test_nsi_total_rejects_malformed_or_unsupported_shape(
    monkeypatch: pytest.MonkeyPatch,
    response: Any,
) -> None:
    monkeypatch.setattr(sync, "_http_post_json", lambda *_args, **_kwargs: response)

    with pytest.raises(RuntimeError, match="NSI SGR total"):
        sync._nsi_sgr_total(code=sync.NSI_SGR_CODE, date_iso="2026-10-13")


def test_nsi_max_rows_is_explicitly_partial(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sync, "_nsi_sgr_total", lambda **_kwargs: 5)

    def fake_page(_url: str, payload: dict[str, Any], **_kwargs: Any) -> list[dict[str, Any]]:
        return [_nsi_item(payload["offset"] + i) for i in range(payload["limit"])]

    monkeypatch.setattr(
        sync,
        "_http_post_json",
        fake_page,
    )
    upserts: list[str] = []
    monkeypatch.setattr(sync, "upsert_sgr", lambda _db, row: upserts.append(row["sgr_number"]))

    count, status = sync.sync_from_nsi(
        object(),
        code=sync.NSI_SGR_CODE,
        date_iso="2026-10-13",
        max_rows=3,
    )

    assert count == 3
    assert len(upserts) == 3
    assert status == "nsi_partial:max_rows=3;official_total=5"


def test_incomplete_nsi_fetch_performs_no_upserts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sync, "_nsi_sgr_total", lambda **_kwargs: 3)
    pages = iter([[_nsi_item(0)], []])
    monkeypatch.setattr(sync, "_http_post_json", lambda *_args, **_kwargs: next(pages))
    upserts: list[dict[str, Any]] = []
    monkeypatch.setattr(sync, "upsert_sgr", lambda _db, row: upserts.append(row))

    with pytest.raises(RuntimeError, match="pagination exhausted"):
        sync.sync_from_nsi(
            object(),
            code=sync.NSI_SGR_CODE,
            date_iso="2026-10-13",
        )

    assert upserts == []


def test_malformed_total_performs_no_upserts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sync,
        "_http_post_json",
        lambda *_args, **_kwargs: {"byFilterCount": "unknown"},
    )
    upserts: list[dict[str, Any]] = []
    monkeypatch.setattr(sync, "upsert_sgr", lambda _db, row: upserts.append(row))

    with pytest.raises(RuntimeError, match="total field 'byFilterCount' is malformed"):
        sync.sync_from_nsi(
            object(),
            code=sync.NSI_SGR_CODE,
            date_iso="2026-10-13",
        )

    assert upserts == []


def test_missing_numb_doc_performs_no_upserts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sync, "_nsi_sgr_total", lambda **_kwargs: 2)
    malformed = {"data": {"NAME_PROD": "Missing certificate number"}}
    monkeypatch.setattr(
        sync,
        "_http_post_json",
        lambda *_args, **_kwargs: [_nsi_item(0), malformed],
    )
    upserts: list[dict[str, Any]] = []
    monkeypatch.setattr(sync, "upsert_sgr", lambda _db, row: upserts.append(row))

    with pytest.raises(RuntimeError, match="row 1 is malformed or has no NUMB_DOC"):
        sync.sync_from_nsi(
            object(),
            code=sync.NSI_SGR_CODE,
            date_iso="2026-10-13",
        )

    assert upserts == []


@pytest.mark.parametrize(
    ("total", "note_parts", "http_failed", "demo_seed_enabled", "expected"),
    [
        (0, ["nsi_ok"], False, False, "ok"),
        (0, ["auto_nsi:nsi_ok"], False, False, "ok"),
        (3, ["nsi_partial:max_rows=3;official_total=5"], False, False, "partial"),
        (3, ["auto_nsi:nsi_partial:max_rows=3;official_total=5"], False, False, "partial"),
        (3, ["nsi_ok"], True, False, "error"),
    ],
)
def test_nsi_sync_log_status(
    total: int,
    note_parts: list[str],
    http_failed: bool,
    demo_seed_enabled: bool,
    expected: str,
) -> None:
    assert (
        sync._sgr_sync_log_status(
            total=total,
            note_parts=note_parts,
            http_failed=http_failed,
            demo_seed_enabled=demo_seed_enabled,
        )
        == expected
    )
