"""Fill incoming CSV themes and bodies from Outlook messages."""

from __future__ import annotations

import csv
import re
import sys
from collections import defaultdict

import win32com.client

SRC = r"c:\Users\mdj\Desktop\конструктор\входящие_2000.csv"
OUT = r"c:\Users\mdj\Desktop\конструктор\входящие_вложения.csv"
SCAN_LIMIT = 40000
_SPACE = re.compile(r"\s+")
_PREFIX = re.compile(r"^(re|fw|fwd|ответ|пересл)\s*:\s*", re.I)


def _norm(value: str) -> str:
    text = _SPACE.sub(" ", (value or "").replace("\xa0", " ")).strip().lower()
    while True:
        cleaned = _PREFIX.sub("", text).strip()
        if cleaned == text:
            return text
        text = cleaned


def _largest_mail_folder(namespace):
    best = None
    best_count = -1
    for store_index in range(1, int(namespace.Stores.Count) + 1):
        root = namespace.Stores.Item(store_index).GetRootFolder()
        for folder_index in range(1, int(root.Folders.Count) + 1):
            folder = root.Folders.Item(folder_index)
            try:
                count = int(folder.Items.Count)
            except Exception:
                continue
            if count > best_count:
                best = folder
                best_count = count
    if best is None:
        raise RuntimeError("В Outlook нет почтовых папок")
    return best, best_count


def _body(message) -> str:
    text = str(getattr(message, "Body", "") or "").strip()
    if text:
        return text
    html = str(getattr(message, "HTMLBody", "") or "")
    if "<" in html and ">" in html:
        html = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
        html = re.sub(r"<[^>]+>", " ", html)
    return _SPACE.sub(" ", html).strip()


def main() -> int:
    with open(SRC, encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))
    pending: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        key = _norm(row.get("тема") or "")
        if key:
            pending[key].append(index)
    need = sum(len(indexes) for indexes in pending.values())
    print(f"rows={len(rows)} subjects={len(pending)} need={need}", flush=True)

    outlook = win32com.client.Dispatch("Outlook.Application")
    namespace = outlook.GetNamespace("MAPI")
    folder, folder_count = _largest_mail_folder(namespace)
    print(f"folder_count={folder_count}", flush=True)
    items = folder.Items
    items.Sort("[ReceivedTime]", True)

    found = 0
    scanned = 0
    for message in items:
        scanned += 1
        if scanned > SCAN_LIMIT or found >= need:
            break
        try:
            if getattr(message, "Class", 0) != 43:
                continue
            key = _norm(str(getattr(message, "Subject", "") or ""))
            indexes = pending.get(key)
            if not indexes:
                continue
            body = _body(message)
            subject = str(getattr(message, "Subject", "") or "").strip()
            if not body or not subject:
                continue
            index = indexes.pop(0)
            if not indexes:
                pending.pop(key, None)
            rows[index]["тема"] = subject
            rows[index]["содержимое"] = body
            sender = str(getattr(message, "SenderName", "") or "").strip()
            if sender:
                rows[index]["отправитель"] = sender
            found += 1
        except Exception:
            continue
        if scanned % 500 == 0:
            print(f"scanned={scanned} found={found}", flush=True)

    with open(OUT, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["Отдел", "отправитель", "тема", "содержимое"],
            delimiter=";",
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"done scanned={scanned} found={found} rows={len(rows)}", flush=True)
    return 0 if found else 1


if __name__ == "__main__":
    sys.exit(main())
