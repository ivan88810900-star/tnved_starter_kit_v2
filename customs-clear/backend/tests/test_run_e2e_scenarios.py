"""Regression tests for the read-only MVP acceptance harness."""

from __future__ import annotations

from typing import Any

from scripts import run_e2e_scenarios as e2e


class _Response:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict[str, Any]:
        return self._payload


def test_prepare_environment_creates_process_local_secrets(monkeypatch) -> None:
    for name in (
        "SECRET_KEY",
        "ADMIN_PASSWORD",
        "VIEWER_PASSWORD",
        "DECLARANT_PASSWORD",
        "E2E_USERNAME",
        "E2E_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)

    username, password = e2e._prepare_e2e_environment()

    assert username == "declarant"
    assert password
    assert e2e.os.environ["DECLARANT_PASSWORD"] == password
    assert e2e.os.environ["SECRET_KEY"]
    assert e2e.os.environ["ADMIN_PASSWORD"]
    assert e2e.os.environ["VIEWER_PASSWORD"]


def test_prepare_environment_supports_configured_admin(monkeypatch) -> None:
    for name in ("SECRET_KEY", "ADMIN_PASSWORD", "VIEWER_PASSWORD", "DECLARANT_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("E2E_USERNAME", "admin")
    monkeypatch.setenv("E2E_PASSWORD", "admin-e2e-secret")

    username, password = e2e._prepare_e2e_environment()

    assert username == "admin"
    assert password == "admin-e2e-secret"
    assert e2e.os.environ["ADMIN_PASSWORD"] == password


def test_login_verifies_anonymous_rejection_and_cookie_session() -> None:
    class Client:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def post(self, path: str, **kwargs) -> _Response:  # noqa: ANN003
            self.calls.append(("POST", path))
            if path == "/api/risk/check":
                return _Response(401, {"detail": "authentication_required"})
            return _Response(200, {"status": "OK"})

        def get(self, path: str) -> _Response:
            self.calls.append(("GET", path))
            return _Response(200, {"authenticated": True})

    client = Client()
    e2e._login(client, "declarant", "secret")  # type: ignore[arg-type]

    assert client.calls == [
        ("POST", "/api/risk/check"),
        ("POST", "/api/auth/login"),
        ("GET", "/api/auth/me"),
    ]


def test_payments_fall_back_from_group_to_confirmed_leaf(monkeypatch) -> None:
    monkeypatch.delenv("E2E_PAYMENT_HS_CODE", raising=False)

    class Client:
        def __init__(self) -> None:
            self.codes: list[str] = []

        def post(self, path: str, *, json: dict[str, Any]) -> _Response:
            assert path == "/api/calculator/compute"
            code = str(json["hs_code"])
            self.codes.append(code)
            if code == "9988100000":
                return _Response(200, {"status": "CLARIFICATION_NEEDED"})
            return _Response(
                200,
                {
                    "status": "OK",
                    "breakdown": {"vat_rate": 22.0, "total_payable": 38481.0},
                },
            )

    client = Client()
    ctx = e2e.AcceptanceContext(hs_code="9988100000", product_name="Тест")
    result = e2e.scenario_payments(client, ctx)  # type: ignore[arg-type]

    assert result.ok is True
    assert ctx.hs_code == "8509400000"
    assert client.codes == ["9988100000", "8509400000"]
