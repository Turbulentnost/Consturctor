"""CSV of incoming correspondence: subject and body from the attached letter."""

from __future__ import annotations

import csv
import html
import io
import re
import sys
from pathlib import Path

from app.clients.erp_sql import get_user_profile_by_fio
from app.services.onec_tools import _odata_get

TARGET = 2000
PAGE = 200
START_SKIP = 98000
OUT = r"c:\Users\mdj\Desktop\конструктор\входящие_вложения.csv"
ENTITY = "Document_ТД_ВходящаяКорреспонденция"
FILES = "Catalog_ТД_ВходящаяКорреспонденцияПрисоединенныеФайлы"
VOLUMES = "Catalog_ТомаХраненияФайлов"
EMPTY = "00000000-0000-0000-0000-000000000000"
MAIL_EXT = {".msg", ".eml"}
_TAG = re.compile(r"<[^>]+>", re.IGNORECASE)
_SCRIPT = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)

_dept_names: dict[str, str] = {}
_user_names: dict[str, str] = {}
_user_depts: dict[str, str] = {}
_volumes: dict[str, str] = {}


def _guid(value: object) -> str:
    text = str(value or "").strip()
    if not text or text == EMPTY:
        return ""
    return text


def _clean(value: object) -> str:
    raw = str(value or "").replace("\x00", " ")
    if "<" in raw and ">" in raw:
        raw = _SCRIPT.sub(" ", raw)
        raw = html.unescape(_TAG.sub(" ", raw))
    return " ".join(raw.replace("\xa0", " ").split())


def _description(entity: str, guid: str) -> str:
    data = _odata_get({"path": f"{entity}(guid'{guid}')", "select": "Description"})["data"]
    if isinstance(data, dict) and "value" in data:
        rows = data.get("value") or []
        data = rows[0] if rows else {}
    if not isinstance(data, dict):
        return ""
    return _clean(data.get("Description") or data.get("Наименование") or "")


def _department_name(guid: str) -> str:
    key = _guid(guid)
    if not key:
        return ""
    cached = _dept_names.get(key.lower())
    if cached is not None:
        return cached
    try:
        name = _description("Catalog_СтруктураПредприятия", key)
    except Exception:
        name = ""
    _dept_names[key.lower()] = name
    return name


def _user_name(guid: str) -> str:
    key = _guid(guid)
    if not key:
        return ""
    cached = _user_names.get(key.lower())
    if cached is not None:
        return cached
    try:
        name = _description("Catalog_Пользователи", key)
    except Exception:
        name = ""
    _user_names[key.lower()] = name
    return name


def _department_of_user(guid: str) -> str:
    key = _guid(guid)
    if not key:
        return ""
    cached = _user_depts.get(key.lower())
    if cached is not None:
        return cached
    name = _user_name(key)
    department = ""
    if name:
        try:
            department = _clean(get_user_profile_by_fio(name).department)
        except Exception:
            department = ""
    _user_depts[key.lower()] = department
    return department


def _department(row: dict) -> str:
    executors = row.get("CRM_Исполнители") or []
    if isinstance(executors, list) and executors:
        person = _guid((executors[-1] or {}).get("Исполнитель_Key"))
        found = _department_of_user(person)
        if found:
            return found
    for field in ("КомуПодразделениеСсылка_Key", "ПодразделениеИсполнитель_Key"):
        found = _department_name(str(row.get(field) or ""))
        if found:
            return found
    return ""


def _sender(row: dict) -> str:
    return _clean(row.get("EmailОтправителяПисьма") or row.get("Партнер") or "")


def _read_file(path: Path) -> bytes:
    return path.read_bytes()


def _volume_root(volume_key: str) -> str:
    key = _guid(volume_key)
    if not key:
        return ""
    cached = _volumes.get(key.lower())
    if cached is not None:
        return cached
    root = ""
    try:
        data = _odata_get({"path": f"{VOLUMES}(guid'{key}')"})["data"]
        if isinstance(data, dict) and "value" in data:
            rows = data.get("value") or []
            data = rows[0] if rows else {}
        if isinstance(data, dict):
            root = str(data.get("ПолныйПутьWindows") or "").strip()
    except Exception:
        root = ""
    _volumes[key.lower()] = root
    return root


def _attachments(owner: str) -> list[dict]:
    path = f"{FILES}?$filter=ВладелецФайла_Key eq guid'{owner}'"
    try:
        data = _odata_get({"path": path, "top": 20})["data"]
    except Exception:
        return []
    rows = data.get("value") if isinstance(data, dict) else []
    return [row for row in rows or [] if isinstance(row, dict)]


