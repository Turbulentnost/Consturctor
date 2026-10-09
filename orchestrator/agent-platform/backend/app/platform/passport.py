"""Паспорт ИИ-агента в формате Constructor и иконка агента в стиле иконок TurboTester."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from typing import Any

from pydantic import BaseModel

# Порядок и подписи — как в паспорте Constructor (backend/app/services/agent_passport).
PASSPORT_LABELS = {
    "name": "ИИ-агент",
    "goal": "Цель",
    "trigger": "Триггер",
    "receives": "Получает",
    "checks": "Проверяет",
    "decisions": "Принимает решения",
    "can_autonomous": "Может самостоятельно",
    "needs_human_approval": "Требует подтверждения человека",
    "forbidden": "Не может",
    "result": "Результат",
}
FIELD_CHARS = 1_200


class AgentPassport(BaseModel):
    name: str = ""
    goal: str = ""
    trigger: str = ""
    receives: str = ""
    checks: str = ""
    decisions: str = ""
    can_autonomous: str = ""
    needs_human_approval: str = ""
    forbidden: str = ""
    result: str = ""

    @classmethod
    def from_payload(cls, payload: Any) -> AgentPassport:
        data = payload if isinstance(payload, dict) else {}
        values = {}
        for key in PASSPORT_LABELS:
            value = data.get(key)
            if isinstance(value, list):
                value = "; ".join(str(item).strip() for item in value if str(item).strip())
            values[key] = " ".join(str(value or "").split())[:FIELD_CHARS]
        return cls(**values)

    def missing(self) -> list[str]:
        return [key for key in PASSPORT_LABELS if not getattr(self, key).strip()]


def parse_json_object(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


# -- иконка -----------------------------------------------------------------
# Те же атрибуты корня, что у компонента Svg в desktop-electron/src/renderer/src/components/Icons.tsx:
# контур 24×24, цвет берётся из темы через currentColor.
ICON_ROOT = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
)
ICON_TAGS = {
    "path": ("d",),
    "circle": ("cx", "cy", "r"),
    "ellipse": ("cx", "cy", "rx", "ry"),
    "rect": ("x", "y", "width", "height", "rx", "ry"),
    "line": ("x1", "y1", "x2", "y2"),
    "polyline": ("points",),
    "polygon": ("points",),
}
ICON_SHAPES = 12
_VALUE = re.compile(r"^[0-9eE.,\s+\-MmLlHhVvCcSsQqTtAaZz]{1,1500}$")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def clean_icon(raw: Any) -> str:
    """Оставить из SVG только контурные фигуры с геометрией; иначе пустая строка."""
    text = str(raw or "")
    match = re.search(r"<svg\b.*?</svg>", text, re.DOTALL | re.IGNORECASE)
    if not match or "<!" in match.group(0):
        return ""
    try:
        root = ET.fromstring(match.group(0))
    except ET.ParseError:
        return ""
    shapes: list[str] = []
    for node in root.iter():
        allowed = ICON_TAGS.get(_local(node.tag))
        if allowed is None:
            continue
        attrs = {name: node.attrib[name].strip() for name in allowed if name in node.attrib}
        if not attrs or not all(_VALUE.match(value) for value in attrs.values()):
            continue
        rendered = " ".join(f'{name}="{value}"' for name, value in attrs.items())
        shapes.append(f"<{_local(node.tag)} {rendered}/>")
        if len(shapes) >= ICON_SHAPES:
            break
    return f"{ICON_ROOT}{''.join(shapes)}</svg>" if shapes else ""
