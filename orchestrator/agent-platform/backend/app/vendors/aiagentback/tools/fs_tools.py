from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.vendors.aiagentback.core.config import settings
from app.vendors.aiagentback.tools.base import Tool
from app.vendors.aiagentback.tools.fs.operations import run_filesystem
from app.vendors.aiagentback.tools.registry import register_tool
from app.vendors.aiagentback.tools.schemas import ToolContext


class FilesystemInput(BaseModel):
    operation: Literal["resolve", "list", "read"] = Field(
        description="resolve — найти путь; list — содержимое каталога; read — прочитать файл",
    )
    path: str = Field(
        default="",
        description=(
            "Путь к файлу или каталогу. Может быть обрезанным или с опечатками; "
            "допускаются UNC вида \\\\192.168.1.198\\... и относительные пути от корня шары."
        ),
    )
    query: str | None = Field(
        default=None,
        description="Опциональное имя файла для поиска под path (если path — каталог или неполный).",
    )
    max_bytes: int | None = Field(
        default=None,
        description="Лимит байт при read (не больше FS_MAX_READ_BYTES).",
        ge=1,
    )


class FsCandidate(BaseModel):
    path: str
    score: float


class FsDirEntry(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: int | None = None
    modified_at: str | None = None


class FilesystemOutput(BaseModel):
    operation: str
    ok: bool
    resolved_path: str | None = None
    match_type: str | None = None
    score: float | None = None
    candidates: list[FsCandidate] = Field(default_factory=list)
    entries: list[FsDirEntry] = Field(default_factory=list)
    truncated: bool = False
    name: str | None = None
    size: int | None = None
    content_type: str | None = None
    encoding: str | None = None
    text: str | None = None
    content_truncated: bool = False
    hint: str | None = None


def _settings_kwargs() -> dict[str, Any]:
    return {
        "allowed_roots": settings.fs_allowed_roots,
        "max_list_entries": settings.FS_MAX_LIST_ENTRIES,
        "min_score": settings.FS_FUZZY_MIN_SCORE,
        "max_candidates": settings.FS_RESOLVE_MAX_CANDIDATES,
        "max_search_entries": settings.FS_SEARCH_MAX_ENTRIES,
        "default_max_read_bytes": settings.FS_MAX_READ_BYTES,
    }


async def filesystem(payload: FilesystemInput, context: ToolContext) -> FilesystemOutput:
    del context
    raw = run_filesystem(
        operation=payload.operation,
        path=payload.path,
        query=payload.query,
        max_bytes=payload.max_bytes,
        **_settings_kwargs(),
    )
    return FilesystemOutput.model_validate(raw)


class FilesystemTool(Tool):
    name = "filesystem"
    description = (
        "Чтение сетевой файловой системы внутри разрешённых корней: "
        "resolve / list / read с нечётким поиском путей."
    )
    agent_description = (
        "Инструмент filesystem работает только с разрешённой сетевой шарой "
        "(по умолчанию \\\\192.168.1.198). "
        "operation=resolve — восстановить полный путь при обрезке или опечатке; "
        "operation=list — список файлов каталога; "
        "operation=read — прочитать текст файла (PDF — текстовый слой без OCR). "
        "Используй для путей из 1С (ПутьКФайлу) и артефактов поручений. "
        "При ambiguous смотри candidates и уточни path/query."
    )
    input_model = FilesystemInput
    output_model = FilesystemOutput
    preview_safe = True
    preview_default_params = {
        "operation": "resolve",
        "path": r"\\192.168.1.198",
    }

    async def execute(self, payload: FilesystemInput, context: ToolContext) -> FilesystemOutput:
        return await filesystem(payload, context)


register_tool(FilesystemTool())
