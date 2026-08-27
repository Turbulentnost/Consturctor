from __future__ import annotations

import ast
import json
import logging
import re
from typing import Any

from app.clients import cursor as cursor_client
from app.clients.cursor import CursorAgentError
from app.config import settings
from app.schemas.regulation import (
    FragmentEntityTag,
    RegulationEntityLegendItem,
    RegulationFragment,
    RegulationParseResult,
)
from app.services.regulation.entity_tags import legend_from_fragments, normalize_entity_key
from app.services.regulation.full_text import compose_regulation_text

logger = logging.getLogger(__name__)

_KIND = {"role", "process"}


def annotate_parse_result_with_cursor(
    result: RegulationParseResult,
    *,
    position: str,
    department: str = "",
) -> RegulationParseResult:
    """Replace heuristic entity tags with Cursor SDK attribution."""
    if not result.fragments:
        return result
    try:
        payload = _extract_entities(result, position=position.strip(), department=department.strip())
        tagged, legend = apply_entity_payload(result.fragments, payload, position=position)
    except CursorAgentError as exc:
        logger.warning("Cursor entity tagging failed: %s", exc)
        return result
    except Exception:
        logger.exception("Cursor entity tagging crashed")
        return result
    if not legend and not any(item.entities for item in tagged):
        logger.info("Cursor entity tagging returned no assignments, keep heuristic tags")
        return result
    return result.model_copy(update={"fragments": tagged, "entityLegend": legend})


def apply_entity_payload(
    fragments: list[RegulationFragment],
    payload: dict[str, Any],
    *,
    position: str = "",
) -> tuple[list[RegulationFragment], list[RegulationEntityLegendItem]]:
    catalog = _catalog_from_payload(payload, position=position)
    assigned: dict[str, list[FragmentEntityTag]] = {item.fragmentId: [] for item in fragments}
    known = {item.fragmentId for item in fragments}

    for row in payload.get("assignments") or []:
        if not isinstance(row, dict):
            continue
        fragment_id = str(row.get("fragmentId") or row.get("fragment_id") or "").strip()
        if fragment_id not in known:
            continue
        entity_ids = row.get("entityIds") or row.get("entity_ids") or []
        if not isinstance(entity_ids, list):
            entity_ids = [entity_ids] if entity_ids else []
        if not entity_ids and row.get("entityId"):
            entity_ids = [row.get("entityId")]
        seen: set[str] = set()
        tags: list[FragmentEntityTag] = []
        for raw_id in entity_ids:
            tag = catalog.get(str(raw_id or "").strip())
            if tag is None or tag.entityId in seen:
                continue
            seen.add(tag.entityId)
            tags.append(tag)
        assigned[fragment_id] = tags

    tagged = [
        fragment.model_copy(update={"entities": assigned.get(fragment.fragmentId) or []})
        for fragment in fragments
    ]
    legend = legend_from_fragments(tagged)
    return tagged, _prefer_user_role(legend, position)


def _extract_entities(
    result: RegulationParseResult,
    *,
    position: str,
    department: str,
) -> dict[str, Any]:
    prompt = _build_prompt(result, position=position, department=department)
    created = cursor_client.create_agent(
        prompt=prompt,
        model_id=settings.cursor_regulation_model,
        name="Разметка блоков по должностям",
        mode="agent",
        model_params=[{"id": "fast", "value": "true"}],
    )
    agent = created.get("agent") if isinstance(created.get("agent"), dict) else {}
    run = created.get("run") if isinstance(created.get("run"), dict) else {}
    agent_id = str(agent.get("id") or "")
    run_id = str(run.get("id") or "")
    if not agent_id or not run_id:
        raise CursorAgentError("Cursor API ne vernul agent/run id")
    final = cursor_client.wait_for_run(agent_id, run_id)
    parsed = _parse_agent_response(str(final.get("result") or ""))
    if not parsed:
        raise CursorAgentError("Cursor Agent vernul pustoy otvet razmetki")
    return parsed


