"""Allowlists and validators for 1C OData / SQL tools (from jalko platform-tool-onec)."""

from __future__ import annotations

import os
import re
from typing import Any

_SELECT_ONLY = re.compile(r"^\s*SELECT\b", re.IGNORECASE | re.DOTALL)
_FORBIDDEN_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|EXEC|EXECUTE|MERGE|TRUNCATE|CREATE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)
_FROM_RE = re.compile(r"\bFROM\s+(\[[\w.]+\]|[\w.]+)", re.IGNORECASE)
_JOIN_RE = re.compile(r"\bJOIN\s+(\[[\w.]+\]|[\w.]+)", re.IGNORECASE)

_DEFAULT_ODATA_ENTITIES = (
    "Document_ТД_ВходящаяКорреспонденция",
    "Document_ТД_ИсходящаяКорреспонденция",
    "Document_ВходящаяКорреспонденция",
    "Document_Changes",
    "Catalog_ТД_ВходящаяКорреспонденцияПрисоединенныеФайлы",
    "Catalog_КонтрагентыForMail",
    "Catalog_ПодразделенияForMail",
    "Catalog_ТомаХраненияФайлов",
    "BusinessProcess_Задание",
    "Task_ЗадачаИсполнителя",
    "InformationRegister_СведенияОФайлах",
)

_DEFAULT_SQL_TABLES = (
    "dbo.v8users",
    "v8users",
)


def _split_csv(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def odata_entity_allowlist(raw: str = "") -> set[str]:
    source = (raw or os.environ.get("ONEC_ODATA_ENTITY_ALLOWLIST") or "").strip()
    if not source:
        return set(_DEFAULT_ODATA_ENTITIES)
    return set(_split_csv(source))


def sql_table_allowlist(raw: str = "") -> set[str]:
    source = (raw or os.environ.get("ONEC_SQL_ALLOWLIST") or "").strip()
    if not source:
        return set(_DEFAULT_SQL_TABLES)
    return set(_split_csv(source))


def normalize_table_name(name: str) -> str:
    name = name.strip().strip("[]")
    if "." not in name:
        return f"dbo.{name}"
    return name


def extract_sql_tables(sql: str) -> set[str]:
    tables: set[str] = set()
    for pattern in (_FROM_RE, _JOIN_RE):
        for match in pattern.finditer(sql):
            tables.add(normalize_table_name(match.group(1)))
    return tables


def validate_sql_query(sql: str, *, allowlist: set[str] | None = None) -> str:
    query = sql.strip()
    if not query:
        raise ValueError("sql required")
    if not _SELECT_ONLY.match(query) or _FORBIDDEN_SQL.search(query):
        raise ValueError("Only read-only SELECT queries are allowed")
    allowed = allowlist or sql_table_allowlist()
    allowed_norm = {normalize_table_name(item) for item in allowed}
    tables = extract_sql_tables(query)
    if not tables:
        return query
    unknown = sorted(table for table in tables if table not in allowed_norm)
    if unknown:
        raise ValueError(f"SQL table not allowed: {', '.join(unknown)}")
    return query


def normalize_entity_name(entity: str) -> str:
    return entity.strip().lstrip("/").split("?", 1)[0]


def validate_odata_entity(entity: str, *, allowlist: set[str] | None = None) -> str:
    normalized = normalize_entity_name(entity)
    if not normalized:
        raise ValueError("entity required")
    allowed = allowlist or odata_entity_allowlist()
    if normalized not in allowed:
        raise ValueError(f"OData entity not allowed: {normalized}")
    return normalized


def validate_odata_path(path: str, *, allowlist: set[str] | None = None) -> str:
    cleaned = path.strip().lstrip("/")
    if not cleaned:
        raise ValueError("path required")
    head = cleaned.split("?", 1)[0]
    entity_head = head.split("(", 1)[0] if "(" in head else head
    validate_odata_entity(entity_head, allowlist=allowlist)
    return cleaned


def stub_odata_rows(entity: str, top: int) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for index in range(1, top + 1):
        rows.append(
            {
                "Ref_Key": f"00000000-0000-0000-0000-{index:012d}",
                "Number": f"STUB-{index:04d}",
                "Date": "2026-01-01T12:00:00",
                "Description": f"Stub record for {entity} #{index}",
                "Subject": f"Stub {entity}",
            }
        )
    return {
        "summary": f"stub: {len(rows)} записей ({entity})",
        "entity": entity,
        "count": len(rows),
        "value": rows,
        "source": "stub",
    }
