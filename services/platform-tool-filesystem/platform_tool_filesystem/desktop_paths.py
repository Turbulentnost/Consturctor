"""Default agent file output paths and FS allowlist entries."""

from __future__ import annotations

import os
import sys
from pathlib import Path

DEFAULT_PUBLIC_DOCUMENTS = Path(r"C:\Users\Public\Documents")


def primary_output_dir() -> Path:
    """Directory for agent-created files (default: C:\\Users\\Public\\Documents)."""
    for raw in (
        os.environ.get("AGENT_BUILD_OUTPUT_DIR"),
        os.environ.get("FS_AGENT_BUILD_DIR"),
    ):
        if raw and str(raw).strip():
            path = Path(str(raw).strip()).expanduser().resolve()
            path.mkdir(parents=True, exist_ok=True)
            return path
    if sys.platform == "win32" and DEFAULT_PUBLIC_DOCUMENTS.is_dir():
        return DEFAULT_PUBLIC_DOCUMENTS.resolve()
    fallback = (Path.home() / "Documents").resolve()
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def agent_build_dir(*, subdir: str = "") -> Path:
    base = primary_output_dir()
    if subdir.strip():
        path = (base / subdir.strip()).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path
    return base


def constructor_root() -> Path:
    raw = (os.environ.get("CONSTRUCTOR_ROOT") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    cwd = Path.cwd().resolve()
    for candidate in (cwd, *cwd.parents):
        if (candidate / "AGENT_BUILDER.md").is_file() or (candidate / "infra" / "docker-compose.yml").is_file():
            return candidate
    return cwd


def fs_allowlist_output_entries() -> list[str]:
    entries: list[str] = []
    seen: set[str] = set()
    for candidate in (
        primary_output_dir(),
        DEFAULT_PUBLIC_DOCUMENTS,
        constructor_root(),
        Path.home() / "Documents",
    ):
        try:
            if not candidate.is_dir():
                continue
            text = str(candidate.resolve())
        except OSError:
            continue
        if text in seen:
            continue
        seen.add(text)
        entries.append(text)
    if not entries:
        entries.append(str(primary_output_dir()))
    return entries


def default_fs_allowlist(*, repo_data_filesystem: Path | None = None) -> str:
    data_root = repo_data_filesystem or (Path.cwd() / "data" / "filesystem")
    parts = [str(data_root.resolve()), *fs_allowlist_output_entries()]
    unique: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if part not in seen:
            seen.add(part)
            unique.append(part)
    return ",".join(unique)


# Backward-compatible aliases
DEFAULT_OUTPUT_FOLDER = ""


def desktop_agent_build_dir(*, subdir: str = "") -> Path:
    return agent_build_dir(subdir=subdir)
