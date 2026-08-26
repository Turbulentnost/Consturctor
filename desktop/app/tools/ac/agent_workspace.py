"""Изолированные рабочие папки агентов для работы с файлами (Excel и др.).

Каждый агент получает свою директорию ``<root>/<agent_id>/``. Все файловые
инструменты обязаны резолвить пути только внутри неё, чтобы агент не мог выйти
за пределы песочницы (защита от path traversal).
"""

from __future__ import annotations

import re
from pathlib import Path

_SAFE_ID = re.compile(r"[^A-Za-z0-9_.-]")


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
        """Вернуть файлы в папке агента, включая materials/."""
        files: list[dict] = []
        root = self.directory.resolve()
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            if relative.startswith("code/") or relative.startswith("tool_results/"):
                continue
            files.append({"name": relative, "size_bytes": path.stat().st_size})
        return files


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