def _mail_file(rows: list[dict]) -> dict | None:
    mails = []
    for row in rows:
        ext = str(row.get("Расширение") or "").strip().lower()
        if ext and not ext.startswith("."):
            ext = "." + ext
        name = str(row.get("Description") or "")
        if not ext:
            ext = Path(name).suffix.lower()
        if ext in MAIL_EXT:
            mails.append(row)
    if not mails:
        return None
    mails.sort(key=lambda row: int(row.get("Размер") or 0), reverse=True)
    return mails[0]


def _prop_text(streams: dict[str, bytes], prop: str) -> str:
    for suffix, encoding in (("001F", "utf-16-le"), ("001E", "cp1251")):
        raw = streams.get(f"__substg1.0_{prop}{suffix}")
        if not raw:
            continue
        text = raw.decode(encoding, errors="replace").replace("\x00", "").strip()
        if text:
            return text
    raw = streams.get(f"__substg1.0_{prop}0102")
    if not raw:
        return ""
    for encoding in ("utf-8", "cp1251"):
        text = raw.decode(encoding, errors="replace").replace("\x00", "").strip()
        if text:
            return text
    return ""


def _msg_streams(data: bytes) -> dict[str, bytes]:
    import olefile

    ole = olefile.OleFileIO(io.BytesIO(data))
    streams: dict[str, bytes] = {}
    try:
        for entry in ole.listdir():
            leaf = entry[-1]
            if not leaf.startswith("__substg1.0_"):
                continue
            current = streams.get(leaf)
            blob = ole.openstream(entry).read()
            if current is None or len(blob) > len(current):
                streams[leaf] = blob
    finally:
        ole.close()
    return streams


def _eml_parts(data: bytes) -> tuple[str, str, str]:
    import email
    from email.policy import default

    message = email.message_from_bytes(data, policy=default)
    subject = _clean(message.get("subject") or "")
    sender = _clean(message.get("from") or "")
    body = ""
    html_body = ""
    if message.is_multipart():
        for part in message.walk():
            kind = part.get_content_type()
            if kind == "text/plain" and not body:
                body = part.get_content()
            elif kind == "text/html" and not html_body:
                html_body = part.get_content()
    else:
        kind = message.get_content_type()
        content = message.get_content()
        if kind == "text/html":
            html_body = content
        else:
            body = content
    return sender, subject, _clean(body or html_body)


def _letter_text(path: Path) -> tuple[str, str, str]:
    data = _read_file(path)
    if path.suffix.lower() == ".eml":
        return _eml_parts(data)
    streams = _msg_streams(data)
    sender = _prop_text(streams, "5D01") or _prop_text(streams, "0C1F") or _prop_text(streams, "0065")
    subject = _prop_text(streams, "0037")
    body = _prop_text(streams, "1000") or _prop_text(streams, "1013")
    return _clean(sender), _clean(subject), _clean(body)


def _letter_from_row(row: dict) -> tuple[str, str, str]:
    mail = _mail_file(_attachments(str(row.get("Ref_Key") or "")))
    if not mail:
        return "", "", ""
    root = _volume_root(str(mail.get("Том_Key") or ""))
    relative = str(mail.get("ПутьКФайлу") or "").strip().replace("/", "\\")
    if not root or not relative:
        return "", "", ""
    try:
        return _letter_text(Path(root) / relative)
    except Exception:
        return "", "", ""


def main() -> int:
    written = 0
    with_body = 0
    with_subject = 0
    seen: set[str] = set()
    with open(OUT, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["Отдел", "отправитель", "тема", "содержимое"])
        skip = START_SKIP
        while written < TARGET:
            raw = _odata_get({"path": ENTITY, "top": PAGE, "skip": skip})
            rows = raw["data"].get("value") or []
            if not rows:
                break
            fresh = 0
            for row in rows:
                ref = str(row.get("Ref_Key") or "")
                if not ref or ref in seen or row.get("DeletionMark"):
                    continue
                seen.add(ref)
                fresh += 1
                mail_sender, subject, body = _letter_from_row(row)
                if not subject:
                    subject = _clean(row.get("ТемаСлужебнойЗаписки"))
                sender = mail_sender or _sender(row)
                writer.writerow([_department(row), sender, subject, body])
                handle.flush()
                written += 1
                if subject:
                    with_subject += 1
                if body:
                    with_body += 1
                if written % 25 == 0:
                    print(
                        f"written={written} subject={with_subject} body={with_body} skip={skip}",
                        flush=True,
                    )
                if written >= TARGET:
                    break
            if fresh == 0:
                break
            skip += PAGE
    print(f"done written={written} subject={with_subject} body={with_body}", flush=True)
    return 0 if with_body else 1


if __name__ == "__main__":
    sys.exit(main())
