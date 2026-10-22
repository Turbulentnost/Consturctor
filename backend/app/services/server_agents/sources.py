"""Точечные источники для серверного агента доступа.

Агент не листает всю оргструктуру и всю шару. Он называет фамилию, отдел или файл,
и получает только эту запись: сотрудник и должность из org_members, отдел из org_units,
текст одного нормативного документа подразделения.
"""

from __future__ import annotations

import io
import json
import re
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
LOOKUPS = {"people", "department", "norm", "position", "manager"}
TEXT_LIMIT = 16_000
NORM_TEXT_LIMIT = 6_000


def extract_text(name: str, data: bytes, limit: int = TEXT_LIMIT) -> str:
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
            text = _pdf_text(data, limit)
        else:
            text = ""
    except Exception:
        text = ""
    return " ".join(text.split())[:limit] if text else ""


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


def position_lookup(db: Session, query: str) -> dict:
    """Кто занимает должность. Слишком общий запрос не возвращает толпу людей."""
    safe = _safe(query)
    if len(fio_key(safe)) < 8:
        return {"ok": False, "error": "Укажите должность целиком, например «главный конструктор»"}
    rows = [
        member
        for member in db.scalars(select(OrgMember).where(OrgMember.position.ilike(f"%{safe}%")).limit(16)).all()
        if not is_liquidated(member.position) and not is_liquidated(member.fio) and not is_liquidated(member.department)
    ]
    if len(rows) > 5:
        return {
            "ok": True,
            "too_many": True,
            "count": len(rows),
            "items": [],
            "error": "Должность слишком общая, уточните её так, как она написана в документе",
        }
    return {"ok": True, "too_many": False, "items": [_person(db, member) for member in rows]}


def position_holders(db: Session, query: str) -> list[dict[str, str]]:
    found = position_lookup(db, query)
    items = found.get("items")
    return list(items) if isinstance(items, list) else []


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


_HEAD_POST = re.compile(r"^(начальник|руководитель|директор|заведующ)", re.IGNORECASE)


def superiors(db: Session, fio: str) -> dict | None:
    """Факты для выбора руководителя: цепочка подразделений 1С и руководящие должности своего отдела.

    Кто из них непосредственный руководитель, решает агент: в 1С подразделение заполнено не у всех,
    а документ может сам назначать, кто контролирует.
    """
    own = fio_key(fio)
    member = db.get(OrgMember, own)
    if member is None:
        return None
    units = {unit.id: unit for unit in db.scalars(select(OrgUnit)).all()}
    led = [unit for unit in units.values() if fio_key(unit.head_fio) == own]
    current = units.get(member.unit_id) or (led[0] if len(led) == 1 else None)
    chain: list[dict[str, str]] = []
    for _ in range(40):
        if current is None:
            break
        head = fio_key(current.head_fio)
        if head and head != own:
            boss = db.get(OrgMember, head)
            if boss is not None and not is_liquidated(boss.fio):
                chain.append(_person(db, boss) | {"heads_unit": current.name})
            else:
                chain.append({"user_id": "", "fio": current.head_fio, "position": "", "department": "", "heads_unit": current.name})
        current = units.get(current.parent_id)
    leaders = [
        _person(db, row)
        for row in db.scalars(
            select(OrgMember).where(OrgMember.department == member.department, OrgMember.fio_key != own).limit(400)
        ).all()
        if member.department and _HEAD_POST.match(row.position or "") and not is_liquidated(row.fio)
    ][:10]
    return {
        "person": _person(db, member),
        "own_unit": units[member.unit_id].name if member.unit_id in units else "",
        "heads_units": [unit.name for unit in led],
        "unit_chain_heads": chain,
        "department_leaders": leaders,
    }


def is_superior(db: Session, fio: str, boss_fio: str) -> bool:
    found = superiors(db, fio)
    if not found:
        return False
    key = fio_key(boss_fio)
    return any(fio_key(item["fio"]) == key for item in found["unit_chain_heads"] + found["department_leaders"])


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
    if not args or args[0] not in LOOKUPS:
        _emit({"ok": False, "error": "Команда: people, department, position, manager или norm, и строка поиска"})
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
        elif command == "position":
            _emit(position_lookup(db, query))
        elif command == "manager":
            found = superiors(db, query)
            _emit({"ok": True} | found if found else {"ok": False, "error": "Сотрудник не найден, уточните ФИО"})
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


def pdf_page_images(data: bytes, *, first: int = 2, last: int = 1, dpi: int = 110) -> list[tuple[int, bytes]]:
    """PNG первых и последних страниц PDF: на скане подписи, даты и печати есть только на изображении."""
    try:
        import pymupdf
    except ImportError:
        return []
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        return []
    try:
        count = document.page_count
        wanted = sorted({*range(min(first, count)), *range(max(count - last, 0), count)})
        return [(index + 1, document[index].get_pixmap(dpi=dpi).tobytes("png")) for index in wanted]
    except Exception:
        return []
    finally:
        document.close()


def _pdf_text(data: bytes, limit: int = TEXT_LIMIT) -> str:
    """Текст PDF через уже установленные PyMuPDF и pdfplumber. Страницы читаем, пока не наберём лимит."""
    pages = max(30, limit // 1000)
    text = _pdf_pymupdf(data, limit, pages)
    if len(text.strip()) >= 40:
        return text
    fallback = _pdf_pdfplumber(data, limit, pages)
    return fallback if len(fallback.strip()) > len(text.strip()) else text


def _pdf_pymupdf(data: bytes, limit: int, pages: int) -> str:
    try:
        import pymupdf
    except ImportError:
        return ""
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        return ""
    parts: list[str] = []
    total = 0
    try:
        for page in document:
            if len(parts) >= pages or total >= limit:
                break
            piece = page.get_text("text") or ""
            parts.append(piece)
            total += len(piece)
    finally:
        document.close()
    return "\n".join(parts)


def _pdf_pdfplumber(data: bytes, limit: int, pages: int) -> str:
    try:
        import pdfplumber
    except ImportError:
        return ""
    parts: list[str] = []
    total = 0
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                if len(parts) >= pages or total >= limit:
                    break
                piece = page.extract_text() or ""
                parts.append(piece)
                total += len(piece)
    except Exception:
        return ""
    return "\n".join(parts)
