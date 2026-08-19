"""Helpers for user FIO in filenames and labels."""

from __future__ import annotations

import re


def fio_initials_slug(fio: str, *, fallback: str = "user") -> str:
    """Short slug from FIO for filenames, e.g. «Жалыбин Максим Дмитриевич» → «ZhMD»."""
    parts = [p.strip() for p in re.split(r"\s+", (fio or "").strip()) if p.strip()]
    if not parts:
        return fallback
    if len(parts) >= 3:
        letters = "".join(p[0] for p in parts[:3])
    elif len(parts) == 2:
        letters = parts[0][0] + parts[1][0]
    else:
        letters = parts[0][:2]
    slug = re.sub(r"[^\w\-]+", "", letters, flags=re.UNICODE)
    return (slug[:12] or fallback).upper()
