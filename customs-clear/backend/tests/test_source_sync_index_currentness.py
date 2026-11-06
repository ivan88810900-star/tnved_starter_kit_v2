"""Fail-closed currentness tests for landing-page observations."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services import source_sync


class _Response:
    text = "<html>official index</html>"

    def raise_for_status(self) -> None:
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sync_fn", "source_code"),
    (
        (source_sync.sync_eec_snapshot, "EEC_ETT"),
        (source_sync.sync_trade_defense, "TRADE_DEFENSE"),
    ),
)
async def test_landing_page_hash_does_not_claim_authoritative_currentness(
    sync_fn,
    source_code: str,
) -> None:
    with (
        patch.object(
            source_sync,
            "_http_get_with_retries",
            new=AsyncMock(return_value=_Response()),
        ),
        patch.object(source_sync, "upsert_source_status") as upsert_status,
        patch.object(source_sync, "append_sync_log") as append_log,
    ):
        result = await sync_fn()

    assert result["status"] == "PARTIAL"
    assert result["source"] == source_code
    assert result["verification_scope"] == "landing_page_only"
    assert result["authoritative_currentness_confirmed"] is False

    status_kwargs = upsert_status.call_args.kwargs
    assert status_kwargs["source_code"] == source_code
    assert status_kwargs["is_stale"] is True
    assert "не подтверж" in status_kwargs["note"]

    log_kwargs = append_log.call_args.kwargs
    assert log_kwargs["source_code"] == source_code
    assert log_kwargs["status"] == "PARTIAL"
    assert log_kwargs["rows_affected"] == 0


@pytest.mark.asyncio
async def test_source_pipeline_surfaces_index_only_observations_as_warning() -> None:
    partial = {"status": "PARTIAL", "source": "EEC_ETT"}
    ok = {"status": "OK", "source": "OTHER"}
    skipped = {"status": "SKIPPED", "source": "OPTIONAL"}

    with (
        patch.object(source_sync, "sync_eec_snapshot", new=AsyncMock(return_value=partial)),
        patch.object(source_sync, "sync_trade_defense", new=AsyncMock(return_value=partial)),
        patch.object(source_sync, "sync_odata_sources", new=AsyncMock(return_value=ok)),
        patch.object(source_sync, "sync_ett_pdf", new=AsyncMock(return_value=ok)),
        patch.object(source_sync, "sync_rates_feed", new=AsyncMock(return_value=skipped)),
        patch.object(source_sync, "sync_csv_feed", new=AsyncMock(return_value=skipped)),
        patch.object(source_sync, "sync_normative_bundle_url", new=AsyncMock(return_value=skipped)),
        patch.object(source_sync, "sync_tamdoc_documents", new=AsyncMock(return_value=skipped)),
        patch.object(source_sync, "sync_tamdoc_targeted", new=AsyncMock(return_value=skipped)),
        patch.object(source_sync, "sync_tamdoc_archive", return_value=skipped),
        patch.object(source_sync, "sync_trois_sources", new=AsyncMock(return_value=skipped)),
    ):
        result = await source_sync.sync_all_sources()

    assert result["status"] == "WARNING"
    assert any(item["status"] == "PARTIAL" for item in result["sources"])
