"""Local snapshot of 1C ERP OData document metadata.

`onec.odata_catalog` searches this file first so the constructor does not
download live 1C $metadata on every lookup. Live OData is a fallback when
the snapshot has no match or the caller asks for refresh.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

DEFAULT_SNAPSHOT_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "odata_document_structures.json"
)

_CAMEL_RE = re.compile(
    r"[A-ZА-ЯЁ]+(?![a-zа-яё])|[A-ZА-ЯЁ][a-zа-яё]+|[0-9]+|[a-zа-яё]+"
)
_NON_ALNUM_RE = re.compile(r"[^0-9A-Za-zА-Яа-яЁё]+")

_STRUCTURE_FIELD_LIMIT = 80
_STRUCTURE_TABULAR_LIMIT = 16

_cache: dict[str, Any] | None = None
_cache_mtime_ns: int | None = None
_cache_path: str = ""


def reset_local_catalog_cache() -> None:
    global _cache, _cache_mtime_ns, _cache_path
    _cache = None
    _cache_mtime_ns = None
    _cache_path = ""


def snapshot_path(override: Path | str | None = None) -> Path:
    if override:
        return Path(override)
    try:
        from app.config import settings

        configured = getattr(settings, "odata_local_catalog_path", None)
        if configured:
            return Path(configured)
    except Exception:
        pass
    return DEFAULT_SNAPSHOT_PATH


def snapshot_available(path: Path | str | None = None) -> bool:
    return snapshot_path(path).is_file()


def _empty_index() -> dict[str, Any]:
    return {
        "path": "",
        "source": "",
        "document_count": 0,
        "entitytype_count": 0,
        "documents": {},
        "tabular_names": set(),
    }


def _read_snapshot(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise ValueError("OData snapshot must be a JSON object")
    documents = raw.get("documents")
    if not isinstance(documents, dict):
        documents = {}
    tabular_names: set[str] = set()
    cleaned: dict[str, dict[str, Any]] = {}
    for name, structure in documents.items():
        entity = str(name or "").strip()
        if not entity or not isinstance(structure, dict):
            continue
        cleaned[entity] = structure
        tabular = structure.get("tabular")
        if not isinstance(tabular, dict):
            continue
        for section in tabular.values():
            if not isinstance(section, dict):
                continue
            child = str(section.get("entity") or "").strip()
            if child:
                tabular_names.add(child)
    return {
        "path": str(path),
        "source": str(raw.get("source") or ""),
        "document_count": int(raw.get("document_count") or len(cleaned)),
        "entitytype_count": int(raw.get("entitytype_count") or 0),
        "documents": cleaned,
        "tabular_names": tabular_names,
    }


def load_snapshot(path: Path | str | None = None, *, force: bool = False) -> dict[str, Any]:
    global _cache, _cache_mtime_ns, _cache_path
    resolved = snapshot_path(path)
    key = str(resolved)
    if not resolved.is_file():
        return _empty_index()
    mtime_ns = resolved.stat().st_mtime_ns
    if (
        not force
        and _cache is not None
        and _cache_path == key
        and _cache_mtime_ns == mtime_ns
    ):
        return _cache
    index = _read_snapshot(resolved)
    _cache = index
    _cache_mtime_ns = mtime_ns
    _cache_path = key
    return index


def document_names(path: Path | str | None = None) -> list[str]:
    return sorted(load_snapshot(path)["documents"])


def extra_entity_names(path: Path | str | None = None) -> set[str]:
    index = load_snapshot(path)
    names = set(index["documents"])
    names.update(index["tabular_names"])
    return names


def snapshot_meta(path: Path | str | None = None) -> dict[str, Any]:
    index = load_snapshot(path)
    return {
        "snapshot_path": index["path"],
        "snapshot_source": index["source"],
        "snapshot_documents": index["document_count"],
        "snapshot_entitytypes": index["entitytype_count"],
    }


def get_structure(name: str, path: Path | str | None = None) -> dict[str, Any] | None:
    entity = str(name or "").strip()
    if not entity:
        return None
    documents = load_snapshot(path)["documents"]
    if entity in documents:
        return documents[entity]
    folded = entity.casefold()
    for key, structure in documents.items():
        if key.casefold() == folded:
            return structure
    return None


def compact_structure(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    fields: list[dict[str, Any]] = []
    for item in raw.get("fields") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        fields.append(
            {
                "name": name,
                "type": str(item.get("type") or ""),
                "nullable": bool(item.get("nullable", True)),
            }
        )
        if len(fields) >= _STRUCTURE_FIELD_LIMIT:
            break
    navigations: list[dict[str, str]] = []
    for item in raw.get("navigations") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        navigations.append({"name": name, "type": str(item.get("type") or "")})
    tabular: dict[str, Any] = {}
    raw_tab = raw.get("tabular")
    if isinstance(raw_tab, dict):
        for index, (section_name, section) in enumerate(raw_tab.items()):
            if index >= _STRUCTURE_TABULAR_LIMIT:
                break
            if not isinstance(section, dict):
                continue
            child = compact_structure(
                {
                    "fields": section.get("fields"),
                    "navigations": section.get("navigations"),
                }
            )
            tabular[str(section_name)] = {
                "entity": str(section.get("entity") or ""),
                **(child or {"fields": [], "navigations": []}),
            }
    return {
        "fields": fields,
        "field_names": [item["name"] for item in fields],
        "navigations": navigations,
        "tabular": tabular,
        "tabular_names": list(tabular),
    }


def tokens(text: str) -> list[str]:
    parts: list[str] = []
    for chunk in _NON_ALNUM_RE.split(str(text or "")):
        if not chunk:
            continue
        camel = _CAMEL_RE.findall(chunk)
        parts.extend(camel or [chunk])
    return [part.casefold() for part in parts if len(part) >= 2]


def compact_text(text: str) -> str:
    return _NON_ALNUM_RE.sub("", str(text or "")).casefold()


def entity_search_score(
    query: str,
    name: str,
    structure: dict[str, Any] | None = None,
) -> int:
    needle = str(query or "").strip()
    entity = str(name or "").strip()
    if not needle or not entity:
        return 0
    q = needle.casefold()
    n = entity.casefold()
    compact_q = compact_text(needle)
    compact_n = compact_text(entity)
    score = 0
    if q == n or compact_q == compact_n:
        return 1000
    if q in n:
        score += 80
    elif compact_q and compact_q in compact_n:
        score += 70
    query_tokens = tokens(needle)
    name_tokens = tokens(entity)
    if query_tokens:
        matched = 0
        for token in query_tokens:
            if token in compact_n or token in n:
                matched += 1
                continue
            if any(
                (
                    other.startswith(token) or token.startswith(other)
                )
                and min(len(token), len(other)) >= 4
                for other in name_tokens
            ):
                matched += 1
        if matched == len(query_tokens):
            score += 40 + 8 * matched
        elif matched:
            score += 8 * matched
    if score:
        return score
    if structure and query_tokens:
        haystack = compact_text(
            " ".join(
                [
                    " ".join(
                        str(item.get("name") or "")
                        for item in (structure.get("fields") or [])
                        if isinstance(item, dict)
                    ),
                    " ".join(str(key) for key in (structure.get("tabular") or {})),
                ]
            )
        )
        if haystack and all(token in haystack for token in query_tokens if len(token) >= 4):
            return 15
    return score


def search_documents(
    query: str,
    *,
    path: Path | str | None = None,
    limit: int = 40,
    search_fields: bool = False,
) -> list[dict[str, Any]]:
    needle = str(query or "").strip()
    documents = load_snapshot(path)["documents"]
    scored: list[tuple[int, str]] = []
    for name, structure in documents.items():
        payload = structure if search_fields else None
        score = entity_search_score(needle, name, payload)
        if score > 0:
            scored.append((score, name))
    scored.sort(key=lambda row: (-row[0], row[1]))
    matches: list[dict[str, Any]] = []
    for score, name in scored[: max(1, limit)]:
        structure = compact_structure(documents.get(name))
        item = {"name": name, "score": score}
        if structure:
            item.update(structure)
        matches.append(item)
    return matches
