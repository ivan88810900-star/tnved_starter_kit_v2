#!/usr/bin/env python3
"""End-to-end acceptance of the current CustomsClear MVP slices.

The script uses the real FastAPI application and a cookie-authenticated declarant
session. It intentionally avoids external services, persistent feedback writes,
semantic-vector ingestion, and feature-flag rollout.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import sys
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import unquote

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

ROOT_OK = "✅"
ROOT_FAIL = "❌"
ROOT_INFO = "🔎"
ROOT_STEP = "➡️"

FULL_DATA_MINIMUMS = {
    "tnved_sections": 20,
    "tnved_chapters": 90,
    "tnved_commodities": 10_000,
    "hs_rates": 3_000,
}


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
    # This must be set before importing app.db/app.main: the engine is created
    # once and opens SQLite with mode=ro + PRAGMA query_only.
    os.environ["CUSTOMSCLEAR_READ_ONLY"] = "1"
    os.environ["AUDIT_LOG_ENABLED"] = "0"
    os.environ["REGULATORY_SYNC_SCHEDULER_ENABLED"] = "false"
    os.environ["SCHEDULER_ENABLED"] = "false"
    os.environ["CANONICAL_TREE_ENABLED"] = "0"
    os.environ["CANONICAL_TREE_SHADOW"] = "0"
    # The acceptance is deterministic and must not spend API quota or send data
    # outside the machine even when backend/.env contains an LLM key.
    os.environ["GEMINI_API_KEY"] = ""
    os.environ["GOOGLE_API_KEY"] = ""
    os.environ["ANTHROPIC_API_KEY"] = ""
    if not (os.getenv("SECRET_KEY") or "").strip():
        os.environ["SECRET_KEY"] = secrets.token_urlsafe(48)
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
    os.environ[password_env] = password
    for env_name in password_env_by_user.values():
        if not (os.getenv(env_name) or "").strip():
            os.environ[env_name] = secrets.token_urlsafe(24)
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
    metrics: dict[str, Any] = field(default_factory=dict)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only end-to-end acceptance of the CustomsClear MVP",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="Write a compact JSON report to this path (no secrets or product records).",
    )
    parser.add_argument(
        "--require-full-data",
        action="store_true",
        help="Fail unless the database meets the full-data minimum row counts.",
    )
    return parser.parse_args(argv)


def _sqlite_database_path(engine: Any) -> Path | None:
    if engine.dialect.name != "sqlite":
        return None
    database = str(engine.url.database or "")
    if not database or database == ":memory:":
        return None
    if database.startswith("file:"):
        database = unquote(database[5:])
    database = database.split("?", 1)[0]
    return Path(database).expanduser().resolve()


def _file_state(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"available": False}
    try:
        stat = path.stat()
    except FileNotFoundError:
        return {"available": False, "filename": path.name}
    return {
        "available": True,
        "filename": path.name,
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _meets_full_data_minimums(counts: dict[str, int | None]) -> bool:
    return all(
        int(counts.get(table_name) or 0) >= minimum
        for table_name, minimum in FULL_DATA_MINIMUMS.items()
    )


def _database_profile(engine: Any) -> dict[str, Any]:
    """Return aggregate-only diagnostics without exposing paths or row contents."""
    from sqlalchemy import inspect, text

    path = _sqlite_database_path(engine)
    counts: dict[str, int | None] = {}
    read_only_enforced = False
    with engine.connect() as connection:
        table_names = set(inspect(connection).get_table_names())
        for table_name in FULL_DATA_MINIMUMS:
            if table_name not in table_names:
                counts[table_name] = None
                continue
            counts[table_name] = int(
                connection.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar_one()
            )
        if engine.dialect.name == "sqlite":
            read_only_enforced = bool(
                connection.execute(text("PRAGMA query_only")).scalar_one()
            )

    full_data_ok = _meets_full_data_minimums(counts)
    return {
        "dialect": engine.dialect.name,
        "filename": path.name if path else None,
        "size_bytes": _file_state(path).get("size_bytes"),
        "read_only_enforced": read_only_enforced,
        "counts": counts,
        "minimums": dict(FULL_DATA_MINIMUMS),
        "full_data_ok": full_data_ok,
    }


def _scenario_payload(result: ScenarioResult) -> dict[str, Any]:
    payload = {
        "name": result.name,
        "ok": result.ok,
        "metrics": result.metrics,
    }
    if result.ok:
        payload["detail"] = result.detail
    else:
        payload["error_type"] = result.detail.partition(":")[0] or "ScenarioError"
    return payload


def _safe_error(phase: str, exc: Exception) -> dict[str, str]:
    """Keep machine-readable failures free of paths, secrets and response bodies."""
    return {"phase": phase, "type": type(exc).__name__}


def _write_report(path: Path | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    _log(f"{ROOT_INFO} JSON-отчёт: {target}")


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
    return ScenarioResult(
        name=name,
        ok=True,
        detail=detail,
        metrics={
            "hs_code": ctx.hs_code,
            "is_leaf": bool(selected.get("is_leaf")),
            "search_strategy": strategy,
            "canonical_anchor_present": bool(anchor),
        },
    )


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
    return ScenarioResult(
        name=name,
        ok=True,
        detail=detail,
        metrics={
            "hs_code": selected_code,
            "vat_rate": float(breakdown.get("vat_rate") or 0),
            "total_payable_rub": total,
        },
    )


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
    return ScenarioResult(
        name=name,
        ok=True,
        detail=detail,
        metrics={
            "normative_status": normative_body.get("status"),
            "risk_status": risk_body.get("status"),
            "risk_coverage_complete": risk_body.get("coverage_complete"),
            "risk_sources": len(risk_body.get("source_coverage") or []),
        },
    )


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
    return ScenarioResult(
        name=name,
        ok=True,
        detail=detail,
        metrics={
            "mode": grounding.get("mode"),
            "citations": len(citations),
            "suggested_actions": len(suggestions),
        },
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    username, password = _prepare_e2e_environment()
    generated_at = datetime.now(timezone.utc).isoformat()
    report: dict[str, Any] = {
        "format": "customsclear-mvp-acceptance-v1",
        "generated_at": generated_at,
        "require_full_data": bool(args.require_full_data),
        "read_only": {
            "requested": True,
            "startup_mutations_disabled": False,
            "database_enforced": False,
            "main_database_file_unchanged": False,
        },
        "external_llm_enabled": False,
        "feature_flags": {
            "canonical_tree_enabled": False,
            "canonical_tree_shadow": False,
        },
        "database": {},
        "authentication_ok": False,
        "scenarios": [],
        "ok": False,
        "exit_code": 2,
    }
    try:
        from app.db import engine, is_read_only_mode
        from app.main import app
        from app.services.tree_engine.flags import (
            is_canonical_tree_enabled,
            is_canonical_tree_shadow_enabled,
        )
    except Exception as exc:
        _log(f"{ROOT_FAIL} Не удалось импортировать app.main")
        _log(traceback.format_exc())
        report["error"] = _safe_error("app_import", exc)
        _write_report(args.report, report)
        return 2

    read_only_mode = is_read_only_mode()
    canonical_enabled = is_canonical_tree_enabled()
    canonical_shadow = is_canonical_tree_shadow_enabled()
    report["read_only"]["startup_mutations_disabled"] = read_only_mode
    report["feature_flags"] = {
        "canonical_tree_enabled": canonical_enabled,
        "canonical_tree_shadow": canonical_shadow,
    }

    database_path = _sqlite_database_path(engine)
    database_before = _file_state(database_path)
    try:
        database = _database_profile(engine)
    except Exception as exc:
        _log(f"{ROOT_FAIL} Не удалось проверить базу данных: {exc}")
        _log(traceback.format_exc())
        report["error"] = _safe_error("database_profile", exc)
        report["database"] = {"filename": database_before.get("filename")}
        _write_report(args.report, report)
        return 2
    report["database"] = database
    report["read_only"]["database_enforced"] = database["read_only_enforced"]

    if not read_only_mode or not database["read_only_enforced"]:
        _log(f"{ROOT_FAIL} База не открыта в строгом read-only режиме; прогон остановлен")
        report["error"] = "strict_read_only_not_enforced"
        _write_report(args.report, report)
        return 2
    if canonical_enabled or canonical_shadow:
        _log(f"{ROOT_FAIL} Canonical feature flags должны быть выключены")
        report["error"] = "canonical_feature_flags_enabled"
        _write_report(args.report, report)
        return 2

    _log("🚀 CustomsClear MVP end-to-end acceptance")
    _log("   Строгий read-only, cookie-auth, без внешнего LLM и без включения feature flags.")
    counts = database["counts"]
    _log(
        "   База: "
        f"sections={counts.get('tnved_sections')}, chapters={counts.get('tnved_chapters')}, "
        f"commodities={counts.get('tnved_commodities')}, hs_rates={counts.get('hs_rates')}\n"
    )
    ctx = AcceptanceContext()
    scenarios: list[Callable[[TestClient, AcceptanceContext], ScenarioResult]] = [
        scenario_search_and_card,
        scenario_payments,
        scenario_requirements_and_risk,
        scenario_grounded_assistant,
    ]
    results: list[ScenarioResult] = []
    authentication_ok = False
    try:
        with TestClient(app) as client:
            try:
                _login(client, username, password)
                authentication_ok = True
                _log(f"{ROOT_OK} Авторизация и cookie-сессия")
            except Exception as exc:
                _log(f"{ROOT_FAIL} Авторизация: {exc}")
                report["authentication_error"] = _safe_error("authentication", exc)
            if authentication_ok:
                for scenario in scenarios:
                    try:
                        results.append(scenario(client, ctx))
                    except Exception as exc:
                        detail = f"{type(exc).__name__}: {exc}"
                        _log(f"{ROOT_FAIL} {scenario.__name__}: {detail}")
                        _log(traceback.format_exc())
                        results.append(ScenarioResult(name=scenario.__name__, ok=False, detail=detail))
                        break
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        _log(f"{ROOT_FAIL} Приложение не запустилось в read-only режиме: {detail}")
        _log(traceback.format_exc())
        report["application_error"] = _safe_error("application_lifespan", exc)

    database_after = _file_state(database_path)
    database_file_unchanged = database_before == database_after
    report["read_only"]["main_database_file_unchanged"] = database_file_unchanged
    report["authentication_ok"] = authentication_ok
    report["scenarios"] = [_scenario_payload(result) for result in results]

    _log("\n📊 Итог MVP acceptance:")
    for result in results:
        _log(f"  {ROOT_OK if result.ok else ROOT_FAIL} {result.name} — {result.detail}")
    ok_count = sum(1 for result in results if result.ok)
    _log(f"\n{ROOT_INFO} Успешно: {ok_count}/{len(scenarios)}")
    if not database_file_unchanged:
        _log(f"{ROOT_FAIL} Основной файл базы данных изменился во время read-only прогона")
    if args.require_full_data and not database["full_data_ok"]:
        _log(f"{ROOT_FAIL} База не достигла минимального объёма полного набора данных")

    scenarios_ok = authentication_ok and ok_count == len(scenarios)
    full_data_gate_ok = database["full_data_ok"] or not args.require_full_data
    overall_ok = scenarios_ok and database_file_unchanged and full_data_gate_ok
    exit_code = 0 if overall_ok else 1
    report["ok"] = overall_ok
    report["exit_code"] = exit_code
    _write_report(args.report, report)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
