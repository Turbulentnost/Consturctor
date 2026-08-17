"""Read-only web tools для актуальной внешней информации."""

from __future__ import annotations

import json
import subprocess
from html.parser import HTMLParser
from typing import Any
from urllib import error, parse, request

from app.tools.ac.tooling import (
    ToolCallResult,
    ToolDefinition,
    ToolExecutionMode,
    ToolSideEffectLevel,
)
from app.tools.ac.base import BaseTool
from app.tools.ac.registry import ToolRegistry
from app.tools.ac.workers.browser_cdp_worker import (
    DEFAULT_CDP_PORT,
    BrowserCdpError,
    BrowserCdpWorker,
    BrowserLaunchConfig,
    _require_http_url,
)
from app.tools.ac.workers.browser_detect import (
    find_readable_browser,
    list_installed_browsers,
    normalize_browser_id,
    resolve_browser_executable,
    resolve_default_user_data_dir,
)

DEFAULT_MAX_RESULTS = 5
MAX_RESULTS = 10

# Реалистичный браузерный User-Agent: DuckDuckGo HTML/Lite отдаёт результаты
# только «браузерным» клиентам, иначе возвращает пустую страницу.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
# Endpoints обычного веб-поиска DuckDuckGo (SERP как в Google), без API-ключа.
DUCKDUCKGO_HTML_ENDPOINT = "https://html.duckduckgo.com/html/"
DUCKDUCKGO_LITE_ENDPOINT = "https://lite.duckduckgo.com/lite/"
TITLE_RESULT_CLASSES = ("result__a", "result-link")
SNIPPET_RESULT_CLASSES = ("result__snippet", "result-snippet")


class BrowserWorkerProvider:
    """Выдаёт CDP-worker для конкретного браузера или дефолтного (авто-выбор)."""

    def __init__(self, default_worker: BrowserCdpWorker) -> None:
        """Сохранить дефолтный worker и кэш per-browser workers."""
        self._default_worker = default_worker
        self._by_browser: dict[str, BrowserCdpWorker] = {}

    def get(self, input_data: dict) -> BrowserCdpWorker:
        """Вернуть worker: дефолтный (авто) или под конкретный browser/profile."""
        input_data = _inherit_browser_context(input_data)
        name = _requested_browser_name(input_data)
        profile_options = _profile_options(input_data)
        if not name and not _has_explicit_profile(input_data):
            return self._default_worker
        key = normalize_browser_id(name) if name else "default"
        cache_key = _worker_cache_key(key, profile_options)
        cached = self._by_browser.get(cache_key)
        if cached is not None:
            return cached
        if name and find_readable_browser(key) is None:
            raise BrowserCdpError(
                f"Браузер {name!r} не поддерживает чтение через CDP. Доступны "
                "Chromium-браузеры: edge, chrome, brave, yandex, opera, vivaldi, "
                "chromium. Проверь список через browser.list_installed_browsers."
            )
        executable = resolve_browser_executable(key) if name else None
        if name and executable is None:
            raise BrowserCdpError(
                f"Браузер {name!r} не найден на устройстве. Посмотри доступные "
                "через browser.list_installed_browsers."
            )
        worker = BrowserCdpWorker(
            BrowserLaunchConfig(
                port=DEFAULT_CDP_PORT + 1 + len(self._by_browser),
                executable_path=executable,
                browser_id=key,
                **profile_options,
            )
        )
        self._by_browser[cache_key] = worker
        return worker

    def input_for_worker(self, input_data: dict) -> dict:
        """Вернуть input с унаследованными browser_id/url/profile для worker action."""
        return _inherit_browser_context(input_data)


def _requested_browser_name(input_data: dict) -> str:
    """Достать browser_id/browser_name/browser из входных данных."""
    return str(
        input_data.get("browser_id")
        or input_data.get("browser_name")
        or input_data.get("browser")
        or ""
    ).strip()


