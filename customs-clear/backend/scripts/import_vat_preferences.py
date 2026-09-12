from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))



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


def import_json(path: Path) -> dict[str, Any]:
    """Legacy CLI application is closed before file parsing or DB access."""
    from app.services.official_payment_admission import blocked_payment_import

    return blocked_payment_import(source="import_vat_preferences", domain="vat")


def generate_sample(path: Path) -> None:
    sample = [
        {
            "candidate_only": True,
            "legal_review_verified": False,
            "hs_code_prefix": "0101",
            "vat_rate": 10,
            "decree_info": "UNREVIEWED_EXAMPLE_NO_LEGAL_AUTHORITY",
            "comment": "Продовольственные товары (пример)",
        },
        {
            "candidate_only": True,
            "legal_review_verified": False,
            "hs_code_prefix": "3004",
            "vat_rate": 10,
            "decree_info": "UNREVIEWED_EXAMPLE_NO_LEGAL_AUTHORITY",
            "comment": "Лекарственные средства (пример)",
        },
        {
            "candidate_only": True,
            "legal_review_verified": False,
            "hs_code_prefix": "9018",
            "vat_rate": 10,
            "decree_info": "UNREVIEWED_EXAMPLE_NO_LEGAL_AUTHORITY",
            "comment": "Инструменты и аппаратура медицинские",
        },
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Sample VAT JSON создан: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Формат legacy НДС; применение без manifest-bound review закрыто")
    parser.add_argument("input", nargs="?", help="Путь к JSON-файлу")
    parser.add_argument("--generate-sample", default="", help="Создать sample JSON и выйти")
    args = parser.parse_args()

    if args.generate_sample:
        generate_sample(Path(args.generate_sample))
        return 0
    if not args.input:
        raise SystemExit("Укажите путь к JSON или используйте --generate-sample")
    result = import_json(Path(args.input))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
