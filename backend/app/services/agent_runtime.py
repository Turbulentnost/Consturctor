from __future__ import annotations

import re
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.models.workflow import Workflow
from app.services.local_mcp import list_tools
from app.services.onec_tools import ONEC_TOOLS as _ONEC_TOOLS
from app.services.plan_run import (
    PlanRunError,
    build_plan_export_arguments,
    format_plan_run_answer,
    uses_plan_export,
)
from app.services.tool_bridge import DEFAULT_TIMEOUT_S, tool_bridge


AgentEventCallback = Callable[[dict[str, Any]], None]

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

_IMAP_TOOLS = frozenset(
    {
        "imap.list_unread",
        "imap.search",
        "imap.fetch_message",
        "imap.fetch_attachments",
    }
)
_TURBOPROJECT_TOOLS = frozenset({"turboproject", "turboproject.projects"})


class AgentRuntimeError(RuntimeError):
    pass


def available_tools() -> list[dict[str, Any]]:
    return list_tools()


def run_agent_task(
    db: Session,
    *,
    user_id: str,
    workflow_id: str,
    message: str,
    emit: AgentEventCallback,
    run_id: str,
    agent_kind: str = "",
    source: str = "chat",
) -> dict[str, Any]:
    workflow = (
        db.query(Workflow)
        .filter(Workflow.id == workflow_id, Workflow.user_id == user_id)
        .first()
    )
    if workflow is None:
        raise AgentRuntimeError("Workflow не найден")
    task = message.strip()
    if not task:
        raise AgentRuntimeError("Пустая задача")

    from app.services.cursor_chat_runtime import ensure_cursor_chat_runtime

    emit({"type": "status", "text": "Думаю…"})
    playbook = ensure_cursor_chat_runtime(db, workflow)
    return _run_with_playbook(
        db,
        workflow=workflow,
        user_id=user_id,
        message=task,
        emit=emit,
        run_id=run_id,
        playbook=playbook,
        source=source,
    )


_FILE_URL_RE = re.compile(r"file:///\S+", re.IGNORECASE)
_WIN_PATH_RE = re.compile(r"[A-Za-z]:\\[^\s\"'<>]+")
_COPY_NAME_RE = re.compile(
    r"назван\w*\s+([^\r\n]+)",
    re.IGNORECASE,
)
_RENAME_TARGET_RE = re.compile(
    r"(?:назван(?:ие|ия)|имя)\s+файла\s+(?:на\s+)?[«\"']?([^»\"'\n,.]+)[»\"']?",
    re.IGNORECASE,
)
_RENAME_TO_RE = re.compile(
    r"переимен(?:уй|ить)(?:\s+файл)?[^\n]*?(?:в|на)\s+[«\"']?([^»\"'\n]+?)[»\"']?(?:\s*$|\s+и\s+)",
    re.IGNORECASE,
)
_RENAME_PORUCHENIYA_RE = re.compile(
    r"переимен(?:уй|ить)?\s+(?:файл\s+)?(?:поручен\w*|act[_\s-]?porucheniya\w*)\s+(?:в|на)\s+(.+)$",
    re.IGNORECASE,
)


def _normalize_rename_dest_name(dest_raw: str, task_low: str) -> str:
    dest = dest_raw.strip().strip(" «»\"'")
    dest = re.sub(r"\s+и\s+(?:сегодняшн\w*|сегодня).*$", "", dest, flags=re.I).strip()
    if any(x in task_low for x in ("сегодняшн", "сегодня")):
        from datetime import date

        suffix = date.today().strftime("%d.%m.%Y")
        if suffix not in dest:
            dest = f"{dest}_{suffix}"
    return dest


def _extract_rename_dest_name(text: str, low: str) -> str:
    for pattern in (_RENAME_TARGET_RE, _RENAME_PORUCHENIYA_RE, _RENAME_TO_RE, _COPY_NAME_RE):
        named = pattern.search(text)
        if named:
            dest_name = _normalize_rename_dest_name(named.group(1), low)
            if dest_name.casefold().startswith("файла "):
                dest_name = dest_name[6:].strip()
            if dest_name.casefold().startswith("на "):
                dest_name = dest_name[3:].strip()
            return dest_name
    return ""


def _parse_file_rename_command(task: str) -> dict[str, str] | None:
    text = (task or "").strip()
    low = text.casefold()
    if not any(
        hint in low
        for hint in (
            "название файла",
            "имя файла",
            "переимен",
            "rename",
            "назови файл",
            "измени название",
        )
    ):
        return None
    if not any(hint in low for hint in ("файл", ".xlsx", "file:", "excel", "поручен")):
        return None

    dest_name = _extract_rename_dest_name(text, low)
    if not dest_name:
        return None

    match = _FILE_URL_RE.search(text) or _WIN_PATH_RE.search(text)
    if match is not None:
        source = match.group(0).rstrip(".,;")
        return {"source": source, "dest_name": dest_name}

    if "поручен" in low or "porucheniya" in low:
        return {"source": "desktop:porucheniya", "dest_name": dest_name}

    return None


def _parse_file_copy_command(task: str) -> dict[str, str] | None:
    text = (task or "").strip()
    low = text.casefold()
    if not any(hint in low for hint in ("дубл", "копир", "скопир", "copy")):
        return None
    match = _FILE_URL_RE.search(text) or _WIN_PATH_RE.search(text)
    if match is None:
        return None
    source = match.group(0).rstrip(".,;")
    dest_name = ""
    named = _COPY_NAME_RE.search(text)
    if named:
        dest_name = named.group(1).strip().strip(" «»\"'")
        dest_name = dest_name.split(".xlsx")[0].strip() if dest_name.lower().endswith(".xlsx") else dest_name
    args = {"source": source}
    if dest_name:
        args["dest_name"] = dest_name
    return args


