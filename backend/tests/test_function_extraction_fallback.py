from types import SimpleNamespace

import pytest

from app.services.regulation_functions.service import (
    RegulationFunctionExtractionError,
    extract_functions_or_fallback_match,
)


def test_extract_falls_back_when_cursor_unavailable(monkeypatch):
    calls = {"fallback": 0}

    def boom(*_args, **_kwargs):
        raise RegulationFunctionExtractionError("CURSOR_API_KEY не настроен", status_code=500)

    def fallback(*_args, **_kwargs):
        calls["fallback"] += 1
        return SimpleNamespace(runId="role-run-fallback")

    monkeypatch.setattr(
        "app.services.regulation_functions.service.create_cursor_function_extraction",
        boom,
    )
    monkeypatch.setattr(
        "app.services.regulation_functions.service.create_role_match_run",
        fallback,
    )

    result = extract_functions_or_fallback_match(
        SimpleNamespace(),
        user_id="user-1",
        regulation_id="reg-1",
        position="Секретарь",
        department="КУ",
    )
    assert result.runId == "role-run-fallback"
    assert calls["fallback"] == 1


def test_extract_does_not_fallback_on_missing_document(monkeypatch):
    def missing(*_args, **_kwargs):
        raise RegulationFunctionExtractionError("Регламент не найден", status_code=404)

    monkeypatch.setattr(
        "app.services.regulation_functions.service.create_cursor_function_extraction",
        missing,
    )
    monkeypatch.setattr(
        "app.services.regulation_functions.service.create_role_match_run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not fallback")),
    )

    with pytest.raises(RegulationFunctionExtractionError) as exc:
        extract_functions_or_fallback_match(
            SimpleNamespace(),
            user_id="user-1",
            regulation_id="reg-missing",
            position="Секретарь",
            department="КУ",
        )
    assert exc.value.status_code == 404


def test_extract_falls_back_when_cursor_returns_no_functions(monkeypatch):
    empty = SimpleNamespace(functions=[], matches=[])
    monkeypatch.setattr(
        "app.services.regulation_functions.service.create_cursor_function_extraction",
        lambda *_args, **_kwargs: empty,
    )
    monkeypatch.setattr(
        "app.services.regulation_functions.service.create_role_match_run",
        lambda *_args, **_kwargs: SimpleNamespace(runId="role-run-from-doc", functions=["ok"], matches=[]),
    )

    result = extract_functions_or_fallback_match(
        SimpleNamespace(),
        user_id="user-1",
        regulation_id="reg-1",
        position="Промпт-инженер 2 категории",
        department="Сектор ИИ",
    )
    assert result.runId == "role-run-from-doc"


def test_extract_falls_back_when_cursor_returns_invalid_json(monkeypatch):
    def bad_json(*_args, **_kwargs):
        raise RegulationFunctionExtractionError(
            "Cursor Agent не вернул корректный JSON",
            status_code=502,
        )

    monkeypatch.setattr(
        "app.services.regulation_functions.service.create_cursor_function_extraction",
        bad_json,
    )
    monkeypatch.setattr(
        "app.services.regulation_functions.service.create_role_match_run",
        lambda *_args, **_kwargs: SimpleNamespace(runId="role-run-json-fallback"),
    )

    result = extract_functions_or_fallback_match(
        SimpleNamespace(),
        user_id="user-1",
        regulation_id="reg-1",
        position="Помощник Председателя совета директоров",
        department="Корпоративное управление",
    )
    assert result.runId == "role-run-json-fallback"


def test_extract_falls_back_on_unexpected_error(monkeypatch):
    monkeypatch.setattr(
        "app.services.regulation_functions.service.create_cursor_function_extraction",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(
        "app.services.regulation_functions.service.create_role_match_run",
        lambda *_args, **_kwargs: SimpleNamespace(runId="role-run-ok"),
    )

    result = extract_functions_or_fallback_match(
        SimpleNamespace(),
        user_id="user-1",
        regulation_id="reg-1",
        position="Секретарь",
        department="КУ",
    )
    assert result.runId == "role-run-ok"
