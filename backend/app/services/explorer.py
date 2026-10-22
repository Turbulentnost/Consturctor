"""Проводник «База знаний»: зашифрованные файлы на общей сетевой папке.

Каждый файл шифруется своим ключом (Fernet). Ключ, владелец и выданные доступы
хранятся в Postgres; на диске лежит только шифротекст, поэтому файл, положенный
в папку мимо программы, в проводник не попадает и не открывается.
"""

from __future__ import annotations

import io
import mimetypes
import os
import re
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.explorer import ExplorerEntry, ExplorerFileKey, ExplorerKeyGrant
from app.models.user import AppUser
from app.services import explorer_history

SHARED_FOLDER_ID = "shared"
SHARED_FOLDER_NAME = "Доступные мне"
FILE_MAGIC = b"ORCHX1"
ACCESS_MODES = ("private", "users", "department", "all")

_FORBIDDEN_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_NAMES = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


class ExplorerError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class Actor:
    user_id: str
    fio: str
    department: str


@dataclass
class AccessSpec:
    mode: str = "private"
    users: list[dict[str, str]] = field(default_factory=list)
    departments: list[str] = field(default_factory=list)
    all_permission: str = "write"


def actor_for(db: Session, user_id: str, fio: str | None, department: str | None) -> Actor:
    user = db.get(AppUser, user_id)
    return Actor(
        user_id=user_id,
        fio=((user.fio if user else "") or fio or "").strip(),
        department=((user.department if user else "") or department or "").strip(),
    )


# ---------- storage ----------


def _root() -> Path:
    return Path(settings.explorer_root)


def _abs(rel_path: str) -> Path:
    root = _root()
    target = root.joinpath(*[part for part in rel_path.split("/") if part])
    if os.path.commonpath([str(root), str(target)]) != str(root):
        raise ExplorerError("Путь выходит за пределы хранилища", 400)
    return target


def _ensure_root() -> None:
    root = _root()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ExplorerError(f"Хранилище недоступно: {root}", 503) from exc


def _write_encrypted(path: Path, key: str, data: bytes) -> None:
    blob = FILE_MAGIC + Fernet(key.encode("ascii")).encrypt(data)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_bytes(blob)
        os.replace(tmp, path)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise ExplorerError("Не удалось записать файл в хранилище", 503) from exc


def _read_encrypted(path: Path, key: str) -> bytes:
    try:
        blob = path.read_bytes()
    except FileNotFoundError as exc:
        raise ExplorerError("Файл отсутствует в хранилище", 404) from exc
    except OSError as exc:
        raise ExplorerError("Хранилище недоступно", 503) from exc
    if not blob.startswith(FILE_MAGIC):
        raise ExplorerError("Файл изменён вне программы и не может быть открыт", 409)
    try:
        return Fernet(key.encode("ascii")).decrypt(blob[len(FILE_MAGIC) :])
    except InvalidToken as exc:
        raise ExplorerError("Файл повреждён или изменён вне программы", 409) from exc


def _blank_content(name: str) -> bytes:
    """Пустой, но корректный документ: Word и Excel не открывают файлы нулевой длины."""
    ext = Path(name).suffix.lower()
    buffer = io.BytesIO()
    if ext == ".docx":
        from docx import Document

        Document().save(buffer)
        return buffer.getvalue()
    if ext == ".xlsx":
        from openpyxl import Workbook

        Workbook().save(buffer)
        return buffer.getvalue()
    return b""


# ---------- names and folders ----------


def clean_name(raw: str) -> str:
    name = (raw or "").strip().rstrip(". ")
    if not name or name in {".", ".."}:
        raise ExplorerError("Укажите имя")
    if _FORBIDDEN_CHARS.search(name):
        raise ExplorerError('Имя не может содержать символы < > : " / \\ | ? *')
    if Path(name).stem.lower() in _RESERVED_NAMES:
        raise ExplorerError("Это имя зарезервировано Windows")
    if name.lower() == explorer_history.REPO_DIR:
        raise ExplorerError("Это имя зарезервировано системой")
    if len(name) > 200:
        raise ExplorerError("Слишком длинное имя")
    return name