def _build_prompt(result: RegulationParseResult, *, position: str, department: str) -> str:
    document_text = compose_regulation_text(result)
    who = position or "должность пользователя неизвестна"
    dept = department or "не указано"
    return (
        "Ты Cursor Agent. Разметь распознанный регламент: какой фрагмент относится "
        "к какой должности или к какому процессу.\n"
        f"Должность текущего пользователя: «{who}». Подразделение: «{dept}».\n"
        "Это якорь: сначала найди функции и обязанности именно этой должности "
        "и её явных алиасов в тексте (например «Помощник ПСД», сокращения, "
        "«помощник председателя»). Не путай её с ПСД, СД, секретарём РК "
        "или другими ролями только из-за соседних слов.\n"
        "Не помечай как должность заголовок документа, содержание, колонтитул, "
        "версию и разделы вроде «Заседания Совета директоров», если там нет "
        "исполнителя-должности.\n"
        "Должность — это роль-исполнитель (кто делает). Процесс — этап/порядок работ, "
        "если исполнитель не назван.\n"
        "Верни строго JSON без markdown:\n"
        "{\n"
        '  "entities": [\n'
        "    {\n"
        '      "entityId": "role:user",\n'
        '      "kind": "role",\n'
        f'      "title": "{who}",\n'
        '      "shortTitle": "короткое имя"\n'
        "    }\n"
        "  ],\n"
        '  "assignments": [\n'
        '    {"fragmentId": "id-из-документа", "entityIds": ["role:user"]}\n'
        "  ]\n"
        "}\n"
        "Правила:\n"
        "- fragmentId бери только из полей fragmentId документа.\n"
        "- Один фрагмент может иметь 0 или несколько entityIds.\n"
        f"- Для функций пользователя в title сущности ставь «{who}».\n"
        "- Другие должности добавляй отдельными role, если они явно исполнители блока.\n"
        "- Если блок общий/вводный и не закреплён за ролью — не назначай entityIds.\n\n"
        f"{document_text}"
    )


def _catalog_from_payload(payload: dict[str, Any], *, position: str) -> dict[str, FragmentEntityTag]:
    catalog: dict[str, FragmentEntityTag] = {}
    for raw in payload.get("entities") or []:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or "").strip().casefold()
        if kind not in _KIND:
            continue
        title = str(raw.get("title") or "").strip()
        if not title:
            continue
        entity_id = str(raw.get("entityId") or raw.get("id") or "").strip()
        if not entity_id:
            entity_id = f"{kind}:{normalize_entity_key(title)}"
        short = str(raw.get("shortTitle") or raw.get("short_title") or "").strip() or title
        tag = FragmentEntityTag(
            entityId=entity_id,
            kind=kind,  # type: ignore[arg-type]
            title=title,
            shortTitle=short[:80],
        )
        catalog[entity_id] = tag
        catalog[normalize_entity_key(title)] = tag
    if position and not any(_same_role(item.title, position) for item in catalog.values() if item.kind == "role"):
        tag = FragmentEntityTag(
            entityId=f"role:{normalize_entity_key(position)}",
            kind="role",
            title=position,
            shortTitle=position,
        )
        catalog[tag.entityId] = tag
    return catalog


def _prefer_user_role(
    legend: list[RegulationEntityLegendItem],
    position: str,
) -> list[RegulationEntityLegendItem]:
    if not position:
        return legend
    mine = [item for item in legend if item.kind == "role" and _same_role(item.title, position)]
    rest = [item for item in legend if item not in mine]
    return mine + rest


def _same_role(left: str, right: str) -> bool:
    a = normalize_entity_key(left)
    b = normalize_entity_key(right)
    if not a or not b:
        return False
    return a == b or a in b or b in a


def _parse_agent_response(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    for candidate in (text,):
        parsed = _try_object(candidate)
        if parsed:
            return parsed
    match = re.search(r"\{.*\}", text, flags=re.S)
    if match:
        parsed = _try_object(match.group(0))
        if parsed:
            return parsed
    return {}


def _try_object(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        try:
            parsed = ast.literal_eval(text)
            return parsed if isinstance(parsed, dict) else {}
        except (SyntaxError, ValueError):
            return {}
