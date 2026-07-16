#!/usr/bin/env python3
"""End-to-end acceptance of the current CustomsClear MVP slices.

The script uses the real FastAPI application and a cookie-authenticated declarant
session. It intentionally avoids external services, persistent feedback writes,
semantic-vector ingestion, and feature-flag rollout.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import sys
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi.testclient import TestClient

ROOT_OK = "✅"
ROOT_FAIL = "❌"
ROOT_INFO = "🔎"
ROOT_STEP = "➡️"


def _log(message: str) -> None:
    print(message, flush=True)


def _pretty(data: Any) -> str:
    try:
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception:
        return str(data)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _prepare_e2e_environment() -> tuple[str, str]:
    """Provide process-local secrets when the caller did not configure them."""
    os.environ.setdefault("SECRET_KEY", secrets.token_urlsafe(48))
    username = (os.getenv("E2E_USERNAME") or "declarant").strip()
    password_env_by_user = {
        "admin": "ADMIN_PASSWORD",
        "viewer": "VIEWER_PASSWORD",
        "declarant": "DECLARANT_PASSWORD",
    }
    password_env = password_env_by_user.get(username)
    _assert(password_env is not None, f"Неизвестный E2E_USERNAME: {username}")
    password = (os.getenv("E2E_PASSWORD") or os.getenv(password_env) or "").strip()
    if not password:
        password = secrets.token_urlsafe(24)
    os.environ.setdefault(password_env, password)
    for env_name in password_env_by_user.values():
        os.environ.setdefault(env_name, secrets.token_urlsafe(24))
    return username, password


@dataclass
class AcceptanceContext:
    hs_code: str = ""
    product_name: str = ""
    payment: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScenarioResult:
    name: str
    ok: bool
    detail: str = ""


def _login(client: TestClient, username: str, password: str) -> None:
    anonymous = client.post(
        "/api/risk/check",
        json={"hs_code": "8509400000", "country": "CN"},
    )
    _assert(anonymous.status_code == 401, "Защищённый risk endpoint доступен без входа")
    response = client.post(
        "/api/auth/login",
        data={"username": username, "password": password},
    )
    _assert(response.status_code == 200, f"Вход не выполнен: {response.status_code} {response.text[:500]}")
    payload = response.json()
    _assert(payload.get("status") == "OK", f"Неожиданный ответ входа: {_pretty(payload)}")
    me = client.get("/api/auth/me")
    _assert(me.status_code == 200 and me.json().get("authenticated"), "Cookie-сессия не сохранилась")


def scenario_search_and_card(client: TestClient, ctx: AcceptanceContext) -> ScenarioResult:
    name = "Умный поиск и карточка ТН ВЭД"
    _log(f"\n{ROOT_STEP} {name}")
    searches = [
        (os.getenv("E2E_SEARCH_QUERY") or "").strip(),
        "9988100000",
        "8509400000",
        "ноутбук",
    ]
    selected: dict[str, Any] | None = None
    selected_body: dict[str, Any] = {}
    for query in dict.fromkeys(q for q in searches if q):
        response = client.get("/api/v1/tnved/search", params={"q": query, "limit": 8})
        _assert(response.status_code == 200, f"Поиск {query!r}: HTTP {response.status_code}")
        body = response.json()
        selected = next(iter(body.get("results") or []), None)
        if selected:
            selected_body = body
            break
    _assert(selected is not None, "Поиск не вернул ни одного кода ТН ВЭД")
    strategy = str((selected_body.get("search") or {}).get("strategy") or "")
    _assert(strategy in {"hybrid_fts", "like_fallback"}, f"Неизвестная стратегия поиска: {strategy}")

    ctx.hs_code = str(selected.get("code") or "")
    ctx.product_name = str(selected.get("name") or "")
    card = client.get(f"/api/v1/tnved/{ctx.hs_code}")
    _assert(card.status_code == 200, f"Карточка {ctx.hs_code}: HTTP {card.status_code} {card.text[:500]}")
    card_body = card.json()
    _assert(str(card_body.get("code") or "") == ctx.hs_code, "Карточка вернула другой код")
    _assert(bool(card_body.get("description") or ctx.product_name), "В карточке отсутствует наименование")

    anchor = selected.get("canonical_anchor") or card_body.get("canonical_anchor")
    if anchor:
        _assert(bool(anchor.get("stable_id")), "Canonical anchor не содержит stable_id")
        _assert(bool(anchor.get("snapshot_id")), "Canonical anchor не содержит snapshot_id")
    detail = (
        f"code={ctx.hs_code}, leaf={bool(selected.get('is_leaf'))}, strategy={strategy}, "
        f"canonical={'yes' if anchor else 'soft-fallback'}"
    )
    _log(f"{ROOT_OK} {detail}")
    return ScenarioResult(name=name, ok=True, detail=detail)


def scenario_payments(client: TestClient, ctx: AcceptanceContext) -> ScenarioResult:
    name = "Объяснимые таможенные платежи"
    _log(f"\n{ROOT_STEP} {name}")
    body: dict[str, Any] = {}
    selected_code = ""
    candidates = [
        ctx.hs_code,
        (os.getenv("E2E_PAYMENT_HS_CODE") or "").strip(),
        "8509400000",
        "0201300000",
        "8471300000",
    ]
    for code in dict.fromkeys(code for code in candidates if code):
        response = client.post(
            "/api/calculator/compute",
            json={
                "hs_code": code,
                "customs_value": 100000,
                "invoice_currency": "RUB",
                "freight": 5000,
                "country": "CN",
                "save_history": False,
            },
        )
        _assert(response.status_code == 200, f"Расчёт {code}: HTTP {response.status_code} {response.text[:700]}")
        candidate_body = response.json()
        if candidate_body.get("status") != "CLARIFICATION_NEEDED":
            body = candidate_body
            selected_code = code
            break
    _assert(selected_code, "Расчёт не нашёл ни одного подтверждённого конечного кода")
    ctx.hs_code = selected_code
    breakdown = body.get("breakdown") or {}
    _assert("vat_rate" in breakdown, f"В расчёте нет ставки НДС: {_pretty(body)}")
    _assert(float(breakdown.get("vat_rate") or 0) in {0.0, 10.0, 22.0}, "Недопустимая ставка НДС")
    total = float(body.get("total_payable") or breakdown.get("total_payable") or 0)
    _assert(total >= 0, "Отрицательная итоговая сумма платежей")
    ctx.payment = body
    detail = f"vat={breakdown.get('vat_rate')}%, total={total:.2f} RUB"
    _log(f"{ROOT_OK} {detail}")
    return ScenarioResult(name=name, ok=True, detail=detail)


def scenario_requirements_and_risk(client: TestClient, ctx: AcceptanceContext) -> ScenarioResult:
    name = "Нормативные требования и evidence-first риск"
    _log(f"\n{ROOT_STEP} {name}")
    normative = client.post(
        "/api/non_tariff/normative-block",
        json={
            "items": [
                {
                    "hs_code": ctx.hs_code,
                    "description": ctx.product_name,
                    "country": "CN",
                    "permits": [],
                }
            ]
        },
    )
    _assert(normative.status_code == 200, f"Normative block: HTTP {normative.status_code} {normative.text[:700]}")
    normative_body = normative.json()
    _assert(normative_body.get("items"), "Normative block не вернул позицию")
    block = normative_body["items"][0].get("normative_block") or {}
    for field_name in ("required_documents", "missing_documents", "advisory_requirements"):
        _assert(isinstance(block.get(field_name, []), list), f"{field_name} должен быть списком")

    risk = client.post(
        "/api/risk/check",
        json={
            "hs_code": ctx.hs_code,
            "description": ctx.product_name,
            "country": "CN",
        },
    )
    _assert(risk.status_code == 200, f"Risk block: HTTP {risk.status_code} {risk.text[:700]}")
    risk_body = risk.json()
    _assert(risk_body.get("status") in {"OK", "WARNING", "CRITICAL", "MANUAL_REVIEW"}, "Неизвестный risk status")
    _assert(isinstance(risk_body.get("coverage_complete"), bool), "Не указан coverage_complete")
    _assert(isinstance(risk_body.get("source_coverage"), list), "Нет сведений о покрытии источников")
    _assert(bool(risk_body.get("disclaimer")), "Нет диагностического disclaimer")
    if not risk_body.get("coverage_complete"):
        _assert(
            risk_body.get("status") != "OK" or bool(risk_body.get("warnings")),
            "Неполное покрытие ошибочно показано как безусловно чистый результат",
        )
    detail = f"normative={normative_body.get('status')}, risk={risk_body.get('status')}, coverage={risk_body.get('coverage_complete')}"
    _log(f"{ROOT_OK} {detail}")
    return ScenarioResult(name=name, ok=True, detail=detail)


def scenario_grounded_assistant(client: TestClient, ctx: AcceptanceContext) -> ScenarioResult:
    name = "Grounded AI-помощник"
    _log(f"\n{ROOT_STEP} {name}")
    breakdown = ctx.payment.get("breakdown") or {}
    response = client.post(
        "/api/v1/assistant/chat",
        json={
            "message": "Какие документы, платежи и риски нужно проверить по этому товару?",
            "history": [],
            "current_context": {
                "hs_code": ctx.hs_code,
                "product_name": ctx.product_name,
                "origin_country": "CN",
                "total_payable": ctx.payment.get("total_payable") or breakdown.get("total_payable"),
            },
        },
    )
    _assert(response.status_code == 200, f"Assistant: HTTP {response.status_code} {response.text[:900]}")
    body = response.json()
    _assert(body.get("status") == "OK", f"Assistant status: {_pretty(body)}")
    _assert(bool(str(body.get("answer") or "").strip()), "Ассистент вернул пустой ответ")
    grounding = body.get("grounding") or {}
    _assert(grounding.get("mode") in {"deterministic", "llm_grounded"}, "Ответ не прошёл grounding")
    citations = grounding.get("citations") or []
    _assert(bool(citations), "Grounded-ответ не содержит источников")
    suggestions = body.get("suggestions") or []
    _assert(bool(suggestions), "Ассистент не предложил следующие действия")
    detail = f"mode={grounding.get('mode')}, citations={len(citations)}, actions={len(suggestions)}"
    _log(f"{ROOT_OK} {detail}")
    return ScenarioResult(name=name, ok=True, detail=detail)


def main() -> int:
    username, password = _prepare_e2e_environment()
    try:
        from app.main import app
        from app.services.normative_store import init_db
    except Exception:
        _log(f"{ROOT_FAIL} Не удалось импортировать app.main")
        _log(traceback.format_exc())
        return 2

    _log("🚀 CustomsClear MVP end-to-end acceptance")
    _log("   Реальный FastAPI stack, cookie-auth, без внешнего LLM и без включения feature flags.\n")
    ctx = AcceptanceContext()
    scenarios: list[Callable[[TestClient, AcceptanceContext], ScenarioResult]] = [
        scenario_search_and_card,
        scenario_payments,
        scenario_requirements_and_risk,
        scenario_grounded_assistant,
    ]
    results: list[ScenarioResult] = []
    init_db()
    with TestClient(app) as client:
        try:
            _login(client, username, password)
            _log(f"{ROOT_OK} Авторизация и cookie-сессия")
        except Exception as exc:
            _log(f"{ROOT_FAIL} Авторизация: {exc}")
            return 1
        for scenario in scenarios:
            try:
                results.append(scenario(client, ctx))
            except Exception as exc:
                detail = f"{type(exc).__name__}: {exc}"
                _log(f"{ROOT_FAIL} {scenario.__name__}: {detail}")
                _log(traceback.format_exc())
                results.append(ScenarioResult(name=scenario.__name__, ok=False, detail=detail))
                break

    _log("\n📊 Итог MVP acceptance:")
    for result in results:
        _log(f"  {ROOT_OK if result.ok else ROOT_FAIL} {result.name} — {result.detail}")
    ok_count = sum(1 for result in results if result.ok)
    _log(f"\n{ROOT_INFO} Успешно: {ok_count}/{len(scenarios)}")
    return 0 if ok_count == len(scenarios) else 1


if __name__ == "__main__":
    raise SystemExit(main())