def _surname_slug(fio: str) -> str:
    surname = (fio or "").strip().split()[0] if (fio or "").strip() else ""
    slug = _FORBIDDEN_CHARS.sub("", surname).strip(". ").lower()
    return slug or "user"


def _dir_writable(path: Path) -> bool:
    """Папка есть и в неё можно записать файл.

    На Windows mkdir(exist_ok=True) всё равно бросает FileExistsError, если каталог
    уже есть, но текущей учётной записи его не открыть.
    """
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    probe = path / f".{uuid.uuid4().hex}.tmp"
    try:
        probe.write_bytes(b"")
        probe.unlink(missing_ok=True)
    except OSError:
        return False
    return True


def _folder_taken_by_other(db: Session, actor: Actor, folder: str) -> bool:
    return bool(
        db.scalar(
            select(ExplorerEntry.id)
            .where(
                func.lower(ExplorerEntry.owner_folder) == func.lower(folder),
                ExplorerEntry.owner_user_id != actor.user_id,
            )
            .limit(1)
        )
    )


def owner_folder(db: Session, actor: Actor) -> str:
    """Папка пользователя в корне хранилища: фамилия в нижнем регистре.

    Если такая фамилия уже занята другим сотрудником или каталог есть, но его
    не открыть, добавляются инициалы, затем id.
    """
    existing = list(
        dict.fromkeys(
            db.scalars(
                select(ExplorerEntry.owner_folder).where(ExplorerEntry.owner_user_id == actor.user_id)
            ).all()
        )
    )
    for name in existing:
        if name and _dir_writable(_abs(name)):
            return name
    base = _surname_slug(actor.fio)
    parts = actor.fio.split()
    initials = "".join(part[0] for part in parts[1:3]).lower()
    candidates = [base]
    if initials:
        candidates.append(f"{base}_{initials}")
    candidates.extend((f"{base}_{actor.user_id}", f"{base}_{uuid.uuid4().hex[:6]}"))
    seen = {name for name in existing if name}
    for candidate in candidates:
        if not candidate or candidate in seen or _folder_taken_by_other(db, actor, candidate):
            continue
        if _dir_writable(_abs(candidate)):
            return candidate
    raise ExplorerError("Не удалось создать папку пользователя в хранилище", 503)


def _ensure_owner_dir(folder: str) -> Path:
    _ensure_root()
    path = _abs(folder)
    if _dir_writable(path):
        return path
    raise ExplorerError("Не удалось создать папку пользователя в хранилище", 503)


def _own_folder(db: Session, actor: Actor, folder_id: str | None) -> ExplorerEntry | None:
    if not folder_id:
        return None
    folder = db.get(ExplorerEntry, folder_id)
    if folder is None or folder.kind != "folder":
        raise ExplorerError("Папка не найдена", 404)
    if folder.owner_user_id != actor.user_id:
        raise ExplorerError("Создавать файлы можно только в своих папках", 403)
    return folder


def _check_unique(db: Session, actor: Actor, parent_id: str | None, name: str, rel_path: str) -> None:
    clash = db.scalar(
        select(ExplorerEntry.id)
        .where(
            ExplorerEntry.owner_user_id == actor.user_id,
            ExplorerEntry.parent_id.is_(None) if parent_id is None else ExplorerEntry.parent_id == parent_id,
            func.lower(ExplorerEntry.name) == func.lower(name),
        )
        .limit(1)
    )
    if clash or _abs(rel_path).exists():
        raise ExplorerError(f"«{name}» уже существует в этой папке", 409)


# ---------- access ----------


