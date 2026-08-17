from __future__ import annotations

from pathlib import Path

from platform_tool_filesystem.desktop_paths import (
    DEFAULT_PUBLIC_DOCUMENTS,
    agent_build_dir,
    default_fs_allowlist,
    primary_output_dir,
)


def test_primary_output_is_public_documents() -> None:
    primary = primary_output_dir()
    assert primary.is_dir()
    if DEFAULT_PUBLIC_DOCUMENTS.is_dir():
        assert primary == DEFAULT_PUBLIC_DOCUMENTS.resolve()


def test_agent_build_dir_same_as_primary_without_subdir() -> None:
    assert agent_build_dir() == primary_output_dir()


def test_default_fs_allowlist_includes_public_documents() -> None:
    allowlist = default_fs_allowlist(repo_data_filesystem=Path("data/filesystem"))
    parts = [part.strip() for part in allowlist.split(",") if part.strip()]
    assert any("Public" in part and "Documents" in part for part in parts)


def test_default_fs_allowlist_includes_constructor_root() -> None:
    from platform_tool_filesystem.desktop_paths import constructor_root

    allowlist = default_fs_allowlist(repo_data_filesystem=Path("data/filesystem"))
    parts = [part.strip() for part in allowlist.split(",") if part.strip()]
    root = str(constructor_root())
    assert any(part == root or "Consturctor" in part or part.endswith("filesystem") for part in parts)
