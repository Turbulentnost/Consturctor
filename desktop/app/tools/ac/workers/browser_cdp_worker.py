"""Read-only browser worker на Chrome DevTools Protocol.

Worker управляет Chromium-браузером (Edge/Chrome/Chromium) через CDP без
зависимостей Selenium/Playwright. Инструменты используют его только для чтения:
навигация, извлечение текста/ссылок/таблиц и прокрутка.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import shutil
import socket
import struct
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, parse, request

from app.tools.ac.workers.browser_detect import resolve_default_user_data_dir

DEFAULT_CDP_PORT = 9223
DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_MAX_CHARS = 8000
MAX_MAX_CHARS = 50000
MAX_LINKS = 50
MAX_TABLES = 10
MAX_TABLE_ROWS = 80
MAX_TABLE_COLUMNS = 20

BLOCKED_URL_SCHEMES = {"javascript", "mailto", "file", "data", "ftp"}
DEFAULT_AUTOMATION_PROFILE_NAME = "automation"


class BrowserCdpError(RuntimeError):
    """Ошибка CDP browser worker."""

    def __init__(self, message: str, *, output_data: dict | None = None) -> None:
        """Сохранить человекочитаемую ошибку и безопасную диагностику."""
        super().__init__(message)
        self.output_data = output_data or {}


class BrowserCdpEndpointUnavailable(BrowserCdpError):
    """Браузер запущен, но локальный CDP endpoint не поднялся."""


@dataclass
class BrowserLaunchConfig:
    """Параметры запуска Chromium-браузера."""

    port: int = DEFAULT_CDP_PORT
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    user_data_dir: str | None = None
    executable_path: str | None = None
    browser_id: str | None = None
    profile_name: str | None = None
    use_default_profile: bool = False


class BrowserCdpWorker:
    """Управляет браузером через CDP в read-only сценариях."""

    def __init__(self, config: BrowserLaunchConfig | None = None) -> None:
        """Создать worker с ленивым запуском браузера."""
        self._config = config or BrowserLaunchConfig()
        self._process: subprocess.Popen | None = None
        self._user_data_dir = _resolve_user_data_dir(self._config, profile_kind="cdp")
        self._profile_mode = _profile_mode(self._config)
        self._last_command_args_summary: list[str] = []

    def open_page(self, input_data: dict) -> dict:
        """Открыть страницу и извлечь title/text/links."""
        url = _require_http_url(input_data.get("url"))
        max_chars = _clamp_int(
            input_data.get("max_chars"),
            DEFAULT_MAX_CHARS,
            1,
            MAX_MAX_CHARS,
        )
        with self._session_for_url(url) as session:
            self._navigate(session, url)
            return self._page_snapshot(session, max_chars)

    def scroll_page(self, input_data: dict) -> dict:
        """Прокрутить страницу и вернуть текст после прокрутки."""
        url = _require_http_url(input_data.get("url"))
        direction = str(input_data.get("direction") or "down").strip().casefold()
        pixels = _clamp_int(input_data.get("pixels"), 900, 1, 10000)
        max_chars = _clamp_int(
            input_data.get("max_chars"),
            DEFAULT_MAX_CHARS,
            1,
            MAX_MAX_CHARS,
        )
        delta = -pixels if direction in {"up", "вверх"} else pixels
        with self._session_for_url(url) as session:
            self._navigate(session, url)
            session.evaluate(f"window.scrollBy(0, {delta}); true")
            time.sleep(0.2)
            snapshot = self._page_snapshot(session, max_chars)
            snapshot["scroll_y"] = int(
                session.evaluate("Math.round(window.scrollY || 0)") or 0
            )
            return snapshot

    def click_link(self, input_data: dict) -> dict:
        """Перейти по безопасной ссылке на странице и вернуть новую страницу."""
        url = _require_http_url(input_data.get("url"))
        href = str(input_data.get("href") or "").strip()
        link_text = str(input_data.get("link_text") or "").strip()
        if not href and not link_text:
            raise BrowserCdpError("Укажите href или link_text для browser.click_link.")
        max_chars = _clamp_int(
            input_data.get("max_chars"),
            DEFAULT_MAX_CHARS,
            1,
            MAX_MAX_CHARS,
        )
        with self._session_for_url(url) as session:
            self._navigate(session, url)
            target_url = self._find_link_url(session, href=href, link_text=link_text)
            self._navigate(session, target_url)
            return self._page_snapshot(session, max_chars)

    def extract_table(self, input_data: dict) -> dict:
        """Извлечь таблицы со страницы."""
        url = _require_http_url(input_data.get("url"))
        table_hint = str(input_data.get("table_hint") or "").strip()
        with self._session_for_url(url) as session:
            self._navigate(session, url)
            tables = session.evaluate(_tables_script(table_hint)) or []
            return {
                "url": session.evaluate("location.href"),
                "title": session.evaluate("document.title"),
                "tables": tables[:MAX_TABLES] if isinstance(tables, list) else [],
                **self.profile_output(cdp_available=True),
            }

    def _session_for_url(self, url: str) -> "_CdpSession":
        """Вернуть CDP session для страницы."""
        self._ensure_browser()
        websocket_url = self._get_page_websocket_url(url)
        return _CdpSession(websocket_url, timeout_seconds=self._config.timeout_seconds)

    def _ensure_browser(self) -> None:
        """Подключиться к существующему CDP или запустить Chromium."""
        if self._is_cdp_available():
            return
        executable = self._config.executable_path or _find_chromium_executable()
        if executable is None:
            raise BrowserCdpError(
                "Не найден Edge/Chrome/Chromium для browser CDP worker."
            )
        command = [
            executable,
            f"--remote-debugging-port={self._config.port}",
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
        if self._wait_for_cdp_endpoint():
            return
        raise self._cdp_unavailable_error()

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

    def _get_page_websocket_url(self, url: str) -> str:
        """Создать/найти вкладку и вернуть webSocketDebuggerUrl."""
        encoded_url = parse.quote(url, safe="")
        for method in ("PUT", "GET"):
            try:
                payload = self._get_json(f"/json/new?{encoded_url}", method=method)
                websocket_url = payload.get("webSocketDebuggerUrl")
                if websocket_url:
                    return str(websocket_url)
            except Exception:
                continue
        pages = self._get_json("/json/list")
        if isinstance(pages, list):
            for page in pages:
                if page.get("type") == "page" and page.get("webSocketDebuggerUrl"):
                    return str(page["webSocketDebuggerUrl"])
        raise BrowserCdpError("Не удалось получить CDP websocket вкладки.")

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

    def _navigate(self, session: "_CdpSession", url: str) -> None:
        """Перейти на URL и дождаться загрузки DOM."""
        session.send("Page.enable")
        session.send("Runtime.enable")
        session.send("Page.navigate", {"url": _require_http_url(url)})
        deadline = time.time() + self._config.timeout_seconds
        while time.time() < deadline:
            ready_state = session.evaluate("document.readyState")
            if ready_state in {"interactive", "complete"}:
                return
            time.sleep(0.2)
        raise BrowserCdpError("Страница не загрузилась за timeout.")

    def _page_snapshot(self, session: "_CdpSession", max_chars: int) -> dict:
        """Вернуть title/text/links текущей страницы."""
        snapshot = session.evaluate(_snapshot_script(max_chars, MAX_LINKS)) or {}
        if isinstance(snapshot, dict):
            snapshot.update(self.profile_output(cdp_available=True))
        return snapshot

    def profile_output(
        self,
        *,
        cdp_available: bool | None = None,
        fallback_used: bool = False,
        fallback_reason: str = "",
    ) -> dict:
        """Вернуть безопасную диагностику режима профиля browser worker."""
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

    def _find_link_url(self, session: "_CdpSession", *, href: str, link_text: str) -> str:
        """Найти безопасный href по href или тексту ссылки."""
        link = session.evaluate(_find_link_script(href, link_text))
        if not isinstance(link, dict) or not link.get("href"):
            raise BrowserCdpError("Подходящая ссылка не найдена на странице.")
        target_url = _require_http_url(link["href"])
        return target_url


class _CdpSession:
    """Минимальный CDP WebSocket session."""

    def __init__(self, websocket_url: str, timeout_seconds: int) -> None:
        """Открыть WebSocket к CDP target."""
        self._url = websocket_url
        self._timeout_seconds = timeout_seconds
        self._socket: socket.socket | None = None
        self._next_id = 0

    def __enter__(self) -> "_CdpSession":
        self._socket = _open_websocket(self._url, self._timeout_seconds)
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass

    def send(self, method: str, params: dict | None = None) -> dict:
        """Отправить CDP command и дождаться matching response."""
        if self._socket is None:
            raise BrowserCdpError("CDP websocket не открыт.")
        self._next_id += 1
        message_id = self._next_id
        payload = {"id": message_id, "method": method}
        if params:
            payload["params"] = params
        _send_ws_text(self._socket, json.dumps(payload, ensure_ascii=False))
        deadline = time.time() + self._timeout_seconds
        while time.time() < deadline:
            raw_message = _recv_ws_text(self._socket)
            if raw_message is None:
                continue
            message = json.loads(raw_message)
            if message.get("id") != message_id:
                continue
            if "error" in message:
                raise BrowserCdpError(f"CDP {method} error: {message['error']}")
            return message.get("result") or {}
        raise BrowserCdpError(f"CDP {method} не ответил за timeout.")

    def evaluate(self, expression: str) -> Any:
        """Выполнить JS expression и вернуть JSON-значение."""
        result = self.send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": True,
                "returnByValue": True,
            },
        )
        remote_object = result.get("result") or {}
        if "exceptionDetails" in result:
            raise BrowserCdpError(f"JS error: {result['exceptionDetails']}")
        return remote_object.get("value")


def _open_websocket(websocket_url: str, timeout_seconds: int) -> socket.socket:
    """Открыть WebSocket handhake для ws:// CDP URL."""
    parsed = parse.urlparse(websocket_url)
    if parsed.scheme != "ws":
        raise BrowserCdpError(f"Поддерживается только ws:// CDP URL: {websocket_url}")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    sock = socket.create_connection((host, port), timeout=timeout_seconds)
    sock.settimeout(timeout_seconds)
    key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
    request_text = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    sock.sendall(request_text.encode("ascii"))
    response = _recv_until(sock, b"\r\n\r\n")
    if b" 101 " not in response.split(b"\r\n", 1)[0]:
        sock.close()
        raise BrowserCdpError("CDP websocket handshake не принят.")
    accept = base64.b64encode(
        hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
    ).decode("ascii")
    if accept.encode("ascii") not in response:
        sock.close()
        raise BrowserCdpError("CDP websocket handshake вернул неверный accept key.")
    return sock