def _run_with_playbook(
    db: Session,
    *,
    workflow: Workflow,
    user_id: str,
    message: str,
    emit: AgentEventCallback,
    run_id: str,
    playbook: dict[str, Any],
    source: str = "chat",
) -> dict[str, Any]:
    from app.clients import cursor as cursor_client
    from app.clients.cursor import CursorAgentError
    from app.services.workflows import prompts
    from app.services.cursor_chat_runtime import resolve_chat_tool_names
    from app.services.workflows.cursor_tools import (
        set_allowed_tools,
        set_tool_context,
        stream_cursor_with_tools,
        wants_notifications,
        with_tools_if_desktop,
    )
    from app.services.workflows.service import _create_exec_agent, _stream_run

    set_tool_context(run_id, user_id)
    tool_names = resolve_chat_tool_names(workflow)
    set_allowed_tools(tool_names)
    allowed = frozenset(tool_names) if tool_names else None
    regulation = str(getattr(workflow, "document_text", "") or "").strip()
    if not regulation:
        regulation = str(playbook.get("instructions") or "")
    plan = workflow.plan_json if isinstance(workflow.plan_json, dict) else {}
    goal = str(plan.get("goal") or "").strip()
    prompt = with_tools_if_desktop(
        prompts.build_published_run_prompt(
            instructions=str(playbook.get("instructions") or ""),
            example_run=str(playbook.get("example_run") or ""),
            user_message=message,
            title=workflow.title or "",
            source=source,
            regulation=regulation,
            goal=goal,
        ),
        allowed_names=allowed,
    )
    emit({"type": "status", "text": "Планирую шаги и вызываю tools…"})

    def on_event(event_type: str, text: str = "", extra: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"type": event_type}
        if text:
            payload["text"] = text
        if extra:
            payload.update(extra)
        emit(payload)

    try:
        agent_id = str(workflow.exec_agent_id or "")
        if agent_id.startswith("mcp:"):
            agent_id = ""
        if agent_id:
            try:
                run = cursor_client.create_run_when_ready(
                    agent_id,
                    prompt=prompt,
                    mode="agent",
                    previous_run_id=str(workflow.exec_run_id or ""),
                )
                cursor_run_id = str(run.get("id") or "")
            except CursorAgentError:
                agent_id, cursor_run_id = _create_exec_agent(workflow.title or "агент", prompt)
                workflow.exec_agent_id = agent_id
                db.commit()
        else:
            agent_id, cursor_run_id = _create_exec_agent(workflow.title or "агент", prompt)
            workflow.exec_agent_id = agent_id
            db.commit()
        if not agent_id or not cursor_run_id:
            raise AgentRuntimeError("Cursor не вернул agent/run")
        required = (
            ["notify"]
            if (source or "") != "chat"
            and wants_notifications(
                str(playbook.get("instructions") or ""),
                message,
                str(workflow.notes or ""),
            )
            else (
                ["notify"]
                if wants_notifications(message)
                else []
            )
        )
        phase = stream_cursor_with_tools(
            agent_id=agent_id,
            run_id=cursor_run_id,
            on_event=on_event,
            workflow_id=workflow.id,
            mode="execute",
            stream_run=_stream_run,
            required_live_tools=required,
        )
    except CursorAgentError as exc:
        emit({"type": "error", "message": exc.message})
        raise AgentRuntimeError(exc.message) from exc
    finally:
        from app.services.workflows.cursor_tools import clear_tool_context

        clear_tool_context()

    work = prompts.parse_work_result(phase.text or "")
    answer = (work.get("text") or "").strip() or "Прогон завершён."
    emit(
        {
            "type": "work_result",
            "text": answer,
            "files": work.get("files") or [],
            "actions": work.get("actions") or [],
            "notifications": work.get("notifications") or [],
        }
    )
    emit({"type": "agent_message", "text": answer})
    local = dict(workflow.local_run or {})
    local["work_result"] = work
    workflow.local_run = local
    workflow.last_result = answer
    db.commit()
    return {
        "answer": answer,
        "work_result": work,
        "tool": "cursor",
        "tool_result": {"tools": list(phase.successful_live_tools or [])},
    }


