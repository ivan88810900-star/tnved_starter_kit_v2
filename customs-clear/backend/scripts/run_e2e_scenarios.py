#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import sys
import traceback
from dataclasses import dataclass
from typing import Any

from fastapi.testclient import TestClient

ROOT_OK = "✅"
ROOT_FAIL = "❌"
ROOT_INFO = "🔎"
ROOT_STEP = "➡️"


def _log(msg: str) -> None:
    print(msg, flush=True)


def _pretty(data: Any) -> str:
    try:
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception:
        return str(data)


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


@dataclass
class ScenarioResult:
    name: str
    ok: bool
    detail: str = ""


def _extract_docs_from_ved_response(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("items") or []
    if not items:
        return []
    item0 = items[0] if isinstance(items[0], dict) else {}
    profile = item0.get("payment_profile") if isinstance(item0, dict) else {}
    if not isinstance(profile, dict):
        return []
    docs = profile.get("documents") or []
    if not isinstance(docs, list):
        return []
    return [d for d in docs if isinstance(d, dict)]


def scenario_1_registry_matching(client: TestClient) -> ScenarioResult:
    name = "Сценарий 1: Умный комплаенс + сверка реестров"
    _log(f"\n{ROOT_STEP} {name}")

    # CSV в формате, максимально близком к инвойсу (чтобы анализатор собрал item_data).
    csv_text = (
        "name,brand,article,qty,price,currency,hs_code\n"
        "Apple iPhone 15 Pro Max 256GB,Apple,A3108,1,150000,RUB,8517130000\n"
    )
    files = {
        "document": (
            "iphone_invoice.csv",
            io.BytesIO(csv_text.encode("utf-8")),
            "text/csv",
        )
    }
    data = {
        "country": "CN",
        "run_payment": "true",
        "persist": "false",
        "verify_fsa": "false",
        "skip_registry_verify": "true",
        "extract_permits": "false",
    }

    _log(f"{ROOT_INFO} Отправляем /api/documents/ved-intelligent-analyze для iPhone")
    resp = client.post("/api/documents/ved-intelligent-analyze", files=files, data=data)
    _assert(resp.status_code == 200, f"Ожидали 200, получили {resp.status_code}: {resp.text[:600]}")
    payload = resp.json()

    docs = _extract_docs_from_ved_response(payload)
    _assert(docs, "В ответе нет payment_profile.documents (items[0].payment_profile.documents).")

    _log(f"{ROOT_INFO} Найдено документов комплаенса: {len(docs)}")
    _log(_pretty(docs[:6]))

    has_vet = any(str(d.get("doc_type") or "").strip().lower() == "ветконтроль" for d in docs)
    _assert(not has_vet, "Найден Ветконтроль, но для 8517130000 его быть не должно.")

    fsb_docs = [
        d
        for d in docs
        if str(d.get("doc_type") or "").strip().lower() == "нотификация фсб"
        or "нотификация фсб" in str(d.get("title") or "").strip().lower()
    ]
    _assert(fsb_docs, "Не нашли документ 'Нотификация ФСБ' в payment_profile.documents.")

    fsb_doc = fsb_docs[0]
    reg_match = str(fsb_doc.get("registry_match") or "").strip()
    _assert(reg_match != "", "У документа ФСБ пустое поле registry_match.")
    _assert(reg_match.startswith("Найдена"), f"registry_match не начинается с 'Найдена...': {reg_match}")

    _log(f"{ROOT_OK} Проверка пройдена: ФСБ найден, vet отсутствует, registry_match='{reg_match}'")
    return ScenarioResult(name=name, ok=True, detail=reg_match)


def scenario_2_embargo(client: TestClient) -> ScenarioResult:
    name = "Сценарий 2: Санкции и эмбарго"
    _log(f"\n{ROOT_STEP} {name}")

    body = {
        "hs_code": "8542319000",
        "customs_value": 2500000,
        "invoice_currency": "RUB",
        "freight": 150000,
        "country": "US",
        "save_history": False,
    }
    _log(f"{ROOT_INFO} Отправляем /api/calculator/compute: {_pretty(body)}")
    resp = client.post("/api/calculator/compute", json=body)
    _assert(resp.status_code == 200, f"Ожидали 200, получили {resp.status_code}: {resp.text[:600]}")
    payload = resp.json()

    geo = payload.get("geo") or {}
    status = str(payload.get("status") or "")
    embargo_flag = bool(geo.get("embargo"))

    text_blob = " ".join(
        [
            status,
            str(geo.get("document_basis") or ""),
            str(geo.get("measure_type") or ""),
            str(geo.get("note") or ""),
            str(geo.get("reason") or ""),
        ]
    ).lower()

    has_forbidden_text = any(tok in text_blob for tok in ("эмбар", "запрет", "forbid", "prohibit"))
    _assert(
        embargo_flag or status.upper() == "EMBARGO",
        f"Не сработало эмбарго: status={status}, geo={_pretty(geo)}",
    )
    _assert(
        has_forbidden_text,
        f"Не нашли текстовое описание запрета/эмбарго в geo/status: {_pretty({'status': status, 'geo': geo})}",
    )

    _log(f"{ROOT_OK} Эмбарго подтверждено: embargo={embargo_flag}, status={status}")
    return ScenarioResult(name=name, ok=True, detail=f"embargo={embargo_flag}, status={status}")


def scenario_3_feedback_loop(client: TestClient) -> ScenarioResult:
    name = "Сценарий 3: Петля самообучения (feedback loop)"
    _log(f"\n{ROOT_STEP} {name}")

    calc_body = {
        "hs_code": "6601100000",
        "customs_value": 45000,
        "invoice_currency": "RUB",
        "freight": 2000,
        "country": "CN",
        "save_history": False,
    }
    _log(f"{ROOT_INFO} Прогреваем сценарий через /api/calculator/compute")
    calc_resp = client.post("/api/calculator/compute", json=calc_body)
    _assert(calc_resp.status_code == 200, f"compute вернул {calc_resp.status_code}: {calc_resp.text[:400]}")

    approve_body = {
        "original_description": "Зонт-трость нейлоновый",
        "approved_hs_code": "6601100000",
        "invoice_context": "позиция E2E, бренд DemoUmbrella, артикул UMB-001",
        "user_note": "E2E feedback approve",
    }
    _log(f"{ROOT_INFO} Отправляем /api/classify/feedback/approve: {_pretty(approve_body)}")
    approve_resp = client.post("/api/classify/feedback/approve", json=approve_body)
    _assert(
        approve_resp.status_code == 201,
        f"Ожидали 201 Created, получили {approve_resp.status_code}: {approve_resp.text[:600]}",
    )
    approve_payload = approve_resp.json()
    _assert(
        bool(approve_payload.get("embedding_scheduled")) is True,
        f"Ожидали embedding_scheduled=True, получили: {_pretty(approve_payload)}",
    )

    _log(
        f"{ROOT_OK} Feedback loop OK: example_id={approve_payload.get('example_id')} "
        f"embedding_scheduled={approve_payload.get('embedding_scheduled')}"
    )
    return ScenarioResult(name=name, ok=True, detail=f"example_id={approve_payload.get('example_id')}")


def main() -> int:
    try:
        from app.main import app
    except Exception:
        _log(f"{ROOT_FAIL} Не удалось импортировать app.main: проверьте запуск из customs-clear/backend")
        _log(traceback.format_exc())
        return 2

    _log("🚀 Запуск E2E сценариев (TestClient/FastAPI)")
    _log("   Цель: проверить комплаенс, эмбарго и feedback loop сквозным вызовом API.\n")

    scenarios = [
        scenario_1_registry_matching,
        scenario_2_embargo,
        scenario_3_feedback_loop,
    ]

    results: list[ScenarioResult] = []
    with TestClient(app) as client:
        for fn in scenarios:
            try:
                results.append(fn(client))
            except Exception as exc:
                err = f"{type(exc).__name__}: {exc}"
                _log(f"{ROOT_FAIL} {fn.__name__} упал: {err}")
                _log(traceback.format_exc())
                results.append(ScenarioResult(name=fn.__name__, ok=False, detail=err))

    _log("\n📊 Итог E2E:")
    ok_count = 0
    for r in results:
        mark = ROOT_OK if r.ok else ROOT_FAIL
        _log(f"  {mark} {r.name} — {r.detail}")
        if r.ok:
            ok_count += 1

    _log(f"\n{ROOT_INFO} Успешно: {ok_count}/{len(results)}")
    return 0 if ok_count == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

