"""Очистка рабочих папок агентов после прогона и при удалении."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _keep_paths_for(workflow_id: str) -> frozenset[Path]:
    from app.tools.result_files import remembered_result_files

    kept: set[Path] = set()
    for path in remembered_result_files(workflow_id):
        try:
            kept.add(path.resolve())
        except OSError:
            kept.add(path)
    return frozenset(kept)


def cleanup_after_run(workflow_id: str) -> list[str]:
    """Удалить черновики после завершения прогона; итоговые файлы в out/ сохраняются."""
    wid = (workflow_id or "").strip()
    if not wid:
        return []
    from app.tools.ac.dispatch import get_workspace_resolver

    resolver = get_workspace_resolver()
    removed = resolver.cleanup_agent(wid, keep_paths=_keep_paths_for(wid))
    if removed:
        logger.info("Agent workspace scratch cleaned (%s): %d items", wid, len(removed))
    return removed


def cleanup_before_run(workflow_id: str) -> list[str]:
    """Убрать черновики прошлого прогона перед новым запуском."""
    return cleanup_after_run(workflow_id)


def cleanup_on_delete(workflow_id: str) -> None:
    """Полностью удалить рабочую папку при удалении агента."""
    wid = (workflow_id or "").strip()
    if not wid:
        return
    from app.tools.ac.dispatch import get_workspace_resolver
    from app.tools.result_files import clear_remembered_result_files

    get_workspace_resolver().cleanup_agent_all(wid)
    clear_remembered_result_files(wid)
    logger.info("Agent workspace removed: %s", wid)


def sweep_stale_workspaces(*, max_age_days: int = 7) -> list[str]:
    """Удалить давно не использовавшиеся папки агентов."""
    from app.tools.ac.dispatch import get_workspace_resolver

    removed = get_workspace_resolver().sweep_stale(max_age_days=max_age_days)
    if removed:
        logger.info("Stale agent workspaces removed: %d", len(removed))
    return removed