def _bool_input(value: object) -> bool:
    """Разобрать bool-флаг из JSON-like input."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "да", "истина"}
    return bool(value)


def _profile_options(input_data: dict) -> dict[str, object]:
    """Вытащить настройки профиля для CDP worker.

    По умолчанию (флаг не передан) — штатный пользовательский профиль с
    существующей авторизацией; automation только при use_default_profile=false.
    """
    if "use_default_profile" in input_data:
        use_default = _bool_input(input_data.get("use_default_profile"))
    else:
        use_default = True
    return {
        "use_default_profile": use_default,
        "profile_name": str(input_data.get("profile_name") or "").strip() or None,
        "user_data_dir": str(input_data.get("user_data_dir") or "").strip() or None,
    }


def _has_explicit_profile(input_data: dict) -> bool:
    """Проверить, просил ли caller не дефолтный automation worker."""
    return any(
        key in input_data and input_data.get(key) not in {None, "", False}
        for key in ("use_default_profile", "profile_name", "user_data_dir")
    )


def _inherit_browser_context(input_data: dict) -> dict:
    """Унаследовать browser_id/url/profile из предыдущих browser tool outputs.

    Read-only DOM/table tools не должны внезапно открывать другой браузер или
    automation-профиль, если пользователь уже работал в конкретном браузере с
    активной сессией. Поэтому берём контекст из browser.open_browser/navigate,
    но не наследуем OS fallback как режим исполнения: для DOM всё равно нужен CDP.
    """
    enriched = dict(input_data)
    context = _inherited_browser_context(input_data)
    if context is None:
        return enriched
    if not _requested_browser_name(enriched):
        browser_id = str(
            context.get("browser_id") or context.get("browser_name") or ""
        ).strip()
        if browser_id:
            enriched["browser_id"] = browser_id
    if not _has_explicit_profile(enriched) and (
        context.get("used_default_profile") is True
        or context.get("profile_mode") == "default"
    ):
        enriched["use_default_profile"] = True
    if not str(enriched.get("url") or "").strip():
        url = str(context.get("url") or "").strip()
        if url:
            enriched["url"] = url
    return enriched


def _inherited_browser_context(input_data: dict) -> dict | None:
    """Найти последний browser output с browser_id/url/profile в tool_outputs."""
    tool_outputs = input_data.get("tool_outputs")
    if not isinstance(tool_outputs, dict):
        return None
    for tool_name in (
        "browser.dump_page_source",
        "browser.get_page_html",
        "browser.extract_table",
        "browser.navigate",
        "browser.open_browser",
        "browser.open_page",
    ):
        output = tool_outputs.get(tool_name)
        if not isinstance(output, dict):
            continue
        browser_id = str(
            output.get("browser_id") or output.get("browser_name") or ""
        ).strip()
        url = str(output.get("url") or "").strip()
        has_profile = (
            output.get("used_default_profile") is True
            or bool(output.get("profile_mode"))
        )
        if browser_id or url or has_profile:
            return output
    return None


def _worker_cache_key(browser_id: str, profile_options: dict[str, object]) -> str:
    """Стабильный cache key для browser/profile worker."""
    return "|".join(
        [
            browser_id,
            f"default={bool(profile_options.get('use_default_profile'))}",
            f"profile={profile_options.get('profile_name') or ''}",
            f"data={profile_options.get('user_data_dir') or ''}",
        ]
    )


_BROWSER_PROFILE_INPUT_PROPERTIES = {
    "use_default_profile": {"type": "boolean"},
    "profile_name": {"type": "string"},
    "user_data_dir": {"type": "string"},
}

_BROWSER_PROFILE_OUTPUT_PROPERTIES = {
    "browser_id": {"type": "string"},
    "browser_name": {"type": "string"},
    "profile_mode": {"type": "string"},
    "user_data_dir": {"type": "string"},
    "used_default_profile": {"type": "boolean"},
    "command_args_summary": {"type": "array"},
    "cdp_available": {"type": "boolean"},
    "cdp_url": {"type": "string"},
    "fallback_used": {"type": "boolean"},
    "fallback_reason": {"type": "string"},
    "next_action_hint": {"type": "string"},
}


class BrowserListInstalledBrowsersTool(BaseTool):
    """Определяет установленные на устройстве браузеры (read-only, без запуска)."""

    def __init__(self) -> None:
        """Создать инструмент browser.list_installed_browsers."""
        super().__init__(
            ToolDefinition(
                name="browser.list_installed_browsers",
                title="Список браузеров на устройстве",
                description=(
                    "Определяет, какие браузеры установлены на компьютере "
                    "(Edge, Chrome, Brave, Yandex, Opera, Vivaldi, Chromium, "
                    "Firefox): путь, версия и поддержка чтения через CDP."
                ),
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=False,
                timeout_seconds=15,
                input_schema={"type": "object", "properties": {}},
                output_schema={
                    "type": "object",
                    "properties": {
                        "browsers": {"type": "array"},
                        "count": {"type": "integer"},
                        "default_readable_browser": {"type": "string"},
                    },
                },
            )
        )

    def execute(self, input_data: dict) -> ToolCallResult:
        """Вернуть список установленных браузеров."""
        try:
            browsers = list_installed_browsers()
        except Exception as exc:  # noqa: BLE001 - изоляция ошибок сканирования ФС
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="BROWSER_DETECT_ERROR",
                error_message=str(exc),
            )
        default_readable = next(
            (item["name"] for item in browsers if item.get("readable")),
            "",
        )
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={
                "browsers": browsers,
                "count": len(browsers),
                "default_readable_browser": default_readable,
            },
        )


class BrowserOpenBrowserTool(BaseTool):
    """Открывает конкретный установленный браузер по id/name, а не default app."""

    def __init__(self) -> None:
        """Создать инструмент browser.open_browser."""
        super().__init__(
            ToolDefinition(
                name="browser.open_browser",
                title="Открыть конкретный браузер",
                description=(
                    "Открывает установленный браузер по browser_id/browser_name "
                    "(например yandex, edge, chrome) и опционально URL. Запускает "
                    "обычный профиль браузера без --user-data-dir, чтобы сохранить "
                    "пользовательские логины и сессии."
                ),
                side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=False,
                timeout_seconds=15,
                input_schema={
                    "type": "object",
                    "properties": {
                        "browser_id": {"type": "string"},
                        "browser_name": {"type": "string"},
                        "browser": {"type": "string"},
                        "url": {"type": "string"},
                    },
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "browser_id": {"type": "string"},
                        "browser_name": {"type": "string"},
                        "path": {"type": "string"},
                        "url": {"type": "string"},
                        "pid": {"type": "integer"},
                        "available_browsers": {"type": "array"},
                        "profile_mode": {"type": "string"},
                        "user_data_dir": {"type": "string"},
                        "used_default_profile": {"type": "boolean"},
                        "command_args_summary": {"type": "array"},
                    },
                },
            )
        )

    def execute(self, input_data: dict) -> ToolCallResult:
        """Запустить выбранный браузер напрямую по найденному executable path."""
        requested = _requested_browser_name(input_data)
        if not requested:
            return _browser_not_found_result(
                self.definition.name,
                requested,
                "Для browser.open_browser нужен browser_id или browser_name.",
            )

        browser_id = normalize_browser_id(requested)
        executable = resolve_browser_executable(browser_id)
        if executable is None:
            return _browser_not_found_result(
                self.definition.name,
                requested,
                f"Браузер {requested!r} не найден на устройстве.",
            )

        url = str(input_data.get("url") or "").strip()
        if url:
            try:
                url = _require_http_url(url)
            except BrowserCdpError as exc:
                return ToolCallResult(
                    ok=False,
                    tool_name=self.definition.name,
                    error_type="INVALID_INPUT",
                    error_message=str(exc),
                )

        command = [executable, *([url] if url else [])]
        try:
            process = subprocess.Popen(  # noqa: S603 - executable найден локально
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="BROWSER_OPEN_ERROR",
                error_message=f"Не удалось открыть браузер {requested!r}: {exc}",
            )

        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={
                "browser_id": browser_id,
                "browser_name": browser_id,
                "path": executable,
                "url": url,
                "pid": process.pid,
                "profile_mode": "default",
                "user_data_dir": resolve_default_user_data_dir(browser_id) or "",
                "used_default_profile": True,
                "command_args_summary": [
                    "<browser_executable>",
                    *([url] if url else []),
                    "no --remote-debugging-port",
                    "no --user-data-dir",
                    "no --profile-directory",
                ],
            },
        )


class BrowserSearchWebTool(BaseTool):
    """Безопасный read-only поиск актуальной web-информации."""

    def __init__(self) -> None:
        """Создать инструмент browser.search_web."""
        super().__init__(
            ToolDefinition(
                name="browser.search_web",
                title="Поиск web-информации",
                description="Ищет актуальную информацию в интернете read-only.",
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.EXTERNAL_API,
                requires_human_approval=False,
                timeout_seconds=20,
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "max_results": {"type": "integer"},
                        "allowed_domains": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["query"],
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "answer": {"type": "string"},
                        "results": {"type": "array"},
                        "source": {"type": "string"},
                    },
                },
            )
        )

    def execute(self, input_data: dict) -> ToolCallResult:
        """Выполнить web-поиск и вернуть структурированные результаты."""
        query = str(input_data.get("query") or "").strip()
        if not query:
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="INVALID_INPUT",
                error_message="Для browser.search_web нужен непустой query.",
            )

        max_results = _clamp_int(
            input_data.get("max_results"),
            DEFAULT_MAX_RESULTS,
            1,
            MAX_RESULTS,
        )
        try:
            if _looks_like_weather_query(query):
                output_data = _search_weather(query, max_results)
            else:
                output_data = _search_web(query, max_results)
        except Exception as exc:  # noqa: BLE001 - urllib возвращает разные ошибки
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="WEB_SEARCH_ERROR",
                error_message=str(exc),
            )

        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data=output_data,
        )


class BrowserOpenPageTool(BaseTool):
    """Открывает страницу через CDP и извлекает видимый текст/ссылки."""

    def __init__(self, worker: BrowserCdpWorker | None = None) -> None:
        """Создать инструмент browser.open_page."""
        super().__init__(
            ToolDefinition(
                name="browser.open_page",
                title="Чтение web-страницы",
                description="Открывает web-страницу read-only и извлекает текст.",
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.BROWSER_WORKER,
                requires_human_approval=False,
                timeout_seconds=30,
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "max_chars": {"type": "integer"},
                        "browser": {"type": "string"},
                        "browser_id": {"type": "string"},
                        "browser_name": {"type": "string"},
                        **_BROWSER_PROFILE_INPUT_PROPERTIES,
                    },
                    "required": ["url"],
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "title": {"type": "string"},
                        "text": {"type": "string"},
                        "links": {"type": "array"},
                        **_BROWSER_PROFILE_OUTPUT_PROPERTIES,
                    },
                },
            )
        )
        self._provider = BrowserWorkerProvider(worker or BrowserCdpWorker())

    def execute(self, input_data: dict) -> ToolCallResult:
        """Открыть страницу через browser worker."""
        return _execute_browser_worker(
            self.definition.name,
            self._provider,
            "open_page",
            input_data,
        )


class BrowserExtractTableTool(BaseTool):
    """Извлекает таблицы со страницы через CDP."""

    def __init__(self, worker: BrowserCdpWorker | None = None) -> None:
        """Создать инструмент browser.extract_table."""
        super().__init__(
            ToolDefinition(
                name="browser.extract_table",
                title="Извлечение таблиц web-страницы",
                description="Извлекает таблицы с web-страницы read-only.",
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.BROWSER_WORKER,
                requires_human_approval=False,
                timeout_seconds=30,
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "table_hint": {"type": "string"},
                        "browser": {"type": "string"},
                        "browser_id": {"type": "string"},
                        "browser_name": {"type": "string"},
                        **_BROWSER_PROFILE_INPUT_PROPERTIES,
                    },
                    "required": ["url"],
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "title": {"type": "string"},
                        "tables": {"type": "array"},
                        **_BROWSER_PROFILE_OUTPUT_PROPERTIES,
                    },
                },
            )
        )
        self._provider = BrowserWorkerProvider(worker or BrowserCdpWorker())

    def execute(self, input_data: dict) -> ToolCallResult:
        """Извлечь таблицы через browser worker."""
        return _execute_browser_worker(
            self.definition.name,
            self._provider,
            "extract_table",
            input_data,
        )


class BrowserScrollPageTool(BaseTool):
    """Прокручивает страницу через CDP и возвращает видимый текст."""

    def __init__(self, worker: BrowserCdpWorker | None = None) -> None:
        """Создать инструмент browser.scroll_page."""
        super().__init__(
            ToolDefinition(
                name="browser.scroll_page",
                title="Прокрутка web-страницы",
                description="Прокручивает web-страницу read-only.",
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.BROWSER_WORKER,
                requires_human_approval=False,
                timeout_seconds=30,
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "direction": {"type": "string"},
                        "pixels": {"type": "integer"},
                        "max_chars": {"type": "integer"},
                        "browser": {"type": "string"},
                        "browser_id": {"type": "string"},
                        "browser_name": {"type": "string"},
                        **_BROWSER_PROFILE_INPUT_PROPERTIES,
                    },
                    "required": ["url"],
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "title": {"type": "string"},
                        "text": {"type": "string"},
                        "scroll_y": {"type": "integer"},
                        **_BROWSER_PROFILE_OUTPUT_PROPERTIES,
                    },
                },
            )
        )
        self._provider = BrowserWorkerProvider(worker or BrowserCdpWorker())

    def execute(self, input_data: dict) -> ToolCallResult:
        """Прокрутить страницу через browser worker."""
        return _execute_browser_worker(
            self.definition.name,
            self._provider,
            "scroll_page",
            input_data,
        )


class BrowserClickLinkTool(BaseTool):
    """Переходит по безопасной http/https ссылке через CDP."""

    def __init__(self, worker: BrowserCdpWorker | None = None) -> None:
        """Создать инструмент browser.click_link."""
        super().__init__(
            ToolDefinition(
                name="browser.click_link",
                title="Переход по ссылке web-страницы",
                description="Открывает найденную ссылку read-only.",
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.BROWSER_WORKER,
                requires_human_approval=False,
                timeout_seconds=30,
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "link_text": {"type": "string"},
                        "href": {"type": "string"},
                        "max_chars": {"type": "integer"},
                        "browser": {"type": "string"},
                        "browser_id": {"type": "string"},
                        "browser_name": {"type": "string"},
                        **_BROWSER_PROFILE_INPUT_PROPERTIES,
                    },
                    "required": ["url"],
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "title": {"type": "string"},
                        "text": {"type": "string"},
                        "links": {"type": "array"},
                        **_BROWSER_PROFILE_OUTPUT_PROPERTIES,
                    },
                },
            )
        )
        self._provider = BrowserWorkerProvider(worker or BrowserCdpWorker())

    def execute(self, input_data: dict) -> ToolCallResult:
        """Перейти по ссылке через browser worker."""
        return _execute_browser_worker(
            self.definition.name,
            self._provider,
            "click_link",
            input_data,
        )


def register_web_tools(
    registry: ToolRegistry,
    *,
    skip_existing: bool = False,
    worker: BrowserCdpWorker | None = None,
    workspace_resolver: "AgentWorkspaceResolver | None" = None,
) -> None:
    """Зарегистрировать read-only web tools."""
    browser_worker = worker or BrowserCdpWorker()
    tools = [
        BrowserListInstalledBrowsersTool(),
        BrowserOpenBrowserTool(),
        BrowserSearchWebTool(),
        BrowserOpenPageTool(browser_worker),
        BrowserExtractTableTool(browser_worker),
        BrowserScrollPageTool(browser_worker),
        BrowserClickLinkTool(browser_worker),
    ]
    for tool in tools:
        if skip_existing and registry.has_tool(tool.definition.name):
            continue
        registry.register(tool)

    from app.tools.ac.browser_vision_tools import (
        register_browser_vision_tools,
    )

    register_browser_vision_tools(
        registry,
        skip_existing=skip_existing,
        workspace_resolver=workspace_resolver,
    )


def _execute_browser_worker(
    tool_name: str,
    provider: "BrowserWorkerProvider",
    method_name: str,
    input_data: dict,
) -> ToolCallResult:
    """Выбрать worker нужного браузера и выполнить его action безопасно."""
    try:
        action_input = provider.input_for_worker(input_data)
        worker = provider.get(action_input)
        action = getattr(worker, method_name)
        output_data = action(action_input)
    except BrowserCdpError as exc:
        return ToolCallResult(
            ok=False,
            tool_name=tool_name,
            error_type="BROWSER_CDP_ERROR",
            error_message=str(exc),
            output_data=exc.output_data,
        )
    except Exception as exc:  # noqa: BLE001 - worker изолирует внешние browser ошибки
        return ToolCallResult(
            ok=False,
            tool_name=tool_name,
            error_type="BROWSER_TOOL_ERROR",
            error_message=str(exc),
        )
    return ToolCallResult(ok=True, tool_name=tool_name, output_data=output_data)


def _browser_not_found_result(
    tool_name: str,
    requested: str,
    message: str,
) -> ToolCallResult:
    """Вернуть понятную ошибку выбора браузера и список доступных id."""
    browsers = list_installed_browsers()
    available = [
        {
            "id": item.get("id") or item.get("name"),
            "name": item.get("name"),
            "path": item.get("path") or item.get("executable_path"),
            "supports_cdp": item.get("supports_cdp"),
        }
        for item in browsers
    ]
    suffix = ""
    if available:
        ids = ", ".join(str(item["id"]) for item in available if item.get("id"))
        suffix = f" Доступные браузеры: {ids}."
    return ToolCallResult(
        ok=False,
        tool_name=tool_name,
        error_type="BROWSER_NOT_FOUND",
        error_message=message + suffix,
        output_data={
            "requested_browser": requested,
            "available_browsers": available,
        },
    )



def _search_weather(query: str, max_results: int) -> dict:
    """Получить погодные данные через wttr.in в JSON-формате."""
    location = _extract_weather_location(query)
    encoded_location = parse.quote(location, safe="")
    url = f"https://wttr.in/{encoded_location}?format=j1&lang=ru"
    payload = _read_json(url)
    current = (payload.get("current_condition") or [{}])[0]
    nearest_area = (payload.get("nearest_area") or [{}])[0]
    area_name = _first_value(nearest_area.get("areaName")) or location or "текущая локация"
    country = _first_value(nearest_area.get("country"))
    description = _first_value(current.get("weatherDesc"))
    answer_parts = [
        f"Локация: {area_name}" + (f", {country}" if country else ""),
        f"Температура: {current.get('temp_C', '—')} °C",
        f"Ощущается как: {current.get('FeelsLikeC', '—')} °C",
        f"Условия: {description or '—'}",
        f"Ветер: {current.get('windspeedKmph', '—')} км/ч",
        f"Влажность: {current.get('humidity', '—')}%",
    ]
    forecast_items = payload.get("weather") or []
    results = [
        {
            "title": "Текущая погода",
            "snippet": "; ".join(answer_parts),
            "url": "https://wttr.in/",
            "source": "wttr.in",
        }
    ]
    for item in forecast_items[: max(0, max_results - 1)]:
        hourly = item.get("hourly") or []
        noon = hourly[len(hourly) // 2] if hourly else {}
        results.append(
            {
                "title": f"Прогноз на {item.get('date', 'дату')}",
                "snippet": (
                    f"Мин: {item.get('mintempC', '—')} °C; "
                    f"макс: {item.get('maxtempC', '—')} °C; "
                    f"днём: {_first_value(noon.get('weatherDesc')) or '—'}"
                ),
                "url": "https://wttr.in/",
                "source": "wttr.in",
            }
        )
    return {
        "query": query,
        "answer": "\n".join(answer_parts),
        "results": results[:max_results],
        "source": "wttr.in",
    }


def _search_web(query: str, max_results: int) -> dict:
    """Выполнить обычный веб-поиск (как Google) и вернуть реальные результаты.

    Стратегия:
    1. SERP DuckDuckGo (html → lite) — общий поиск по любым запросам;
    2. Instant Answer API — короткий прямой ответ для фактологических запросов.
    Результаты объединяются и дедуплицируются.
    """
    errors: list[str] = []
    serp_results: list[dict[str, str]] = []
    try:
        serp_results = _search_duckduckgo_html(query, max_results)
    except Exception as exc:  # noqa: BLE001 - сеть/парсинг могут падать по-разному
        errors.append(str(exc))

    answer = ""
    instant_results: list[dict[str, str]] = []
    try:
        answer, instant_results = _duckduckgo_instant_answer(query, max_results)
    except Exception as exc:  # noqa: BLE001 - instant answer опционален
        errors.append(str(exc))

    combined = _dedupe_results([*instant_results, *serp_results], max_results)
    if not answer and combined:
        answer = combined[0].get("snippet") or combined[0].get("title") or ""

    if not combined and not answer:
        raise RuntimeError(
            "Веб-поиск не вернул результатов"
            + (f": {'; '.join(errors)}" if errors else ".")
        )

    return {
        "query": query,
        "answer": answer,
        "results": combined,
        "source": "duckduckgo",
    }


def _search_duckduckgo_html(query: str, max_results: int) -> list[dict[str, str]]:
    """Получить обычные результаты веб-поиска, распарсив SERP DuckDuckGo."""
    last_error: Exception | None = None
    for endpoint in (DUCKDUCKGO_HTML_ENDPOINT, DUCKDUCKGO_LITE_ENDPOINT):
        try:
            html = _read_text(endpoint, {"q": query, "kl": "ru-ru"})
        except Exception as exc:  # noqa: BLE001 - пробуем следующий endpoint
            last_error = exc
            continue
        parser = _DuckDuckGoHtmlParser()
        parser.feed(html)
        results = parser.cleaned_results()
        if results:
            return results[:max_results]
    if last_error is not None:
        raise RuntimeError(f"Не удалось получить результаты поиска: {last_error}")
    return []


def _duckduckgo_instant_answer(
    query: str,
    max_results: int,
) -> tuple[str, list[dict[str, str]]]:
    """Получить короткий прямой ответ через DuckDuckGo Instant Answer API."""
    params = parse.urlencode(
        {
            "q": query,
            "format": "json",
            "no_html": "1",
            "skip_disambig": "1",
        }
    )
    payload = _read_json(f"https://api.duckduckgo.com/?{params}")
    results: list[dict[str, str]] = []
    abstract = str(payload.get("AbstractText") or "").strip()
    abstract_url = str(payload.get("AbstractURL") or "").strip()
    heading = str(payload.get("Heading") or query).strip()
    if abstract:
        results.append(
            {
                "title": heading,
                "snippet": abstract,
                "url": abstract_url,
                "source": "duckduckgo",
            }
        )
    for item in _flatten_related_topics(payload.get("RelatedTopics") or []):
        if len(results) >= max_results:
            break
        text = str(item.get("Text") or "").strip()
        if not text:
            continue
        results.append(
            {
                "title": text.split(" - ", 1)[0][:120],
                "snippet": text,
                "url": str(item.get("FirstURL") or ""),
                "source": "duckduckgo",
            }
        )
    answer = abstract or str(payload.get("Answer") or "").strip()
    return answer, results


class _DuckDuckGoHtmlParser(HTMLParser):
    """Лёгкий парсер SERP DuckDuckGo (html и lite) без внешних зависимостей."""

    def __init__(self) -> None:
        """Создать парсер результатов поиска."""
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._capture_title = False
        self._capture_snippet = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Начать захват заголовка результата или сниппета по классу элемента."""
        attributes = {name: (value or "") for name, value in attrs}
        css_class = attributes.get("class", "")
        if tag == "a" and _has_result_class(css_class, TITLE_RESULT_CLASSES):
            self.results.append(
                {
                    "title": "",
                    "url": _decode_ddg_href(attributes.get("href", "")),
                    "snippet": "",
                    "source": "duckduckgo",
                }
            )
            self._capture_title = True
            return
        if _has_result_class(css_class, SNIPPET_RESULT_CLASSES) and self.results:
            self._capture_snippet = True

    def handle_endtag(self, tag: str) -> None:
        """Остановить захват при закрытии соответствующего контейнера."""
        if self._capture_title and tag == "a":
            self._capture_title = False
        if self._capture_snippet and tag in {"a", "div", "td", "span"}:
            self._capture_snippet = False

    def handle_data(self, data: str) -> None:
        """Накопить текст заголовка/сниппета текущего результата."""
        if not self.results:
            return
        if self._capture_title:
            self.results[-1]["title"] += data
        elif self._capture_snippet:
            self.results[-1]["snippet"] += data

    def cleaned_results(self) -> list[dict[str, str]]:
        """Вернуть только валидные результаты с http-ссылкой и заголовком."""
        cleaned: list[dict[str, str]] = []
        for item in self.results:
            title = " ".join(item["title"].split())
            snippet = " ".join(item["snippet"].split())
            url = item["url"].strip()
            if not title or not url.startswith("http"):
                continue
            cleaned.append(
                {
                    "title": title,
                    "snippet": snippet,
                    "url": url,
                    "source": "duckduckgo",
                }
            )
        return cleaned


