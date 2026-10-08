"""Сборка списка «сотрудник → опубликованные агенты» из строк workflows/users.

Правило публикации повторяет Constructor:
- admin/common.py workflow_published: агент не удалён и (local_run.published или phase == done);
- agent_library._is_published_row: ещё status published/active/ready;
- agent_library._is_catalog_workflow: черновики (kind=draft, unformed) не агенты.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, Literal
from urllib.parse import quote

from pydantic import BaseModel, Field

_TRUE = {"true", "1", "yes"}
_PUBLISHED_STATUSES = {"published", "active", "ready"}
_DESCRIPTION_LIMIT = 220
_TOOLS_LIMIT = 12


class ConstructorAgent(BaseModel):
    id: str
    title: str
    description: str = ""
    status: Literal["active", "paused"] = "active"
    tools: list[str] = Field(default_factory=list)
    trigger_summary: str = ""
    updated_at: str | None = None


class AgentDetail(BaseModel):
    id: str
    title: str
    name: str = ""
    description: str = ""
    prompt: str = ""
    example_run: str = ""
    chain: str = ""
    steps: list[str] = Field(default_factory=list)
    status: Literal["active", "paused"] = "active"
    tools: list[str] = Field(default_factory=list)
    trigger_summary: str = ""
    owner_fio: str = ""
    owner_position: str = ""
    updated_at: str | None = None


class AgentOwner(BaseModel):
    id: str
    fio: str
    position: str = ""
    department: str = ""
    avatar_url: str | None = None
    agents: list[ConstructorAgent] = Field(default_factory=list)


def _flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in _TRUE


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _block(value: Any) -> str:
    """Текст с абзацами: лишние пробелы в строке убираются, переносы остаются."""
    raw = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = [" ".join(line.split()) for line in raw.split("\n")]
    collapsed: list[str] = []
    blank = False
    for line in lines:
        if not line:
            if blank:
                continue
            blank = True
            collapsed.append("")
            continue
        blank = False
        collapsed.append(line)
    return "\n".join(collapsed).strip()


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value else None


def is_published(row: Mapping[str, Any]) -> bool:
    phase = _text(row.get("phase")).casefold()
    if phase == "deleted" or _flag(row.get("deleted")):
        return False
    if _text(row.get("kind")).casefold() == "draft" or _flag(row.get("unformed")):
        return False
    if _flag(row.get("published")) or phase == "done":
        return True
    return _text(row.get("status")).casefold() in _PUBLISHED_STATUSES


def _name_list(raw: Any, limit: int = 40) -> list[str]:
    if not isinstance(raw, list):
        return []
    names: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            text = _text(item.get("name") or item.get("tool"))
        else:
            text = _text(item)
        if text and text not in names:
            names.append(text)
        if len(names) >= limit:
            break
    return names


def _step_lines(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    lines: list[str] = []
    for index, step in enumerate(raw, start=1):
        if isinstance(step, dict):
            tool = _text(step.get("tool"))
            label = _text(step.get("title") or step.get("name") or step.get("goal"))
            text = f"{tool} — {label}" if tool and label else tool or label
        else:
            text = _text(step)
        if text:
            lines.append(f"{index}. {text}")
    return lines


def _tools(row: Mapping[str, Any]) -> list[str]:
    for key in ("tools", "runtime_tools"):
        raw = row.get(key)
        if isinstance(raw, list):
            return [_text(item) for item in raw if _text(item)][:_TOOLS_LIMIT]
    return []


def agent_detail(row: Mapping[str, Any]) -> AgentDetail | None:
    """Карточка одного агента. None, если запись не считается опубликованной."""
    if not is_published(row):
        return None
    description = ""
    for key in ("plan_goal", "run_expected", "plan_expected", "draft_goal", "document_name", "notes"):
        description = _block(row.get(key))
        if description:
            break
    steps = _step_lines(row.get("run_steps")) or _step_lines(row.get("plan_steps"))
    tools = (
        _name_list(row.get("playbook_tools"))
        or _name_list(row.get("plan_playbook_tools"))
        or _tools(row)
    )
    return AgentDetail(
        id=_text(row.get("id")),
        title=_text(row.get("plan_title")) or _text(row.get("title")) or "ИИ-агент",
        name=_text(row.get("title")),
        description=description,
        prompt=_block(row.get("run_instructions")) or _block(row.get("plan_instructions")),
        example_run=_block(row.get("run_example")) or _block(row.get("plan_example")),
        chain=_block(row.get("run_chain")) or _block(row.get("plan_chain")),
        steps=steps,
        status="paused" if _flag(row.get("paused")) else "active",
        tools=tools,
        trigger_summary=_text(row.get("trigger_summary")),
        owner_fio=_text(row.get("fio")),
        owner_position=_text(row.get("position")) or _text(row.get("department")),
        updated_at=_iso(row.get("updated_at")),
    )


def _description(row: Mapping[str, Any]) -> str:
    for key in ("plan_goal", "draft_goal", "document_name", "notes"):
        value = _text(row.get(key))
        if value:
            return value[:_DESCRIPTION_LIMIT]
    return ""


def _avatar_url(row: Mapping[str, Any]) -> str | None:
    if not _text(row.get("avatar_path")):
        return None
    url = f"/api/v1/constructor/users/{quote(str(row['user_id']), safe='')}/avatar"
    stamp = row.get("user_updated_at")
    if isinstance(stamp, datetime):
        url += f"?v={int(stamp.timestamp())}"
    return url


def build_owners(rows: Iterable[Mapping[str, Any]]) -> list[AgentOwner]:
    owners: dict[str, AgentOwner] = {}
    for row in rows:
        if not is_published(row):
            continue
        user_id = _text(row.get("user_id"))
        if not user_id:
            continue
        owner = owners.get(user_id)
        if owner is None:
            owner = AgentOwner(
                id=user_id,
                fio=_text(row.get("fio")) or "Без имени",
                position=_text(row.get("position")),
                department=_text(row.get("department")),
                avatar_url=_avatar_url(row),
            )
            owners[user_id] = owner
        owner.agents.append(
            ConstructorAgent(
                id=_text(row.get("id")),
                title=_text(row.get("plan_title")) or _text(row.get("title")) or "ИИ-агент",
                description=_description(row),
                status="paused" if _flag(row.get("paused")) else "active",
                tools=_tools(row),
                trigger_summary=_text(row.get("trigger_summary")),
                updated_at=_iso(row.get("updated_at")),
            )
        )
    for owner in owners.values():
        owner.agents.sort(key=lambda agent: agent.updated_at or "", reverse=True)
    return sorted(owners.values(), key=lambda owner: owner.fio.casefold())