def _send_ws_text(sock: socket.socket, text: str) -> None:
    """Отправить masked client text frame."""
    payload = text.encode("utf-8")
    header = bytearray([0x81])
    length = len(payload)
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.append(0x80 | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack("!Q", length))
    mask = secrets.token_bytes(4)
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    sock.sendall(bytes(header) + mask + masked)


def _recv_ws_text(sock: socket.socket) -> str | None:
    """Прочитать один server WebSocket text frame."""
    first_two = _recv_exact(sock, 2)
    if not first_two:
        return None
    first, second = first_two
    opcode = first & 0x0F
    masked = bool(second & 0x80)
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", _recv_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _recv_exact(sock, 8))[0]
    mask = _recv_exact(sock, 4) if masked else b""
    payload = _recv_exact(sock, length) if length else b""
    if masked and mask:
        payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    if opcode == 0x8:
        return None
    if opcode not in {0x1, 0x0}:
        return None
    return payload.decode("utf-8", errors="replace")


def _recv_exact(sock: socket.socket, length: int) -> bytes:
    """Прочитать ровно length bytes."""
    chunks = bytearray()
    while len(chunks) < length:
        chunk = sock.recv(length - len(chunks))
        if not chunk:
            raise BrowserCdpError("CDP websocket закрыл соединение.")
        chunks.extend(chunk)
    return bytes(chunks)