def _run_act_porucheniya_registry(
    db: Session,
    *,
    emit: AgentEventCallback,
    run_id: str,
    user_id: str,
    workflow_id: str,
    workflow: Workflow,
    task: str,
) -> dict[str, Any]:
    from app.config import settings
    from app.services.act_porucheniya_odata import fetch_act_porucheniya_registry
    from app.services.act_porucheniya_report import (
        build_act_excel_arguments,
        compose_act_registry_answer,
    )
    from app.services.app_users import get_app_user

    _ = db
    actor_fio = ""
    user = get_app_user(user_id)
    if user is not None:
        actor_fio = str(user.fio or "")
    if not actor_fio.strip():
        actor_fio = str(settings.erp_login or "").strip()

    from app.services.act_porucheniya_task import (
        apply_act_document_filters,
        parse_act_filter_from_task,
        parse_act_task_intent,
        workflow_attachment_context,
    )

    intent = parse_act_task_intent(task)
    if intent == "freeform_chat":
        return _run_act_freeform_chat(
            emit=emit,
            workflow=workflow,
            task=task,
        )
    if intent == "summarize_excel":
        emit({"type": "status", "text": "Режим: сводка по указанному Excel (без OData)…"})
        return _run_act_summarize_excel(
            emit=emit,
            run_id=run_id,
            user_id=user_id,
            workflow_id=workflow_id,
            workflow=workflow,
            task=task,
        )

    if intent == "reformat_excel":
        return _run_act_reformat_desktop_excel(
            emit=emit,
            run_id=run_id,
            user_id=user_id,
            workflow_id=workflow_id,
            workflow=workflow,
            task=task,
            actor_fio=actor_fio,
        )

    if intent == "composite_workflow":
        return _run_act_composite_workflow(
            db,
            emit=emit,
            run_id=run_id,
            user_id=user_id,
            workflow_id=workflow_id,
            workflow=workflow,
            task=task,
            actor_fio=actor_fio,
        )

    if intent == "edit_excel":
        return _run_act_edit_desktop_excel(
            emit=emit,
            run_id=run_id,
            user_id=user_id,
            workflow_id=workflow_id,
            workflow=workflow,
            task=task,
            actor_fio=actor_fio,
        )

    attachment_ctx = workflow_attachment_context(workflow)
    if attachment_ctx:
        emit({"type": "status", "text": "Учитываю материалы из вложений workflow…"})

    from app.services.act_protocol_merge import (
        extract_protocol_text,
        merge_protocol_documents,
        parse_protocol_to_documents,
        task_implies_protocol_merge,
    )

    registry_payload: dict[str, Any] = {}
    all_documents: list[dict[str, Any]] = []
    odata_source = ""

    if intent == "merge_add":
        emit({"type": "status", "text": "Режим: дополнение реестра по вашей задаче…"})
        excel_read = _read_act_desktop_excel(
            emit,
            run_id=run_id,
            user_id=user_id,
            workflow_id=workflow_id,
            actor_fio=actor_fio,
            task=task,
        )
        if excel_read:
            from app.services.act_porucheniya_report import documents_from_excel_payload

            all_documents = documents_from_excel_payload(excel_read)
            if all_documents:
                odata_source = "excel-desktop"
                task_count = sum(int(doc.get("task_line_count") or 0) for doc in all_documents)
                registry_payload = {
                    "summary": (
                        f"База из Excel на рабочем столе: {len(all_documents)} ACT, {task_count} задач"
                    ),
                    "count": len(all_documents),
                    "task_count": task_count,
                    "documents": all_documents,
                    "source": odata_source,
                }
                emit(
                    {
                        "type": "status",
                        "text": (
                            f"Загружено из Excel: {len(all_documents)} ACT, {task_count} задач "
                            "(OData не вызываю)."
                        ),
                    }
                )
            elif int(excel_read.get("row_count") or 0) > 1:
                emit(
                    {
                        "type": "status",
                        "text": (
                            "Excel прочитан, но строки задач не распознаны. "
                            "OData не вызываю — проверьте лист «Задачи ACT» и заголовки."
                        ),
                    }
                )
                return _run_act_analyze_without_data(
                    emit=emit,
                    workflow=workflow,
                    task=task,
                    factual=(
                        "Файл Excel на рабочем столе найден, но не удалось восстановить задачи ACT "
                        "(ожидаются колонки: Номер ACT, Задача, Исполнитель, Срок, Статус). "
                        "OData не вызывался."
                    ),
                )

    if not all_documents:
        if intent == "analyze_chat":
            excel_read = _read_act_desktop_excel(
                emit,
                run_id=run_id,
                user_id=user_id,
                workflow_id=workflow_id,
                actor_fio=actor_fio,
                task=task,
            )
            if excel_read:
                from app.services.act_porucheniya_report import documents_from_excel_payload

                desktop_docs = documents_from_excel_payload(excel_read)
                if desktop_docs:
                    task_count = sum(int(doc.get("task_line_count") or 0) for doc in desktop_docs)
                    all_documents = desktop_docs
                    registry_payload = {
                        "summary": (
                            f"База из Excel на рабочем столе: {len(desktop_docs)} ACT, {task_count} задач"
                        ),
                        "count": len(desktop_docs),
                        "task_count": task_count,
                        "documents": desktop_docs,
                        "source": "excel-desktop",
                    }
                    odata_source = "excel-desktop"
                    emit(
                        {
                            "type": "status",
                            "text": (
                                f"Загружено из Excel: {len(desktop_docs)} ACT, {task_count} задач "
                                "(OData не вызываю)."
                            ),
                        }
                    )
            if not all_documents:
                return _run_act_analyze_without_data(
                    emit=emit,
                    workflow=workflow,
                    task=task,
                )
        elif intent == "merge_add":
            emit(
                {
                    "type": "status",
                    "text": "Excel на рабочем столе не найден — загружаю базу из OData…",
                }
            )
        else:
            emit({"type": "status", "text": "Читаю реестр поручений ACT через OData…"})

        if intent != "analyze_chat":
            def _odata_progress(message: str) -> None:
                emit({"type": "status", "text": message})

            registry_payload = fetch_act_porucheniya_registry(on_progress=_odata_progress)
            all_documents = list(registry_payload.get("documents") or [])
            odata_source = str(registry_payload.get("source") or "")
            if odata_source == "odata-error":
                emit(
                    {
                        "type": "status",
                        "text": str(registry_payload.get("summary") or "OData: ошибка загрузки реестра ACT."),
                    }
                )
            else:
                task_count = int(registry_payload.get("task_count") or 0)
                emit(
                    {
                        "type": "status",
                        "text": (
                            f"Загружено {len(all_documents)} документов ACT/АСТ из OData"
                            + (f", {task_count} задач." if task_count else ".")
                        ),
                    }
                )

    task_filter = parse_act_filter_from_task(task)

    protocol_merge_stats: dict[str, Any] = {}
    working_documents = list(all_documents)
    if task_implies_protocol_merge(task) or intent == "merge_add":
        protocol_text = extract_protocol_text(task, workflow_text=attachment_ctx)
        if protocol_text.strip():
            from app.services.act_porucheniya_report import assign_next_act_numbers

            emit({"type": "status", "text": "Разбираю задачу и дополняю реестр новой записью…"})
            protocol_docs = parse_protocol_to_documents(protocol_text)
            protocol_docs = assign_next_act_numbers(
                protocol_docs,
                existing_documents=working_documents,
            )
            working_documents, protocol_merge_stats = merge_protocol_documents(
                working_documents, protocol_docs
            )
            emit(
                {
                    "type": "status",
                    "text": (
                        f"Добавлено: +{protocol_merge_stats.get('added_documents', 0)} ACT, "
                        f"+{protocol_merge_stats.get('added_task_lines', 0)} задач."
                    ),
                }
            )
        elif intent == "merge_add":
            return _run_act_analyze_without_data(
                emit=emit,
                workflow=workflow,
                task=task,
                factual=(
                    "Не удалось разобрать новую запись в задаче. "
                    "Примеры: «добавь запись Иванов Иван 29.09.26 Текст задачи» или "
                    "«добавь Задача: …, Исполнитель: …, срок до 29.09.26»."
                ),
            )
        else:
            emit({"type": "status", "text": "Протокол в задаче не найден — только OData."})

    documents, filter_desc = apply_act_document_filters(working_documents, task_filter)

    if filter_desc != "без фильтров (полный реестр)":
        emit(
            {
                "type": "status",
                "text": f"Фильтр по задаче: {filter_desc} → {len(documents)} из {len(working_documents)}.",
            }
        )
    from app.services.act_porucheniya_report import flatten_documents_to_task_rows

    registry_payload = {
        **registry_payload,
        "documents": documents,
        "filter": filter_desc,
        "count": len(documents),
        "task_count": len(flatten_documents_to_task_rows(documents)),
        "protocol_merge": protocol_merge_stats,
    }
    emit({"type": "tool_result", "tool": "onec.act_porucheniya_registry", "result": registry_payload})

    excel_payload: dict[str, Any] | None = None
    if documents and task_filter.get("refresh_excel", True):
        emit({"type": "status", "text": "Формирую Excel (задачи ACT, OData + протокол)…"})
        excel_args = build_act_excel_arguments(
            workflow_id=workflow_id,
            documents=documents,
            actor_fio=actor_fio,
        )
        try:
            excel_payload = _request_desktop_tool(
                emit,
                run_id=run_id,
                user_id=user_id,
                workflow_id=workflow_id,
                tool="excel.create_workbook",
                arguments=excel_args,
                timeout_s=120.0,
            )
            emit({"type": "tool_result", "tool": "excel.create_workbook", "result": excel_payload})
        except AgentRuntimeError as exc:
            emit({"type": "status", "text": f"Excel не создан: {exc}"})

    answer = compose_act_registry_answer(registry_payload, excel_payload)
    from app.services.agent_llm_reply import finalize_agent_answer

    excel_path = ""
    if excel_payload:
        excel_path = str(excel_payload.get("desktop_path") or excel_payload.get("path") or "")
    answer = finalize_agent_answer(
        task=task,
        handler="act_porucheniya_registry",
        workflow=workflow,
        factual_answer=answer,
        extra_context={
            "count": len(documents),
            "task_count": len(flatten_documents_to_task_rows(documents)),
            "total_count": len(all_documents),
            "excel_path": excel_path,
            "filter": filter_desc,
            "protocol_merge": protocol_merge_stats,
            "attachment_context": attachment_ctx[:1200] if attachment_ctx else "",
            "odata_source": odata_source,
            "odata_summary": str(registry_payload.get("summary") or ""),
        },
        emit=emit,
    )
    emit({"type": "agent_message", "text": answer})
    return {
        "answer": answer,
        "tool": "onec.act_porucheniya_registry",
        "tool_result": registry_payload,
        "excel": excel_payload,
    }


def _read_act_desktop_excel(
    emit: AgentEventCallback,
    *,
    run_id: str,
    user_id: str,
    workflow_id: str,
    actor_fio: str,
    source_path: str = "",
    task: str = "",
) -> dict[str, Any] | None:
    from app.services.act_porucheniya_task import (
        act_desktop_excel_candidates,
        resolve_desktop_excel_filename,
    )

    desktop_names: list[str] = []
    if (source_path or "").strip():
        desktop_names.append(source_path.strip())
    if (task or "").strip():
        resolved = resolve_desktop_excel_filename(
            task,
            actor_fio=actor_fio,
            workflow_id=workflow_id,
        )
        if resolved:
            desktop_names.append(resolved)
    desktop_names.extend(
        act_desktop_excel_candidates(
            actor_fio=actor_fio,
            workflow_id=workflow_id,
        )
    )
    seen: set[str] = set()
    for desktop_name in desktop_names:
        key = desktop_name.casefold()
        if key in seen:
            continue
        seen.add(key)
        emit({"type": "status", "text": f"Читаю Excel с рабочего стола: {desktop_name}…"})
        try:
            excel_read = _request_desktop_tool(
                emit,
                run_id=run_id,
                user_id=user_id,
                workflow_id=workflow_id,
                tool="excel.read_workbook",
                arguments={
                    "desktop_path": desktop_name,
                    "sheet": "Задачи ACT",
                    "max_rows": 10000,
                    "runtime_context": {"workflow_id": workflow_id, "agent_id": workflow_id},
                },
                timeout_s=90.0,
            )
        except AgentRuntimeError:
            continue
        if int(excel_read.get("row_count") or 0) >= 2:
            return excel_read
    return None


