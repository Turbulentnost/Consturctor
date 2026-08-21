"""32-bit V83.COMConnector через SysWOW64 cscript. Только ВЫБРАТЬ."""

from __future__ import annotations

import functools
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from app.tools.ported.ac.workers.onec_meeting_notes import assert_select_only

ENV_PROGID = "ONEC_COM_PROGID"
ENV_CONNECTION_STRING = "ONEC_COM_CONNECTION_STRING"
ENV_SERVER = "ONEC_COM_SERVER"
ENV_REF = "ONEC_COM_REF"
ENV_LOGIN = "ERP_LOGIN"
ENV_PASSWORD = "ERP_PASSWORD"
DEFAULT_PROGID = "V83.COMConnector"
# CONNECT к erp_pm часто 60–90 с; 150 с обрывало живой сеанс и уходило в чат как mismatch.
COM32_SELECT_TIMEOUT = 180
COM32_TIMEOUT_RETRIES = 1
COM32_RETRY_PAUSE_SEC = 3


class Com32TimeoutError(RuntimeError):
    """cscript завис на CONNECT/Execute — это не пустой SELECT."""

    def __init__(self, seconds: int) -> None:
        self.seconds = int(seconds)
        super().__init__(
            f"1С не ответила через COM за {self.seconds} с. "
            "Повтори тот же вызов — это таймаут сеанса, не пустой список документов."
        )


def com32_worker_timeout_seconds() -> int:
    """Бюджет subprocess-worker: попытка + повтор + пауза."""
    return (
        COM32_SELECT_TIMEOUT * (1 + COM32_TIMEOUT_RETRIES)
        + COM32_RETRY_PAUSE_SEC
        + 20
    )


def cscript32() -> Path:
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    return windir / "SysWOW64" / "cscript.exe"


@functools.lru_cache(maxsize=1)
def is_com32_available() -> tuple[bool, str]:
    """Проверить, что 32-bit cscript создаёт V83.COMConnector."""
    exe = cscript32()
    if not exe.is_file():
        return False, f"Нет 32-bit cscript: {exe}"
    progid = os.environ.get(ENV_PROGID, DEFAULT_PROGID).strip() or DEFAULT_PROGID
    script = "\r\n".join(
        [
            "On Error Resume Next",
            f'Set o = CreateObject("{progid}")',
            "If Err.Number <> 0 Then",
            "  WScript.StdErr.WriteLine Err.Description",
            "  WScript.Quit 2",
            "End If",
            'WScript.StdOut.WriteLine "ok"',
        ]
    )
    try:
        code, stdout, stderr = _run_vbs(script, timeout=20)
    except Com32TimeoutError as exc:
        return False, str(exc)
    if code == 0 and "ok" in (stdout or ""):
        return True, "32-bit COMConnector доступен"
    return False, (stderr or stdout or f"helper exit {code}").strip()


def run_select(
    query_text: str,
    columns: list[str],
    *,
    timeout: int | None = None,
) -> list[dict[str, str]]:
    """Выполнить один SELECT в 1С через 32-bit COMConnector. Без записи."""
    rows, _index = run_select_first([(query_text, columns)], timeout=timeout)
    return rows


def run_select_first(
    attempts: list[tuple[str, list[str]]],
    *,
    timeout: int | None = None,
) -> tuple[list[dict[str, str]], int]:
    """Один CONNECT, затем варианты SELECT. Без записи в 1С."""
    seconds = int(timeout or COM32_SELECT_TIMEOUT)
    last: BaseException | None = None
    for attempt in range(COM32_TIMEOUT_RETRIES + 1):
        try:
            return _run_select_first_once(attempts, timeout=seconds)
        except Com32TimeoutError as exc:
            last = exc
            if attempt >= COM32_TIMEOUT_RETRIES:
                break
            time.sleep(COM32_RETRY_PAUSE_SEC)
    assert last is not None
    raise last


