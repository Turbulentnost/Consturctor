"""Короткий Python по сохранённому ответу инструмента — без сети и без файлов."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
from typing import Any

ALLOWED_IMPORTS = frozenset(
    {
        "json",
        "re",
        "datetime",
        "math",
        "statistics",
        "collections",
        "itertools",
        "functools",
        "decimal",
        "string",
        "textwrap",
        "unicodedata",
    }
)
_FORBIDDEN_NAMES = frozenset(
    {
        "__import__",
        "open",
        "eval",
        "exec",
        "compile",
        "input",
        "breakpoint",
        "exit",
        "quit",
    }
)
_RESULT_LIMIT = 8000
_DEFAULT_TIMEOUT_S = 15


class SandboxError(ValueError):
    pass


def validate_code(code: str) -> str:
    source = (code or "").strip()
    if not source:
        return "Нужен код: положи ответ в переменную result."
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return f"Синтаксис: {exc.msg}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = (alias.name or "").split(".", 1)[0]
                if root not in ALLOWED_IMPORTS:
                    return f"Импорт «{alias.name}» в песочнице запрещён."
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".", 1)[0]
            if root not in ALLOWED_IMPORTS:
                return f"Импорт «{node.module}» в песочнице запрещён."
        elif isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
            return f"Вызов «{node.id}» в песочнице запрещён."
        elif isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            return "Обращение к служебным атрибутам в песочнице запрещено."
    return ""


def run_dataset_code(
    *,
    code: str,
    data: Any,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    problem = validate_code(code)
    if problem:
        return {"ok": False, "error": problem}
    script = (
        "import json, sys\n"
        "sys.stdin.reconfigure(encoding='utf-8')\n"
        "sys.stdout.reconfigure(encoding='utf-8')\n"
        "sys.stderr.reconfigure(encoding='utf-8')\n"
        "data = json.loads(sys.stdin.read())\n"
        "result = None\n"
        f"{code.rstrip()}\n"
        "if result is None:\n"
        "    raise SystemExit('assign result')\n"
        "sys.stdout.write(json.dumps({'ok': True, 'result': result}, ensure_ascii=False, default=str))\n"
    )
    env = {
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", r"C:\Windows"),
        "WINDIR": os.environ.get("WINDIR", r"C:\Windows"),
        "PATH": os.environ.get("PATH", ""),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "PYTHONNOUSERSITE": "1",
    }
    payload = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", script],
            input=payload,
            capture_output=True,
            timeout=max(1.0, float(timeout_s)),
            cwd=tempfile.gettempdir(),
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Песочница превысила {int(timeout_s)} с."}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    stdout = (proc.stdout or b"").decode("utf-8", errors="replace")
    stderr = (proc.stderr or b"").decode("utf-8", errors="replace")
    if proc.returncode != 0:
        err = (stderr or stdout or "ошибка песочницы").strip()
        if "assign result" in err:
            return {"ok": False, "error": "Код должен положить ответ в переменную result."}
        return {"ok": False, "error": err[:800]}
    try:
        parsed = json.loads(stdout or "")
    except json.JSONDecodeError:
        return {"ok": False, "error": "Песочница вернула не JSON."}
    result = parsed.get("result") if isinstance(parsed, dict) else parsed
    return {"ok": True, "result": _clip_value(result)}


def _clip_value(value: Any, limit: int = _RESULT_LIMIT) -> Any:
    try:
        raw = json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return str(value)[:limit]
    if len(raw) <= limit:
        return value
    if isinstance(value, list):
        return {"truncated": True, "count": len(value), "preview": value[:20]}
    if isinstance(value, dict):
        return {
            "truncated": True,
            "keys": list(value.keys())[:40],
            "preview": raw[:limit] + "…",
        }
    return raw[:limit] + "…"
