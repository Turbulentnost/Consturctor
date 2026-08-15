"""Vision-driven browser worker на Chrome DevTools Protocol.

В отличие от read-only BrowserCdpWorker, этот worker держит постоянную вкладку и
позволяет LLM управлять UI по скриншотам: делать снимок экрана, кликать по
координатам, вводить текст, нажимать клавиши, прокручивать и переходить по URL.
Каждое действие возвращает свежий скриншот (base64 PNG), чтобы LLM «видела»
результат и решала следующий шаг. Worker не принимает решений сам — он только
безопасно исполняет то, что решила LLM.
"""

from __future__ import annotations

import json
import base64
import os
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib import error, request

from app.tools.ac.workers.browser_cdp_worker import (
    BrowserCdpError,
    BrowserCdpEndpointUnavailable,
    BrowserLaunchConfig,
    _CdpSession,
    _cdp_http_url,
    _cdp_unavailable_message,
    _clamp_int,
    _command_args_summary,
    _find_chromium_executable,
    _next_action_hint,
    _planned_command_args_summary,
    _profile_mode,
    _require_http_url,
    _resolved_profile_name,
    _resolve_user_data_dir,
)
from app.tools.ac.workers.browser_os_window import (
    capture_browser_window_png,
    focus_browser_window,
    foreground_window_info,
)

DEFAULT_VISION_PORT = 9333
DEFAULT_VIEWPORT_WIDTH = 1280
DEFAULT_VIEWPORT_HEIGHT = 900
MAX_TEXT_LENGTH = 2000
DEFAULT_MAX_HTML_CHARS = 80_000
MAX_MAX_HTML_CHARS = 100_000
DEFAULT_HTML_SUMMARY_CHARS = 4_000
MAX_HTML_SUMMARY_CHARS = 8_000

