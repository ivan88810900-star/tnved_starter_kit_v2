from app.datetime_util import utc_now_naive


def test_utc_now_naive_no_tzinfo() -> None:
    t = utc_now_naive()
    assert t.tzinfo is None