def _load_act_documents_from_desktop(
    emit: AgentEventCallback,
    *,
    run_id: str,
    user_id: str,
    workflow_id: str,
    actor_fio: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from app.services.act_porucheniya_report import documents_from_excel_payload

    excel_read = _read_act_desktop_excel(
        emit,
        run_id=run_id,
        user_id=user_id,
        workflow_id=workflow_id,
        actor_fio=actor_fio,
        task=task,
    )
    if not excel_read:
        return [], {}

    documents = documents_from_excel_payload(excel_read)
    if not documents:
        return [], {}

    task_count = sum(int(doc.get("task_line_count") or 0) for doc in documents)
    payload = {
        "summary": f"База из Excel на рабочем столе: {len(documents)} ACT, {task_count} задач",
        "count": len(documents),
        "task_count": task_count,
        "documents": documents,
        "source": "excel-desktop",
    }
    emit(
        {
            "type": "status",
            "text": (
                f"Загружено из Excel: {len(documents)} ACT, {task_count} задач "
                "(OData не вызываю)."
            ),
        }
    )
    return documents, payload


def _run_act_freeform_chat(
    *,
    emit: AgentEventCallback,
    workflow: Workflow,
    task: str,
) -> dict[str, Any]:
    from app.services.agent_llm_reply import finalize_agent_answer

    emit({"type": "status", "text": "Отвечаю в чате (без OData и Excel)…"})
    factual = (
        "Сообщение не похоже на команду ACT-реестра. "
        "OData, Excel и фильтры не запускались."
    )
    answer = finalize_agent_answer(
        task=task,
        handler="act_porucheniya_registry",
        workflow=workflow,
        factual_answer=factual,
        extra_context={"intent": "freeform_chat"},
        emit=emit,
    )
    emit({"type": "agent_message", "text": answer})
    return {"answer": answer, "intent": "freeform_chat"}


def _run_act_analyze_without_data(
    *,
    emit: AgentEventCallback,
    workflow: Workflow,
    task: str,
    factual: str = "",
) -> dict[str, Any]:
    from app.services.agent_llm_reply import finalize_agent_answer

    emit({"type": "status", "text": "Отвечаю в чате по имеющимся данным…"})
    if not factual:
        factual = (
            "На рабочем столе нет файла act_porucheniya_*.xlsx для ответа по реестру. "
            "OData не вызывался. Чтобы получить данные: нажмите «Запустить типовую задачу» "
            "или напишите «выгрузи ACT-реестр на рабочий стол»."
        )
    answer = finalize_agent_answer(
        task=task,
        handler="act_porucheniya_registry",
        workflow=workflow,
        factual_answer=factual,
        extra_context={"intent": "analyze_chat", "odata_source": "none"},
        emit=emit,
    )
    emit({"type": "agent_message", "text": answer})
    return {"answer": answer, "intent": "analyze_chat"}


def _run_act_composite_workflow(
    db: Session,
    *,
    emit: AgentEventCallback,
    run_id: str,
    user_id: str,
    workflow_id: str,
    workflow: Workflow,
    task: str,
    actor_fio: str,
) -> dict[str, Any]:
    """OData → Excel + новая запись → Word-отчёт → Outlook в тот же docx."""
    from datetime import datetime

    from app.services.act_porucheniya_odata import fetch_act_porucheniya_registry
    from app.services.act_porucheniya_report import (
        assign_next_act_numbers,
        build_act_excel_arguments,
        compose_act_registry_answer,
        flatten_documents_to_task_rows,
    )
    from app.services.act_protocol_merge import (
        extract_protocol_text,
        merge_protocol_documents,
        parse_protocol_to_documents,
    )
    from app.services.agent_llm_reply import finalize_agent_answer

    emit({"type": "status", "text": "Комплексная задача: OData → Excel → Word → Outlook…"})

    def _odata_progress(message: str) -> None:
        emit({"type": "status", "text": message})

    registry_payload = fetch_act_porucheniya_registry(on_progress=_odata_progress)
    all_documents = list(registry_payload.get("documents") or [])
    odata_source = str(registry_payload.get("source") or "")
    emit(
        {
            "type": "status",
            "text": (
                f"OData: {len(all_documents)} ACT, "
                f"{int(registry_payload.get('task_count') or 0)} задач."
            ),
        }
    )
    emit({"type": "tool_result", "tool": "onec.act_porucheniya_registry", "result": registry_payload})

    protocol_text = extract_protocol_text(task, workflow_text="")
    protocol_merge_stats: dict[str, Any] = {}
    working_documents = list(all_documents)
    if protocol_text.strip():
        emit({"type": "status", "text": "Добавляю новую запись в реестр…"})
        protocol_docs = parse_protocol_to_documents(protocol_text)
        protocol_docs = assign_next_act_numbers(protocol_docs, existing_documents=working_documents)
        working_documents, protocol_merge_stats = merge_protocol_documents(
            working_documents, protocol_docs
        )
        emit(
            {
                "type": "status",
                "text": (
                    f"Добавлено: +{protocol_merge_stats.get('added_task_lines', 0)} задач, "
                    f"+{protocol_merge_stats.get('added_documents', 0)} ACT."
                ),
            }
        )
    else:
        emit({"type": "status", "text": "Новая запись в задаче не распознана — продолжаю без дополнения."})

    documents = working_documents
    excel_payload: dict[str, Any] | None = None
    if documents:
        emit({"type": "status", "text": "Формирую Excel на рабочем столе…"})
        excel_args = build_act_excel_arguments(
            workflow_id=workflow_id,
            documents=documents,
            actor_fio=actor_fio,
        )
        try:
            excel_payload = _request_desktop_tool(
                emit,
                run_id=run_id,
                user_id=user_id,
                workflow_id=workflow_id,
                tool="excel.create_workbook",
                arguments=excel_args,
                timeout_s=120.0,
            )
            emit({"type": "tool_result", "tool": "excel.create_workbook", "result": excel_payload})
        except AgentRuntimeError as exc:
            emit({"type": "status", "text": f"Excel не создан: {exc}"})

    report_body = compose_act_registry_answer(
        {
            **registry_payload,
            "documents": documents,
            "count": len(documents),
            "task_count": len(flatten_documents_to_task_rows(documents)),
            "protocol_merge": protocol_merge_stats,
        },
        excel_payload,
    )
    docx_name = f"act_porucheniya_report_{datetime.now().strftime('%Y%m%d')}.docx"
    docx_payload: dict[str, Any] | None = None
    emit({"type": "status", "text": f"Создаю Word-отчёт {docx_name}…"})
    try:
        docx_payload = _request_desktop_tool(
            emit,
            run_id=run_id,
            user_id=user_id,
            workflow_id=workflow_id,
            tool="document.write_docx",
            arguments={
                "filename": docx_name,
                "title": "Отчёт по поручениям ACT",
                "paragraphs": report_body.splitlines(),
                "save_to_desktop": False,
            },
            timeout_s=90.0,
        )
        emit({"type": "tool_result", "tool": "document.write_docx", "result": docx_payload})
    except AgentRuntimeError as exc:
        emit({"type": "status", "text": f"Word-отчёт не создан: {exc}"})

    calendar_payload: dict[str, Any] | None = None
    emit({"type": "status", "text": "Читаю календарь Outlook (совещания на сегодня)…"})
    try:
        calendar_payload = _request_desktop_tool(
            emit,
            run_id=run_id,
            user_id=user_id,
            workflow_id=workflow_id,
            tool="outlook.read_calendar",
            arguments={"days_forward": 1, "max_results": 40},
            timeout_s=120.0,
        )
        emit({"type": "tool_result", "tool": "outlook.read_calendar", "result": calendar_payload})
    except AgentRuntimeError as exc:
        emit({"type": "status", "text": f"Outlook недоступен: {exc}"})

    docx_path = str((docx_payload or {}).get("desktop_path") or (docx_payload or {}).get("path") or "")
    meeting_lines: list[str] = []
    today = datetime.now().date()
    today_str = today.strftime("%Y-%m-%d")
    for event in (calendar_payload or {}).get("events") or []:
        if not isinstance(event, dict):
            continue
        start_raw = str(event.get("start_at") or event.get("start") or "")
        title = str(event.get("title") or event.get("subject") or "Совещание").strip()
        if today_str not in start_raw:
            continue
        location = str(event.get("location") or "").strip()
        line = f"• {start_raw[:16]} — {title}"
        if location:
            line += f" ({location})"
        meeting_lines.append(line)

    if docx_path and meeting_lines:
        emit({"type": "status", "text": "Дописываю совещания в конец Word-файла…"})
        try:
            append_payload = _request_desktop_tool(
                emit,
                run_id=run_id,
                user_id=user_id,
                workflow_id=workflow_id,
                tool="document.append_docx",
                arguments={
                    "path": docx_path,
                    "heading": f"Совещания на {today.strftime('%d.%m.%Y')}",
                    "paragraphs": meeting_lines,
                },
                timeout_s=90.0,
            )
            emit({"type": "tool_result", "tool": "document.append_docx", "result": append_payload})
        except AgentRuntimeError as exc:
            emit({"type": "status", "text": f"Не удалось дописать Outlook в Word: {exc}"})
    elif docx_path:
        emit({"type": "status", "text": "Совещаний на сегодня в Outlook не найдено."})

    excel_path = str((excel_payload or {}).get("desktop_path") or (excel_payload or {}).get("path") or "")
    factual = (
        f"Комплексная задача выполнена.\n"
        f"OData: {len(all_documents)} ACT → Excel: {excel_path or '—'}.\n"
        f"Добавлено из задачи: +{protocol_merge_stats.get('added_task_lines', 0)} строк.\n"
        f"Word: {docx_path or '—'}.\n"
        f"Outlook: совещаний на сегодня — {len(meeting_lines)}."
    )
    answer = finalize_agent_answer(
        task=task,
        handler="act_porucheniya_registry",
        workflow=workflow,
        factual_answer=factual,
        extra_context={
            "intent": "composite_workflow",
            "excel_path": excel_path,
            "count": len(documents),
            "task_count": len(flatten_documents_to_task_rows(documents)),
            "odata_source": odata_source,
            "protocol_merge": protocol_merge_stats,
        },
        emit=emit,
    )
    emit({"type": "agent_message", "text": answer})
    return {
        "answer": answer,
        "intent": "composite_workflow",
        "excel": excel_payload,
        "document": docx_payload,
        "calendar": calendar_payload,
        "protocol_merge": protocol_merge_stats,
    }


def _run_act_edit_desktop_excel(
    *,
    emit: AgentEventCallback,
    run_id: str,
    user_id: str,
    workflow_id: str,
    workflow: Workflow,
    task: str,
    actor_fio: str,
) -> dict[str, Any]:
    from app.services.act_porucheniya_report import build_act_excel_move_last_row_arguments
    from app.services.act_porucheniya_task import (
        resolve_desktop_excel_filename,
        task_wants_move_last_row_to_top,
    )
    from app.services.agent_llm_reply import finalize_agent_answer

    emit({"type": "status", "text": "Режим: правка Excel на рабочем столе (без OData)…"})
    if not task_wants_move_last_row_to_top(task):
        factual = (
            "Поняла запрос на правку Excel, но не распознала операцию. "
            "Пример: «в файле Поручения на рабочем столе измени последнюю строку: "
            "номер ACT00-… и перенеси наверх»."
        )
        answer = finalize_agent_answer(
            task=task,
            handler="act_porucheniya_registry",
            workflow=workflow,
            factual_answer=factual,
            extra_context={"intent": "edit_excel", "odata_source": "none"},
            emit=emit,
        )
        emit({"type": "agent_message", "text": answer})
        return {"answer": answer, "intent": "edit_excel"}

    target_name = resolve_desktop_excel_filename(
        task,
        actor_fio=actor_fio,
        workflow_id=workflow_id,
    )
    emit({"type": "status", "text": f"Читаю Excel с рабочего стола: {target_name}…"})
    try:
        excel_read = _request_desktop_tool(
            emit,
            run_id=run_id,
            user_id=user_id,
            workflow_id=workflow_id,
            tool="excel.read_workbook",
            arguments={
                "desktop_path": target_name,
                "sheet": "Задачи ACT",
                "max_rows": 10000,
                "runtime_context": {"workflow_id": workflow_id, "agent_id": workflow_id},
            },
            timeout_s=90.0,
        )
        emit({"type": "tool_result", "tool": "excel.read_workbook", "result": excel_read})
    except AgentRuntimeError as exc:
        factual = f"Не удалось прочитать Excel на рабочем столе ({target_name}): {exc}"
        answer = finalize_agent_answer(
            task=task,
            handler="act_porucheniya_registry",
            workflow=workflow,
            factual_answer=factual,
            extra_context={"intent": "edit_excel", "odata_source": "none"},
            emit=emit,
        )
        emit({"type": "agent_message", "text": answer})
        return {"answer": answer, "intent": "edit_excel"}

    save_name = target_name if "*" not in target_name else str(excel_read.get("filename") or "Поручения.xlsx")

    excel_args, meta = build_act_excel_move_last_row_arguments(
        excel_read,
        target_filename=save_name,
        workflow_id=workflow_id,
        actor_fio=actor_fio,
    )
    if not excel_args:
        factual = str(meta.get("error") or "Не удалось подготовить правку Excel.")
        answer = finalize_agent_answer(
            task=task,
            handler="act_porucheniya_registry",
            workflow=workflow,
            factual_answer=factual,
            extra_context={"intent": "edit_excel", "odata_source": "none"},
            emit=emit,
        )
        emit({"type": "agent_message", "text": answer})
        return {"answer": answer, "intent": "edit_excel"}

    new_act = str(meta.get("new_act") or "")
    old_act = str(meta.get("old_act") or "")
    emit(
        {
            "type": "status",
            "text": f"Переношу последнюю строку наверх: {old_act} → {new_act}…",
        }
    )
    excel_payload: dict[str, Any] | None = None
    try:
        excel_payload = _request_desktop_tool(
            emit,
            run_id=run_id,
            user_id=user_id,
            workflow_id=workflow_id,
            tool="excel.create_workbook",
            arguments=excel_args,
            timeout_s=120.0,
        )
        emit({"type": "tool_result", "tool": "excel.create_workbook", "result": excel_payload})
    except AgentRuntimeError as exc:
        factual = f"Excel не сохранён: {exc}"
        answer = finalize_agent_answer(
            task=task,
            handler="act_porucheniya_registry",
            workflow=workflow,
            factual_answer=factual,
            extra_context={"intent": "edit_excel", "odata_source": "none"},
            emit=emit,
        )
        emit({"type": "agent_message", "text": answer})
        return {"answer": answer, "intent": "edit_excel"}

    dest_path = ""
    if excel_payload:
        dest_path = str(excel_payload.get("desktop_path") or excel_payload.get("path") or "")
    factual = (
        f"Последняя строка переименована {old_act} → {new_act} и перенесена наверх "
        f"(всего строк задач: {meta.get('row_count', '?')}). "
        f"Файл: {dest_path or save_name}. OData не вызывался."
    )
    answer = finalize_agent_answer(
        task=task,
        handler="act_porucheniya_registry",
        workflow=workflow,
        factual_answer=factual,
        extra_context={
            "intent": "edit_excel",
            "excel_path": dest_path,
            "new_act": new_act,
            "odata_source": "none",
        },
        emit=emit,
    )
    emit({"type": "agent_message", "text": answer})
    return {
        "answer": answer,
        "tool": "excel.create_workbook",
        "excel": excel_payload,
        "intent": "edit_excel",
        "meta": meta,
    }


def _run_act_reformat_desktop_excel(
    *,
    emit: AgentEventCallback,
    run_id: str,
    user_id: str,
    workflow_id: str,
    workflow: Workflow,
    task: str,
    actor_fio: str,
) -> dict[str, Any]:
    from app.services.act_porucheniya_report import (
        build_act_excel_reformat_arguments,
        compose_act_registry_answer,
    )
    from app.services.act_porucheniya_task import extract_excel_path_from_task
    from app.services.agent_llm_reply import finalize_agent_answer

    emit({"type": "status", "text": "Режим: обновление Excel на рабочем столе (без OData)…"})
    excel_read = _read_act_desktop_excel(
        emit,
        run_id=run_id,
        user_id=user_id,
        workflow_id=workflow_id,
        actor_fio=actor_fio,
        source_path=extract_excel_path_from_task(task),
        task=task,
    )
    if not excel_read:
        factual = (
            "На рабочем столе не найден act_porucheniya_*.xlsx. "
            "OData не вызывался. Сначала выгрузите реестр («выгрузи ACT-реестр») "
            "или укажите путь к файлу."
        )
        answer = finalize_agent_answer(
            task=task,
            handler="act_porucheniya_registry",
            workflow=workflow,
            factual_answer=factual,
            extra_context={"intent": "reformat_excel", "odata_source": "none"},
            emit=emit,
        )
        emit({"type": "agent_message", "text": answer})
        return {"answer": answer, "intent": "reformat_excel"}

    excel_args = build_act_excel_reformat_arguments(
        excel_read,
        workflow_id=workflow_id,
        actor_fio=actor_fio,
    )
    if not excel_args:
        factual = (
            f"Файл {excel_read.get('filename') or 'Excel'} прочитан, но в листе «Задачи ACT» "
            "нет строк для пересохранения. OData не вызывался."
        )
        answer = finalize_agent_answer(
            task=task,
            handler="act_porucheniya_registry",
            workflow=workflow,
            factual_answer=factual,
            extra_context={"intent": "reformat_excel", "odata_source": "none"},
            emit=emit,
        )
        emit({"type": "agent_message", "text": answer})
        return {"answer": answer, "intent": "reformat_excel"}

    row_count = len(excel_args.get("rows") or [])
    registry_payload = {
        "summary": f"Пересохранение Excel: {row_count} строк задач (новая палитра, без OData).",
        "count": row_count,
        "task_count": row_count,
        "source": "excel-desktop",
        "filter": "пересохранение Excel (без OData)",
    }
    excel_payload: dict[str, Any] | None = None
    emit({"type": "status", "text": "Пересохраняю Excel с обновлённой палитрой…"})
    try:
        excel_payload = _request_desktop_tool(
            emit,
            run_id=run_id,
            user_id=user_id,
            workflow_id=workflow_id,
            tool="excel.create_workbook",
            arguments=excel_args,
            timeout_s=120.0,
        )
        emit({"type": "tool_result", "tool": "excel.create_workbook", "result": excel_payload})
    except AgentRuntimeError as exc:
        emit({"type": "status", "text": f"Excel не обновлён: {exc}"})

    factual = compose_act_registry_answer(registry_payload, excel_payload)
    excel_path = ""
    if excel_payload:
        excel_path = str(excel_payload.get("desktop_path") or excel_payload.get("path") or "")
    answer = finalize_agent_answer(
        task=task,
        handler="act_porucheniya_registry",
        workflow=workflow,
        factual_answer=factual,
        extra_context={
            "intent": "reformat_excel",
            "task_count": row_count,
            "excel_path": excel_path,
            "odata_source": "excel-desktop",
        },
        emit=emit,
    )
    emit({"type": "agent_message", "text": answer})
    return {
        "answer": answer,
        "tool": "excel.create_workbook",
        "tool_result": registry_payload,
        "excel": excel_payload,
        "intent": "reformat_excel",
    }


def _run_act_summarize_excel(
    *,
    emit: AgentEventCallback,
    run_id: str,
    user_id: str,
    workflow_id: str,
    workflow: Workflow,
    task: str,
) -> dict[str, Any]:
    from app.services.act_porucheniya_report import compose_excel_workbook_summary
    from app.services.act_porucheniya_task import extract_excel_path_from_task

    source_path = extract_excel_path_from_task(task)
    if not source_path:
        emit({"type": "status", "text": "Путь к Excel не найден в задаче."})
        raise AgentRuntimeError("Укажите путь к .xlsx на рабочем столе, например act_porucheniya_….xlsx")

    emit({"type": "status", "text": f"Читаю Excel: {source_path}…"})
    read_args = {
        "desktop_path": source_path,
        "sheet": "Задачи ACT",
        "max_rows": 5000,
        "runtime_context": {"workflow_id": workflow_id, "agent_id": workflow_id},
    }
    try:
        excel_payload = _request_desktop_tool(
            emit,
            run_id=run_id,
            user_id=user_id,
            workflow_id=workflow_id,
            tool="excel.read_workbook",
            arguments=read_args,
            timeout_s=90.0,
        )
    except AgentRuntimeError as exc:
        emit({"type": "error", "message": str(exc)})
        raise

    emit({"type": "tool_result", "tool": "excel.read_workbook", "result": excel_payload})
    factual = compose_excel_workbook_summary(excel_payload, source_path=source_path)

    from app.services.agent_llm_reply import finalize_agent_answer

    answer = finalize_agent_answer(
        task=task,
        handler="act_porucheniya_registry",
        workflow=workflow,
        factual_answer=factual,
        extra_context={
            "intent": "summarize_excel",
            "excel_path": source_path,
            "row_count": excel_payload.get("row_count"),
        },
        emit=emit,
    )
    emit({"type": "agent_message", "text": answer})
    return {
        "answer": answer,
        "tool": "excel.read_workbook",
        "tool_result": excel_payload,
        "intent": "summarize_excel",
    }


def _agent_domain(workflow: Workflow, *, task: str = "") -> str:
    from app.services.act_porucheniya_report import workflow_runtime_kind
    from app.services.assignments_report import _workflow_text_blob, task_implies_assignments

    plan = workflow.plan_json if isinstance(workflow.plan_json, dict) else {}
    kind = workflow_runtime_kind(workflow)
    if kind in {
        "outlook_calendar",
        "site_search_excel",
        "browser_task",
        "onec",
        "act_porucheniya",
        "act_registry",
        "action_tracker",
        "assignments",
        "user_tasks",
        "porucheniya",
        "porucheniya_smart",
        "action_tracker",
    }:
        if kind in {"act_porucheniya", "act_registry"}:
            return "onec"
        if kind in {
            "assignments",
            "user_tasks",
            "porucheniya",
            "porucheniya_smart",
            "action_tracker",
            "onec",
        }:
            return "onec"
        return kind
    answered = plan.get("answered_questions") or []
    answered_text = ""
    if isinstance(answered, list):
        answered_text = " ".join(
            f"{x.get('question', '')} {x.get('answer', '')}"
            for x in answered
            if isinstance(x, dict)
        )
    elif isinstance(answered, dict):
        answered_text = " ".join(f"{k} {v}" for k, v in answered.items())
    open_qs = plan.get("open_questions") or []
    open_text = ""
    if isinstance(open_qs, list):
        open_text = " ".join(
            f"{x.get('question', '')} {x.get('answer', '')}"
            for x in open_qs
            if isinstance(x, dict)
        )
    blob = f"{_workflow_text_blob(workflow, task=task)} {answered_text} {open_text}".casefold()
    if task_implies_assignments(task):
        return "onec"
    if any(
        tip in blob
        for tip in (
            "1с",
            "1c",
            "onec",
            "odata",
            "erp_pm",
            "задач",
            "поручен",
            "smart",
            "формулиров",
            "action tracker",
            "act00",
            "аст00",
            "act_porucheniya",
            "реестр поручений",
        )
    ) and "outlook" not in blob:
        return "onec"
    if any(
        tip in blob
        for tip in (
            "outlook",
            "календар",
            "совещан",
            "встреч",
            "занятост",
            "confirm_slot",
        )
    ):
        return "outlook_calendar"
    if ("excel" in blob or "xlsx" in blob) and (
        "ключев" in blob or "этп" in blob or "сайт" in blob
    ):
        return "site_search_excel"
    return ""


def _request_desktop_tool(
    emit: AgentEventCallback,
    *,
    run_id: str,
    user_id: str,
    tool: str,
    arguments: dict[str, Any],
    timeout_s: float = DEFAULT_TIMEOUT_S,
    workflow_id: str = "",
) -> dict[str, Any]:
    arguments = dict(arguments)
    if workflow_id:
        arguments.setdefault("workflow_id", workflow_id)
        arguments.setdefault("agent_id", workflow_id)
    if tool.startswith("imap.") or tool in _IMAP_TOOLS:
        return _invoke_imap_server(tool, arguments)
    if tool in _ONEC_TOOLS:
        return _invoke_onec_server(tool, arguments, user_id=user_id)
    if tool in _TURBOPROJECT_TOOLS or tool.startswith("turboproject"):
        return _invoke_turboproject_server(tool, arguments)

    request_id = tool_bridge.new_request_id()
    tool_bridge.begin_wait(request_id=request_id, user_id=user_id)
    emit({"type": "tool_call", "tool": tool, "arguments": arguments})
    emit(
        {
            "type": "tool_request",
            "run_id": run_id,
            "request_id": request_id,
            "tool": tool,
            "arguments": arguments,
        }
    )
    try:
        payload = tool_bridge.await_result(
            request_id=request_id,
            timeout_s=timeout_s,
        )
    except TimeoutError as exc:
        raise AgentRuntimeError(str(exc)) from exc

    if not payload.get("ok"):
        raise AgentRuntimeError(str(payload.get("error") or f"Ошибка инструмента {tool}"))
    result = payload.get("result")
    return result if isinstance(result, dict) else {}


def _invoke_turboproject_server(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    from app.services.turboproject import TurboProjectError, invoke_turboproject

    try:
        return invoke_turboproject(tool, arguments)
    except TurboProjectError as exc:
        raise AgentRuntimeError(str(exc)) from exc


def _invoke_imap_server(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    from app.services.imap_tools import ImapToolError, invoke_imap

    try:
        return invoke_imap(tool, arguments)
    except ImapToolError as exc:
        raise AgentRuntimeError(str(exc)) from exc


def _invoke_onec_server(
    tool: str,
    arguments: dict[str, Any],
    *,
    user_id: str = "",
) -> dict[str, Any]:
    from app.services.app_users import get_app_user
    from app.services.onec_tools import OnecToolError, invoke_onec

    fio = ""
    if user_id:
        user = get_app_user(user_id)
        if user is not None:
            fio = str(user.fio or "")
    try:
        return invoke_onec(tool, arguments, actor_user_id=user_id, actor_fio=fio)
    except OnecToolError as exc:
        raise AgentRuntimeError(str(exc)) from exc


def _extract_url(text: str) -> str:
    m = _URL_RE.search(text or "")
    return m.group(0).rstrip(").,;") if m else ""


def _plan_site_url(workflow: Workflow) -> str:
    plan = workflow.plan_json if isinstance(workflow.plan_json, dict) else {}
    runtime = plan.get("runtime") if isinstance(plan.get("runtime"), dict) else {}
    url = str(runtime.get("site_url") or "").strip()
    if url:
        return url
    for c in plan.get("constraints") or []:
        found = _extract_url(str(c))
        if found:
            return found
    return ""


def _keyword_from_task(task: str, workflow: Workflow) -> str:
    """Short search keyword from the user task / plan keywords — no domain dictionaries."""
    plan = workflow.plan_json if isinstance(workflow.plan_json, dict) else {}
    runtime = plan.get("runtime") if isinstance(plan.get("runtime"), dict) else {}
    keywords = runtime.get("keywords") if isinstance(runtime.get("keywords"), list) else []
    if keywords:
        return str(keywords[0]).strip()[:80]

    text = _URL_RE.sub("", task or "")
    text = re.sub(r"[«»\"']", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .-:")
    words = [w for w in text.split() if len(w) > 2][:6]
    return " ".join(words)[:120] if words else ""


def _search_query(task: str, workflow: Workflow) -> str:
    kw = _keyword_from_task(task, workflow)
    return kw or (workflow.title or task)[:120]


def _outlook_tool_request(task: str) -> tuple[str, dict[str, Any]]:
    low = (task or "").casefold()
    if any(tip in low for tip in ("письм", "почт", "mail", "inbox", "входящ", "отправлен")):
        return "outlook.search_mail", {
            "query": task,
            "folder": "All",
            "max_results": 20,
        }
    return "outlook.read_calendar", {"days_forward": 7, "max_results": 30}


def _compose_outlook_tool_answer(
    task: str, tool_name: str, tool_result: dict[str, Any]
) -> str:
    _ = task
    if tool_name == "outlook.search_mail":
        messages = tool_result.get("messages") or []
        if not messages:
            return "В Outlook писем по запросу не найдено."
        lines = [f"Нашла писем: {len(messages)}"]
        for item in messages[:10]:
            if not isinstance(item, dict):
                continue
            subject = str(item.get("subject") or "Без темы")
            sender = str(item.get("sender") or item.get("from") or "")
            lines.append(f"• {subject}" + (f" — {sender}" if sender else ""))
        return "\n".join(lines)
    events = tool_result.get("events") or []
    if not events:
        return "В календаре Outlook событий за выбранный период нет."
    lines = [f"События календаря: {len(events)}"]
    for item in events[:10]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("subject") or item.get("title") or "Без названия")
        start = str(item.get("start") or item.get("start_time") or "")
        lines.append(f"• {title}" + (f" ({start})" if start else ""))
    return "\n".join(lines)


def _compose_onec_desktop_answer(tool_result: dict[str, Any]) -> str:
    documents = tool_result.get("documents") or []
    if not documents:
        return "Документы 1С не найдены."
    lines = [f"Найдено документов 1С: {len(documents)}"]
    for item in documents[:10]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("number") or "Документ")
        status = str(item.get("status") or "")
        lines.append(f"• {title}" + (f" — {status}" if status else ""))
    return "\n".join(lines)


def _compose_outlook_answer(task: str, workflow: Workflow) -> str:
    """Answer meeting/calendar tasks from the plan — do not call site_browser."""
    plan = workflow.plan_json if isinstance(workflow.plan_json, dict) else {}
    goal = str(plan.get("goal") or workflow.title or "").strip()
    constraints = [
        str(x).strip() for x in (plan.get("constraints") or []) if str(x).strip()
    ]
    criteria = [
        str(x).strip() for x in (plan.get("test_criteria") or []) if str(x).strip()
    ]
    answered = _answered_pairs(plan)
    steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []

    lines = [
        f"Задача: {(task or '').strip() or 'выполнить рабочий сценарий агента'}",
        "",
        "Работаю как агент планирования совещаний по правилам своего плана. "
        "Календарь Outlook пока не подключён напрямую в этом чате, поэтому "
        "не лезу в «просмотр сайта».",
        "",
    ]
    if goal:
        lines.append(f"Цель из плана: {goal}")
    if answered:
        lines.append("Ваши ответы при создании (обязательны):")
        for question, answer in answered[:12]:
            lines.append(f"• {question}: {answer}")
    if constraints:
        lines.append("Правила из паспорта / уточнений:")
        for item in constraints[:8]:
            lines.append(f"• {item}")
    if steps:
        lines.append("Шаги плана:")
        for step in steps[:8]:
            if isinstance(step, dict):
                sid = str(step.get("id") or "").strip()
                title = str(step.get("title") or step.get("action") or "").strip()
                lines.append(f"• {sid + ': ' if sid else ''}{title or step}")
            else:
                lines.append(f"• {step}")
    if criteria:
        lines.append("Критерии готовности:")
        for item in criteria[:6]:
            lines.append(f"• {item}")

    lines.extend(
        [
            "",
            "Чтобы продолжить по делу, напишите в чат:",
            "• тему встречи;",
            "• участников;",
            "• желаемое окно времени / длительность;",
            "• нужно ли обязательное подтверждение человека перед созданием в Outlook.",
            "",
            "Интеграции из ваших ответов (1С / COM Outlook и т.п.) сохранены в плане "
            "и должны использоваться при сборке агента; в этом чате пока только сценарий "
            "по правилам, без живого COM.",
        ]
    )
    return "\n".join(lines)


def _answered_pairs(plan: dict[str, Any]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for key in ("answered_questions", "open_questions"):
        raw = plan.get(key) or []
        if isinstance(raw, dict):
            for qid, value in raw.items():
                if isinstance(value, dict):
                    q = str(value.get("question") or qid).strip()
                    a = str(value.get("answer") or "").strip()
                else:
                    q = str(qid).strip()
                    a = str(value).strip()
                if a and a.casefold() not in seen:
                    pairs.append((q or qid, a))
                    seen.add(a.casefold())
            continue
        if not isinstance(raw, list):
            continue
        for item in raw:
            if not isinstance(item, dict):
                continue
            q = str(item.get("question") or item.get("id") or "").strip()
            a = str(item.get("answer") or "").strip()
            if a and a.casefold() not in seen:
                pairs.append((q or str(item.get("id") or "ответ"), a))
                seen.add(a.casefold())
    # Legacy phantom field
    answers = plan.get("answers")
    if isinstance(answers, dict):
        for key, value in answers.items():
            a = str(value).strip() if not isinstance(value, dict) else str(value.get("answer") or "").strip()
            q = str(key) if not isinstance(value, dict) else str(value.get("question") or key)
            if a and a.casefold() not in seen:
                pairs.append((q, a))
                seen.add(a.casefold())
    return pairs


def _site_browser_args(task: str, workflow: Workflow) -> dict[str, Any] | None:
    """Open site_browser only when task or plan explicitly contains a URL."""
    url = _extract_url(task) or _plan_site_url(workflow)
    if not url:
        return None
    return {
        "action": "open",
        "url": url,
        "wait_ms": 2000,
        "max_items": 25,
        "headless": True,
    }


def _compose_answer(task: str, tool_name: str, tool_result: dict[str, Any] | None) -> str:
    _ = task
    if not tool_result:
        return "Не удалось получить данные. Попробуйте ещё раз или уточните задачу."

    if tool_name == "site_browser":
        cards = tool_result.get("cards") or []
        lines = ["Нашла на сайте:"]
        if cards:
            for item in cards[:10]:
                title = str(item.get("title") or "Без названия").strip()
                url = str(item.get("url") or "").strip()
                snippet = str(item.get("text") or "").strip()
                line = f"• {title}"
                if url:
                    line += f"\n  {url}"
                elif snippet:
                    line += f"\n  {snippet[:160]}"
                lines.append(line)
            return "\n".join(lines)
        text = str(tool_result.get("text") or "").strip()
        if text:
            return "Открыла страницу, но список карточек пуст. Фрагмент:\n" + text[:1200]
        return (
            "Не удалось прочитать содержимое страницы. "
            "Проверьте URL в плане агента и доступ в интернет."
        )

    results = tool_result.get("results") or []
    if not results:
        return "Поиск в интернете не дал результатов. Уточните запрос или укажите URL в плане."
    lines = ["Нашла в интернете:"]
    for item in results[:5]:
        title = str(item.get("title") or "Без названия")
        url = str(item.get("url") or "")
        lines.append(f"• {title}\n  {url}".rstrip())
    return "\n".join(lines)