def _has_result_class(css_class: str, markers: tuple[str, ...]) -> bool:
    """Проверить, что class-атрибут содержит один из маркеров результата."""
    tokens = css_class.split()
    return any(marker in tokens for marker in markers)


def _decode_ddg_href(href: str) -> str:
    """Достать реальный URL из редирект-ссылки DuckDuckGo (/l/?uddg=...)."""
    if not href:
        return ""
    normalized = "https:" + href if href.startswith("//") else href
    try:
        parsed = parse.urlparse(normalized)
    except ValueError:
        return normalized
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = parse.parse_qs(parsed.query).get("uddg", [])
        if target:
            return parse.unquote(target[0])
    return normalized


def _dedupe_results(
    results: list[dict[str, str]],
    max_results: int,
) -> list[dict[str, str]]:
    """Убрать дубли по URL и обрезать до max_results, сохранив порядок."""
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for item in results:
        key = (item.get("url") or item.get("title") or "").strip().casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
        if len(unique) >= max_results:
            break
    return unique


def _read_text(base_url: str, params: dict[str, str] | None = None) -> str:
    """Прочитать HTML по URL с браузерным User-Agent и понятной ошибкой."""
    url = f"{base_url}?{parse.urlencode(params)}" if params else base_url
    http_request = request.Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ru,en;q=0.9",
            "User-Agent": BROWSER_USER_AGENT,
        },
        method="GET",
    )
    try:
        with request.urlopen(http_request, timeout=20) as response:
            raw = response.read()
    except error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} при web-поиске") from exc
    except (error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Не удалось выполнить web-поиск: {exc}") from exc
    return raw.decode("utf-8", errors="replace")


def _read_json(url: str) -> dict[str, Any]:
    """Прочитать JSON по URL с user-agent и понятной ошибкой."""
    http_request = request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "AgentConstructor/1.0 read-only",
        },
        method="GET",
    )
    try:
        with request.urlopen(http_request, timeout=20) as response:
            raw = response.read()
    except error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} при web-поиске") from exc
    except (error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Не удалось выполнить web-поиск: {exc}") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Web endpoint вернул невалидный JSON") from exc