def _grant_filter(actor: Actor):
    clauses = [
        ExplorerKeyGrant.grantee_kind == "all",
        (ExplorerKeyGrant.grantee_kind == "user") & (ExplorerKeyGrant.grantee_id == actor.user_id),
    ]
    if actor.fio:
        clauses.append(
            (ExplorerKeyGrant.grantee_kind == "user")
            & (ExplorerKeyGrant.grantee_id == "")
            & (func.lower(ExplorerKeyGrant.grantee_label) == func.lower(actor.fio))
        )
    if actor.department:
        clauses.append(
            (ExplorerKeyGrant.grantee_kind == "department")
            & (func.lower(ExplorerKeyGrant.grantee_id) == func.lower(actor.department))
        )
    return or_(*clauses)


def _permission_of(grant: ExplorerKeyGrant) -> str:
    value = (grant.permission or "write").strip().lower()
    return value if value in {"read", "write"} else "write"


def access_level(db: Session, actor: Actor, entry: ExplorerEntry) -> str | None:
    """write — можно менять файл, read — только открыть, None — доступа нет."""
    if entry.owner_user_id == actor.user_id:
        return "write"
    if entry.kind != "file":
        return None
    grants = db.scalars(
        select(ExplorerKeyGrant).where(ExplorerKeyGrant.file_id == entry.id, _grant_filter(actor))
    ).all()
    if not grants:
        return None
    if any(_permission_of(grant) == "write" for grant in grants):
        return "write"
    return "read"


def has_access(db: Session, actor: Actor, entry: ExplorerEntry) -> bool:
    return access_level(db, actor, entry) is not None


def _clean_permission(raw: object, default: str = "write") -> str:
    value = str(raw or default).strip().lower()
    return value if value in {"read", "write"} else default


def parse_access(raw: dict[str, Any] | None) -> AccessSpec:
    raw = raw or {}
    mode = str(raw.get("mode") or "private").strip().lower()
    if mode not in ACCESS_MODES:
        raise ExplorerError("Неизвестный режим доступа")
    users: list[dict[str, str]] = []
    for item in raw.get("users") or []:
        if not isinstance(item, dict):
            continue
        uid = str(item.get("id") or "").strip()
        fio = str(item.get("fio") or "").strip()
        if uid or fio:
            users.append(
                {
                    "id": uid,
                    "fio": fio,
                    "permission": _clean_permission(item.get("permission"), "read"),
                    "department": str(item.get("department") or "").strip(),
                }
            )
    departments = [str(d).strip() for d in (raw.get("departments") or []) if str(d).strip()]
    all_permission = _clean_permission(raw.get("all_permission"), "write")
    if mode == "users" and not users:
        raise ExplorerError("Выберите сотрудников, которым выдать ключ")
    if mode == "department" and not departments and not users:
        raise ExplorerError("Выберите отдел, которому выдать ключ")
    if mode == "department" and departments and users and not any(user["department"] for user in users):
        raise ExplorerError("Укажите, кому в отделе выдать ключ на чтение или на запись")
    return AccessSpec(mode=mode, users=users, departments=departments, all_permission=all_permission)


def _user_grants(users: list[dict[str, str]], actor: Actor) -> list[ExplorerKeyGrant]:
    grants: list[ExplorerKeyGrant] = []
    seen: set[str] = set()
    for user in users:
        if user["id"] == actor.user_id:
            continue
        marker = user["id"] or user["fio"].lower()
        if not marker or marker in seen:
            continue
        seen.add(marker)
        grants.append(
            ExplorerKeyGrant(
                grantee_kind="user",
                grantee_id=user["id"],
                grantee_label=user["fio"],
                permission=_clean_permission(user.get("permission"), "read"),
                source_department=user.get("department") or "",
            )
        )
    return grants


def _apply_access(db: Session, key_row: ExplorerFileKey, spec: AccessSpec, actor: Actor) -> None:
    db.query(ExplorerKeyGrant).filter(ExplorerKeyGrant.file_id == key_row.file_id).delete()
    key_row.access_mode = spec.mode
    grants: list[ExplorerKeyGrant] = []
    if spec.mode == "all":
        grants.append(
            ExplorerKeyGrant(
                grantee_kind="all",
                grantee_id="",
                grantee_label="Все сотрудники",
                permission=spec.all_permission,
            )
        )
    elif spec.mode == "users":
        grants.extend(_user_grants(spec.users, actor))
    elif spec.mode == "department":
        grouped = [user for user in spec.users if user.get("department")]
        if grouped:
            grants.extend(_user_grants(grouped, actor))
        else:
            for dept in dict.fromkeys(spec.departments):
                grants.append(
                    ExplorerKeyGrant(
                        grantee_kind="department",
                        grantee_id=dept,
                        grantee_label=dept,
                        permission="write",
                    )
                )
    for grant in grants:
        grant.id = uuid.uuid4().hex
        grant.file_id = key_row.file_id
        db.add(grant)