def _run_select_first_once(
    attempts: list[tuple[str, list[str]]],
    *,
    timeout: int,
) -> tuple[list[dict[str, str]], int]:
    if not attempts:
        raise RuntimeError("Нет SELECT-запросов для 32-bit helper")
    conn = connection_string()
    if not conn:
        raise RuntimeError(
            "Не заданы ONEC_COM_CONNECTION_STRING или ONEC_COM_SERVER/ONEC_COM_REF"
        )
    prepared: list[tuple[str, list[str]]] = []
    for query_text, columns in attempts:
        query = assert_select_only(query_text)
        aliases = [col for col in columns if col and col.isascii()]
        if not aliases:
            raise RuntimeError("Для 32-bit helper нужны латинские алиасы колонок")
        prepared.append((query, aliases))
    script = _query_vbs()
    with tempfile.TemporaryDirectory(prefix="onec_com32_") as raw_dir:
        folder = Path(raw_dir)
        (folder / "conn.txt").write_text(conn, encoding="utf-16")
        (folder / "count.txt").write_text(str(len(prepared)), encoding="utf-16")
        for index, (query, aliases) in enumerate(prepared):
            (folder / f"q{index}.txt").write_text(query, encoding="utf-16")
            (folder / f"c{index}.txt").write_text("\n".join(aliases), encoding="utf-16")
        code, stdout, stderr = _run_vbs(script, args=[str(folder)], timeout=timeout)
        raw = ""
        out_path = folder / "out.txt"
        if out_path.is_file():
            raw = out_path.read_text(encoding="utf-16")
    if code != 0:
        raise RuntimeError((stderr or stdout or f"COM32 exit {code}").strip())
    text = raw.strip() or (stdout or "").strip() or "[]"
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"COM32 вернул не JSON: {text[:400]}") from exc
    if not isinstance(payload, list):
        raise RuntimeError("COM32: ожидался массив строк")
    rows: list[dict[str, str]] = []
    for item in payload:
        if isinstance(item, dict):
            rows.append({str(key): str(value) for key, value in item.items()})
    chosen = 0
    for line in (stderr or "").splitlines():
        if line.startswith("OK "):
            try:
                chosen = int(line.split()[1])
            except (IndexError, ValueError):
                chosen = 0
    return rows, chosen


def connection_string() -> str:
    explicit = os.environ.get(ENV_CONNECTION_STRING, "").strip()
    if explicit:
        return explicit
    server = os.environ.get(ENV_SERVER, "").strip()
    ref = os.environ.get(ENV_REF, "").strip()
    if not server or not ref:
        return ""
    parts = [f"Srvr={_quote(server)}", f"Ref={_quote(ref)}"]
    login = os.environ.get(ENV_LOGIN, "").strip()
    password = os.environ.get(ENV_PASSWORD, "").strip()
    if login and password:
        parts.append(f"Usr={_quote(login)}")
        parts.append(f"Pwd={_quote(password)}")
    return ";".join(parts) + ";"


def _quote(value: str) -> str:
    if not value:
        return value
    if any(char in value for char in (" ", ";", '"')):
        return '"' + value.replace('"', '""') + '"'
    return value


