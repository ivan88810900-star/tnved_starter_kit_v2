from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal
from app.models.tnved import VatPreference
from app.services.preview_cache_revision import bump_preview_cache_revision


def _norm_prefix(raw: object) -> str:
    d = re.sub(r"\D", "", str(raw or ""))
    if len(d) < 2:
        return ""
    return d[:10]


def _norm_rate(raw: object) -> int | None:
    try:
        v = int(str(raw).strip())
    except Exception:
        return None
    if v in (0, 10, 22):
        return v
    return None


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("items", "data", "vat_preferences"):
            if isinstance(payload.get(key), list):
                return [x for x in payload[key] if isinstance(x, dict)]
    return []


def import_json(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = _extract_items(payload)
    if not items:
        raise ValueError("JSON не содержит массива записей")

    created = 0
    updated = 0
    skipped = 0
    with SessionLocal() as db:
        for it in items:
            pref = _norm_prefix(it.get("hs_code_prefix") or it.get("hs_code"))
            rate = _norm_rate(it.get("vat_rate"))
            decree = str(it.get("decree_info") or "").strip()
            comment = str(it.get("comment") or it.get("description") or "").strip()
            if not pref or rate is None:
                skipped += 1
                continue
            row = (
                db.query(VatPreference)
                .filter(
                    VatPreference.hs_code_prefix == pref,
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
                        hs_code_prefix=pref,
                        vat_rate=rate,
                        decree_info=decree,
                        comment=comment,
                    )
                )
                created += 1
        db.commit()
    bump_preview_cache_revision("import_vat_preferences")
    print(f"[OK] VAT preferences: created={created}, updated={updated}, skipped={skipped}")


def generate_sample(path: Path) -> None:
    sample = [
        {
            "hs_code_prefix": "0101",
            "vat_rate": 10,
            "decree_info": "ПП РФ № 908",
            "comment": "Продовольственные товары (пример)",
        },
        {
            "hs_code_prefix": "3004",
            "vat_rate": 10,
            "decree_info": "ПП РФ № 688",
            "comment": "Лекарственные средства (пример)",
        },
        {
            "hs_code_prefix": "9018",
            "vat_rate": 10,
            "decree_info": "ПП РФ № 688 от 15.09.2008 (медицинские товары)",
            "comment": "Инструменты и аппаратура медицинские",
        },
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Sample VAT JSON создан: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Импорт льготных ставок НДС из JSON (ПП РФ №908/№688)")
    parser.add_argument("input", nargs="?", help="Путь к JSON-файлу")
    parser.add_argument("--generate-sample", default="", help="Создать sample JSON и выйти")
    args = parser.parse_args()

    if args.generate_sample:
        generate_sample(Path(args.generate_sample))
        return
    if not args.input:
        raise SystemExit("Укажите путь к JSON или используйте --generate-sample")
    import_json(Path(args.input))


if __name__ == "__main__":
    main()
