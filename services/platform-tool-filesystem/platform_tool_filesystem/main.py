from __future__ import annotations

import base64
import fnmatch
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic_settings import SettingsConfigDict

from platform_contracts.tools import ToolInvokeRequest
from platform_service_common.app_factory import ServiceSettings, create_tool_app, run_app

_STUB_TREE: dict[str, Any] = {
    "incoming": {
        "README.txt": "Incoming documents\n",
        "scan001.pdf": b"%PDF-stub\n",
    },
    "outgoing": {},
    "attachments": {"note.txt": "Attachment placeholder\n"},
    "README.txt": "Constructor filesystem stub workspace\n",
}


class FilesystemSettings(ServiceSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "platform-tool-filesystem"
    api_port: int = 7827
    fs_root_allowlist: str = ""
    fs_max_read_bytes: int = 10_485_760


settings = FilesystemSettings()


def ensure_fs_workspace(root: Path) -> None:
    """Create demo folders so sandbox fs.list is not empty on first run."""
    root.mkdir(parents=True, exist_ok=True)
    for name in ("incoming", "outgoing", "attachments"):
        (root / name).mkdir(exist_ok=True)
    readme = root / "README.txt"
    if not readme.exists():
        readme.write_text("Constructor filesystem workspace\n", encoding="utf-8")
    incoming_readme = root / "incoming" / "README.txt"
    if not incoming_readme.exists():
        incoming_readme.write_text("Incoming documents\n", encoding="utf-8")
    note = root / "attachments" / "note.txt"
    if not note.exists():
        note.write_text("Attachment placeholder\n", encoding="utf-8")


def _allowlist_roots() -> list[Path]:
    raw = (settings.fs_root_allowlist or os.environ.get("FS_ROOT_ALLOWLIST") or "").strip()
    if not raw:
        from platform_tool_filesystem.desktop_paths import default_fs_allowlist

        raw = default_fs_allowlist()
    roots: list[Path] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        path = Path(part).expanduser().resolve()
        ensure_fs_workspace(path)
        roots.append(path)
    if not roots:
        raise RuntimeError("FS_ROOT_ALLOWLIST is empty after parsing")
    return roots


def _resolve_allowed(path_str: str) -> Path:
    if not path_str or not str(path_str).strip():
        raise ValueError("path required")
    candidate = Path(str(path_str).strip()).expanduser()
    if not candidate.is_absolute():
        candidate = _allowlist_roots()[0] / candidate
    resolved = candidate.resolve()
    for root in _allowlist_roots():
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue
    raise ValueError(f"path not allowed: {path_str}")


def _stat_payload(path: Path) -> dict[str, Any]:
    st = path.stat()
    return {
        "path": str(path),
        "is_dir": path.is_dir(),
        "size": st.st_size,
        "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
    }


def _list(req: ToolInvokeRequest) -> dict[str, Any]:
    path = _resolve_allowed(str(req.payload.get("path", ".")))
    if not path.is_dir():
        raise ValueError("path is not a directory")
    pattern = str(req.payload.get("pattern", "*")).strip() or "*"
    recursive = bool(req.payload.get("recursive", False))
    entries: list[dict[str, Any]] = []
    iterator = path.rglob("*") if recursive else path.iterdir()
    for item in iterator:
        if item.name.startswith("."):
            continue
        rel = str(item.relative_to(path)) if item != path else item.name
        if not fnmatch.fnmatch(item.name if not recursive else rel, pattern):
            if not recursive or not fnmatch.fnmatch(item.name, pattern):
                continue
        try:
            entries.append(_stat_payload(item))
        except OSError:
            continue
    entries.sort(key=lambda x: x["path"])
    return {
        "summary": f"listed {len(entries)} entries",
        "path": str(path),
        "entries": entries,
        "source": "filesystem",
    }


def _read(req: ToolInvokeRequest) -> dict[str, Any]:
    path = _resolve_allowed(str(req.payload.get("path", "")))
    if not path.is_file():
        raise ValueError("path is not a file")
    max_bytes = int(req.payload.get("max_bytes", settings.fs_max_read_bytes))
    max_bytes = max(1, min(max_bytes, settings.fs_max_read_bytes))
    data = path.read_bytes()[:max_bytes]
    encoding = str(req.payload.get("encoding", "utf-8")).strip() or "utf-8"
    as_base64 = bool(req.payload.get("as_base64", False))
    if as_base64:
        content: str = base64.b64encode(data).decode("ascii")
        content_type = "base64"
    else:
        try:
            content = data.decode(encoding)
            content_type = "text"
        except UnicodeDecodeError:
            content = base64.b64encode(data).decode("ascii")
            content_type = "base64"
    return {
        "summary": f"read {len(data)} bytes",
        "path": str(path),
        "content": content,
        "content_type": content_type,
        "truncated": path.stat().st_size > len(data),
        "source": "filesystem",
    }


def _write(req: ToolInvokeRequest) -> dict[str, Any]:
    path = _resolve_allowed(str(req.payload.get("path", "")))
    mode = str(req.payload.get("mode", "overwrite")).strip().lower()
    if mode not in {"create", "overwrite", "append"}:
        raise ValueError("mode must be create|overwrite|append")
    if mode == "create" and path.exists():
        raise ValueError("file already exists")
    content_b64 = req.payload.get("content_base64")
    if content_b64 is not None:
        data = base64.b64decode(str(content_b64))
    else:
        data = str(req.payload.get("content", "")).encode(
            str(req.payload.get("encoding", "utf-8")) or "utf-8"
        )
    if len(data) > settings.fs_max_read_bytes:
        raise ValueError("content too large")
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode == "append" and path.exists():
        with path.open("ab") as fh:
            fh.write(data)
    else:
        path.write_bytes(data)
    return {
        "summary": f"written {len(data)} bytes ({mode})",
        "path": str(path),
        "bytes": len(data),
        "mode": mode,
        "source": "filesystem",
    }


def _build_office_file(req: ToolInvokeRequest) -> dict[str, Any]:
    from platform_tool_filesystem.agent_build_files import build_office_write_payload

    path = str(req.payload.get("path", "")).strip()
    if not path:
        raise ValueError("path required (full path including filename, e.g. C:\\Users\\Public\\Documents\\file.xlsx)")
    rows = req.payload.get("rows")
    if rows is not None and not isinstance(rows, list):
        raise ValueError("rows must be a list of lists")
    inner = build_office_write_payload(
        path=path,
        format=str(req.payload.get("format", "")).strip(),
        title=str(req.payload.get("title", "Constructor agent file")).strip() or "Constructor agent file",
        body=str(req.payload.get("body", "")),
        rows=rows,
        mode=str(req.payload.get("mode", "overwrite")).strip() or "overwrite",
    )
    write_req = ToolInvokeRequest(
        run_id=req.run_id,
        department=req.department,
        user_id=req.user_id,
        payload=inner,
    )
    result = _write(write_req)
    result["format"] = (str(req.payload.get("format", "")).strip() or Path(path).suffix.lstrip(".")).lower()
    result["source"] = "filesystem"
    return result


def _stub_build_office_file(req: ToolInvokeRequest) -> dict[str, Any]:
    path_str = _stub_resolve(str(req.payload.get("path", "")))
    parts = [p for p in path_str.split("/") if p]
    if not parts:
        raise ValueError("path required")
    node: Any = _STUB_TREE
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = "stub office file\n"
    fmt = str(req.payload.get("format", "")).strip() or Path(path_str).suffix.lstrip(".")
    return {
        "summary": "stub build office file",
        "path": path_str,
        "format": fmt,
        "bytes": len(str(node[parts[-1]])),
        "mode": str(req.payload.get("mode", "overwrite")),
        "source": "stub",
    }


def _stat(req: ToolInvokeRequest) -> dict[str, Any]:
    path = _resolve_allowed(str(req.payload.get("path", "")))
    payload = _stat_payload(path)
    payload["summary"] = "stat ok"
    payload["source"] = "filesystem"
    return payload


def _move(req: ToolInvokeRequest) -> dict[str, Any]:
    src = _resolve_allowed(str(req.payload.get("from", "")))
    dst = _resolve_allowed(str(req.payload.get("to", "")))
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return {"summary": "moved", "from": str(src), "to": str(dst), "source": "filesystem"}


def _copy(req: ToolInvokeRequest) -> dict[str, Any]:
    src = _resolve_allowed(str(req.payload.get("from", "")))
    dst = _resolve_allowed(str(req.payload.get("to", "")))
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dst)
    return {"summary": "copied", "from": str(src), "to": str(dst), "source": "filesystem"}


