from app.services import non_tariff_service, normative_store


def test_data_freshness_fails_closed_when_eec_status_is_missing(monkeypatch):
    monkeypatch.setattr(normative_store, "list_source_status", lambda: [])

    assert non_tariff_service._data_freshness() == {
        "source_name": "Локальная база правил",
        "source_code": "LOCAL",
        "synced_at": None,
        "is_stale": True,
        "revision": "seed",
    }


def test_data_freshness_fails_closed_when_status_lookup_raises(monkeypatch):
    def raise_status_error():
        raise RuntimeError("status unavailable")

    monkeypatch.setattr(normative_store, "list_source_status", raise_status_error)

    freshness = non_tariff_service._data_freshness()

    assert freshness["source_code"] == "LOCAL"
    assert freshness["synced_at"] is None
    assert freshness["is_stale"] is True
    assert freshness["revision"] == "seed"


def test_data_freshness_preserves_verified_eec_status(monkeypatch):
    verified = {
        "source_name": "Единый таможенный тариф ЕАЭС",
        "source_code": "EEC_ETT",
        "synced_at": "2026-09-14T12:00:00+00:00",
        "is_stale": False,
        "revision": "2026-09-14",
    }
    monkeypatch.setattr(
        normative_store,
        "list_source_status",
        lambda: [
            {
                "source_name": "Другой источник",
                "source_code": "OTHER",
                "synced_at": None,
                "is_stale": True,
                "revision": None,
            },
            verified,
        ],
    )

    assert non_tariff_service._data_freshness() == verified
