from app.services.duty_parser import DutyParser


def test_parse_ad_valorem():
    r = DutyParser.parse("5%")
    assert r is not None
    assert r.type == "ad_valorem"
    assert r.ad_valorem_pct == 5.0


def test_parse_specific():
    r = DutyParser.parse("0,1 евро/кг")
    assert r is not None
    assert r.type == "specific"
    assert r.specific_amount == 0.1
    assert r.specific_currency == "EUR"
    assert r.specific_uom == "kg"


def test_parse_combined_max():
    r = DutyParser.parse("5%, но не менее 0.1 евро/кг")
    assert r is not None
    assert r.type == "combined_max"
    assert r.ad_valorem_pct == 5.0
    assert r.specific_amount == 0.1


def test_parse_combined_min():
    r = DutyParser.parse("10%, но не более 2 usd за 1 л")
    assert r is not None
    assert r.type == "combined_min"
    assert r.ad_valorem_pct == 10.0
    assert r.specific_amount == 2.0
    assert r.specific_currency == "USD"
    assert r.specific_uom == "l"