def _looks_like_weather_query(query: str) -> bool:
    """Проверить, что запрос похож на запрос о погоде."""
    lowered = query.casefold()
    return any(marker in lowered for marker in ["погода", "weather", "температура"])


def _extract_weather_location(query: str) -> str:
    """Выделить локацию из простого погодного запроса или оставить авто-локацию."""
    lowered = query.casefold()
    for marker in [" в ", " во ", " для "]:
        if marker in lowered:
            location = query[lowered.rindex(marker) + len(marker) :].strip(" ?.!")
            if location:
                return location
    return ""


def _flatten_related_topics(items: list) -> list[dict]:
    """Развернуть RelatedTopics DuckDuckGo с вложенными группами."""
    flattened: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if "Topics" in item and isinstance(item["Topics"], list):
            flattened.extend(_flatten_related_topics(item["Topics"]))
        else:
            flattened.append(item)
    return flattened


def _first_value(items: object) -> str:
    """Достать value из wttr.in массива вида [{'value': '...'}]."""
    if isinstance(items, list) and items and isinstance(items[0], dict):
        return str(items[0].get("value") or "").strip()
    return ""


def _clamp_int(value: object, default: int, minimum: int, maximum: int) -> int:
    """Привести числовой параметр к безопасному диапазону."""
    try:
        parsed_value = int(value)
    except (TypeError, ValueError):
        parsed_value = default
    return max(minimum, min(maximum, parsed_value))
