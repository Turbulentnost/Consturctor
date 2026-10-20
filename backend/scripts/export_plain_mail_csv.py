"""Export plain text of inbox messages that have no file attachments."""

from __future__ import annotations

import csv
import re
import sys

import win32com.client

TARGET = 1000
SCAN_LIMIT = 20000
OUT = r"c:\Users\mdj\Desktop\конструктор\файл.csv"
_SIGNATURE_IMAGE = re.compile(r"image\d+\.(png|jpe?g|gif|bmp)$", re.I)


def _real_attachment_count(message) -> int:
    try:
        attachments = message.Attachments
        count = int(attachments.Count or 0)
    except Exception:
        return 0
    real = 0
    for index in range(1, count + 1):
        try:
            item = attachments.Item(index)
            name = str(getattr(item, "FileName", "") or "")
            att_type = int(getattr(item, "Type", 1) or 1)
            if att_type != 1 or not name:
                continue
            if _SIGNATURE_IMAGE.match(name):
                continue
            real += 1
        except Exception:
            continue
    return real


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


def main() -> int:
    outlook = win32com.client.Dispatch("Outlook.Application")
    namespace = outlook.GetNamespace("MAPI")
    inbox, folder_count = _largest_mail_folder(namespace)
    print(f"folder_count={folder_count}", flush=True)
    items = inbox.Items
    items.Sort("[ReceivedTime]", True)

    written = 0
    scanned = 0
    with open(OUT, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["текст"])
        for message in items:
            scanned += 1
            if scanned > SCAN_LIMIT or written >= TARGET:
                break
            try:
                if getattr(message, "Class", 0) != 43:
                    continue
                if _real_attachment_count(message) > 0:
                    continue
                text = str(getattr(message, "Body", "") or "").strip()
                if not text:
                    continue
                writer.writerow([text])
                written += 1
                if written % 100 == 0:
                    print(f"written={written} scanned={scanned}", flush=True)
            except Exception:
                continue
    print(f"done written={written} scanned={scanned}", flush=True)
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
