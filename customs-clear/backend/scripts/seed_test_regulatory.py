"""Тестовое наполнение для проверки каркаса ведомственных документов."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.services.regulatory_ai_classifier import classify_document  # noqa: E402
from app.services.regulatory_fetcher import save_document  # noqa: E402

TEST_DOCS = [
    {
        "agency": "FTS",
        "doc_type": "order",
        "title": "Об утверждении Порядка совершения таможенных операций в отношении легковых автомобилей для личного пользования",
        "source_url": "https://test.local/fts/order-001",
        "body": (
            "Настоящий приказ определяет порядок таможенного оформления "
            "легковых автомобилей (ТН ВЭД 870323) при ввозе для личного пользования. "
            "В отношении автомобилей с объёмом двигателя 1500-3000 куб. см "
            "применяется единая ставка таможенных платежей."
        ),
    },
    {
        "agency": "MPT",
        "doc_type": "decree",
        "title": "Об утверждении Перечня товаров маркируемых средствами идентификации",
        "source_url": "https://test.local/mpt/decree-001",
        "body": (
            "Утвердить перечень товаров подлежащих обязательной маркировке: "
            "обувь (6401-6405), в т.ч. позиция 640399, парфюмерия (3303), фотокамеры (9006), "
            "шины (4011), легковые автомобили (8703)."
        ),
    },
    {
        "agency": "RPN",
        "doc_type": "order",
        "title": "Об усилении контроля БАД ввозимых из третьих стран",
        "source_url": "https://test.local/rpn/order-001",
        "body": (
            "Усилить контроль за ввозом биологически активных добавок к пище "
            "(коды 2106909200, 2106909800) из третьих стран. "
            "Обязательное предъявление СГР Роспотребнадзора."
        ),
    },
    {
        "agency": "RSN",
        "doc_type": "letter",
        "title": "О временном ограничении ввоза мясной продукции из Бразилии",
        "source_url": "https://test.local/rsn/letter-001",
        "body": (
            "Временно ограничить ввоз говядины (ТН ВЭД 020110, 020210) из Бразилии "
            "в связи с выявленными случаями заболеваний скота."
        ),
    },
    {
        "agency": "EEC",
        "doc_type": "decision",
        "title": "О внесении изменений в Решение №620 в части мобильных устройств 5G",
        "source_url": "https://test.local/eec/decision-001",
        "body": (
            "Включить в перечень обязательной сертификации мобильные телефоны "
            "(коды 851712) с поддержкой 5G."
        ),
    },
]


async def main() -> None:
    for d in TEST_DOCS:
        doc_id = save_document(**d)
        if doc_id:
            print(f"✅ Сохранён: {doc_id} | {d['title'][:80]}")
            try:
                mappings = await classify_document(doc_id)
                print(f"   → {len(mappings)} HS-привязок")
            except Exception as e:
                print(f"   ⚠️ AI не сработал: {e}")
        else:
            print(f"⏭️  Уже есть: {d['title'][:80]}")


if __name__ == "__main__":
    asyncio.run(main())
