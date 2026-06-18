"""Tests for ntm_noise_classifier — principle-based noise detection."""
from __future__ import annotations

import pytest

from app.services.ntm_noise_classifier import is_measure_noise


NOISE_CASES: list[tuple[str, str, bool]] = [
    # SGR: only valid for 1901, 1904, 2104, 2106, 3808, 3924, 9619, 3306, 2201
    ("8517120000", "sgr", True),   # smartphone — no SGR
    ("8471300000", "sgr", True),   # laptop — no SGR
    ("9503007500", "sgr", True),   # toy — no SGR
    ("3304990000", "sgr", True),   # cosmetics — no SGR
    ("8703230000", "sgr", True),   # car — no SGR
    ("2106909200", "sgr", False),  # BAD (food supplement) — SGR valid
    ("1901900000", "sgr", False),  # baby food — SGR valid
    ("3808940000", "sgr", False),  # disinfectant — SGR valid

    # Vet control: chapters 01-05, some of 15-16, 23, 41, 43, 51
    ("0201100000", "vet_control", False),  # beef — vet valid
    ("0401200001", "vet_control", False),  # milk — vet valid
    ("0808108000", "vet_control", True),   # apples — no vet
    ("8517120000", "vet_control", True),   # smartphone — no vet
    ("6403990000", "vet_control", True),   # shoes — no vet
    ("3304990000", "vet_control", True),   # cosmetics — no vet

    # Phyto control: chapters 06-14, some of 44
    ("0808108000", "phyto_control", False),  # apples — phyto valid
    ("0701901000", "phyto_control", False),  # potato — phyto valid
    ("1001990000", "phyto_control", False),  # wheat — phyto valid
    ("0201100000", "phyto_control", True),   # beef — no phyto
    ("8517120000", "phyto_control", True),   # smartphone — no phyto
    ("3304990000", "phyto_control", True),   # cosmetics — no phyto

    # License: alcohol (22), tobacco (24), weapons (93), explosives (36), etc.
    ("2204210000", "license", False),  # wine — license valid
    ("9301000000", "license", False),  # weapons — license valid
    ("3004909200", "license", False),  # medicine (ch.30) — license valid
    ("8517120000", "license", True),   # smartphone — no license
    ("9503007500", "license", True),   # toy — no license
    ("6403990000", "license", True),   # shoes — no license

    # Certificate: very broad scope, almost nothing is noise
    ("8517120000", "certificate", False),
    ("0201100000", "certificate", False),
    ("6403990000", "certificate", False),

    # TR TS: valid where TR TS catalog has prefixes or food chapters
    ("8517120000", "tr_ts", False),  # smartphone — TR TS valid
    ("9503007500", "tr_ts", False),  # toy — TR TS valid (008/2011)
    ("0201100000", "tr_ts", False),  # beef — TR TS valid (021/2011)

    # FSETC: always noise
    ("8517120000", "fsetc", True),
    ("0201100000", "fsetc", True),
]


@pytest.mark.parametrize("hs_code,measure_type,expected_noise", NOISE_CASES)
def test_noise_classification(hs_code: str, measure_type: str, expected_noise: bool) -> None:
    result = is_measure_noise(hs_code, measure_type)
    label = "noise" if expected_noise else "legitimate"
    assert result == expected_noise, (
        f"{hs_code} + {measure_type}: expected {label}, got {'noise' if result else 'legitimate'}"
    )


CONTROL_CODES = [
    ("8517120000", "Смартфон", {"certificate", "tr_ts"}, {"sgr", "vet_control", "phyto_control"}),
    ("8471300000", "Ноутбук", {"certificate", "tr_ts"}, {"sgr", "vet_control", "phyto_control"}),
    ("0808108000", "Яблоки", {"phyto_control"}, {"sgr", "vet_control"}),
    ("0201100000", "Говядина", {"vet_control", "certificate"}, {"phyto_control", "sgr"}),
    ("6403990000", "Обувь", {"certificate", "tr_ts"}, {"vet_control", "phyto_control", "sgr"}),
    ("9503007500", "Игрушка", {"certificate", "tr_ts"}, {"vet_control", "phyto_control", "sgr"}),
    ("3304990000", "Косметика", {"certificate", "tr_ts"}, {"vet_control", "phyto_control", "sgr"}),
    ("9401300000", "Кресло", {"certificate", "tr_ts"}, {"vet_control", "phyto_control", "sgr"}),
    ("3004909200", "Лекарство", {"license", "certificate"}, {"vet_control", "phyto_control", "sgr"}),
    ("2106909200", "БАД", {"sgr", "certificate", "tr_ts"}, {"vet_control", "phyto_control"}),
    ("2204210000", "Вино", {"license", "certificate", "tr_ts"}, {"vet_control", "phyto_control"}),
    ("8703230000", "Автомобиль", {"certificate", "tr_ts"}, {"vet_control", "phyto_control", "sgr"}),
]


@pytest.mark.parametrize("hs_code,desc,keep_types,noise_types", CONTROL_CODES)
def test_control_code_noise(hs_code: str, desc: str, keep_types: set[str], noise_types: set[str]) -> None:
    for mt in keep_types:
        assert not is_measure_noise(hs_code, mt), f"{hs_code} ({desc}): {mt} should be kept, got noise"
    for mt in noise_types:
        assert is_measure_noise(hs_code, mt), f"{hs_code} ({desc}): {mt} should be noise, got kept"
