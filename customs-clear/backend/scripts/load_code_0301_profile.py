from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal
from app.models.tnved import NonTariffMeasure, VatPreference


@dataclass(frozen=True)
class SourceDoc:
    url: str
    title_hint: str
    measure_type: str
    document_required: str
    description: str


DOCS: list[SourceDoc] = [
    SourceDoc(
        url="https://www.alta.ru/tamdoc/10sr0317/",
        title_hint="Решение КТС от 18.06.2010 № 317",
        measure_type="vet_control",
        document_required="Ветеринарный сертификат и/или разрешение уполномоченного органа",
        description="Товарная группа 0301 подпадает под ветеринарно-санитарный контроль при импорте.",
    ),
    SourceDoc(
        url="https://www.alta.ru/tamdoc/10sr0299/",
        title_hint="Решение КТС от 28.05.2010 № 299",
        measure_type="other",
        document_required="Документы санитарно-эпидемиологического контроля",
        description="Для отдельных позиций группы 0301 применяются санитарные меры и контроль.",
    ),
    SourceDoc(
        url="https://www.alta.ru/tamdoc/15kr0030/",
        title_hint="Решение Коллегии ЕЭК от 21.04.2015 № 30",
        measure_type="certificate",
        document_required="Разрешительные документы в рамках Единого перечня (при применимости)",
        description="Проверка требований по сертификации/декларированию в отношении продукции группы 0301.",
    ),
    SourceDoc(
        url="https://www.alta.ru/tamdoc/08ps0337/",
        title_hint="Постановление Правительства РФ от 04.05.2008 № 337",
        measure_type="license",
        document_required="Разрешение Росприроднадзора и документы CITES (если вид подпадает под Конвенцию)",
        description="Для отдельных видов живой рыбы может требоваться разрешительная документация CITES.",
    ),
    SourceDoc(
        url="https://www.alta.ru/tamdoc/14uk0560/",
        title_hint="Указ Президента РФ от 06.08.2014 № 560",
        measure_type="ban",
        document_required="Проверка страны происхождения и исключений",
        description="Применяются специальные экономические меры (контрсанкции) к товарам из отдельных стран.",
    ),
    SourceDoc(
        url="https://www.alta.ru/tamdoc/14ps0778/",
        title_hint="Постановление Правительства РФ от 07.08.2014 № 778",
        measure_type="ban",
        document_required="Проверка ограничений и исключений по Постановлению",
        description="Ограничения на ввоз отдельных продовольственных товаров из перечня стран.",
    ),
    SourceDoc(
        url="https://www.alta.ru/tamdoc/22ps0353/",
        title_hint="Постановление Правительства РФ от 12.03.2022 № 353",
        measure_type="certificate",
        document_required="Документы об оценке соответствия (в том числе в упрощенном режиме)",
        description="Особенности разрешительной деятельности и подтверждения соответствия для импортируемой продукции.",
    ),
]

VAT_DOCS: list[tuple[str, str, int, str]] = [
    (
        "https://www.alta.ru/tamdoc/04ps0908/",
        "Постановление Правительства РФ от 31.12.2004 № 908",
        10,
        "Живая рыба для пищевых/кормовых целей (при соблюдении условий перечня).",
    ),
    (
        "https://www.alta.ru/tamdoc/21ps1982/",
        "Постановление Правительства РФ от 20.11.2021 № 1982",
        10,
        "Уточнение перечня по видам форели и связанным товарным позициям.",
    ),
]


def _fetch_title(url: str, fallback_title: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    try:
        with httpx.Client(headers=headers, follow_redirects=True, timeout=40.0) as client:
            resp = client.get(url)
            resp.raise_for_status()
            html = resp.text
    except Exception:
        return fallback_title
    soup = BeautifulSoup(html, "lxml")
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return re.sub(r"\s+", " ", h1.get_text(" ", strip=True)).strip()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    return re.sub(r"\s+", " ", title).strip() or fallback_title


def _upsert_non_tariff_for_0301() -> dict[str, int]:
    target_codes: list[str] = []
    created = 0
    duplicates = 0
    downloaded = 0

    with SessionLocal() as db:
        db_codes = [
            code
            for (code,) in db.execute(
                text("SELECT code FROM tnved_commodities WHERE code LIKE '0301%' AND length(code)=10")
            ).fetchall()
        ]
        target_codes = sorted(set(db_codes + ["0301000000"]))

        existing_keys = {
            (
                m.commodity_code,
                (m.measure_type or "").strip().lower(),
                (m.regulatory_act or "").strip(),
            )
            for m in db.query(NonTariffMeasure).filter(NonTariffMeasure.commodity_code.in_(target_codes)).all()
        }

        batch: list[NonTariffMeasure] = []
        for src in DOCS:
            title = _fetch_title(src.url, src.title_hint)
            if title != src.title_hint:
                downloaded += 1

            reg_act = f"{title} ({src.url})"
            for commodity_code in target_codes:
                key = (
                    commodity_code,
                    src.measure_type,
                    reg_act,
                )
                if key in existing_keys:
                    duplicates += 1
                    continue
                existing_keys.add(key)
                batch.append(
                    NonTariffMeasure(
                        commodity_code=commodity_code,
                        measure_type=src.measure_type,
                        description=src.description,
                        document_required=src.document_required,
                        regulatory_act=reg_act,
                    )
                )

        if batch:
            db.bulk_save_objects(batch)
            db.commit()
            created = len(batch)

    return {
        "created": created,
        "duplicates": duplicates,
        "downloaded": downloaded,
        "target_codes": len(target_codes),
    }


def _upsert_vat_for_0301() -> dict[str, int]:
    hs_prefix = "0301"
    created = 0
    updated = 0
    downloaded = 0

    with SessionLocal() as db:
        for url, title_hint, rate, comment in VAT_DOCS:
            title = _fetch_title(url, title_hint)
            if title != title_hint:
                downloaded += 1
            decree = f"{title} ({url})"
            row = (
                db.query(VatPreference)
                .filter(
                    VatPreference.hs_code_prefix == hs_prefix,
                    VatPreference.vat_rate == rate,
                    VatPreference.decree_info == decree,
                )
                .first()
            )
            if row:
                row.comment = comment
                updated += 1
            else:
                db.add(
                    VatPreference(
                        hs_code_prefix=hs_prefix,
                        vat_rate=rate,
                        decree_info=decree,
                        comment=comment,
                    )
                )
                created += 1
        db.commit()

    return {"created": created, "updated": updated, "downloaded": downloaded}


def main() -> None:
    nt = _upsert_non_tariff_for_0301()
    vat = _upsert_vat_for_0301()
    print(
        {
            "status": "OK",
            "target_code_prefix": "0301",
            "non_tariff": nt,
            "vat_preferences": vat,
        }
    )


if __name__ == "__main__":
    main()