def _query_vbs() -> str:
    # Строки собираются списком, чтобы кавычки VBS не ломали Python-строку.
    return "\r\n".join(
        [
            "Option Explicit",
            "Dim fso, folder, connector, session, query, table, row, i, j, n, qidx",
            "Dim conn, qtext, cols, col, parts, value, lastErr, first, outFile",
            "Set fso = CreateObject(\"Scripting.FileSystemObject\")",
            "folder = WScript.Arguments.Item(0)",
            "If Right(folder, 1) <> \"\\\" Then folder = folder & \"\\\"",
            "conn = fso.OpenTextFile(folder & \"conn.txt\", 1, False, -1).ReadAll()",
            "n = CInt(Trim(fso.OpenTextFile(folder & \"count.txt\", 1, False, -1).ReadAll()))",
            "On Error Resume Next",
            "Set connector = CreateObject(\"V83.COMConnector\")",
            "If Err.Number <> 0 Then",
            "  WScript.StdErr.WriteLine \"CREATE \" & Err.Description",
            "  WScript.Quit 2",
            "End If",
            "Err.Clear",
            "Set session = connector.Connect(conn)",
            "If Err.Number <> 0 Then",
            "  WScript.StdErr.WriteLine \"CONNECT \" & Err.Description",
            "  WScript.Quit 3",
            "End If",
            "lastErr = \"\"",
            "For qidx = 0 To n - 1",
            "  Err.Clear",
            "  qtext = fso.OpenTextFile(folder & \"q\" & qidx & \".txt\", 1, False, -1).ReadAll()",
            "  cols = Split(Replace(fso.OpenTextFile(folder & \"c\" & qidx & \".txt\", 1, False, -1).ReadAll(), vbCr, \"\"), vbLf)",
            "  Set query = session.NewObject(\"Query\")",
            "  query.Text = qtext",
            "  Set table = query.Execute().Unload()",
            "  If Err.Number = 0 Then",
            "    WScript.StdErr.WriteLine \"OK \" & qidx",
            "    Set outFile = fso.CreateTextFile(folder & \"out.txt\", True, True)",
            "    outFile.Write \"[\"",
            "    first = True",
            "    For i = 0 To table.Count() - 1",
            "      Set row = table.Get(i)",
            "      If Not first Then outFile.Write \",\"",
            "      first = False",
            "      outFile.Write \"{\"",
            "      parts = 0",
            "      For j = 0 To UBound(cols)",
            "        col = Trim(cols(j))",
            "        If col <> \"\" Then",
            "          If parts > 0 Then outFile.Write \",\"",
            "          Err.Clear",
            "          value = CStr(CallByName(row, col, 2))",
            "          If Err.Number <> 0 Then",
            "            Err.Clear",
            "            value = CStr(row.Get(j))",
            "          End If",
            "          If Err.Number <> 0 Then",
            "            Err.Clear",
            "            value = \"\"",
            "          End If",
            "          outFile.Write Chr(34) & col & Chr(34) & \":\" & Chr(34) & JsonEscape(value) & Chr(34)",
            "          parts = parts + 1",
            "        End If",
            "      Next",
            "      outFile.Write \"}\"",
            "    Next",
            "    outFile.Write \"]\"",
            "    outFile.Close",
            "    WScript.Quit 0",
            "  End If",
            "  lastErr = Err.Description",
            "  Err.Clear",
            "Next",
            "WScript.StdErr.WriteLine \"QUERY \" & lastErr",
            "WScript.Quit 4",
            "",
            "Function JsonEscape(text)",
            "  Dim s",
            "  s = text",
            "  s = Replace(s, \"\\\", \"\\\\\")",
            "  s = Replace(s, Chr(34), \"\\\" & Chr(34))",
            "  s = Replace(s, vbCrLf, \"\\n\")",
            "  s = Replace(s, vbCr, \"\\n\")",
            "  s = Replace(s, vbLf, \"\\n\")",
            "  JsonEscape = s",
            "End Function",
        ]
    )


def _run_vbs(script: str, *, args: list[str] | None = None, timeout: int = 60) -> tuple[int, str, str]:
    exe = cscript32()
    with tempfile.TemporaryDirectory(prefix="onec_com32_vbs_") as raw_dir:
        path = Path(raw_dir) / "run.vbs"
        path.write_text(script, encoding="utf-16")
        command = [str(exe), "//Nologo", str(path), *(args or [])]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            _kill_hung(exc)
            raise Com32TimeoutError(timeout) from None
    return (
        completed.returncode,
        _decode_stream(completed.stdout),
        _decode_stream(completed.stderr),
    )


def _kill_hung(exc: subprocess.TimeoutExpired) -> None:
    proc = getattr(exc, "process", None)
    if proc is None:
        return
    try:
        proc.kill()
    except OSError:
        return
    try:
        proc.wait(timeout=5)
    except Exception:
        return


def _decode_stream(raw: bytes | str | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    for encoding in ("utf-8", "utf-16", "cp1251"):
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "\ufffd" not in text:
            return text
    return raw.decode("cp1251", errors="replace")