def _stub_resolve(path_str: str) -> str:
    path_str = (path_str or ".").strip().replace("\\", "/").strip("/")
    return path_str or "."


def _stub_get_node(path_str: str) -> Any:
    node: Any = _STUB_TREE
    parts = [p for p in _stub_resolve(path_str).split("/") if p and p != "."]
    for part in parts:
        if not isinstance(node, dict) or part not in node:
            raise ValueError(f"path not found: {path_str}")
        node = node[part]
    return node


def _stub_list(req: ToolInvokeRequest) -> dict[str, Any]:
    path_str = _stub_resolve(str(req.payload.get("path", ".")))
    node = _stub_get_node(path_str)
    if not isinstance(node, dict):
        raise ValueError("path is not a directory")
    entries = []
    for name, value in node.items():
        entries.append(
            {
                "path": f"{path_str}/{name}".replace("./", ""),
                "is_dir": isinstance(value, dict),
                "size": len(value) if isinstance(value, (str, bytes)) else 0,
            }
        )
    return {
        "summary": f"stub listed {len(entries)} entries",
        "path": path_str,
        "entries": entries,
        "source": "stub",
    }


def _stub_read(req: ToolInvokeRequest) -> dict[str, Any]:
    path_str = _stub_resolve(str(req.payload.get("path", "")))
    node = _stub_get_node(path_str)
    if isinstance(node, dict):
        raise ValueError("path is a directory")
    if isinstance(node, bytes):
        content = base64.b64encode(node).decode("ascii")
        content_type = "base64"
    else:
        content = str(node)
        content_type = "text"
    return {
        "summary": "stub read ok",
        "path": path_str,
        "content": content,
        "content_type": content_type,
        "source": "stub",
    }


