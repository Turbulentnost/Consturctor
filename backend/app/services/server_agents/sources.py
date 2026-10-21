"""Точечные источники для серверного агента доступа.

Агент не листает всю оргструктуру и всю шару. Он называет фамилию, отдел или файл,
и получает только эту запись: сотрудник и должность из org_members, отдел из org_units,
текст одного нормативного документа подразделения.
"""

from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.org import OrgMember, OrgUnit
from app.models.user import AppUser
from app.services.org_structure import fio_key, is_liquidated

NORMS_DIR = Path(
    r"\\192.168.1.198\Files\10.СКТБ\НОРМАТИВНЫЕ ДОКУМЕНТЫ ОРГАНИЗАЦИИ"
    r"\НОРМАТИВНЫЕ ДОКУМЕНТЫ\Нормативные документы по подразделениям"
)
TEXT_LIMIT = 16_000
NORM_TEXT_LIMIT = 6_000


def extract_text(name: str, data: bytes) -> str:
    """Текст документа, если формат понятен. Пустая строка — агент не знает, что это за файл."""
    ext = Path(name).suffix.lower()
    try:
        if ext in {".txt", ".md", ".csv", ".json", ".xml", ".html", ".htm", ".log", ".rtf"}:
            text = _plain(data)
        elif ext == ".docx":
            text = _docx_text(data)
        elif ext == ".xlsx":
            text = _xlsx_text(data)
        elif ext == ".pdf":
            text = _pdf_text(data)
        else:
            text = ""
    except Exception:
        text = ""
    return " ".join(text.split())[:TEXT_LIMIT] if text else ""


def people_lookup(db: Session, query: str) -> dict:
    safe = _safe(query)
    if len(fio_key(safe)) < 3:
        return {"ok": False, "error": "Укажите хотя бы три буквы фамилии, без перебора всех сотрудников"}
    rows = db.scalars(
        select(OrgMember)
        .where(or_(OrgMember.fio.ilike(f"%{safe}%"), OrgMember.position.ilike(f"%{safe}%")))
        .limit(15)
    ).all()
    items = []
    for member in rows:
        if is_liquidated(member.department) or is_liquidated(member.position) or is_liquidated(member.fio):
            continue
        items.append(
            {
                "fio": member.fio,
                "position": member.position,
                "department": member.department,
                "user_id": _app_user_id(db, member),
            }
        )
    return {"ok": True, "items": items}


def department_lookup(db: Session, query: str) -> dict:
    safe = _safe(query)
    if len(fio_key(safe)) < 3:
        return {"ok": False, "error": "Укажите название отдела, которое уже есть в документе"}
    rows = db.scalars(select(OrgUnit).where(OrgUnit.name.ilike(f"%{safe}%")).limit(30)).all()
    items = []
    for unit in rows:
        if is_liquidated(unit.name):
            continue
        count = db.scalar(select(func.count()).select_from(OrgMember).where(OrgMember.unit_id == unit.id)) or 0
        items.append({"name": unit.name, "head_fio": unit.head_fio, "members": int(count)})
        if len(items) >= 10:
            break
    return {"ok": True, "items": items}


def resolve_person(db: Session, fio: str):
    """Один сотрудник по ФИО. None, если такого нет или под строку подходят двое."""
    key = fio_key(fio)
    if not key:
        return None
    exact = db.get(OrgMember, key)
    if exact is not None and not is_liquidated(exact.fio):
        return _person(db, exact)
    safe = _safe(fio)
    if len(fio_key(safe)) < 3:
        return None
    rows = [
        row
        for row in db.scalars(select(OrgMember).where(OrgMember.fio.ilike(f"%{safe}%")).limit(3)).all()
        if not is_liquidated(row.fio)
    ]
    if len(rows) != 1:
        return None
    return _person(db, rows[0])


def resolve_department(db: Session, name: str) -> str:
    """Точное название отдела из org_units. Пусто, если отдел не найден или нашлось несколько."""
    key = fio_key(name)
    if len(key) < 3:
        return ""
    rows = [
        unit.name
        for unit in db.scalars(select(OrgUnit).where(OrgUnit.name.ilike(f"%{_safe(name)}%")).limit(8)).all()
        if not is_liquidated(unit.name) and (fio_key(unit.name) == key or key in fio_key(unit.name))
    ]
    exact = [item for item in rows if fio_key(item) == key]
    if len(exact) == 1:
        return exact[0]
    if len(rows) == 1:
        return rows[0]
    return ""