def read_access(db: Session, actor: Actor, file_id: str) -> dict[str, Any]:
    entry = _entry_for(db, actor, file_id)
    key_row = db.get(ExplorerFileKey, entry.id)
    grants = db.scalars(select(ExplorerKeyGrant).where(ExplorerKeyGrant.file_id == entry.id)).all()
    departments = [g.grantee_id for g in grants if g.grantee_kind == "department"]
    for grant in grants:
        if grant.source_department and grant.source_department not in departments:
            departments.append(grant.source_department)
    all_grant = next((g for g in grants if g.grantee_kind == "all"), None)
    return {
        "mode": key_row.access_mode if key_row else "private",
        "users": [
            {
                "id": g.grantee_id,
                "fio": g.grantee_label,
                "permission": _permission_of(g),
                "department": g.source_department or "",
            }
            for g in grants
            if g.grantee_kind == "user"
        ],
        "departments": departments,
        "all_permission": _permission_of(all_grant) if all_grant else "write",
    }


def update_access(db: Session, actor: Actor, file_id: str, spec: AccessSpec) -> dict[str, Any]:
    entry = _entry_for(db, actor, file_id)
    if entry.owner_user_id != actor.user_id:
        raise ExplorerError("Доступ к файлу меняет только владелец", 403)
    key_row = db.get(ExplorerFileKey, entry.id)
    if key_row is None:
        raise ExplorerError("У файла нет ключа", 409)
    _apply_access(db, key_row, spec, actor)
    db.commit()
    return serialize(db, actor, entry)


# ---------- listing ----------


def serialize(db: Session, actor: Actor, entry: ExplorerEntry, access_mode: str | None = None) -> dict[str, Any]:
    is_owner = entry.owner_user_id == actor.user_id
    if entry.kind == "file" and access_mode is None:
        key_row = db.get(ExplorerFileKey, entry.id)
        access_mode = key_row.access_mode if key_row else "private"
    return {
        "id": entry.id,
        "kind": entry.kind,
        "name": entry.name,
        "parent_id": entry.parent_id,
        "owner_user_id": entry.owner_user_id,
        "owner_fio": entry.owner_fio,
        "is_owner": is_owner,
        "size": entry.size,
        "content_type": entry.content_type,
        "access_mode": access_mode or "",
        "created_at": entry.created_at.isoformat() if entry.created_at else "",
        "updated_at": entry.updated_at.isoformat() if entry.updated_at else "",
    }


def _path_of(db: Session, entry: ExplorerEntry | None) -> list[dict[str, str]]:
    chain: list[dict[str, str]] = []
    current = entry
    while current is not None:
        chain.append({"id": current.id, "name": current.name})
        current = db.get(ExplorerEntry, current.parent_id) if current.parent_id else None
    return list(reversed(chain))


def _sorted(rows: list[ExplorerEntry]) -> list[ExplorerEntry]:
    return sorted(rows, key=lambda e: (e.kind != "folder", e.name.lower()))


