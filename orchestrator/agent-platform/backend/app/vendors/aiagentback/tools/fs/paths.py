from __future__ import annotations

import os
import re
from pathlib import Path


def normalize_path_str(raw: str) -> str:
    r"""Нормализует путь: `/` → `\`, схлопывает лишние `\`, сохраняет UNC `\\`."""
    text = (raw or "").strip().replace("/", "\\")
    if not text:
        return ""
    is_unc = text.startswith("\\\\")
    # Не обрезаем корень вида \\server или C:\
    if text in {"\\", "\\\\"}:
        return "\\\\" if is_unc else "\\"
    if re.fullmatch(r"[A-Za-z]:\\?", text):
        return text[:2] + "\\"
    parts = [p for p in text.split("\\") if p]
    if is_unc:
        if not parts:
            return "\\\\"
        return "\\\\" + "\\".join(parts)
    if re.match(r"^[A-Za-z]:", text) and parts:
        # parts[0] is like 'C:' when split kept drive with colon? 
        # 'C:\Temp\x'.split('\\') -> ['C:', 'Temp', 'x']
        drive = parts[0]
        rest = parts[1:]
        if not rest:
            return drive + "\\"
        return drive + "\\" + "\\".join(rest)
    return "\\".join(parts)


def path_key(raw: str) -> str:
    """Ключ для сравнения путей (casefold на Windows)."""
    normalized = normalize_path_str(raw)
    if os.name == "nt":
        return normalized.casefold()
    return normalized


def collapse_segments(segments: list[str]) -> list[str]:
    """Убирает `.` и обрабатывает `..` (не даёт подняться выше корня списка)."""
    out: list[str] = []
    for segment in segments:
        if not segment or segment == ".":
            continue
        if segment == "..":
            if out:
                out.pop()
            continue
        out.append(segment)
    return out


def split_segments(raw: str) -> tuple[str | None, list[str]]:
    """Возвращает (абсолютный префикс корня или None, сегменты пути)."""
    text = normalize_path_str(raw)
    if not text:
        return None, []

    if text.startswith("\\\\"):
        parts = [p for p in text.split("\\") if p]
        if len(parts) < 2:
            return text if text.startswith("\\\\") else None, []
        root = "\\\\" + "\\".join(parts[:2])
        return root, collapse_segments(parts[2:])

    if re.match(r"^[A-Za-z]:\\", text) or re.match(r"^[A-Za-z]:$", text):
        drive = text[:2] + "\\"
        rest = text[2:].lstrip("\\")
        return drive, collapse_segments([p for p in rest.split("\\") if p])

    return None, collapse_segments([p for p in text.split("\\") if p])


def is_absolute_path(raw: str) -> bool:
    prefix, _ = split_segments(raw)
    return prefix is not None


def join_root_segments(root: str, segments: list[str]) -> str:
    root_norm = normalize_path_str(root)
    clean = collapse_segments(list(segments))
    if not clean:
        return root_norm.rstrip("\\") if not root_norm.endswith(":\\") else root_norm
    if root_norm.endswith("\\"):
        return root_norm + "\\".join(clean)
    return root_norm + "\\" + "\\".join(clean)


def canonicalize_path_str(raw: str) -> str:
    """Нормализует путь и схлопывает `.` / `..` в сегментах."""
    prefix, segments = split_segments(raw)
    if prefix is None:
        clean = collapse_segments(segments)
        return "\\".join(clean)
    return join_root_segments(prefix, segments)


def parse_allowed_roots(roots: list[str] | tuple[str, ...] | str | None) -> list[str]:
    if roots is None:
        return []
    if isinstance(roots, str):
        items = [item.strip() for item in roots.split(",") if item.strip()]
    else:
        items = [str(item).strip() for item in roots if str(item).strip()]
    return [normalize_path_str(item) for item in items]


def path_under_root(candidate: str, root: str) -> bool:
    """Проверяет, что candidate лежит внутри root (после схлопывания `..`)."""
    cand_key = path_key(canonicalize_path_str(candidate))
    root_key = path_key(canonicalize_path_str(root))
    if not cand_key or not root_key:
        return False
    if cand_key == root_key:
        return True
    root_prefix = root_key if root_key.endswith("\\") else root_key + "\\"
    return cand_key.startswith(root_prefix)


def ensure_under_allowed_roots(candidate: str, allowed_roots: list[str]) -> str:
    """Возвращает канонический путь или бросает ValueError."""
    normalized = canonicalize_path_str(candidate)
    if not normalized:
        raise ValueError("Путь не задан")
    for root in allowed_roots:
        if path_under_root(normalized, root):
            return normalized
    raise ValueError(
        f"Путь вне разрешённых корней: {normalized}. "
        f"Разрешено: {', '.join(allowed_roots) or '(пусто)'}"
    )


def to_path(raw: str) -> Path:
    return Path(canonicalize_path_str(raw) or normalize_path_str(raw))


def name_similarity(query: str, candidate: str) -> float:
    """Сходство имён: SequenceMatcher + бонус за prefix/contains."""
    from difflib import SequenceMatcher

    q = (query or "").casefold().strip()
    c = (candidate or "").casefold().strip()
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0
    score = SequenceMatcher(None, q, c).ratio()
    if c.startswith(q) or q.startswith(c):
        score = min(1.0, score + 0.12)
    elif q in c or c in q:
        score = min(1.0, score + 0.08)
    return score
