from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from google.api_core.exceptions import PermissionDenied, RetryError, ServiceUnavailable

from app.services import ai_assistant


def _install_model(monkeypatch: pytest.MonkeyPatch, outcome: object) -> None:
    class FakeModel:
        def generate_content(self, *_args, **_kwargs):
            if isinstance(outcome, BaseException):
                raise outcome
            return SimpleNamespace(text=outcome)

    monkeypatch.setenv("GEMINI_API_KEY", "configured-test-key")
    monkeypatch.setattr(
        ai_assistant,
        "configure_google_generativeai",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(ai_assistant, "resolved_gemini_model_name", lambda: "test-model")
    monkeypatch.setattr(ai_assistant.genai, "GenerativeModel", lambda _name: FakeModel())


def _ask() -> str:
    return asyncio.run(
        ai_assistant.ask_ai_assistant(
            question="Что указано в примечаниях?",
            code="8517620000",
            notes="Тестовые примечания",
        )
    )


def test_missing_key_keeps_generic_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    assert _ask() == ai_assistant._WARN_GENERIC


def test_provider_outage_keeps_generic_warning_without_details(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "https://provider.invalid/generate?key=SECRET"
    _install_model(monkeypatch, ServiceUnavailable(secret))

    answer = _ask()

    assert answer == ai_assistant._WARN_GENERIC
    assert secret not in answer
    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err


def test_provider_permission_failure_keeps_region_warning_without_details(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "user location is not supported; key=SECRET"
    _install_model(monkeypatch, PermissionDenied(secret))

    answer = _ask()

    assert answer == ai_assistant._WARN_REGION
    assert secret not in answer
    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err


@pytest.mark.parametrize(
    "provider_error",
    [
        TimeoutError("provider timeout"),
        RetryError("provider retry exhausted", cause=TimeoutError("timeout")),
    ],
    ids=["timeout", "retry-exhausted"],
)
def test_recognized_provider_failures_keep_generic_warning(
    monkeypatch: pytest.MonkeyPatch,
    provider_error: BaseException,
) -> None:
    _install_model(monkeypatch, provider_error)

    assert _ask() == ai_assistant._WARN_GENERIC


@pytest.mark.parametrize(
    "programming_error",
    [
        TypeError("wrong call contract"),
        ValueError("wrong data contract"),
        AttributeError("missing response attribute"),
        AssertionError("broken invariant"),
        KeyError("missing field"),
        RuntimeError("403 from unrelated application code"),
    ],
    ids=["type", "value", "attribute", "assertion", "key", "runtime"],
)
def test_programming_and_data_contract_errors_propagate(
    monkeypatch: pytest.MonkeyPatch,
    programming_error: BaseException,
) -> None:
    _install_model(monkeypatch, programming_error)

    with pytest.raises(type(programming_error), match="403|wrong|missing|broken"):
        _ask()


def test_empty_successful_output_keeps_notes_absent_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_model(monkeypatch, "   ")

    assert _ask() == "В примечаниях к данной группе эта информация отсутствует"
