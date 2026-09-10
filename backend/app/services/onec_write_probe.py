"""Constructor write probes: create a test 1C object, change it, remember, delete."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from app.services.erp_assignments import (
    ASSIGNMENT_ENTITY,
    PROBE_MARK,
    assignment_write_recipe,
    build_probe_topic,
    is_probe_topic,
    mark_assignment_deleted,
    probe_assignment_write,
    stub_write_probe as stub_assignment_probe,
    sweep_probe_assignments,
)
from app.services.workflow_tool_routing import WriteIntent

_MARK_FIELDS = (
    "ОЧем",
    "Description",
    "Наименование",
    "Комментарий",
    "Тема",
    "Содержание",
    "Subject",
)
_STATUS_FIELDS = ("Статус", "Status", "Состояние")
_UNSAFE_CATALOG = (
    "пользовател",
    "контрагент",
    "организац",
    "подраздел",
    "сотрудник",
    "физическ",
)
_REGISTER_PREFIXES = (
    "InformationRegister_",
    "AccumulationRegister_",
    "AccountingRegister_",
    "CalculationRegister_",
)
_TYPE_PROP_RE = re.compile(r"свойства '([^']+)'")
_FIELD_RE = re.compile(
    r"(?:реквизит|поле|свойств[оа])\s*[:«\"']?\s*([A-Za-zА-Яа-яЁё0-9_]+)",
    re.IGNORECASE,
)


class WriteProbeError(RuntimeError):
    pass


def recipe_covers_intents(existing: dict[str, Any], keys: list[str]) -> bool:
    stored = existing.get("intent_keys")
    return bool(existing.get("ok") and isinstance(stored, list) and stored == keys)


def normalize_intent_dicts(raw: Any) -> list[dict[str, str]]:
    if isinstance(raw, WriteIntent):
        return [raw.to_dict()]
    if isinstance(raw, dict):
        return [raw]
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if isinstance(item, WriteIntent):
            out.append(item.to_dict())
        elif isinstance(item, dict):
            out.append({str(key): str(value or "") for key, value in item.items()})
    return out


def _odata_get(args: dict[str, Any]) -> dict[str, Any]:
    from app.services.onec_tools import _fetch_odata_list

    return _fetch_odata_list(args)


def _odata_post(args: dict[str, Any]) -> dict[str, Any]:
    from app.services.onec_tools import _odata_post

    return _odata_post(args)


def _odata_patch(args: dict[str, Any]) -> dict[str, Any]:
    from app.services.onec_tools import _odata_patch

    return _odata_patch(args)


def _looks_like_guid(value: str) -> bool:
    text = str(value or "").strip()
    return len(text) == 36 and text.count("-") == 4


def _ref_from_write(result: dict[str, Any]) -> tuple[str, str]:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    if not data:
        data = result
    ref_key = str(
        data.get("Ref_Key") or result.get("erp_document_id") or result.get("ref_key") or ""
    ).strip()
    number = str(data.get("Number") or result.get("number") or "").strip()
    return ref_key, number


def _sample_row(entity: str) -> dict[str, Any]:
    result = _odata_get({"entity": entity, "top": 1})
    rows = [row for row in (result.get("value") or []) if isinstance(row, dict)]
    return rows[0] if rows else {}


def _pick_mark_field(sample: dict[str, Any]) -> str:
    keys = set(sample)
    for name in _MARK_FIELDS:
        if name in keys:
            return name
    for key, value in sample.items():
        if str(key).endswith(("_Key", "_Type", "_Name")):
            continue
        if key in {"Ref_Key", "Number", "DataVersion", "Posted", "DeletionMark", "Date"}:
            continue
        if isinstance(value, str):
            return str(key)
    return "Description"


def _next_status(current: str) -> str:
    key = "".join(str(current or "").casefold().split())
    if key in {"", "создано"}:
        return "ВРаботе"
    if key == "вработе":
        return "Создано"
    return "ВРаботе"


def _guess_change(
    sample: dict[str, Any],
    change: str,
    mark_field: str,
    topic: str,
) -> tuple[str, Any]:
    if change == "status":
        for name in _STATUS_FIELDS:
            if name in sample:
                return name, _next_status(str(sample.get(name) or ""))
    if change == "due":
        for key in sample:
            low = str(key).casefold()
            if "срок" in low:
                return str(key), (datetime.now() + timedelta(days=14)).strftime(
                    "%Y-%m-%dT00:00:00"
                )
    return mark_field, f"{topic} OK"


def _create_body(sample: dict[str, Any], mark_field: str, topic: str) -> dict[str, Any]:
    body: dict[str, Any] = {mark_field: topic, "DeletionMark": False, "Posted": False}
    if "Date" in sample:
        body["Date"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    for key, value in sample.items():
        if not str(key).endswith("_Type"):
            continue
        base = str(key)[: -len("_Type")]
        raw = sample.get(base)
        empty = raw in ("", None) or (isinstance(raw, str) and raw.startswith("0001-01-01"))
        if empty:
            body[str(key)] = value or "Edm.String"
            if base not in body:
                body[base] = "" if "String" in str(value or "Edm.String") else raw
    return body


def _fields_from_error(text: str) -> list[str]:
    found: list[str] = []
    found.extend(_TYPE_PROP_RE.findall(text or ""))
    found.extend(_FIELD_RE.findall(text or ""))
    return list(dict.fromkeys(found))


def _apply_error_hint(body: dict[str, Any], error: str) -> bool:
    changed = False
    low = (error or "").casefold()
    for field in _fields_from_error(error):
        if "составн" in low or "типа" in low or "type" in low:
            type_key = f"{field}_Type"
            if type_key not in body:
                body[type_key] = "Edm.String"
                changed = True
            if field not in body:
                body[field] = ""
                changed = True
            continue
        if field in body:
            continue
        if field.endswith("_Key"):
            body[field] = "00000000-0000-0000-0000-000000000000"
        elif "дат" in field.casefold() or field == "Date":
            body[field] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        else:
            body[field] = ""
        changed = True
    return changed


def mark_probe_deleted(entity: str, ref_key: str) -> None:
    if not _looks_like_guid(ref_key):
        return
    try:
        _odata_patch({"entity": entity, "ref_key": ref_key, "body": {"Posted": False}})
    except Exception:  # noqa: BLE001
        pass
    _odata_patch({"entity": entity, "ref_key": ref_key, "body": {"DeletionMark": True}})


def list_probe_rows(entity: str, mark_field: str, *, limit: int = 20) -> list[dict[str, Any]]:
    filt = f"DeletionMark eq false and substringof('{PROBE_MARK}', {mark_field})"
    result = _odata_get({"entity": entity, "top": max(1, min(limit, 50)), "filter": filt})
    return [row for row in (result.get("value") or []) if isinstance(row, dict)]


def sweep_probe_rows(entity: str, mark_field: str) -> int:
    removed = 0
    try:
        rows = list_probe_rows(entity, mark_field)
    except Exception:  # noqa: BLE001
        return 0
    for row in rows:
        topic = str(row.get(mark_field) or "")
        if not is_probe_topic(topic):
            continue
        key = str(row.get("Ref_Key") or "")
        try:
            mark_probe_deleted(entity, key)
            removed += 1
        except Exception:  # noqa: BLE001
            continue
    return removed


def _row_has_probe(row: dict[str, Any]) -> bool:
    for key, value in row.items():
        if isinstance(value, str) and is_probe_topic(value):
            return True
        if isinstance(value, str) and PROBE_MARK in value.upper().replace(" ", ""):
            return True
    return False


def _search_catalog(search: str) -> list[str]:
    from app.services.onec_tools import _odata_catalog, _stub_odata_catalog, odata_configured

    query = str(search or "").strip()
    if not query:
        return []
    handler = _odata_catalog if odata_configured() else _stub_odata_catalog
    result = handler({"search": query, "limit": 20})
    names: list[str] = []
    for key in ("documents", "other", "catalogs"):
        for name in result.get(key) or []:
            if name and name not in names:
                names.append(str(name))
    return names


def resolve_odata_entity(intent: dict[str, str]) -> str:
    from app.services.onec_security import looks_like_odata_entity

    named = str(intent.get("odata_entity") or intent.get("entity") or "").strip()
    if looks_like_odata_entity(named):
        return named
    title = str(intent.get("title") or "")
    tokens = [named] if named and named not in {"document", "odata_entity", "odata"} else []
    for word in title.replace("/", " ").split():
        clean = word.strip(" «»\"'.,;:").casefold()
        if len(clean) >= 4 and clean not in {"измен", "смен", "статус", "документ"}:
            tokens.append(word.strip(" «»\"'.,;:"))
    for token in tokens:
        found = _search_catalog(token)
        documents = [name for name in found if str(name).startswith("Document_")]
        if documents:
            return documents[0]
        if found:
            return found[0]
    return ""


def _safe_to_create(entity: str) -> str:
    name = str(entity or "")
    if any(name.startswith(prefix) for prefix in _REGISTER_PREFIXES):
        return f"Constructor does not create register test rows: {name}"
    if name.startswith("Catalog_"):
        low = name.casefold()
        if any(hint in low for hint in _UNSAFE_CATALOG):
            return f"Constructor does not create catalog test rows: {name}"
    if name.startswith(("Document_", "Catalog_", "Task_")):
        return ""
    return f"No safe create for {name or 'unknown entity'}"


def _failed(
    *,
    summary: str,
    error: str,
    cleaned: bool = True,
    test_left: bool = False,
    recipe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "cleaned": cleaned,
        "test_left": test_left,
        "source": "odata",
        "summary": summary,
        "error": error,
        "recipe": recipe or {},
    }


def probe_odata_entity_write(
    args: dict[str, Any],
    *,
    intent: dict[str, str],
) -> dict[str, Any]:
    entity = resolve_odata_entity(intent)
    if not entity:
        return _failed(
            summary="Write probe failed: entity not resolved",
            error="Ne izvestna EntitySet 1C dlya shaga zapisi",
        )
    unsafe = _safe_to_create(entity)
    if unsafe:
        return _failed(summary=f"Write probe skipped: {unsafe}", error=unsafe)
    workflow_id = str(args.get("workflow_id") or args.get("agent_id") or "").strip()
    topic = build_probe_topic(workflow_id)
    change = str(intent.get("change") or "update")
    sample = _sample_row(entity)
    mark_field = _pick_mark_field(sample)
    sweep_probe_rows(entity, mark_field)
    body = _create_body(sample, mark_field, topic)
    created_key = ""
    try:
        created: dict[str, Any] = {}
        last_error = ""
        for _attempt in range(4):
            try:
                created = _odata_post({"entity": entity, "body": body})
                last_error = ""
                break
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                if not _apply_error_hint(body, last_error):
                    raise WriteProbeError(last_error) from exc
        if last_error:
            raise WriteProbeError(last_error)
        created_key, number = _ref_from_write(created)
        if not created_key:
            raise WriteProbeError("Create ne vernul Ref_Key")
        check = _odata_get({"entity": entity, "ref_key": created_key, "top": 1})
        rows = [row for row in (check.get("value") or []) if isinstance(row, dict)]
        row = rows[0] if rows else {}
        if row and not _row_has_probe(row):
            raise WriteProbeError("Create vernul chuzhuyu kartu, ne test")
        field, value = _guess_change(sample or row, change, mark_field, topic)
        before = str((row or sample).get(field) or "")
        _odata_patch({"entity": entity, "ref_key": created_key, "body": {field: value}})
        again = _odata_get({"entity": entity, "ref_key": created_key, "top": 1})
        after_rows = [item for item in (again.get("value") or []) if isinstance(item, dict)]
        after_row = after_rows[0] if after_rows else {}
        after = str(after_row.get(field) or "")
        expected = str(value)
        if expected not in after:
            raise WriteProbeError(
                f"Pole {field} ne smenilos: zhili {before or 'pust'}, stalo {after or 'pust'}"
            )
        mark_probe_deleted(entity, created_key)
        recipe = {
            "entity": entity,
            "tool": "onec.odata_patch" if change != "create" else "onec.odata_post",
            "create": {"via": "odata_post", "mark_field": mark_field},
            "update": {"via": "odata_patch", "field": field},
            "delete": {"via": "DeletionMark"},
            "verified": [{"field": field, "from": before, "to": after}],
            "source": "odata",
        }
        return {
            "ok": True,
            "cleaned": True,
            "source": "odata",
            "summary": (
                f"Write probe ok: created {number or created_key} on {entity}, "
                f"{field} changed, deleted"
            ),
            "recipe": recipe,
            "test_number": number,
            "test_ref_key": created_key,
            "test_left": False,
            **recipe,
        }
    except Exception as exc:  # noqa: BLE001
        cleaned = False
        if created_key:
            try:
                mark_probe_deleted(entity, created_key)
                cleaned = True
            except Exception:  # noqa: BLE001
                cleaned = False
        sweep_probe_rows(entity, mark_field)
        return _failed(
            summary=f"Write probe failed: {exc}",
            error=str(exc),
            cleaned=cleaned or not created_key,
            test_left=bool(created_key) and not cleaned,
        )


def _task_comment_recipe() -> dict[str, Any]:
    return {
        "ok": True,
        "cleaned": True,
        "source": "code",
        "verified": False,
        "summary": (
            "Write recipe: comment executor task via PATCH РезультатВыполнения. "
            "Constructor does not create live Task_ZadachaIspolnitelya rows."
        ),
        "recipe": {
            "entity": "Task_ЗадачаИсполнителя",
            "tool": "onec.erp_assignments_write",
            "comment": {
                "action": "comment_task",
                "field": "РезультатВыполнения",
                "via": "odata_patch",
            },
            "delete": {"via": "none"},
            "source": "code",
        },
        "test_left": False,
    }


def _attach_recipe() -> dict[str, Any]:
    return {
        "ok": False,
        "cleaned": True,
        "source": "code",
        "summary": "Write probe skipped: onec.attach_file is NOT_IMPLEMENTED",
        "error": "onec.attach_file NOT_IMPLEMENTED",
        "recipe": {
            "entity": "file",
            "tool": "onec.attach_file",
            "create": {"via": "not_implemented"},
            "source": "code",
        },
        "test_left": False,
    }


def _group_intents(intents: list[dict[str, str]]) -> list[tuple[str, str, list[dict[str, str]]]]:
    groups: dict[tuple[str, str], list[dict[str, str]]] = {}
    order: list[tuple[str, str]] = []
    for intent in intents:
        family = str(intent.get("family") or "odata")
        entity = str(intent.get("odata_entity") or "")
        key = (family, entity if family == "odata" else family)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(intent)
    return [(key[0], key[1], groups[key]) for key in order]


def _merge_probe_results(
    results: list[dict[str, Any]],
    *,
    keys: list[str],
) -> dict[str, Any]:
    recipes = []
    for item in results:
        recipe = item.get("recipe") if isinstance(item.get("recipe"), dict) else {}
        if recipe:
            recipes.append(recipe)
    required = [item for item in results if item.get("recipe", {}).get("tool") != "onec.attach_file"]
    if not required:
        required = results
    ok = all(item.get("ok") for item in required) if required else False
    cleaned = all(item.get("cleaned", True) for item in results) if results else True
    left = any(item.get("test_left") for item in results)
    primary = next((item for item in results if item.get("ok") and item.get("recipe")), None)
    if primary is None:
        primary = results[0] if results else {}
    errors = [
        str(item.get("error") or item.get("summary") or "")
        for item in results
        if not item.get("ok") and item.get("recipe", {}).get("tool") != "onec.attach_file"
    ]
    summaries = [str(item.get("summary") or "") for item in results if item.get("summary")]
    merged = {
        "ok": ok,
        "cleaned": cleaned,
        "test_left": left,
        "source": str(primary.get("source") or "odata"),
        "summary": "; ".join(item for item in summaries if item) or "Write probe empty",
        "error": errors[0] if errors else None,
        "recipe": primary.get("recipe") or {},
        "recipes": recipes,
        "probes": results,
        "intent_keys": keys,
        "test_number": primary.get("test_number") or "",
        "test_ref_key": primary.get("test_ref_key") or "",
    }
    return merged


def stub_write_probe(args: dict[str, Any], **_: Any) -> dict[str, Any]:
    intents = normalize_intent_dicts(args.get("intents"))
    if not intents or all(str(item.get("family") or "assignment") == "assignment" for item in intents):
        result = stub_assignment_probe(args)
        recipe = result.get("recipe") or assignment_write_recipe(source="stub")
        keys = [
            str(item.get("key") or f"assignment:{item.get('operation')}:{item.get('change')}:")
            for item in intents
        ] or ["assignment:update:status:" + ASSIGNMENT_ENTITY]
        result["recipes"] = [recipe]
        result["intent_keys"] = keys
        result["probes"] = [result]
        return result
    recipes = []
    probes = []
    for intent in intents:
        family = str(intent.get("family") or "odata")
        if family == "file":
            item = _attach_recipe()
        elif family == "task":
            item = _task_comment_recipe()
        elif family == "assignment":
            item = stub_assignment_probe(args)
        else:
            entity = str(intent.get("odata_entity") or "Document_ТД_Протокол")
            item = {
                "ok": True,
                "cleaned": True,
                "source": "stub",
                "summary": f"stub write probe: {entity}",
                "recipe": {
                    "entity": entity,
                    "tool": "onec.odata_patch",
                    "create": {"via": "odata_post", "mark_field": "Description"},
                    "update": {"via": "odata_patch", "field": "Description"},
                    "delete": {"via": "DeletionMark"},
                    "source": "stub",
                },
                "test_left": False,
            }
        probes.append(item)
        if item.get("recipe"):
            recipes.append(item["recipe"])
    keys = [str(item.get("key") or "") for item in intents]
    return _merge_probe_results(probes, keys=keys)


def probe_onec_writes(
    args: dict[str, Any],
    *,
    actor_fio: str = "",
    actor_user_id: str = "",
    **_: Any,
) -> dict[str, Any]:
    from app.services.onec_tools import odata_configured

    intents = normalize_intent_dicts(args.get("intents"))
    if not intents:
        intents = [
            {
                "family": "assignment",
                "entity": "assignment",
                "operation": "update",
                "change": "status",
                "tool": "onec.erp_assignments_write",
                "odata_entity": ASSIGNMENT_ENTITY,
                "key": f"assignment:update:status:{ASSIGNMENT_ENTITY}",
            }
        ]
    keys = [str(item.get("key") or "") for item in intents]
    if not odata_configured():
        return stub_write_probe({**args, "intents": intents})
    results: list[dict[str, Any]] = []
    for family, _group_entity, group in _group_intents(intents):
        if family == "assignment":
            changes = [str(item.get("change") or "status") for item in group]
            results.append(
                probe_assignment_write(
                    {**args, "changes": changes},
                    actor_fio=actor_fio,
                    actor_user_id=actor_user_id,
                )
            )
            continue
        if family == "file":
            results.append(_attach_recipe())
            continue
        if family == "task":
            results.append(_task_comment_recipe())
            continue
        results.append(probe_odata_entity_write(args, intent=group[0]))
    merged = _merge_probe_results(results, keys=keys)
    if not merged.get("ok"):
        try:
            sweep_probe_assignments()
        except Exception:  # noqa: BLE001
            pass
    return merged
