"""
Сериализация/разбор внутреннего формата 1С (ЗначениеВСтрокуВнутр).

Нужен HTTP-сервису ДО: тело POST — массив УИД или структура,
ответ — ТаблицаЗначений.
"""

from __future__ import annotations

import re
from typing import Any

ARRAY_TYPE_ID = "51e7a0d2-530b-11d4-b98a-008048da3034"
STRUCTURE_TYPE_ID = "4238019d-7e49-4fc9-91db-b6b951d5cf8e"
VALUE_TABLE_TYPE_ID = "acf6192e-81ca-46ef-93a6-5a6968b78663"


def string_to_internal(value: str) -> str:
    escaped = value.replace('"', '""')
    return f'{{"S","{escaped}"}}'


def array_of_strings_to_internal(values: list[str]) -> str:
    items = ",".join(string_to_internal(item) for item in values)
    return f'{{"#",{ARRAY_TYPE_ID},{{1,{items}}}}}'


def _value_to_internal(value: Any) -> str:
    if isinstance(value, bool):
        return f'{{"B",{1 if value else 0}}}'
    if isinstance(value, int):
        return f'{{"N",{value}}}'
    if isinstance(value, float):
        return f'{{"N",{value}}}'
    return string_to_internal(str(value))


def structure_to_internal(fields: dict[str, Any]) -> str:
    if not fields:
        return f'{{"#",{STRUCTURE_TYPE_ID},{{0}}}}'
    pairs = []
    for key, value in fields.items():
        safe_key = str(key).replace('"', '""')
        pairs.append(f'{{{{"S","{safe_key}"}},{_value_to_internal(value)}}}')
    joined = ",".join(pairs)
    return f'{{"#",{STRUCTURE_TYPE_ID},{{{len(fields)},{joined}}}}}'


def _split_top_level_params(body: str) -> list[str]:
    body = body.strip()
    if not body.startswith("{") or not body.endswith("}"):
        return [body]
    inner = body[1:-1]
    parts: list[str] = []
    depth = 0
    start = 0
    in_string = False
    i = 0
    while i < len(inner):
        ch = inner[i]
        if ch == '"':
            if in_string and i + 1 < len(inner) and inner[i + 1] == '"':
                i += 2
                continue
            in_string = not in_string
        elif not in_string:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            elif ch == "," and depth == 0:
                parts.append(inner[start:i].strip())
                start = i + 1
        i += 1
    parts.append(inner[start:].strip())
    return parts


def parse_primitive(token: str) -> Any:
    token = token.strip()
    if token in ('{"U"}', '{"L"}'):
        return None
    match = re.fullmatch(r'\{"([NSBD])",([^}]*)\}', token)
    if not match:
        return token
    kind, raw = match.group(1), match.group(2).strip()
    if kind == "S":
        return raw.strip('"').replace('""', '"')
    if kind == "N":
        return float(raw) if "." in raw else int(raw)
    if kind == "B":
        return bool(int(raw))
    if kind == "D":
        text = raw.strip('"')
        if len(text) == 14 and text.isdigit():
            return (
                f"{text[0:4]}-{text[4:6]}-{text[6:8]} "
                f"{text[8:10]}:{text[10:12]}:{text[12:14]}"
            )
        return text
    return token


def parse_value_table(body: str) -> list[dict[str, Any]]:
    columns = re.findall(
        r'\{\d+,\s*"([^"]+)"\s*,\s*\{"Pattern"',
        body,
        flags=re.DOTALL,
    )
    if not columns:
        columns = [
            name for _, name in re.findall(r'\{(\d+),"([^"]+)",\{""\},"",\d+\}', body)
        ]

    rows: list[dict[str, Any]] = []
    for cells_raw in re.findall(
        r'\{2,0,\d+,\s*((?:\{"[NSBUD]",[^}]*\},?\s*)+),0\}',
        body,
    ):
        cells = re.findall(r'\{"[NSBUDL]",[^}]*\}', cells_raw)
        record: dict[str, Any] = {}
        for index, column in enumerate(columns):
            if index < len(cells):
                record[column] = parse_primitive(cells[index])
        if record:
            rows.append(record)
    return rows


def from_internal_string(value: str) -> Any:
    text = value.strip().lstrip("\ufeff")
    if VALUE_TABLE_TYPE_ID in text and text.startswith('{"#",'):
        return parse_value_table(text)
    if text.startswith('{"#",') and ARRAY_TYPE_ID in text:
        parts = _split_top_level_params(text)
        if len(parts) >= 3:
            content = parts[2]
            if content.startswith("{") and content.endswith("}"):
                inner_parts = _split_top_level_params(content)
                return [parse_primitive(part) for part in inner_parts[1:]]
    return text