def norm_lookup(query: str) -> dict:
    """Один нормативный файл подразделения. Несколько совпадений — только имена, без текста."""
    safe = _safe(query)
    if len(fio_key(safe)) < 4:
        return {"ok": False, "error": "Укажите отдел, чей нормативный документ нужно прочитать"}
    try:
        names = _norm_names()
    except OSError as exc:
        return {"ok": False, "error": f"Папка нормативных документов недоступна: {exc}"}
    needle = fio_key(safe)
    matches = [name for name in names if needle in fio_key(name)][:8]
    if len(matches) != 1:
        return {"ok": True, "matches": matches, "text": ""}
    path = _norm_path(matches[0])
    try:
        data = path.read_bytes()
    except OSError as exc:
        return {"ok": False, "error": f"Не удалось прочитать «{matches[0]}»: {exc}"}
    if len(data) > 8_000_000:
        return {"ok": True, "matches": matches, "text": ""}
    return {"ok": True, "matches": matches, "text": extract_text(path.name, data)[:NORM_TEXT_LIMIT]}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in {"people", "department", "norm"}:
        _emit({"ok": False, "error": "Команда: people, department или norm, и строка поиска"})
        return 2
    command, query = args[0], " ".join(args[1:]).strip()
    if command == "norm":
        _emit(norm_lookup(query))
        return 0
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        if command == "people":
            _emit(people_lookup(db, query))
        else:
            _emit(department_lookup(db, query))
    except Exception as exc:  # noqa: BLE001 — агент должен увидеть ошибку, а не трассировку с адресом базы
        _emit({"ok": False, "error": str(exc) or exc.__class__.__name__})
        return 1
    finally:
        db.close()
    return 0


def _person(db: Session, member: OrgMember) -> dict[str, str]:
    return {
        "user_id": _app_user_id(db, member),
        "fio": member.fio,
        "position": member.position,
        "department": member.department,
    }


def _app_user_id(db: Session, member: OrgMember) -> str:
    if member.user_id and db.get(AppUser, member.user_id) is not None:
        return member.user_id
    account = db.scalar(select(AppUser).where(func.lower(AppUser.fio) == member.fio.lower()))
    return account.id if account is not None else ""


def _safe(value: str) -> str:
    return (value or "").replace("%", "").replace("_", "").strip()


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _norm_names() -> list[str]:
    if not NORMS_DIR.is_dir():
        raise OSError(str(NORMS_DIR))
    names: list[str] = []
    for item in NORMS_DIR.iterdir():
        if item.is_file():
            names.append(item.name)
        elif item.is_dir():
            for child in item.iterdir():
                if child.is_file():
                    names.append(f"{item.name}/{child.name}")
        if len(names) >= 400:
            break
    return names


def _norm_path(name: str) -> Path:
    parts = [part for part in name.replace("\\", "/").split("/") if part and part not in {".", ".."}]
    return NORMS_DIR.joinpath(*parts)


def _plain(data: bytes) -> str:
    text = data.decode("utf-8", errors="replace")
    if text.count("\ufffd") > 8:
        text = data.decode("cp1251", errors="replace")
    if data[:5].lower() == b"{\\rtf":
        return _rtf(text)
    return text


def _rtf(text: str) -> str:
    import re

    return re.sub(r"\\[a-z]+-?\d* ?", " ", text.replace("\\par", "\n"))


def _docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        xml = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml)
    parts: list[str] = []
    for node in root.iter():
        if node.tag.endswith("}t") and node.text:
            parts.append(node.text)
        elif node.tag.endswith("}p"):
            parts.append("\n")
    return "".join(parts)


def _xlsx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if "xl/sharedStrings.xml" not in archive.namelist():
            return ""
        xml = archive.read("xl/sharedStrings.xml")
    root = ElementTree.fromstring(xml)
    return "\n".join(node.text or "" for node in root.iter() if node.tag.endswith("}t") and node.text)


def _pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfReader
        except ImportError:
            return ""
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages[:8])