def _folder_sizes(db: Session, owner_user_id: str) -> dict[str, int]:
    """Сумма размеров файлов внутри каждой папки, вместе с вложенными."""
    rows = db.execute(
        select(ExplorerEntry.id, ExplorerEntry.parent_id, ExplorerEntry.kind, ExplorerEntry.size).where(
            ExplorerEntry.owner_user_id == owner_user_id
        )
    ).all()
    children: dict[str | None, list[Any]] = {}
    for row in rows:
        children.setdefault(row.parent_id, []).append(row)
    totals: dict[str, int] = {}

    def total(entry_id: str) -> int:
        if entry_id in totals:
            return totals[entry_id]
        size = 0
        for child in children.get(entry_id, []):
            if child.kind == "file":
                size += int(child.size or 0)
            else:
                size += total(child.id)
        totals[entry_id] = size
        return size

    for row in rows:
        if row.kind == "folder":
            total(row.id)
    return totals


def _shared_entries(db: Session, actor: Actor) -> list[ExplorerEntry]:
    return list(
        db.scalars(
            select(ExplorerEntry)
            .join(ExplorerKeyGrant, ExplorerKeyGrant.file_id == ExplorerEntry.id)
            .where(ExplorerEntry.owner_user_id != actor.user_id, _grant_filter(actor))
            .distinct()
        ).all()
    )


def list_folder(db: Session, actor: Actor, folder_id: str | None) -> dict[str, Any]:
    if folder_id == SHARED_FOLDER_ID:
        rows = _shared_entries(db, actor)
        return {
            "folder": {"id": SHARED_FOLDER_ID, "name": SHARED_FOLDER_NAME, "virtual": True},
            "path": [{"id": SHARED_FOLDER_ID, "name": SHARED_FOLDER_NAME}],
            "parent_id": None,
            "items": [serialize(db, actor, e) for e in _sorted(rows)],
        }
    folder = _own_folder(db, actor, folder_id) if folder_id else None
    stmt = select(ExplorerEntry).where(ExplorerEntry.owner_user_id == actor.user_id)
    stmt = stmt.where(
        ExplorerEntry.parent_id.is_(None) if folder is None else ExplorerEntry.parent_id == folder.id
    )
    sizes = _folder_sizes(db, actor.user_id)
    items = []
    for entry in _sorted(list(db.scalars(stmt).all())):
        item = serialize(db, actor, entry)
        if entry.kind == "folder":
            item["size"] = sizes.get(entry.id, 0)
        items.append(item)
    if folder is None:
        shared = _shared_entries(db, actor)
        items.insert(
            0,
            {
                "id": SHARED_FOLDER_ID,
                "kind": "folder",
                "name": SHARED_FOLDER_NAME,
                "parent_id": None,
                "virtual": True,
                "is_owner": False,
                "size": sum(int(entry.size or 0) for entry in shared),
            },
        )
    return {
        "folder": serialize(db, actor, folder) if folder else None,
        "path": _path_of(db, folder),
        "parent_id": folder.parent_id if folder else None,
        "items": items,
    }


def _entry_for_disk_path(db: Session, raw_path: str) -> ExplorerEntry | None:
    """Находит файл базы знаний по пути, которым его открыли в проводнике Windows."""
    normalized = (raw_path or "").strip().strip('"').replace("\\", "/").rstrip("/")
    if not normalized:
        return None
    root = str(_root()).replace("\\", "/").rstrip("/")
    rel = ""
    if normalized.lower().startswith(root.lower() + "/"):
        rel = normalized[len(root) :].lstrip("/")
    if rel:
        found = db.scalar(
            select(ExplorerEntry).where(
                ExplorerEntry.kind == "file",
                func.lower(ExplorerEntry.rel_path) == rel.lower(),
            )
        )
        if found is not None:
            return found
    name = normalized.rsplit("/", 1)[-1]
    if not name:
        return None
    candidates = db.scalars(
        select(ExplorerEntry).where(
            ExplorerEntry.kind == "file",
            func.lower(ExplorerEntry.name) == name.lower(),
        )
    ).all()
    needle = normalized.lower()
    for entry in candidates:
        suffix = entry.rel_path.replace("\\", "/").lower()
        if needle.endswith("/" + suffix) or needle == suffix:
            return entry
    return None


def resolve_disk_path(db: Session, actor: Actor, raw_path: str) -> dict[str, str]:
    entry = _entry_for_disk_path(db, raw_path)
    if entry is None or not has_access(db, actor, entry):
        raise ExplorerError("Файл не найден или к нему нет доступа", 404)
    return {"id": entry.id, "name": entry.name}