def _recv_until(sock: socket.socket, marker: bytes) -> bytes:
    """Читать socket до marker."""
    data = bytearray()
    while marker not in data:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data.extend(chunk)
    return bytes(data)


def _find_chromium_executable() -> str | None:
    """Найти Edge/Chrome/Chromium на Windows/Linux/macOS."""
    for command in ["msedge", "chrome", "google-chrome", "chromium", "chromium-browser"]:
        if path := shutil.which(command):
            return path
    candidates = [
        Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", ""))
        / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", ""))
        / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def _resolve_user_data_dir(config: BrowserLaunchConfig, *, profile_kind: str) -> str | None:
    """Вернуть каталог профиля для CDP launch без временных одноразовых профилей."""
    if config.user_data_dir:
        return config.user_data_dir
    if config.use_default_profile:
        return resolve_default_user_data_dir(config.browser_id or "")
    browser_id = _safe_profile_segment(config.browser_id or "default")
    profile_name = _safe_profile_segment(
        config.profile_name or DEFAULT_AUTOMATION_PROFILE_NAME
    )
    return str(_browser_profiles_root() / profile_kind / browser_id / profile_name)


def _profile_mode(config: BrowserLaunchConfig) -> str:
    """Определить режим профиля для user-facing диагностики."""
    if config.user_data_dir:
        return "custom"
    if config.use_default_profile:
        return "default"
    return "automation"


def _resolved_profile_name(config: BrowserLaunchConfig) -> str | None:
    """Вернуть profile-directory, если его нужно явно передать Chromium."""
    if config.profile_name:
        return config.profile_name
    return None


def _planned_command_args_summary(
    config: BrowserLaunchConfig,
    user_data_dir: str | None,
) -> list[str]:
    """Собрать краткое описание будущих аргументов запуска без запуска процесса."""
    summary = [f"--remote-debugging-port={config.port}"]
    if user_data_dir:
        summary.append(f"--user-data-dir={user_data_dir}")
    profile_name = _resolved_profile_name(config)
    if profile_name:
        summary.append(f"--profile-directory={profile_name}")
    summary.extend(
        [
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-popup-blocking",
            "about:blank",
        ]
    )
    return summary


def _command_args_summary(command: list[str], *, executable: str) -> list[str]:
    """Убрать полный путь exe из summary, оставив важные флаги запуска."""
    return ["<browser_executable>", *command[1:]] if command and command[0] == executable else command


def _cdp_http_url(port: int) -> str:
    """Вернуть базовый URL локального CDP HTTP endpoint."""
    return f"http://127.0.0.1:{port}"


def _cdp_unavailable_message(profile_mode: str) -> str:
    """Вернуть понятную причину, почему CDP endpoint мог не подняться."""
    if profile_mode == "default":
        return (
            "Браузер запущен, но CDP endpoint не ответил. Частая причина: штатный "
            "профиль уже открыт обычным процессом браузера без remote debugging, "
            "поэтому новый запуск с тем же профилем не создаёт управляемый CDP endpoint."
        )
    return "Браузер запущен, но CDP endpoint не ответил."


def _next_action_hint(
    profile_mode: str,
    *,
    cdp_available: bool,
    fallback_used: bool,
) -> str:
    """Подсказать planner-у безопасный следующий шаг."""
    if cdp_available:
        return "CDP доступен: можно продолжать browser vision/CDP действия."
    if fallback_used:
        return (
            "URL открыт в штатном профиле без CDP: пользовательская сессия сохранена. "
            "Продолжай через browser.screenshot/browser.click/browser.type_text/"
            "browser.press_key/browser.scroll в OS fallback. Скриншот — окно "
            "браузера (если найдено) или virtual desktop; координаты клика — в "
            "пикселях приложенной картинки (image_width×image_height). Не "
            "переключайся на automation profile, если нужна текущая авторизация "
            "пользователя."
        )
    if profile_mode == "default":
        return (
            "CDP недоступен для штатного профиля. Если нужна авторизация пользователя, "
            "не переключайся на automation profile и не меняй браузер: попроси человека "
            "закрыть уже открытые окна этого браузера, затем повтори действие с тем же "
            "browser_id и use_default_profile=true. Для простого визуального управления "
            "без DOM можно использовать browser.open_browser + OS fallback. Для HTML/CSS "
            "или таблиц программно нужен именно CDP."
        )
    return (
        "CDP endpoint недоступен даже в automation profile: проверь установленный "
        "Chromium-браузер, порт remote debugging и локальные политики безопасности."
    )


def _browser_profiles_root() -> Path:
    """Стабильный per-user root для automation-профилей браузера."""
    configured = os.environ.get("AGENT_CONSTRUCTOR_BROWSER_PROFILE_ROOT")
    if configured:
        return Path(configured)
    base_dir = (
        os.environ.get("LOCALAPPDATA")
        or os.environ.get("XDG_DATA_HOME")
        or str(Path.home() / ".agent_constructor")
    )
    return Path(base_dir) / "AgentConstructor" / "browser_profiles"


def _safe_profile_segment(value: str) -> str:
    """Сделать имя сегмента пути стабильным и безопасным для ФС."""
    cleaned = "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "_"
        for char in value.strip().casefold()
    ).strip("._")
    return cleaned or DEFAULT_AUTOMATION_PROFILE_NAME


