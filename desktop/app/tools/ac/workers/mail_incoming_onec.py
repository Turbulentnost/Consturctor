"""Регистрация входящей из письма Outlook — как agent-pochta: .msg + форма 1С."""

from __future__ import annotations

import base64
import hashlib
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from app.tools.ac.workers.onec_com_actions import (
    DEFAULT_INCOMING_DOC_FORM,
    launch_onec_client_form,
)
from app.tools.ac.workers.outlook_com_actions import save_mail_message

_DEFAULT_POCHTA_ENV = (
    r"C:\Users\mdj\Desktop\рабочее\Входящая корреспонденция"
    r"\2. Входящая корреспонденция\agent-pochta\.env"
)
_UNSAFE_PATH = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _parse_dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            out[key] = value
    return out


def _agent_pochta_env() -> dict[str, str]:
    explicit = (os.environ.get("ORCH_ODATA_ENV_PATH") or "").strip()
    path = Path(explicit) if explicit else Path(_DEFAULT_POCHTA_ENV)
    return _parse_dotenv(path)


def _local_incoming_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    root = Path(base) / "Constructor" / "incoming_mail"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _entry_segment(entry_id: str) -> str:
    raw = (entry_id or "msg").strip()
    if len(raw) <= 32:
        cleaned = _UNSAFE_PATH.sub("_", raw)[:32]
        return cleaned or "msg"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _copy_to_volume_if_configured(src: Path, file_name: str) -> Path | None:
    env = _agent_pochta_env()
    volume_root = (env.get("ODATA_FILE_VOLUME_ROOT") or os.environ.get("ODATA_FILE_VOLUME_ROOT") or "").strip()
    preupload = (
        (env.get("ODATA_FILE_VOLUME_PREUPLOAD") or os.environ.get("ODATA_FILE_VOLUME_PREUPLOAD") or "")
        .strip()
        .lower()
    )
    if not volume_root or preupload in {"", "0", "false", "no"}:
        return None
    day = datetime.now().strftime("%Y%m%d")
    safe_name = _UNSAFE_PATH.sub("_", file_name) or "message.msg"
    dest_dir = Path(volume_root) / day
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / safe_name
    shutil.copy2(src, dest)
    return dest.resolve()


def stage_incoming_msg_file(src_path: str, *, entry_id: str, file_name: str | None = None) -> Path:
    """Локальный staging + опционально том 1С (agent-pochta ODATA_FILE_VOLUME_PREUPLOAD)."""
    src = Path(src_path).resolve()
    if not src.is_file():
        raise FileNotFoundError(f"Файл письма не найден: {src}")
    name = (file_name or src.name or "message.msg").strip()
    if not name.lower().endswith(".msg"):
        name = f"{name}.msg" if not name.endswith(".") else "message.msg"
    local_dir = _local_incoming_root() / _entry_segment(entry_id)
    local_dir.mkdir(parents=True, exist_ok=True)
    local_copy = (local_dir / _UNSAFE_PATH.sub("_", name)).resolve()
    shutil.copy2(src, local_copy)
    volume_copy = _copy_to_volume_if_configured(local_copy, local_copy.name)
    return volume_copy or local_copy


def save_incoming_mail_msg(input_data: dict[str, Any]) -> dict[str, Any]:
    """Сохранить .msg из Outlook и положить в staging/том (без открытия формы 1С)."""
    entry_id = str(input_data.get("entry_id") or input_data.get("entryId") or "").strip()
    if not entry_id:
        raise ValueError("entry_id обязателен (Outlook EntryID)")

    save_result = save_mail_message({"entry_id": entry_id, "save_dir": input_data.get("save_dir")})
    saved_path = str(save_result.get("saved_path") or "").strip()
    if not saved_path:
        raise RuntimeError("Outlook не вернул путь к .msg")

    staged_path = stage_incoming_msg_file(
        saved_path,
        entry_id=entry_id,
        file_name=str(save_result.get("file_name") or ""),
    )
    out: dict[str, Any] = {
        "saved_path": saved_path,
        "staged_path": str(staged_path),
        "entry_id": entry_id,
        "subject": save_result.get("subject") or input_data.get("mail_subject") or "",
        "source": "mail_incoming_onec",
        "method": "onec.save_incoming_mail_msg",
    }
    try:
        raw = Path(staged_path).read_bytes()
        if len(raw) <= 12 * 1024 * 1024:
            out["msg_base64"] = base64.b64encode(raw).decode("ascii")
            out["msg_filename"] = Path(staged_path).name
    except OSError:
        pass
    return out


def register_incoming_from_outlook_mail(input_data: dict[str, Any]) -> dict[str, Any]:
    """Сохранить .msg, положить в staging/том, открыть форму входящей в 1С."""
    staged = save_incoming_mail_msg(input_data)
    staged_path = staged.get("staged_path") or ""

    form_input = dict(input_data)
    form_input.setdefault("form", DEFAULT_INCOMING_DOC_FORM)
    form_input["attach_mail_file"] = True
    form_input["mail_file_path"] = str(staged_path)
    form_input.setdefault("mail_subject", staged.get("subject") or input_data.get("mail_subject") or "")
    form_input.setdefault("mail_sender", input_data.get("mail_sender") or "")
    if input_data.get("mail_received_at"):
        form_input["mail_received_at"] = input_data.get("mail_received_at")

    opened = launch_onec_client_form(form_input)
    return {
        **opened,
        **staged,
        "source": "mail_incoming_onec",
    }
