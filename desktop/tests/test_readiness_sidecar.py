from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import httpx

from app.api_client import ApiError, _extract_detail, _http_client

ROOT = Path(__file__).resolve().parents[2]
PYBRIDGE = ROOT / "desktop-electron" / "pybridge"
if str(PYBRIDGE) not in sys.path:
    sys.path.insert(0, str(PYBRIDGE))

from agent_sidecar import (  # noqa: E402
    READINESS_SDK_TOOLS,
    _build_readiness_prompt,
    _prepare_readiness_workspace,
)


def test_readiness_tools_are_questions_only() -> None:
    names = {item["name"] for item in READINESS_SDK_TOOLS}
    assert names == {"askQuestion"}


def test_readiness_prompt_mentions_previous_answers() -> None:
    fresh = _build_readiness_prompt(has_answers=False)
    resumed = _build_readiness_prompt(has_answers=True)
    assert "askQuestion" in fresh
    assert "answers.md уже есть ответы" in resumed


def test_readiness_workspace_survives_regulation_503(tmp_path: Path) -> None:
    class _FailingApi:
        def get_regulation(self, regulation_id: str):
            raise ApiError("down", status_code=503)

    draft = SimpleNamespace(
        regulation_id="reg-1",
        agent_suggestions=[
            SimpleNamespace(
                title="Контроль инициации",
                function_id="fn-1",
                source_block_id="b1",
                description="описание",
            )
        ],
        result_json={},
    )
    has_answers = _prepare_readiness_workspace(_FailingApi(), draft, str(tmp_path))
    assert has_answers is False
    functions = (tmp_path / "materials" / "functions.md").read_text(encoding="utf-8")
    assert "Контроль инициации" in functions
    regulation = (tmp_path / "materials" / "regulation.md").read_text(encoding="utf-8")
    assert "недоступен" in regulation


def test_extract_detail_empty_503_is_retryable() -> None:
    text = _extract_detail(httpx.Response(503, text=""))
    assert "503" in text
    assert "Запустить агента" in text


def test_http_client_ignores_system_proxy() -> None:
    with _http_client(timeout=1.0) as client:
        assert client._trust_env is False
