"""Изолированные рабочие папки агентов для работы с файлами (Excel и др.).

Каждый агент получает свою директорию ``<root>/<agent_id>/``. Все файловые
инструменты обязаны резолвить пути только внутри неё, чтобы агент не мог выйти
за пределы песочницы (защита от path traversal).
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

_SAFE_ID = re.compile(r"[^A-Za-z0-9_.-]")
OUTPUT_SUBDIR = "out"
SCRATCH_DIRS = frozenset({"code", "page_dumps"})


class WorkspaceError(Exception):
    """Ошибка доступа к рабочей папке агента (например, выход за пределы)."""


class AgentWorkspace:
    """Управляет одной рабочей папкой конкретного агента."""

    def __init__(self, root: Path, agent_id: str) -> None:
        """Создать (при необходимости) папку агента внутри общего корня."""
        safe_id = _SAFE_ID.sub("_", (agent_id or "unknown").strip()) or "unknown"
        self.directory = Path(root).resolve() / safe_id
        self.directory.mkdir(parents=True, exist_ok=True)

    def resolve(self, filename: str, *, must_exist: bool = False) -> Path:
        """Вернуть безопасный путь внутри папки агента."""
        if not filename or not str(filename).strip():
            raise WorkspaceError("Имя файла не должно быть пустым")
        candidate = (self.directory / str(filename).strip()).resolve()
        base = self.directory.resolve()
        if base != candidate and base not in candidate.parents:
            raise WorkspaceError("Путь выходит за пределы рабочей папки агента")
        if must_exist and not candidate.exists():
            raise WorkspaceError(f"Файл не найден: {filename}")
        return candidate

    def list_files(self) -> list[dict]:
        """Вернуть список файлов в папке агента с размером."""
        files: list[dict] = []
        for path in sorted(self.directory.rglob("*")):
            if path.is_file():
                rel = path.relative_to(self.directory)
                files.append(
                    {
                        "name": str(rel).replace("\\", "/"),
                        "size_bytes": path.stat().st_size,
                    }
                )
        return files

    @property
    def output_directory(self) -> Path:
        """Каталог итоговых файлов агента (не удаляется при очистке черновиков)."""
        out = self.directory / OUTPUT_SUBDIR
        out.mkdir(parents=True, exist_ok=True)
        return out

    def is_path_allowed(self, path: Path) -> bool:
        """Проверить, что путь внутри рабочей папки агента."""
        try:
            resolved = path.resolve()
        except OSError:
            return False
        base = self.directory.resolve()
        return base == resolved or base in resolved.parents

    def resolve_output(self, filename: str, *, must_exist: bool = False) -> Path:
        """Безопасный путь в подкаталоге out/ рабочей папки."""
        if not filename or not str(filename).strip():
            raise WorkspaceError("Имя файла не должно быть пустым")
        candidate = (self.output_directory / Path(str(filename).strip()).name).resolve()
        base = self.directory.resolve()
        if base != candidate and base not in candidate.parents:
            raise WorkspaceError("Путь выходит за пределы рабочей папки агента")
        if must_exist and not candidate.exists():
            raise WorkspaceError(f"Файл не найден: {filename}")
        return candidate

    def cleanup_scratch(self, *, keep_paths: frozenset[Path] | None = None) -> list[str]:
        """Удалить временные файлы; сохранить out/ и явно указанные deliverables."""
        kept = keep_paths or frozenset()
        removed: list[str] = []
        if not self.directory.is_dir():
            return removed
        for item in list(self.directory.iterdir()):
            if item.name == OUTPUT_SUBDIR:
                continue
            if item.name in SCRATCH_DIRS or item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
                removed.append(str(item))
                continue
            if item.is_file():
                try:
                    resolved = item.resolve()
                except OSError:
                    resolved = item
                if resolved not in kept:
                    item.unlink(missing_ok=True)
                    removed.append(str(item))
        return removed

    def cleanup_all(self) -> None:
        """Полностью удалить рабочую папку агента."""
        shutil.rmtree(self.directory, ignore_errors=True)


class AgentWorkspaceResolver:
    """Строит ``AgentWorkspace`` по agent_id относительно общего корня."""

    def __init__(self, root: Path | str) -> None:
        """Сохранить корень рабочих папок агентов."""
        self._root = Path(root)

    @property
    def root(self) -> Path:
        """Вернуть корневую директорию рабочих папок агентов."""
        return self._root

    def for_agent(self, agent_id: str) -> AgentWorkspace:
        """Вернуть рабочую папку конкретного агента."""
        return AgentWorkspace(self._root, agent_id)

    def cleanup_agent(
        self,
        agent_id: str,
        *,
        keep_paths: frozenset[Path] | None = None,
    ) -> list[str]:
        """Удалить черновики агента, оставив deliverables."""
        workspace = self.for_agent(agent_id)
        return workspace.cleanup_scratch(keep_paths=keep_paths)

    def cleanup_agent_all(self, agent_id: str) -> None:
        """Удалить всю рабочую папку агента."""
        self.for_agent(agent_id).cleanup_all()

    def sweep_stale(self, *, max_age_days: int = 7) -> list[str]:
        """Удалить папки агентов, не трогавшиеся дольше max_age_days."""
        if max_age_days <= 0 or not self._root.is_dir():
            return []
        import time

        cutoff = time.time() - max_age_days * 86400
        removed: list[str] = []
        for item in self._root.iterdir():
            if not item.is_dir():
                continue
            try:
                if item.stat().st_mtime >= cutoff:
                    continue
            except OSError:
                continue
            shutil.rmtree(item, ignore_errors=True)
            removed.append(str(item))
        return removed

    def agent_id_from_input(self, input_data: dict) -> str:
        """Извлечь agent_id из runtime_context или входных данных."""
        context = input_data.get("runtime_context") if isinstance(input_data.get("runtime_context"), dict) else {}
        agent_id = (
            context.get("agent_id")
            or input_data.get("agent_id")
            or context.get("workflow_id")
            or input_data.get("workflow_id")
            or "default"
        )
        return str(agent_id)