def _entry_for(db: Session, actor: Actor, entry_id: str) -> ExplorerEntry:
    entry = db.get(ExplorerEntry, entry_id)
    if entry is None or not has_access(db, actor, entry):
        raise ExplorerError("Файл не найден или к нему нет доступа", 404)
    return entry


# ---------- history ----------


@dataclass
class _EntryRef:
    id: str
    kind: str
    name: str
    owner_folder: str
    owner_user_id: str
    owner_fio: str
    rel_path: str

    @classmethod
    def of(cls, entry: ExplorerEntry) -> "_EntryRef":
        return cls(
            entry.id,
            entry.kind,
            entry.name,
            entry.owner_folder,
            entry.owner_user_id,
            entry.owner_fio,
            entry.rel_path,
        )


def _repo_relative(entry: ExplorerEntry | _EntryRef) -> str:
    prefix = f"{entry.owner_folder}/"
    return entry.rel_path[len(prefix) :] if entry.rel_path.startswith(prefix) else entry.rel_path


def _history(
    db: Session,
    actor: Actor,
    entry: _EntryRef,
    data: bytes | None,
    message: str,
) -> None:
    path = _repo_relative(entry) + ("/" if entry.kind == "folder" else "")

    def baseline() -> list[explorer_history.BaselineSource]:
        rows = db.execute(
            select(ExplorerEntry, ExplorerFileKey.key)
            .join(ExplorerFileKey, ExplorerFileKey.file_id == ExplorerEntry.id)
            .where(
                ExplorerEntry.owner_folder == entry.owner_folder,
                ExplorerEntry.kind == "file",
                ExplorerEntry.id != entry.id,
            )
        ).all()
        return [(_repo_relative(row), _abs(row.rel_path), key) for row, key in rows]

    explorer_history.record(
        db,
        owner_dir=_abs(entry.owner_folder),
        owner_folder=entry.owner_folder,
        owner_user_id=entry.owner_user_id,
        owner_name=entry.owner_fio,
        actor_id=actor.user_id,
        actor_name=actor.fio,
        changes=[explorer_history.Change(path, data)],
        message=f"{message} «{entry.name}»\n\nFile-Id: {entry.id}\n",
        baseline=baseline,
        reader=_read_encrypted,
    )


# ---------- mutations ----------


def create_folder(db: Session, actor: Actor, parent_id: str | None, raw_name: str) -> dict[str, Any]:
    name = clean_name(raw_name)
    parent = _own_folder(db, actor, parent_id)
    folder_name = parent.owner_folder if parent else owner_folder(db, actor)
    _ensure_owner_dir(folder_name)
    rel_path = f"{parent.rel_path if parent else folder_name}/{name}"
    _check_unique(db, actor, parent.id if parent else None, name, rel_path)
    try:
        _abs(rel_path).mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise ExplorerError("Не удалось создать папку в хранилище", 503) from exc
    entry = ExplorerEntry(
        id=uuid.uuid4().hex,
        kind="folder",
        name=name,
        parent_id=parent.id if parent else None,
        owner_user_id=actor.user_id,
        owner_fio=actor.fio,
        owner_folder=folder_name,
        rel_path=rel_path,
        updated_by=actor.user_id,
    )
    db.add(entry)
    db.commit()
    return serialize(db, actor, entry)