def _require_http_url(value: object) -> str:
    """Проверить URL и заблокировать небезопасные схемы."""
    url = str(value or "").strip()
    parsed = parse.urlparse(url)
    if parsed.scheme.casefold() in BLOCKED_URL_SCHEMES:
        raise BrowserCdpError(f"Схема URL запрещена: {parsed.scheme}")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise BrowserCdpError("URL должен быть абсолютным http/https адресом.")
    return url


def _snapshot_script(max_chars: int, max_links: int) -> str:
    """JS expression для извлечения текста и ссылок."""
    return f"""
(() => {{
  const maxChars = {int(max_chars)};
  const maxLinks = {int(max_links)};
  const text = (document.body ? document.body.innerText : '').slice(0, maxChars);
  const links = Array.from(document.querySelectorAll('a[href]'))
    .map((a) => {{
      let href = '';
      try {{ href = new URL(a.getAttribute('href'), location.href).href; }} catch (e) {{}}
      return {{ text: (a.innerText || a.textContent || '').trim().slice(0, 200), href }};
    }})
    .filter((item) => item.href && item.text)
    .slice(0, maxLinks);
  return {{ url: location.href, title: document.title || '', text, links }};
}})()
"""


def _find_link_script(href: str, link_text: str) -> str:
    """JS expression для поиска ссылки."""
    return f"""
(() => {{
  const wantedHref = {json.dumps(href)};
  const wantedText = {json.dumps(link_text.casefold())};
  const links = Array.from(document.querySelectorAll('a[href]'));
  for (const a of links) {{
    let absoluteHref = '';
    try {{ absoluteHref = new URL(a.getAttribute('href'), location.href).href; }} catch (e) {{}}
    const text = (a.innerText || a.textContent || '').trim().toLowerCase();
    if (wantedHref && absoluteHref === wantedHref) return {{ href: absoluteHref, text }};
    if (wantedText && text.includes(wantedText)) return {{ href: absoluteHref, text }};
  }}
  return null;
}})()
"""


def _tables_script(table_hint: str) -> str:
    """JS expression для извлечения таблиц."""
    return f"""
(() => {{
  const hint = {json.dumps(table_hint.casefold())};
  return Array.from(document.querySelectorAll('table'))
    .map((table, index) => {{
      const caption = (table.caption ? table.caption.innerText : '').trim();
      const rows = Array.from(table.querySelectorAll('tr')).slice(0, {MAX_TABLE_ROWS})
        .map((row) => Array.from(row.querySelectorAll('th,td')).slice(0, {MAX_TABLE_COLUMNS})
          .map((cell) => (cell.innerText || cell.textContent || '').trim()));
      const text = [caption, ...rows.flat()].join(' ').toLowerCase();
      return {{ index, caption, rows }};
    }})
    .filter((table) => !hint || JSON.stringify(table).toLowerCase().includes(hint))
    .slice(0, {MAX_TABLES});
}})()
"""


def _clamp_int(value: object, default: int, minimum: int, maximum: int) -> int:
    """Привести числовой параметр к безопасному диапазону."""
    try:
        parsed_value = int(value)
    except (TypeError, ValueError):
        parsed_value = default
    return max(minimum, min(maximum, parsed_value))
