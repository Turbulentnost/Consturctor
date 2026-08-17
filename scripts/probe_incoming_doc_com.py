"""Open incoming correspondence НП00-004286 via COM and extract attachment contents."""
from __future__ import annotations

import base64
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "platform-tool-onec-com"))

env: dict[str, str] = {}
for line in (ROOT / "infra" / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, _, v = line.partition("=")
    env[k.strip()] = v.strip().strip('"').strip("'")

import os

for k, v in env.items():
    os.environ[k] = v

from platform_tool_onec_com.onec_com import (  # noqa: E402
    connect_session,
    query_attached_files,
    resolve_ref_info,
)

DOC_NUMBER = "НП00-004286"
DOC_TYPE = "ТД_ВходящаяКорреспонденция"
ATTACH_CATALOG = f"{DOC_TYPE}ПрисоединенныеФайлы"


def safe_str(val, limit=2000):
    if val is None:
        return ""
    s = str(val).strip()
    if s.startswith("0001-01-01"):
        return ""
    return s[:limit] + ("..." if len(s) > limit else "")


def read_file_bytes(app, file_ref) -> bytes | None:
    """Try several 1C APIs to read attached file binary."""
    # Method 1: РаботаСФайлами
    try:
        mgr = app.РаботаСФайлами
        for method in (
            "ПолучитьДанныеФайла",
            "ПолучитьДвоичныеДанныеФайла",
            "ДанныеФайла",
        ):
            if not hasattr(mgr, method):
                continue
            fn = getattr(mgr, method)
            try:
                data = fn(file_ref)
                if data is None:
                    continue
                if hasattr(data, "Получить"):
                    return bytes(data.Получить())
                if isinstance(data, (bytes, bytearray)):
                    return bytes(data)
            except Exception:
                continue
    except Exception:
        pass

    # Method 2: save to temp via ПолучитьИмяВременногоФайла + write
    try:
        mgr = app.РаботаСФайлами
        if hasattr(mgr, "ПолучитьИмяФайла"):
            path = mgr.ПолучитьИмяФайла(file_ref, app.КаталогВременныхФайлов(), 1)
            if path and Path(str(path)).is_file():
                return Path(str(path)).read_bytes()
    except Exception:
        pass

    # Method 3: open file object and read binary field
    try:
        obj = file_ref.ПолучитьОбъект() if hasattr(file_ref, "ПолучитьОбъект") else app.Справочники[ATTACH_CATALOG].ПолучитьОбъект(file_ref)
        for attr in ("ДвоичныеДанные", "ДвоичныеДанныеФайла", "Хранилище"):
            try:
                val = getattr(obj, attr, None)
                if val is None:
                    continue
                if hasattr(val, "Получить"):
                    return bytes(val.Получить())
            except Exception:
                continue
    except Exception:
        pass

    # Method 4: export via ПолучитьНавигационнуюСсылку + path field
    try:
        obj = file_ref.ПолучитьОбъект()
        path = getattr(obj, "ПутьКФайлу", "") or getattr(obj, "Том", None)
        if path:
            p = str(getattr(path, "ПолныйПутьWindows", path) if path else "")
            if p and Path(p).is_file():
                return Path(p).read_bytes()
    except Exception:
        pass

    return None


def extract_text_from_bytes(data: bytes, ext: str) -> str:
    ext = ext.lower().lstrip(".")
    if ext in {"txt", "csv", "xml", "html", "htm", "json", "md", "log"}:
        for enc in ("utf-8", "cp1251", "latin-1"):
            try:
                return data.decode(enc)
            except Exception:
                continue
    if ext == "pdf":
        try:
            import pypdf

            from io import BytesIO

            reader = pypdf.PdfReader(BytesIO(data))
            parts = []
            for page in reader.pages[:20]:
                parts.append(page.extract_text() or "")
            return "\n".join(parts).strip()
        except Exception as exc:
            return f"[PDF {len(data)} bytes, text extract failed: {exc}]"
    if ext in {"doc", "docx"}:
        if ext == "docx":
            try:
                from io import BytesIO
                import zipfile

                zf = zipfile.ZipFile(BytesIO(data))
                xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")
                import re

                text = re.sub(r"<[^>]+>", " ", xml)
                text = re.sub(r"\s+", " ", text).strip()
                return text[:8000]
            except Exception as exc:
                return f"[DOCX {len(data)} bytes, extract failed: {exc}]"
        return f"[DOC binary {len(data)} bytes — нужен конвертер]"
    if ext in {"xls", "xlsx"}:
        return f"[Excel {len(data)} bytes — бинарный, нужен парсер]"
    if ext == "msg":
        try:
            import extract_msg

            tmp = Path(tempfile.gettempdir()) / "probe.msg"
            tmp.write_bytes(data)
            msg = extract_msg.Message(str(tmp))
            body = msg.body or ""
            subject = msg.subject or ""
            sender = msg.sender or ""
            tmp.unlink(missing_ok=True)
            return f"From: {sender}\nSubject: {subject}\n\n{body}".strip()
        except Exception:
            return f"[MSG {len(data)} bytes — установите extract-msg для полного разбора]"
    if ext in {"jpg", "jpeg", "png", "gif", "bmp"}:
        return f"[Изображение {len(data)} bytes]"
    # fallback printable preview
    try:
        text = data.decode("utf-8")
        if sum(1 for c in text[:200] if c.isprintable() or c in "\n\r\t") > 150:
            return text[:8000]
    except Exception:
        pass
    return f"[Бинарный файл {len(data)} bytes, base64 preview: {base64.b64encode(data[:200]).decode()}...]"


def main() -> int:
    print(f"=== Входящая корреспонденция {DOC_NUMBER} via COM ===")
    session = connect_session()
    app = session["object"]
    print("User:", session.get("current_user"))

    safe_num = DOC_NUMBER.replace('"', '""')
    doc_query = f"""ВЫБРАТЬ ПЕРВЫЕ 1
        Д.Ссылка КАК Ref,
        Д.Номер КАК Number,
        Д.Дата КАК DocDate,
        Д.Комментарий КАК Comment,
        Д.Организация.Наименование КАК Org,
        Д.Контрагент.Наименование КАК Counterparty,
        Д.Содержание КАК Content,
        Д.ТемаСлужебнойЗаписки КАК MemoSubject,
        Д.EmailОтправителяПисьма КАК EmailFrom,
        Д.EmailПолучателяПисьма КАК EmailTo,
        Д.Кому КАК MailTo,
        Д.НомерИсходящий КАК OutNumber,
        Д.ДатаИсходящая КАК OutDate,
        Д.Статус КАК Status,
        Д.ТекстHTML КАК HtmlText
        ИЗ Документ.{DOC_TYPE} КАК Д
        ГДЕ Д.Номер = "{safe_num}"
            И НЕ Д.ПометкаУдаления"""

    table = app.NewObject("Query", doc_query).Execute().Unload()
    if not table.Count():
        print("Документ не найден!")
        return 1

    row = table.Get(0)
    doc_ref = row.Ref
    print("\n--- Документ ---")
    for field in table.Columns:
        name = field.Name
        val = getattr(row, name, None)
        if hasattr(val, "Наименование"):
            val = val.Наименование
        print(f"  {name}: {safe_str(val, 500)}")

    info = resolve_ref_info(doc_ref)
    print("  metadata:", info)

    files_meta = query_attached_files(app, doc_ref, metadata_name=DOC_TYPE)
    print(f"\n--- Вложения ({len(files_meta)}) ---")

    # Also query file refs for binary read
    files_query = f"""ВЫБРАТЬ
        Ф.Ссылка КАК Ref,
        Ф.Наименование КАК Name,
        Ф.Расширение КАК Ext,
        Ф.Размер КАК Size,
        Ф.Описание КАК Description,
        Ф.ДатаСоздания КАК Created
        ИЗ Справочник.{ATTACH_CATALOG} КАК Ф
        ГДЕ Ф.ВладелецФайла = &Ref"""
    fq = app.NewObject("Query", files_query)
    fq.SetParameter("Ref", doc_ref)
    ft = fq.Execute().Unload()

    report_lines: list[str] = []
    report_lines.append(f"Документ: {DOC_NUMBER}")
    report_lines.append(f"Тип: {DOC_TYPE}")

    for i in range(ft.Count()):
        frow = ft.Get(i)
        name = safe_str(getattr(frow, "Name", ""), 300)
        ext = safe_str(getattr(frow, "Ext", ""), 20).lstrip(".")
        size = safe_str(getattr(frow, "Size", ""), 30)
        desc = safe_str(getattr(frow, "Description", ""), 500)
        created = safe_str(getattr(frow, "Created", ""), 30)
        file_ref = getattr(frow, "Ref", None)

        print(f"\n### [{i+1}] {name}.{ext} ({size} bytes)")
        if desc:
            print("  Описание:", desc)
        if created:
            print("  Создан:", created)

        data = read_file_bytes(app, file_ref)
        if data is None:
            print("  Содержимое: не удалось прочитать бинарные данные через COM")
            report_lines.append(f"\n## {name}.{ext}\n[не удалось прочитать]")
            continue

        print(f"  Прочитано: {len(data)} bytes")
        text = extract_text_from_bytes(data, ext)
        preview = text[:3000]
        print("  --- содержимое (preview) ---")
        print(preview)
        print("  --- конец preview ---")
        report_lines.append(f"\n## {name}.{ext} ({len(data)} bytes)\n{text}")

    out = ROOT / "logs" / f"incoming_{DOC_NUMBER.replace('-', '_')}_attachments.txt"
    out.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"\nПолный отчёт: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