def create_file(
    db: Session,
    actor: Actor,
    parent_id: str | None,
    raw_name: str,
    data: bytes | None,
    access: AccessSpec,
) -> dict[str, Any]:
    name = clean_name(raw_name)
    if not Path(name).suffix:
        raise ExplorerError("Укажите имя файла с расширением, например «план.docx»")
    if data is not None and len(data) > settings.explorer_max_upload_mb * 1024 * 1024:
        raise ExplorerError(f"Файл больше {settings.explorer_max_upload_mb} МБ", 413)
    parent = _own_folder(db, actor, parent_id)
    folder_name = parent.owner_folder if parent else owner_folder(db, actor)
    _ensure_owner_dir(folder_name)
    rel_path = f"{parent.rel_path if parent else folder_name}/{name}"
    _check_unique(db, actor, parent.id if parent else None, name, rel_path)
    content = data if data is not None else _blank_content(name)
    key = Fernet.generate_key().decode("ascii")
    read_key = Fernet.generate_key().decode("ascii")
    entry = ExplorerEntry(
        id=uuid.uuid4().hex,
        kind="file",
        name=name,
        parent_id=parent.id if parent else None,
        owner_user_id=actor.user_id,
        owner_fio=actor.fio,
        owner_folder=folder_name,
        rel_path=rel_path,
        size=len(content),
        content_type=mimetypes.guess_type(name)[0] or "application/octet-stream",
        updated_by=actor.user_id,
    )
    key_row = ExplorerFileKey(
        file_id=entry.id, owner_user_id=actor.user_id, key=key, read_key=read_key
    )
    db.add(entry)
    db.flush()
    db.add(key_row)
    db.flush()
    _apply_access(db, key_row, access, actor)
    _write_encrypted(_abs(rel_path), key, content)
    try:
        db.commit()
    except Exception:
        db.rollback()
        _abs(rel_path).unlink(missing_ok=True)
        raise
    _history(db, actor, _EntryRef.of(entry), content, "Создал")
    return serialize(db, actor, entry)


def read_file(db: Session, actor: Actor, file_id: str) -> tuple[ExplorerEntry, bytes]:
    entry = _entry_for(db, actor, file_id)
    if entry.kind != "file":
        raise ExplorerError("Это папка", 400)
    key_row = db.get(ExplorerFileKey, entry.id)
    if key_row is None:
        raise ExplorerError("У файла нет ключа", 409)
    return entry, _read_encrypted(_abs(entry.rel_path), key_row.key)


def write_file(db: Session, actor: Actor, file_id: str, data: bytes) -> dict[str, Any]:
    entry = _entry_for(db, actor, file_id)
    if entry.kind != "file":
        raise ExplorerError("Это папка", 400)
    if len(data) > settings.explorer_max_upload_mb * 1024 * 1024:
        raise ExplorerError(f"Файл больше {settings.explorer_max_upload_mb} МБ", 413)
    if access_level(db, actor, entry) != "write":
        raise ExplorerError("Для изменения нужен ключ на запись", 403)
    key_row = db.get(ExplorerFileKey, entry.id)
    if key_row is None:
        raise ExplorerError("У файла нет ключа", 409)
    _write_encrypted(_abs(entry.rel_path), key_row.key, data)
    entry.size = len(data)
    entry.updated_by = actor.user_id
    entry.updated_at = func.now()
    db.commit()
    db.refresh(entry)
    _history(db, actor, _EntryRef.of(entry), data, "Изменил")
    return serialize(db, actor, entry)


def delete_entry(db: Session, actor: Actor, entry_id: str) -> None:
    entry = db.get(ExplorerEntry, entry_id)
    if entry is None:
        raise ExplorerError("Не найдено", 404)
    if entry.owner_user_id != actor.user_id:
        raise ExplorerError("Удалять может только владелец", 403)
    target = _abs(entry.rel_path)
    ref = _EntryRef.of(entry)
    if entry.kind == "folder":
        ids = [entry.id]
        frontier = [entry.id]
        while frontier:
            children = db.scalars(
                select(ExplorerEntry.id).where(ExplorerEntry.parent_id.in_(frontier))
            ).all()
            ids.extend(children)
            frontier = list(children)
        for child_id in reversed(ids):
            db.query(ExplorerEntry).filter(ExplorerEntry.id == child_id).delete()
        db.commit()
        shutil.rmtree(target, ignore_errors=True)
        _history(db, actor, ref, None, "Удалил папку")
        return
    db.delete(entry)
    db.commit()
    target.unlink(missing_ok=True)
    _history(db, actor, ref, None, "Удалил")