def _stub_write(req: ToolInvokeRequest) -> dict[str, Any]:
    path_str = _stub_resolve(str(req.payload.get("path", "")))
    parts = [p for p in path_str.split("/") if p]
    if not parts:
        raise ValueError("invalid path")
    node: Any = _STUB_TREE
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = str(req.payload.get("content", ""))
    return {"summary": "stub write ok", "path": path_str, "source": "stub"}


def _stub_stat(req: ToolInvokeRequest) -> dict[str, Any]:
    path_str = _stub_resolve(str(req.payload.get("path", "")))
    node = _stub_get_node(path_str)
    return {
        "summary": "stub stat ok",
        "path": path_str,
        "is_dir": isinstance(node, dict),
        "size": len(node) if isinstance(node, (str, bytes)) else 0,
        "source": "stub",
    }


def _stub_move(req: ToolInvokeRequest) -> dict[str, Any]:
    src = _stub_resolve(str(req.payload.get("from", "")))
    dst = _stub_resolve(str(req.payload.get("to", "")))
    value = _stub_get_node(src)
    _stub_set_node(dst, value)
    _stub_delete_node(src)
    return {"summary": "stub moved", "from": src, "to": dst, "source": "stub"}


def _stub_copy(req: ToolInvokeRequest) -> dict[str, Any]:
    src = _stub_resolve(str(req.payload.get("from", "")))
    dst = _stub_resolve(str(req.payload.get("to", "")))
    value = _stub_get_node(src)
    if isinstance(value, dict):
        _stub_set_node(dst, json.loads(json.dumps(value)))
    else:
        _stub_set_node(dst, value)
    return {"summary": "stub copied", "from": src, "to": dst, "source": "stub"}


def _stub_set_node(path_str: str, value: Any) -> None:
    parts = [p for p in _stub_resolve(path_str).split("/") if p]
    node: Any = _STUB_TREE
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def _stub_delete_node(path_str: str) -> None:
    parts = [p for p in _stub_resolve(path_str).split("/") if p]
    node: Any = _STUB_TREE
    for part in parts[:-1]:
        node = node[part]
    del node[parts[-1]]


REAL_HANDLERS = {
    "fs.list": _list,
    "fs.read": _read,
    "fs.write": _write,
    "fs.build_office_file": _build_office_file,
    "fs.stat": _stat,
    "fs.move": _move,
    "fs.copy": _copy,
}

STUB_HANDLERS = {
    "fs.list": _stub_list,
    "fs.read": _stub_read,
    "fs.write": _stub_write,
    "fs.build_office_file": _stub_build_office_file,
    "fs.stat": _stub_stat,
    "fs.move": _stub_move,
    "fs.copy": _stub_copy,
}

app = create_tool_app(settings, REAL_HANDLERS, stub_handlers=STUB_HANDLERS)


def main() -> None:
    run_app(app, settings)


if __name__ == "__main__":
    main()
