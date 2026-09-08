"""Adversarial contracts for the scheduled official CBR rate adapter."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.core import ExchangeRate, SourceStatus, SyncLog
from app.services import exchange_rates


def _snapshot(date_key, rows):
    return exchange_rates.CBRRateSnapshot(date_key, rows, "a" * 64)


_CBR_TABLES = [ExchangeRate.__table__, SourceStatus.__table__, SyncLog.__table__]


def _memory_sessionmaker():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=_CBR_TABLES)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _xml_payload(
    rate_date: date,
    *,
    codes: tuple[str, ...] = exchange_rates.TRACKED,
) -> bytes:
    records = "".join(
        (
            f'<Valute ID="R{index:05d}"><NumCode>{index:03d}</NumCode>'
            f"<CharCode>{code}</CharCode><Nominal>1</Nominal>"
            f"<Name>{code}</Name><Value>{90 + index},25</Value></Valute>"
        )
        for index, code in enumerate(codes, start=1)
    )
    return (
        f'<ValCurs Date="{rate_date.strftime("%d.%m.%Y")}" '
        f'name="Foreign Currency Market">{records}</ValCurs>'
    ).encode()


def _response(
    *,
    body: bytes,
    status: int = 200,
    content_type: str | None = "application/xml; charset=windows-1251",
    url: str = exchange_rates.CBR_DAILY_URL,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    response_headers = dict(headers or {})
    if content_type is not None:
        response_headers["content-type"] = content_type
    return httpx.Response(
        status,
        content=body,
        headers=response_headers,
        request=httpx.Request("GET", url),
    )


def test_fetch_uses_pinned_tls_transport_and_parses_canonical_xml(monkeypatch) -> None:
    payload = _xml_payload(datetime.now(timezone.utc).date())
    requests: list[str] = []
    client_kwargs: dict[str, object] = {}
    real_async_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(
            200,
            content=payload,
            headers={
                "content-type": "application/xml; charset=windows-1251",
                "content-length": str(len(payload)),
            },
        )

    transport = httpx.MockTransport(handler)

    def client_factory(**kwargs):
        client_kwargs.update(kwargs)
        return real_async_client(transport=transport, **kwargs)

    monkeypatch.setattr(exchange_rates.httpx, "AsyncClient", client_factory)
    date_key, rows = asyncio.run(exchange_rates.fetch_cbr_rates())

    assert date_key == datetime.now(timezone.utc).date().isoformat()
    assert set(rows) == set(exchange_rates.TRACKED)
    assert requests == [exchange_rates.CBR_DAILY_URL]
    assert client_kwargs["follow_redirects"] is False
    assert client_kwargs["trust_env"] is False
    assert client_kwargs["verify"] is True


@pytest.mark.parametrize(
    "url",
    (
        "http://www.cbr.ru/scripts/XML_daily.asp",
        "https://cbr.ru/scripts/XML_daily.asp",
        "https://www.cbr.ru/scripts/XML_daily.asp?date_req=01/01/2020",
        "https://www.cbr.ru/scripts/XML_daily.asp/extra",
        "https://www.cbr.ru@attacker.example/scripts/XML_daily.asp",
    ),
)
def test_fetch_rejects_noncanonical_request_url_before_network(monkeypatch, url: str) -> None:
    constructed = False

    def forbidden_client(**_kwargs):
        nonlocal constructed
        constructed = True
        raise AssertionError("network client must not be constructed")

    monkeypatch.setattr(exchange_rates, "CBR_DAILY_URL", url)
    monkeypatch.setattr(exchange_rates.httpx, "AsyncClient", forbidden_client)

    with pytest.raises(RuntimeError, match="unexpected CBR request URL"):
        asyncio.run(exchange_rates.fetch_cbr_rates())
    assert constructed is False


@pytest.mark.parametrize(
    "url",
    (
        "https://attacker.example/scripts/XML_daily.asp",
        "https://www.cbr.ru/scripts/XML_daily.asp?unexpected=1",
        "http://www.cbr.ru/scripts/XML_daily.asp",
        "https://www.cbr.ru/scripts/XML_daily.asp/",
    ),
)
def test_response_identity_must_equal_the_requested_official_artifact(url: str) -> None:
    response = _response(body=b"<ValCurs/>", url=url)
    with pytest.raises(RuntimeError, match="unexpected CBR response URL"):
        exchange_rates._validated_cbr_response_body(response)


def test_redirect_is_rejected_without_following_location() -> None:
    response = _response(
        body=b"redirect",
        status=302,
        content_type="text/html",
        headers={"location": exchange_rates.CBR_DAILY_URL},
    )
    with pytest.raises(RuntimeError, match="redirects are not allowed"):
        exchange_rates._validated_cbr_response_body(response)


@pytest.mark.parametrize("content_type", (None, "text/html", "application/octet-stream"))
def test_response_rejects_missing_or_non_xml_mime(content_type: str | None) -> None:
    response = _response(body=b"<ValCurs/>", content_type=content_type)
    with pytest.raises(RuntimeError, match="non-XML Content-Type"):
        exchange_rates._validated_cbr_response_body(response)


def test_xml_mime_cannot_disguise_html_or_binary_magic() -> None:
    for body in (b"<html>upstream block page</html>", b"\x00<ValCurs/>"):
        response = _response(body=body, content_type="application/xml")
        with pytest.raises(ValueError, match="expected XML|unsupported encoding"):
            exchange_rates._validated_cbr_response_body(response)


def test_response_enforces_declared_and_actual_body_limits() -> None:
    declared = _response(
        body=b"<ValCurs/>",
        headers={"content-length": str(exchange_rates._CBR_XML_MAX_BYTES + 1)},
    )
    actual = _response(body=b"x" * (exchange_rates._CBR_XML_MAX_BYTES + 1))

    with pytest.raises(RuntimeError, match="size limit"):
        exchange_rates._validated_cbr_response_body(declared)
    with pytest.raises(RuntimeError, match="size limit"):
        exchange_rates._validated_cbr_response_body(actual)


@pytest.mark.parametrize(
    "xml",
    (
        b'<html Date="03.09.2026"><Valute/></html>',
        b'<ns:ValCurs xmlns:ns="urn:evil" Date="03.09.2026"><Valute/></ns:ValCurs>',
        b'<!DOCTYPE ValCurs [<!ENTITY x "USD">]><ValCurs Date="03.09.2026">&x;</ValCurs>',
        b'<ValCurs Date="03.09.2026"><Unexpected/></ValCurs>',
        b'<ValCurs Date="03.09.2026"><Valute><CharCode><b>USD</b></CharCode>'
        b'<Nominal>1</Nominal><Value>90,0</Value></Valute></ValCurs>',
        b'<ValCurs Date="03.09.2026"><Valute><CharCode>USD</CharCode>'
        b'<Nominal>1.0</Nominal><Value>90,0</Value></Valute></ValCurs>',
        b'<ValCurs Date="03.09.2026"><Valute><CharCode>USD</CharCode>'
        b'<Nominal>1</Nominal><Value>NaN</Value></Valute></ValCurs>',
        b'<ValCurs Date="03.09.2026"><Valute><CharCode>USD</CharCode>'
        b'<Nominal>1</Nominal><Value>90</Value><Value>91</Value></Valute></ValCurs>',
        b'<ValCurs Date="03.09.2026"><Valute><CharCode>USD</CharCode>'
        b'<Nominal>1</Nominal><Value>90</Value></Valute><Valute>'
        b'<CharCode>USD</CharCode><Nominal>1</Nominal><Value>91</Value>'
        b'</Valute></ValCurs>',
    ),
)
def test_parser_rejects_wrong_root_dtd_and_schema_ambiguity(xml: bytes) -> None:
    with pytest.raises(ValueError):
        exchange_rates._parse_cbr_xml(xml)


def _seed_rates(db, *, base: float) -> dict[str, float]:
    stored: dict[str, float] = {}
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for index, code in enumerate(exchange_rates.TRACKED):
        rate = base + index
        stored[code] = rate
        db.add(
            ExchangeRate(
                currency_code=code,
                rate=rate,
                nominal=1.0,
                updated_at=now,
            )
        )
    return stored


def _rows(base: float) -> dict[str, tuple[float, float]]:
    return {
        code: (base + index, 1.0)
        for index, code in enumerate(exchange_rates.TRACKED)
    }


def test_older_age_valid_payload_cannot_replace_newer_source_status(
    monkeypatch,
) -> None:
    sm = _memory_sessionmaker()
    persisted_date = datetime.now(timezone.utc).date()
    candidate_date = persisted_date - timedelta(days=1)
    with sm() as db:
        stored = _seed_rates(db, base=700.0)
        db.add(
            SourceStatus(
                source_code=exchange_rates.CBRF_SOURCE_CODE,
                source_name="CBR",
                source_url=exchange_rates.CBR_DAILY_URL,
                revision=f"cbrf:{persisted_date.isoformat()}",
                synced_at=datetime.now(timezone.utc).replace(tzinfo=None),
                is_stale=False,
                note="newer official state",
            )
        )
        db.commit()

    monkeypatch.setattr(exchange_rates, "SessionLocal", sm)
    monkeypatch.setattr("app.services.normative_store.SessionLocal", sm)
    monkeypatch.setattr(
        exchange_rates,
        "fetch_cbr_rates",
        AsyncMock(return_value=_snapshot(candidate_date.isoformat(), _rows(10.0))),
    )

    result = asyncio.run(
        exchange_rates.update_exchange_rates_from_cbrf(allow_fallback=True)
    )

    assert result["status"] == "ERROR"
    assert result["source"] == "preserved_last_good"
    assert result["rollback_rejected"] is True
    assert result["updated"] == 0
    with sm() as db:
        actual = {
            row.currency_code: float(row.rate)
            for row in db.query(ExchangeRate).all()
        }
        status = db.query(SourceStatus).filter_by(
            source_code=exchange_rates.CBRF_SOURCE_CODE
        ).one()
    assert actual == stored
    assert status.revision == f"cbrf:{persisted_date.isoformat()}"
    assert status.is_stale is True


def test_success_log_remains_high_water_after_fallback_status(monkeypatch) -> None:
    sm = _memory_sessionmaker()
    persisted_date = datetime.now(timezone.utc).date()
    candidate_date = persisted_date - timedelta(days=1)
    with sm() as db:
        stored = _seed_rates(db, base=800.0)
        db.add(
            SourceStatus(
                source_code=exchange_rates.CBRF_SOURCE_CODE,
                source_name="CBR",
                source_url=exchange_rates.CBR_DAILY_URL,
                revision="fallback",
                synced_at=datetime.now(timezone.utc).replace(tzinfo=None),
                is_stale=True,
                note="latest attempt failed",
            )
        )
        db.add(
            SyncLog(
                source_code=exchange_rates.CBRF_SOURCE_CODE,
                synced_at=datetime.now(timezone.utc).replace(tzinfo=None),
                status="OK",
                revision=f"cbrf:{persisted_date.isoformat()}",
                rows_affected=len(exchange_rates.TRACKED),
                note="last official success",
            )
        )
        db.commit()

    monkeypatch.setattr(exchange_rates, "SessionLocal", sm)
    monkeypatch.setattr("app.services.normative_store.SessionLocal", sm)
    monkeypatch.setattr(
        exchange_rates,
        "fetch_cbr_rates",
        AsyncMock(return_value=_snapshot(candidate_date.isoformat(), _rows(20.0))),
    )

    result = asyncio.run(
        exchange_rates.update_exchange_rates_from_cbrf(allow_fallback=False)
    )

    assert result["rollback_rejected"] is True
    with sm() as db:
        actual = {
            row.currency_code: float(row.rate)
            for row in db.query(ExchangeRate).all()
        }
    assert actual == stored


def test_same_or_newer_official_date_can_update_and_finalize_provenance(
    monkeypatch,
) -> None:
    sm = _memory_sessionmaker()
    candidate_date = datetime.now(timezone.utc).date()
    persisted_date = candidate_date - timedelta(days=1)
    with sm() as db:
        _seed_rates(db, base=900.0)
        db.add(
            SourceStatus(
                source_code=exchange_rates.CBRF_SOURCE_CODE,
                source_name="CBR",
                source_url=exchange_rates.CBR_DAILY_URL,
                revision=f"cbrf:{persisted_date.isoformat()}",
                synced_at=datetime.now(timezone.utc).replace(tzinfo=None),
                is_stale=False,
                note="older official state",
            )
        )
        db.commit()

    candidate_rows = _rows(30.0)
    monkeypatch.setattr(exchange_rates, "SessionLocal", sm)
    monkeypatch.setattr("app.services.normative_store.SessionLocal", sm)
    monkeypatch.setattr(
        exchange_rates,
        "fetch_cbr_rates",
        AsyncMock(return_value=_snapshot(candidate_date.isoformat(), candidate_rows)),
    )

    result = asyncio.run(
        exchange_rates.update_exchange_rates_from_cbrf(allow_fallback=False)
    )

    assert result["status"] == "OK"
    assert result["source"] == "CBRF"
    assert result["provenance_recorded"] is True
    with sm() as db:
        actual = {
            row.currency_code: float(row.rate)
            for row in db.query(ExchangeRate).all()
        }
        status = db.query(SourceStatus).filter_by(
            source_code=exchange_rates.CBRF_SOURCE_CODE
        ).one()
    assert actual == {code: rate for code, (rate, _nominal) in candidate_rows.items()}
    assert status.revision == f"cbrf:{candidate_date.isoformat()}:sha256:{'a' * 64}"
    assert status.is_stale is False


def test_malformed_persisted_official_revision_fails_closed(monkeypatch) -> None:
    sm = _memory_sessionmaker()
    candidate_date = datetime.now(timezone.utc).date()
    with sm() as db:
        stored = _seed_rates(db, base=1_000.0)
        db.add(
            SourceStatus(
                source_code=exchange_rates.CBRF_SOURCE_CODE,
                source_name="CBR",
                source_url=exchange_rates.CBR_DAILY_URL,
                revision="cbrf:not-a-date",
                synced_at=datetime.now(timezone.utc).replace(tzinfo=None),
                is_stale=False,
                note="corrupt high-water state",
            )
        )
        db.commit()

    monkeypatch.setattr(exchange_rates, "SessionLocal", sm)
    monkeypatch.setattr("app.services.normative_store.SessionLocal", sm)
    monkeypatch.setattr(
        exchange_rates,
        "fetch_cbr_rates",
        AsyncMock(return_value=_snapshot(candidate_date.isoformat(), _rows(40.0))),
    )

    result = asyncio.run(
        exchange_rates.update_exchange_rates_from_cbrf(allow_fallback=False)
    )

    assert result["status"] == "ERROR"
    assert result["updated"] == 0
    assert "cannot prove CBR monotonicity" in result["error"]
    with sm() as db:
        actual = {
            row.currency_code: float(row.rate)
            for row in db.query(ExchangeRate).all()
        }
    assert actual == stored


def test_same_date_artifact_is_immutable_and_failure_does_not_erase_digest(monkeypatch):
    sm = _memory_sessionmaker()
    monkeypatch.setattr(exchange_rates, "SessionLocal", sm)
    key = datetime.now(timezone.utc).date().isoformat()
    exchange_rates._upsert_rates(_rows(10), official_date_key=key, artifact_sha256="a" * 64)
    with pytest.raises(RuntimeError, match="immutable same-date"):
        exchange_rates._upsert_rates(_rows(20), official_date_key=key, artifact_sha256="b" * 64)
    with sm() as db:
        assert db.query(ExchangeRate).filter_by(currency_code="USD").one().rate == 10
        status = db.query(SourceStatus).one()
        assert status.revision.endswith("a" * 64)
        assert db.query(SyncLog).count() == 1


def test_legacy_same_date_must_match_every_stored_rate_and_nominal(monkeypatch):
    sm = _memory_sessionmaker()
    monkeypatch.setattr(exchange_rates, "SessionLocal", sm)
    key = datetime.now(timezone.utc).date().isoformat()
    with sm() as db:
        _seed_rates(db, base=10)
        db.add(SourceStatus(source_code="CBRF", source_name="CBR", source_url=exchange_rates.CBR_DAILY_URL,
                            revision=f"cbrf:{key}", is_stale=False))
        db.commit()
    changed = _rows(10)
    changed["KZT"] = (14, 100)
    with pytest.raises(RuntimeError, match="legacy same-date"):
        exchange_rates._upsert_rates(changed, official_date_key=key, artifact_sha256="a" * 64)
    exchange_rates._upsert_rates(_rows(10), official_date_key=key, artifact_sha256="a" * 64)
    with sm() as db:
        assert db.query(SourceStatus).one().revision.endswith("a" * 64)


@pytest.mark.parametrize("revision", [None, "", "unknown", "cbrf:", "cbrf:2026-99-00"])
def test_corrupt_success_log_cannot_be_ignored(monkeypatch, revision):
    sm = _memory_sessionmaker()
    monkeypatch.setattr(exchange_rates, "SessionLocal", sm)
    with sm() as db:
        db.add(SyncLog(source_code="CBRF", status="OK", revision=revision))
        db.commit()
    with pytest.raises(RuntimeError, match="cannot prove CBR"):
        exchange_rates._upsert_rates(_rows(1), official_date_key="2026-09-08", artifact_sha256="a" * 64)
    with sm() as db:
        assert db.query(ExchangeRate).count() == 0


def test_first_run_concurrent_artifacts_have_one_atomic_winner(monkeypatch, tmp_path):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    engine = create_engine(f"sqlite:///{tmp_path / 'race.db'}", connect_args={"timeout": 5})
    Base.metadata.create_all(engine, tables=_CBR_TABLES)
    sm = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(exchange_rates, "SessionLocal", sm)
    barrier = threading.Barrier(2)
    def write(base, digest):
        barrier.wait(timeout=5)
        try:
            exchange_rates._upsert_rates(_rows(base), official_date_key="2026-09-08", artifact_sha256=digest * 64)
            return base, digest
        except RuntimeError as exc:
            assert "immutable same-date" in str(exc)
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(write, 10, "a")
        b = pool.submit(write, 20, "b")
        winners = [result for result in (a.result(timeout=10), b.result(timeout=10)) if result]
    assert len(winners) == 1
    base, digest = winners[0]
    with sm() as db:
        assert db.query(SyncLog).count() == 1
        status = db.query(SourceStatus).one()
        assert not status.is_stale and status.revision.endswith(digest * 64)
        assert {row.currency_code: (row.rate, row.nominal) for row in db.query(ExchangeRate)} == _rows(base)
    engine.dispose()


def test_late_failed_request_cannot_downgrade_newer_success(monkeypatch):
    sm = _memory_sessionmaker()
    monkeypatch.setattr(exchange_rates, "SessionLocal", sm)
    started = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
    exchange_rates._upsert_rates(_rows(10), official_date_key="2026-09-08", artifact_sha256="a" * 64)
    result = exchange_rates._handle_cbr_failure("delayed timeout", allow_fallback=True, attempt_started_at=started)
    assert result["superseded"] is True and result["updated"] == 0
    with sm() as db:
        assert not db.query(SourceStatus).one().is_stale
        assert db.query(SyncLog).count() == 1