# Виртуальные коды клавиш Windows для типовых спец-клавиш.
_SPECIAL_KEYS: dict[str, dict[str, Any]] = {
    "enter": {"key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13, "text": "\r"},
    "return": {"key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13, "text": "\r"},
    "tab": {"key": "Tab", "code": "Tab", "windowsVirtualKeyCode": 9},
    "escape": {"key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27},
    "esc": {"key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27},
    "backspace": {"key": "Backspace", "code": "Backspace", "windowsVirtualKeyCode": 8},
    "delete": {"key": "Delete", "code": "Delete", "windowsVirtualKeyCode": 46},
    "arrowdown": {"key": "ArrowDown", "code": "ArrowDown", "windowsVirtualKeyCode": 40},
    "arrowup": {"key": "ArrowUp", "code": "ArrowUp", "windowsVirtualKeyCode": 38},
    "arrowleft": {"key": "ArrowLeft", "code": "ArrowLeft", "windowsVirtualKeyCode": 37},
    "arrowright": {"key": "ArrowRight", "code": "ArrowRight", "windowsVirtualKeyCode": 39},
}


class BrowserVisionWorker:
    """Управляет постоянной вкладкой браузера по указаниям LLM (скриншоты + ввод)."""

    def __init__(self, config: BrowserLaunchConfig | None = None) -> None:
        """Создать worker с ленивым запуском видимого браузера."""
        self._config = config or BrowserLaunchConfig(port=DEFAULT_VISION_PORT)
        self._process: subprocess.Popen | None = None
        self._user_data_dir = _resolve_user_data_dir(
            self._config,
            profile_kind="vision",
        )
        self._profile_mode = _profile_mode(self._config)
        self._last_command_args_summary: list[str] = []
        self._page_ws_url: str | None = None
        self._os_fallback_active = False
        self._os_fallback_url = ""
        # Смещение (0,0) картинки OS screenshot → абсолютные экранные координаты.
        self._os_click_origin: tuple[int, int] = (0, 0)
        self._os_capture_meta: dict[str, Any] = {}

    def activate_os_fallback(
        self,
        *,
        url: str = "",
        command_args_summary: list[str] | None = None,
    ) -> None:
        """Пометить worker как привязанный к уже открытому обычному браузеру."""
        self._os_fallback_active = True
        self._os_fallback_url = url
        if command_args_summary:
            self._last_command_args_summary = command_args_summary

    def open(self, input_data: dict) -> dict:
        """Открыть URL в постоянной вкладке и вернуть скриншот."""
        url = _require_http_url(input_data.get("url"))
        if self._os_fallback_active:
            return self._open_without_cdp(
                url,
                fallback_reason="default_profile_os_fallback",
                warning="Штатный профиль уже открыт без CDP; URL открыт через OS fallback.",
            )
        try:
            with self._session() as session:
                self._navigate(session, url)
                return self._state_with_screenshot(session)
        except BrowserCdpEndpointUnavailable as exc:
            if self._can_fallback_to_open_browser(input_data):
                return self._open_without_cdp(
                    url,
                    fallback_reason="default_profile_cdp_unavailable",
                    warning=str(exc),
                )
            raise

    def navigate(self, input_data: dict) -> dict:
        """Синоним open: перейти по URL и вернуть скриншот."""
        return self.open(input_data)

    def screenshot(self, input_data: dict) -> dict:
        """Сделать скриншот текущей вкладки (опционально сначала перейти на url)."""
        url = str(input_data.get("url") or "").strip()
        if self._os_fallback_active:
            if url:
                return self._open_without_cdp(
                    _require_http_url(url),
                    fallback_reason="default_profile_os_fallback",
                    warning="CDP недоступен; URL открыт через OS fallback.",
                )
            return self._state_with_os_screenshot()
        try:
            with self._session() as session:
                if url:
                    self._navigate(session, _require_http_url(url))
                return self._state_with_screenshot(session)
        except BrowserCdpEndpointUnavailable as exc:
            if self._can_fallback_to_os_control(input_data):
                if url:
                    self._open_without_cdp(
                        _require_http_url(url),
                        fallback_reason="default_profile_cdp_unavailable",
                        warning=str(exc),
                    )
            return self._state_with_os_screenshot(
                warning=str(exc),
                fallback_reason="default_profile_cdp_unavailable",
            )
            raise

    def get_page_html(self, input_data: dict) -> dict:
        """Получить HTML текущей вкладки через CDP (без скриншота)."""
        url = str(input_data.get("url") or "").strip()
        max_chars = _clamp_int(
            input_data.get("max_chars"),
            DEFAULT_MAX_HTML_CHARS,
            1,
            MAX_MAX_HTML_CHARS,
        )
        summary_chars = _clamp_int(
            input_data.get("summary_chars"),
            DEFAULT_HTML_SUMMARY_CHARS,
            100,
            MAX_HTML_SUMMARY_CHARS,
        )
        with self._session() as session:
            if url:
                self._navigate(session, _require_http_url(url))
            return self._page_html(
                session,
                max_chars=max_chars,
                summary_chars=summary_chars,
            )

    def dump_page_source(self, input_data: dict) -> dict:
        """Выгрузить полный HTML и собранный CSS текущей вкладки (для анализа)."""
        if self._os_fallback_active:
            raise BrowserCdpError(
                "Выгрузка HTML/CSS требует CDP-доступа к DOM, а сейчас активен "
                "OS fallback. Нельзя получить DOM из обычного окна без CDP. "
                "Если нужна авторизованная страница — попроси человека закрыть этот "
                "браузер и открой её через browser.navigate с тем же browser_id и "
                "use_default_profile=true, чтобы CDP поднялся на штатном профиле. "
                "Если авторизация не нужна — открой URL через browser.navigate без "
                "use_default_profile и повтори browser.dump_page_source.",
                output_data=self.profile_output(
                    cdp_available=False,
                    fallback_used=True,
                    fallback_reason="page_source_requires_cdp",
                ),
            )
        url = str(input_data.get("url") or "").strip()
        try:
            with self._session() as session:
                if url:
                    self._navigate(session, _require_http_url(url))
                session.send("Runtime.enable")
                payload = session.evaluate(_page_source_script()) or {}
                if not isinstance(payload, dict):
                    raise BrowserCdpError("CDP не вернул исходный код страницы.")
                html = str(payload.get("html") or "")
                css = str(payload.get("css") or "")
                return {
                    "url": payload.get("url") or session.evaluate("location.href"),
                    "title": payload.get("title")
                    or session.evaluate("document.title")
                    or "",
                    "html": html,
                    "css": css,
                    "html_length": len(html),
                    "css_length": len(css),
                    "stylesheet_count": int(payload.get("stylesheet_count") or 0),
                    "blocked_stylesheets": payload.get("blocked_stylesheets") or [],
                    **self.profile_output(cdp_available=True),
                }
        except BrowserCdpEndpointUnavailable as exc:
            raise BrowserCdpError(
                "Не удалось получить HTML/CSS: для выбранного браузера/профиля не "
                "поднялся CDP endpoint. DOM-выгрузка невозможна через OS fallback. "
                "Для авторизованной страницы закрой уже открытый браузер и открой "
                "его через browser.navigate с browser_id/use_default_profile=true; "
                "для неавторизованной страницы используй browser.navigate без "
                "use_default_profile и затем повтори browser.dump_page_source.",
                output_data={
                    **self.profile_output(
                        cdp_available=False,
                        fallback_used=False,
                        fallback_reason="page_source_cdp_unavailable",
                    ),
                    "url": url,
                    "warning": str(exc),
                },
            ) from exc

    def click(self, input_data: dict) -> dict:
        """Кликнуть по координатам (x, y) и вернуть новый скриншот."""
        x = _require_number(input_data.get("x"), "x")
        y = _require_number(input_data.get("y"), "y")
        button = str(input_data.get("button") or "left").strip().casefold()
        if self._os_fallback_active:
            focus_meta = focus_browser_window(self._os_fallback_url)
            time.sleep(0.15)
            self._send_os_click(int(x), int(y), button)
            time.sleep(0.25)
            result = self._state_with_os_screenshot()
            result["focus_before_action"] = focus_meta
            result["focused_window_after"] = foreground_window_info()
            return result
        with self._session() as session:
            session.send("Page.enable")
            session.send("Runtime.enable")
            for event_type in ("mousePressed", "mouseReleased"):
                session.send(
                    "Input.dispatchMouseEvent",
                    {
                        "type": event_type,
                        "x": x,
                        "y": y,
                        "button": button,
                        "clickCount": 1,
                    },
                )
            time.sleep(0.4)
            return self._state_with_screenshot(session)

    def type_text(self, input_data: dict) -> dict:
        """Ввести текст в текущий активный элемент и вернуть скриншот."""
        text = str(input_data.get("text") or "")
        if not text:
            raise BrowserCdpError("Для browser.type_text нужен непустой text.")
        if len(text) > MAX_TEXT_LENGTH:
            raise BrowserCdpError(
                f"text слишком длинный (>{MAX_TEXT_LENGTH} символов)."
            )
        if self._os_fallback_active:
            focus_meta = focus_browser_window(self._os_fallback_url)
            time.sleep(0.15)
            self._send_os_text(text)
            time.sleep(0.25)
            result = self._state_with_os_screenshot()
            result["focus_before_action"] = focus_meta
            result["focused_window_after"] = foreground_window_info()
            return result
        with self._session() as session:
            session.send("Input.insertText", {"text": text})
            time.sleep(0.2)
            return self._state_with_screenshot(session)

    def press_key(self, input_data: dict) -> dict:
        """Нажать спец-клавишу (Enter/Tab/Escape/стрелки) и вернуть скриншот."""
        key_name = str(input_data.get("key") or "").strip().casefold()
        descriptor = _SPECIAL_KEYS.get(key_name)
        if descriptor is None:
            raise BrowserCdpError(
                "Поддерживаются клавиши: "
                + ", ".join(sorted({k for k in _SPECIAL_KEYS}))
            )
        if self._os_fallback_active:
            focus_meta = focus_browser_window(self._os_fallback_url)
            time.sleep(0.15)
            self._send_os_key(descriptor)
            time.sleep(0.25)
            result = self._state_with_os_screenshot()
            result["focus_before_action"] = focus_meta
            result["focused_window_after"] = foreground_window_info()
            return result
        with self._session() as session:
            session.send("Input.dispatchKeyEvent", {"type": "rawKeyDown", **descriptor})
            if "text" in descriptor:
                session.send("Input.dispatchKeyEvent", {"type": "char", **descriptor})
            session.send("Input.dispatchKeyEvent", {"type": "keyUp", **descriptor})
            time.sleep(0.3)
            return self._state_with_screenshot(session)

    def scroll(self, input_data: dict) -> dict:
        """Прокрутить нужный контейнер и вернуть скриншот с метриками прокрутки.

        Сама находит подходящую область прокрутки: если заданы x/y — берёт
        элемент под этой точкой и его ближайшего прокручиваемого родителя;
        иначе выбирает самый большой видимый прокручиваемый контейнер (например,
        список чатов), а если такого нет — прокручивает всю страницу. Работает
        по вертикали и по горизонтали и сообщает, сдвинулась ли страница и
        достигнут ли край.
        """
        direction = str(input_data.get("direction") or "down").strip().casefold()
        pixels = int(_require_number(input_data.get("pixels"), "pixels", default=700))
        has_point = input_data.get("x") is not None and input_data.get("y") is not None
        x = int(_require_number(input_data.get("x"), "x", default=0)) if has_point else -1
        y = int(_require_number(input_data.get("y"), "y", default=0)) if has_point else -1

        dx = 0
        dy = 0
        if direction in {"up", "вверх"}:
            dy = -pixels
        elif direction in {"left", "влево"}:
            dx = -pixels
        elif direction in {"right", "вправо"}:
            dx = pixels
        else:
            dy = pixels

        if self._os_fallback_active:
            self._send_os_scroll(dx=dx, dy=dy)
            time.sleep(0.25)
            state = self._state_with_os_screenshot()
            state.update(
                {
                    "scrolled": True,
                    "scroll_top": None,
                    "scroll_left": None,
                    "scroll_height": None,
                    "client_height": None,
                    "at_bottom": False,
                    "at_top": False,
                    "scroll_target": "os_active_window",
                }
            )
            return state

        script = _SCROLL_SCRIPT_TEMPLATE.format(dx=dx, dy=dy, x=x, y=y)
        with self._session() as session:
            session.send("Runtime.enable")
            metrics = session.evaluate(script) or {}
            time.sleep(0.25)
            state = self._state_with_screenshot(session)
        if isinstance(metrics, dict):
            state.update(
                {
                    "scrolled": bool(metrics.get("scrolled")),
                    "scroll_top": metrics.get("scroll_top"),
                    "scroll_left": metrics.get("scroll_left"),
                    "scroll_height": metrics.get("scroll_height"),
                    "client_height": metrics.get("client_height"),
                    "at_bottom": bool(metrics.get("at_bottom")),
                    "at_top": bool(metrics.get("at_top")),
                    "scroll_target": metrics.get("target"),
                }
            )
        return state

    def _state_with_screenshot(self, session: _CdpSession) -> dict:
        """Собрать url/title/размеры и base64 PNG-скриншот текущей страницы."""
        session.send("Page.enable")
        session.send("Runtime.enable")
        result = session.send(
            "Page.captureScreenshot",
            {"format": "png", "captureBeyondViewport": False},
        )
        screenshot_base64 = str(result.get("data") or "")
        url = session.evaluate("location.href")
        title = session.evaluate("document.title")
        viewport = session.evaluate(
            "({w: window.innerWidth||0, h: window.innerHeight||0})"
        ) or {}
        return {
            "url": url,
            "title": title,
            "screenshot_base64": screenshot_base64,
            "screenshot_media_type": "image/png",
            "viewport_width": int(viewport.get("w") or DEFAULT_VIEWPORT_WIDTH),
            "viewport_height": int(viewport.get("h") or DEFAULT_VIEWPORT_HEIGHT),
            **self.profile_output(cdp_available=True),
        }

    def _state_with_os_screenshot(
        self,
        warning: str = "",
        fallback_reason: str = "default_profile_os_fallback",
    ) -> dict:
        """Собрать скриншот виртуального desktop (все мониторы), когда CDP недоступен."""
        screenshot_base64, width, height = self._desktop_screenshot()
        meta = dict(self._os_capture_meta or {})
        return {
            "url": self._os_fallback_url,
            "title": "",
            "screenshot_base64": screenshot_base64,
            "screenshot_media_type": "image/png",
            "viewport_width": width,
            "viewport_height": height,
            "capture_mode": meta.get("capture_mode") or "virtual_desktop",
            "screen_origin_x": int(meta.get("origin_x") or self._os_click_origin[0]),
            "screen_origin_y": int(meta.get("origin_y") or self._os_click_origin[1]),
            "monitor_count": int(meta.get("monitor_count") or 1),
            "warning": (
                warning
                or (
                    "CDP недоступен для штатного профиля; OS fallback — скриншот "
                    + (
                        "окна браузера."
                        if meta.get("capture_mode") == "browser_window"
                        else "виртуального desktop (все мониторы)."
                    )
                )
            ),
            "window_title": meta.get("title") or "",
            **self.profile_output(
                cdp_available=False,
                fallback_used=True,
                fallback_reason=fallback_reason,
            ),
        }

    def _page_html(
        self,
        session: _CdpSession,
        *,
        max_chars: int,
        summary_chars: int,
    ) -> dict:
        """Собрать outerHTML текущей вкладки с лимитом и summary."""
        session.send("Runtime.enable")
        payload = session.evaluate(_html_script(max_chars, summary_chars)) or {}
        if not isinstance(payload, dict):
            raise BrowserCdpError("CDP не вернул HTML страницы.")
        html = str(payload.get("html") or "")
        html_length = int(payload.get("html_length") or len(html))
        truncated = bool(payload.get("truncated")) or html_length > max_chars
        html_summary = str(payload.get("html_summary") or html[:summary_chars])
        return {
            "url": payload.get("url") or session.evaluate("location.href"),
            "title": payload.get("title") or session.evaluate("document.title") or "",
            "html": html[:max_chars],
            "html_length": html_length,
            "truncated": truncated,
            "html_summary": html_summary[:summary_chars],
            **self.profile_output(cdp_available=True),
        }

    def profile_output(
        self,
        *,
        cdp_available: bool | None = None,
        fallback_used: bool = False,
        fallback_reason: str = "",
    ) -> dict:
        """Вернуть безопасную диагностику режима профиля vision worker."""
        if cdp_available is None:
            try:
                available = self._is_cdp_available()
            except Exception:
                available = False
        else:
            available = cdp_available
        return {
            "browser_id": self._config.browser_id or "",
            "browser_name": self._config.browser_id or "",
            "profile_mode": self._profile_mode,
            "user_data_dir": self._user_data_dir or "",
            "used_default_profile": self._profile_mode == "default",
            "command_args_summary": self._last_command_args_summary
            or _planned_command_args_summary(self._config, self._user_data_dir),
            "cdp_available": available,
            "cdp_url": _cdp_http_url(self._config.port) if available else "",
            "fallback_used": fallback_used,
            "fallback_reason": fallback_reason,
            "next_action_hint": _next_action_hint(
                self._profile_mode,
                cdp_available=available,
                fallback_used=fallback_used,
            ),
        }

    def _session(self) -> _CdpSession:
        """Вернуть CDP session постоянной вкладки (запустив браузер при нужде)."""
        self._ensure_browser()
        websocket_url = self._ensure_page_ws_url()
        return _CdpSession(websocket_url, timeout_seconds=self._config.timeout_seconds)

    def _ensure_browser(self) -> None:
        """Подключиться к существующему CDP или запустить видимый Chromium."""
        if self._is_cdp_available():
            return
        executable = self._config.executable_path or _find_chromium_executable()
        if executable is None:
            raise BrowserCdpError(
                "Не найден Edge/Chrome/Chromium для vision browser worker."
            )
        command = [
            executable,
            f"--remote-debugging-port={self._config.port}",
            f"--window-size={DEFAULT_VIEWPORT_WIDTH},{DEFAULT_VIEWPORT_HEIGHT}",
        ]
        if self._user_data_dir:
            if self._profile_mode != "default":
                Path(self._user_data_dir).mkdir(parents=True, exist_ok=True)
            command.append(f"--user-data-dir={self._user_data_dir}")
        profile_name = _resolved_profile_name(self._config)
        if profile_name and (
            self._config.use_default_profile or self._config.user_data_dir
        ):
            command.append(f"--profile-directory={profile_name}")
        command.extend(
            [
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-popup-blocking",
                "about:blank",
            ]
        )
        self._last_command_args_summary = _command_args_summary(
            command,
            executable=executable,
        )
        self._process = subprocess.Popen(  # noqa: S603 - executable найден локально
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._page_ws_url = None
        if self._wait_for_cdp_endpoint():
            return
        raise self._cdp_unavailable_error()

    def _ensure_page_ws_url(self) -> str:
        """Получить websocket постоянной вкладки, создав её один раз."""
        if self._page_ws_url and self._page_ws_alive(self._page_ws_url):
            return self._page_ws_url
        pages = self._get_json("/json/list")
        if isinstance(pages, list):
            for page in pages:
                if page.get("type") == "page" and page.get("webSocketDebuggerUrl"):
                    self._page_ws_url = str(page["webSocketDebuggerUrl"])
                    return self._page_ws_url
        payload = self._get_json("/json/new", method="PUT")
        websocket_url = payload.get("webSocketDebuggerUrl")
        if not websocket_url:
            raise BrowserCdpError("Не удалось создать вкладку для vision worker.")
        self._page_ws_url = str(websocket_url)
        return self._page_ws_url

    def _page_ws_alive(self, websocket_url: str) -> bool:
        """Проверить, что сохранённая вкладка ещё существует."""
        pages = self._get_json("/json/list")
        if not isinstance(pages, list):
            return False
        return any(page.get("webSocketDebuggerUrl") == websocket_url for page in pages)

    def _is_cdp_available(self) -> bool:
        """Проверить, отвечает ли CDP endpoint."""
        try:
            payload = self._get_json("/json/version", timeout_seconds=1.0)
        except Exception:
            return False
        return bool(payload.get("webSocketDebuggerUrl") or payload.get("Browser"))

    def _wait_for_cdp_endpoint(self) -> bool:
        """Дождаться /json/version короткими polling-запросами."""
        deadline = time.monotonic() + self._config.timeout_seconds
        while time.monotonic() < deadline:
            if self._is_cdp_available():
                return True
            time.sleep(0.25)
        return False

    def _cdp_unavailable_error(self) -> BrowserCdpEndpointUnavailable:
        """Собрать понятную ошибку недоступного CDP endpoint."""
        reason = (
            "default_profile_cdp_unavailable"
            if self._profile_mode == "default"
            else "cdp_endpoint_unavailable"
        )
        return BrowserCdpEndpointUnavailable(
            _cdp_unavailable_message(self._profile_mode),
            output_data=self.profile_output(
                cdp_available=False,
                fallback_used=False,
                fallback_reason=reason,
            ),
        )

    def _get_json(
        self,
        path: str,
        method: str = "GET",
        *,
        timeout_seconds: float | None = None,
    ) -> Any:
        """Прочитать JSON с локального CDP HTTP endpoint."""
        url = f"http://127.0.0.1:{self._config.port}{path}"
        http_request = request.Request(url, method=method)
        try:
            with request.urlopen(
                http_request,
                timeout=timeout_seconds or self._config.timeout_seconds,
            ) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            raise BrowserCdpError(f"CDP HTTP {exc.code}: {url}") from exc
        except (error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise BrowserCdpError(f"CDP endpoint недоступен: {exc}") from exc

    def _navigate(self, session: _CdpSession, url: str) -> None:
        """Перейти на URL и дождаться загрузки DOM."""
        session.send("Page.enable")
        session.send("Runtime.enable")
        session.send("Page.navigate", {"url": _require_http_url(url)})
        deadline = time.time() + self._config.timeout_seconds
        while time.time() < deadline:
            ready_state = session.evaluate("document.readyState")
            if ready_state in {"interactive", "complete"}:
                time.sleep(0.4)
                return
            time.sleep(0.2)
        raise BrowserCdpError("Страница не загрузилась за timeout.")

    def _can_fallback_to_open_browser(self, input_data: dict) -> bool:
        """Fallback безопасен только для открытия URL в штатном профиле."""
        return self._profile_mode == "default" and _bool_input(
            input_data.get("allow_open_browser_fallback"),
            default=True,
        )

    def _can_fallback_to_os_control(self, input_data: dict) -> bool:
        """Разрешить OS fallback для штатного профиля, если CDP недоступен."""
        return self._profile_mode == "default" and _bool_input(
            input_data.get("allow_os_fallback"),
            default=True,
        )

    def _open_without_cdp(self, url: str, *, fallback_reason: str, warning: str) -> dict:
        """Открыть URL обычным браузером без remote debugging и вернуть диагностику."""
        executable = self._config.executable_path or _find_chromium_executable()
        if executable is None:
            raise BrowserCdpError(
                "Не найден Edge/Chrome/Chromium для fallback browser.open_browser.",
                output_data=self.profile_output(
                    cdp_available=False,
                    fallback_used=False,
                    fallback_reason="fallback_browser_not_found",
                ),
            )
        command = [executable, url]
        self._last_command_args_summary = _command_args_summary(
            [
                executable,
                url,
                "no --remote-debugging-port",
                "no --user-data-dir",
                "no --profile-directory",
            ],
            executable=executable,
        )
        self._process = subprocess.Popen(  # noqa: S603 - executable найден локально
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._os_fallback_active = True
        self._os_fallback_url = url
        time.sleep(0.6)
        try:
            return self._state_with_os_screenshot(
                warning=warning,
                fallback_reason=fallback_reason,
            )
        except BrowserCdpError:
            pass
        return {
            "url": url,
            "title": "",
            "screenshot_base64": "",
            "screenshot_media_type": "",
            "viewport_width": DEFAULT_VIEWPORT_WIDTH,
            "viewport_height": DEFAULT_VIEWPORT_HEIGHT,
            "warning": (
                f"{warning} URL открыт в штатном профиле без CDP; скриншоты и "
                "vision-действия для этой вкладки недоступны."
            ),
            **self.profile_output(
                cdp_available=False,
                fallback_used=True,
                fallback_reason=fallback_reason,
            ),
        }

    def _desktop_screenshot(self) -> tuple[str, int, int]:
        """PNG-скриншот окна браузера (предпочтительно) или virtual desktop."""
        captured = None
        # E: сначала окно браузера — точнее координаты, меньше лишнего UI.
        if _is_windows():
            window_shot = capture_browser_window_png(
                self._os_fallback_url,
                focus=True,
            )
            if window_shot is not None:
                png_bytes, meta = window_shot
                self._os_click_origin = (
                    int(meta["origin_x"]),
                    int(meta["origin_y"]),
                )
                self._os_capture_meta = dict(meta)
                return (
                    base64.b64encode(png_bytes).decode("ascii"),
                    int(meta["width"]),
                    int(meta["height"]),
                )
            captured = _capture_virtual_desktop_win32()
        if captured is None:
            captured = _capture_virtual_desktop_qt()
        if captured is None:
            raise BrowserCdpError(
                "OS fallback screenshot недоступен: не удалось снять "
                "окно браузера или virtual desktop."
            )
        png_bytes, width, height, origin_x, origin_y, monitor_count, engine = captured
        self._os_click_origin = (int(origin_x), int(origin_y))
        self._os_capture_meta = {
            "capture_mode": "virtual_desktop",
            "origin_x": int(origin_x),
            "origin_y": int(origin_y),
            "monitor_count": int(monitor_count),
            "engine": engine,
            "width": int(width),
            "height": int(height),
        }
        return (
            base64.b64encode(png_bytes).decode("ascii"),
            int(width),
            int(height),
        )

    def _send_os_click(self, x: int, y: int, button: str) -> None:
        """Кликнуть по координатам скриншота (virtual desktop) через Win32."""
        if not _is_windows():
            raise BrowserCdpError("OS fallback click поддержан только на Windows.")
        import win32api
        import win32con

        origin_x, origin_y = self._os_click_origin
        abs_x = int(origin_x) + int(x)
        abs_y = int(origin_y) + int(y)
        down, up = (
            (win32con.MOUSEEVENTF_RIGHTDOWN, win32con.MOUSEEVENTF_RIGHTUP)
            if button == "right"
            else (win32con.MOUSEEVENTF_LEFTDOWN, win32con.MOUSEEVENTF_LEFTUP)
        )
        win32api.SetCursorPos((abs_x, abs_y))
        win32api.mouse_event(down, abs_x, abs_y, 0, 0)
        win32api.mouse_event(up, abs_x, abs_y, 0, 0)

    def _send_os_text(self, text: str) -> None:
        """Вставить текст в активное поле через clipboard + Ctrl+V."""
        if not _is_windows():
            raise BrowserCdpError("OS fallback type_text поддержан только на Windows.")
        import win32api
        import win32clipboard
        import win32con

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
        win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
        win32api.keybd_event(ord("V"), 0, 0, 0)
        win32api.keybd_event(ord("V"), 0, win32con.KEYEVENTF_KEYUP, 0)
        win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)

    def _send_os_key(self, descriptor: dict[str, Any]) -> None:
        """Нажать спец-клавишу в активном окне через Win32."""
        if not _is_windows():
            raise BrowserCdpError("OS fallback press_key поддержан только на Windows.")
        import win32api
        import win32con

        code = int(descriptor["windowsVirtualKeyCode"])
        win32api.keybd_event(code, 0, 0, 0)
        win32api.keybd_event(code, 0, win32con.KEYEVENTF_KEYUP, 0)

    def _send_os_scroll(self, *, dx: int, dy: int) -> None:
        """Прокрутить активное окно через Win32 mouse wheel."""
        if not _is_windows():
            raise BrowserCdpError("OS fallback scroll поддержан только на Windows.")
        import win32api
        import win32con

        if dy:
            win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, int(-dy), 0)
        if dx:
            win32api.mouse_event(win32con.MOUSEEVENTF_HWHEEL, 0, 0, int(dx), 0)


# JS находит правильную область прокрутки и двигает её. Без хардкода конкретных
# сайтов: опирается только на CSS overflow и реальные размеры прокрутки.
_SCROLL_SCRIPT_TEMPLATE = """
(function() {{
  var dx = {dx}, dy = {dy}, px = {x}, py = {y};
  function scrollableAxis(el) {{
    if (!(el instanceof Element)) return {{y: false, x: false}};
    var s = getComputedStyle(el);
    var canY = (s.overflowY === 'auto' || s.overflowY === 'scroll')
      && el.scrollHeight > el.clientHeight + 2;
    var canX = (s.overflowX === 'auto' || s.overflowX === 'scroll')
      && el.scrollWidth > el.clientWidth + 2;
    return {{y: canY, x: canX}};
  }}
  function needAxis(a) {{ return (dy !== 0 && a.y) || (dx !== 0 && a.x); }}
  function fromPoint(x, y) {{
    var el = document.elementFromPoint(x, y);
    while (el && el !== document.body && el !== document.documentElement) {{
      if (needAxis(scrollableAxis(el))) return el;
      el = el.parentElement;
    }}
    return null;
  }}
  function largest() {{
    var best = null, bestArea = 0;
    var nodes = document.querySelectorAll('*');
    for (var i = 0; i < nodes.length; i++) {{
      var el = nodes[i];
      var a = scrollableAxis(el);
      if (!needAxis(a)) continue;
      var rect = el.getBoundingClientRect();
      if (rect.width < 60 || rect.height < 60) continue;
      if (rect.bottom < 0 || rect.top > (window.innerHeight || 0)) continue;
      var area = (el.scrollHeight - el.clientHeight) + (el.scrollWidth - el.clientWidth);
      if (area > bestArea) {{ bestArea = area; best = el; }}
    }}
    return best;
  }}
  var target = (px >= 0 && py >= 0) ? fromPoint(px, py) : largest();
  var usedWindow = false;
  if (!target) {{ target = document.scrollingElement || document.documentElement; usedWindow = true; }}
  var beforeTop = target.scrollTop, beforeLeft = target.scrollLeft;
  target.scrollTop = beforeTop + dy;
  target.scrollLeft = beforeLeft + dx;
  var afterTop = target.scrollTop, afterLeft = target.scrollLeft;
  var desc = (usedWindow ? 'window' : (target.tagName || '').toLowerCase());
  if (!usedWindow && target.className && typeof target.className === 'string') {{
    desc += '.' + target.className.trim().split(/\\s+/).slice(0, 2).join('.');
  }}
  return {{
    scrolled: (afterTop !== beforeTop) || (afterLeft !== beforeLeft),
    scroll_top: afterTop,
    scroll_left: afterLeft,
    scroll_height: target.scrollHeight,
    client_height: target.clientHeight,
    at_bottom: (afterTop + target.clientHeight) >= (target.scrollHeight - 2),
    at_top: afterTop <= 0,
    target: desc.slice(0, 60)
  }};
}})()
"""


def _html_script(max_chars: int, summary_chars: int) -> str:
    """JS expression: documentElement.outerHTML с обрезкой и summary."""
    return f"""
(() => {{
  const maxChars = {int(max_chars)};
  const summaryChars = {int(summary_chars)};
  const root = document.documentElement;
  const full = root ? (root.outerHTML || '') : '';
  const htmlLength = full.length;
  const truncated = htmlLength > maxChars;
  const html = truncated ? full.slice(0, maxChars) : full;
  const htmlSummary = full.slice(0, Math.min(summaryChars, htmlLength));
  return {{
    url: location.href,
    title: document.title || '',
    html,
    html_length: htmlLength,
    truncated,
    html_summary: htmlSummary
  }};
}})()
"""


def _page_source_script() -> str:
    """JS expression: полный outerHTML + собранный CSS всех доступных stylesheet."""
    return """
(() => {
  const root = document.documentElement;
  const html = root ? (root.outerHTML || '') : '';
  const sheets = Array.from(document.styleSheets || []);
  const blocked = [];
  let css = '';
  sheets.forEach((sheet) => {
    const origin = sheet.href || 'inline';
    try {
      const rules = sheet.cssRules;
      if (!rules) return;
      let text = '';
      for (let i = 0; i < rules.length; i++) {
        text += rules[i].cssText + '\\n';
      }
      css += '/* ' + origin + ' */\\n' + text + '\\n';
    } catch (e) {
      blocked.push(origin);
      css += '/* ' + origin + ' (недоступно из-за CORS: ' + e.name + ') */\\n';
    }
  });
  return {
    url: location.href,
    title: document.title || '',
    html,
    css,
    stylesheet_count: sheets.length,
    blocked_stylesheets: blocked
  };
})()
"""


def _require_number(value: object, name: str, default: float | None = None) -> float:
    """Привести значение к числу или вернуть понятную ошибку."""
    if value is None and default is not None:
        return float(default)
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise BrowserCdpError(f"Параметр {name} должен быть числом.") from exc


def _bool_input(value: object, *, default: bool = False) -> bool:
    """Разобрать bool-флаг из JSON-like input."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "да", "истина"}
    return bool(value)


def _is_windows() -> bool:
    """Проверить, что OS fallback input можно выполнить через Win32."""
    return os.name == "nt"


def _png_bytes_from_qimage(image: Any) -> bytes | None:
    """Сохранить QImage/QPixmap в PNG bytes."""
    try:
        from PySide6.QtCore import QByteArray, QBuffer, QIODevice
    except Exception:
        return None
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        return None
    raw = bytes(data)
    return raw or None


def _capture_virtual_desktop_win32() -> (
    tuple[bytes, int, int, int, int, int, str] | None
):
    """Снять весь virtual desktop через Win32 BitBlt (физические пиксели)."""
    try:
        import win32con
        import win32gui
        import win32ui
        from ctypes import windll
        from PySide6.QtGui import QImage
    except Exception:
        return None

    user32 = windll.user32
    # SM_XVIRTUALSCREEN / Y / CX / CY
    left = int(user32.GetSystemMetrics(76))
    top = int(user32.GetSystemMetrics(77))
    width = int(user32.GetSystemMetrics(78))
    height = int(user32.GetSystemMetrics(79))
    if width <= 0 or height <= 0:
        return None
    monitor_count = max(1, int(user32.GetSystemMetrics(80)))  # SM_CMONITORS

    hwnd = win32gui.GetDesktopWindow()
    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
    save_dc.SelectObject(bitmap)
    # SRCCOPY | CAPTUREBLT — захватить layered windows тоже.
    save_dc.BitBlt(
        (0, 0),
        (width, height),
        mfc_dc,
        (left, top),
        win32con.SRCCOPY | getattr(win32con, "CAPTUREBLT", 0x40000000),
    )
    bmp_str = bitmap.GetBitmapBits(True)
    win32gui.DeleteObject(bitmap.GetHandle())
    save_dc.DeleteDC()
    mfc_dc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwnd_dc)

    image = QImage(bmp_str, width, height, QImage.Format.Format_RGB32)
    if image.isNull():
        return None
    # Копия владеет памятью — bmp_str иначе может быть собран GC.
    image = image.copy()
    png = _png_bytes_from_qimage(image)
    if not png:
        return None
    return png, width, height, left, top, monitor_count, "win32"


def _capture_virtual_desktop_qt() -> tuple[bytes, int, int, int, int, int, str] | None:
    """Склеить скриншоты всех QScreen в один virtual desktop (fallback)."""
    try:
        from PySide6.QtCore import QRect, Qt
        from PySide6.QtGui import QGuiApplication, QPainter, QPixmap
    except Exception:
        return None

    app = QGuiApplication.instance()
    if app is None:
        return None
    screens = list(app.screens() or [])
    if not screens:
        return None

    # Логическая геометрия virtual desktop.
    left = min(screen.geometry().x() for screen in screens)
    top = min(screen.geometry().y() for screen in screens)
    right = max(
        screen.geometry().x() + screen.geometry().width() for screen in screens
    )
    bottom = max(
        screen.geometry().y() + screen.geometry().height() for screen in screens
    )
    logical_w = max(1, right - left)
    logical_h = max(1, bottom - top)

    # Рисуем в device pixels primary DPR, чтобы клики оставались согласованы
    # на типичной конфигурации; смешанный DPI — компромисс Qt-пути.
    dpr = float(app.primaryScreen().devicePixelRatio() or 1.0)
    out_w = max(1, int(round(logical_w * dpr)))
    out_h = max(1, int(round(logical_h * dpr)))
    canvas = QPixmap(out_w, out_h)
    canvas.fill(Qt.GlobalColor.black)
    painter = QPainter(canvas)
    try:
        for screen in screens:
            geo = screen.geometry()
            grabbed = screen.grabWindow(0)
            if grabbed.isNull():
                continue
            target = QRect(
                int(round((geo.x() - left) * dpr)),
                int(round((geo.y() - top) * dpr)),
                int(round(geo.width() * dpr)),
                int(round(geo.height() * dpr)),
            )
            painter.drawPixmap(target, grabbed)
    finally:
        painter.end()

    png = _png_bytes_from_qimage(canvas)
    if not png:
        return None
    # origin в тех же единицах, что и SetCursorPos на Win (физические ≈ logical*dpr
    # при едином масштабе); для не-Windows клики всё равно недоступны.
    origin_x = int(round(left * dpr))
    origin_y = int(round(top * dpr))
    return (
        png,
        out_w,
        out_h,
        origin_x,
        origin_y,
        len(screens),
        "qt",
    )
