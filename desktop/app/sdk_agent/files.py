from __future__ import annotations

import json
import re
from pathlib import Path

from app.api_client import ApiClient, WorkflowFileItem


def seed_workflow_files(api: ApiClient, workflow_id: str, cwd: str) -> str:
    """Materialize persistent agent documents into the Cursor SDK workspace."""
    wid = (workflow_id or "").strip()
    if not wid:
        return ""
    root = Path(cwd)
    materials = root / "materials"
    materials.mkdir(parents=True, exist_ok=True)
    files = api.list_workflow_files(wid)
    manifest: list[dict] = []
    for index, item in enumerate(files.user_files, start=1):
        entry = _materialize_file(api, wid, item, materials, index=index)
        if entry:
            manifest.append(entry)
    manifest_path = materials / "manifest.json"
    manifest_path.write_text(
        json.dumps({"files": manifest}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if not manifest:
        return (
            "\n\n===== БАЗА ДОКУМЕНТОВ АГЕНТА =====\n"
            "В рабочей папке есть materials/manifest.json, но база документов пока пуста. "
            "Если для задачи нужен файл, задай пользователю вопрос через askQuestion и попроси "
            "прикрепить файл, затем продолжай после ответа.\n"
            "===== END БАЗА ДОКУМЕНТОВ АГЕНТА ====="
        )
    listed = "\n".join(
        f"- {item['filename']}: {item['path']} ({item.get('summary') or 'без summary'})"
        for item in manifest
    )
    return (
        "\n\n===== БАЗА ДОКУМЕНТОВ АГЕНТА =====\n"
        "Полные файлы лежат в рабочей папке Cursor SDK. Сначала прочитай "
        "materials/manifest.json, затем нужные файлы через read/grep. "
        "Для PDF/DOCX/изображений есть извлечённый текст в поле extracted_text_path.\n"
        f"{listed}\n"
        "Если нужного документа нет, задай пользователю вопрос через askQuestion и попроси "
        "прикрепить файл, затем продолжай после ответа.\n"
        "===== END БАЗА ДОКУМЕНТОВ АГЕНТА ====="
    )


def _materialize_file(
    api: ApiClient,
    workflow_id: str,
    item: WorkflowFileItem,
    materials: Path,
    *,
    index: int,
) -> dict | None:
    if not item.id:
        return None
    filename = _safe_filename(item.filename or f"file-{index}")
    target = materials / f"{index:03d}_{filename}"
    api.download_workflow_file_to(workflow_id, item.id, target)
    text_payload = api.workflow_file_text(workflow_id, item.id)
    text = str(text_payload.get("text") or "").strip()
    text_path = ""
    if text:
        extracted = target.with_suffix(target.suffix + ".txt")
        extracted.write_text(text, encoding="utf-8")
        text_path = extracted.relative_to(materials.parent).as_posix()
    return {
        "id": item.id,
        "filename": item.filename,
        "path": target.relative_to(materials.parent).as_posix(),
        "extracted_text_path": text_path,
        "mime_type": item.mime_type,
        "kind": item.kind,
        "size": item.size,
        "sha256": item.sha256,
        "summary": item.summary or str(text_payload.get("summary") or ""),
        "source": item.source,
        "scope": item.scope,
    }


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-zА-Яа-я0-9_.() -]", "_", (name or "file").strip())
    cleaned = cleaned.strip(" .") or "file"
    return cleaned[:180]
