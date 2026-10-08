import mimetypes
from pathlib import PurePosixPath
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from app.constructor.avatars import USER_ID_PATTERN
from app.constructor.brief import BriefError, ConstructorBrief, build_brief
from app.constructor.catalog import constructor_catalog
from app.constructor.db import fetch_agent_detail, fetch_agent_run
from app.constructor.owners import agent_detail
from app.platform import attachments, profile, shared
from app.platform.approvals import WAIT_SECONDS as APPROVAL_WAIT_SECONDS
from app.platform.approvals import ApprovalError, approvals, classify, hook_reply
from app.platform.attachments import Attachment, AttachmentError, AttachmentUpload, DecodedFile
from app.platform.configs import PlatformConfig, configs_root, find_config, list_configs
from app.platform.history import RemoteRun, machine, reader
from app.platform.instructions import planning_prompt, run_prompt
from app.platform.library import LibraryError, list_login_users, publish as publish_to_library
from app.platform.process import ConfigNotRunnable, cancel_turn, start_turn, wait_idle
from app.platform.questions import WAIT_SECONDS, QuestionAnswer, QuestionError, QuestionItem, questions
from app.platform.sessions import PlatformSession, context_view, metrics_view, parse_stamp, store, trace_view
from app.platform.tool_test import TESTER_CONFIG_ID, tool_test_prompt
from app.tools.registry import get_tool

router = APIRouter(prefix="/platform")

TITLE_CHARS = 60
# Агентов, сформированных в Конструкторе, исполняет та же конфигурация, что и агентов TurboTester.
CONSTRUCTOR_CONFIG_ID = "02-plan-instruction"


class SessionCreate(BaseModel):
    config_id: str
    source: Literal["custom", "constructor"] = "custom"
    prompt: str = ""
    title: str = ""
    constructor_agent_id: str = ""
    attachments: list[AttachmentUpload] = Field(default_factory=list)


class SessionMessage(BaseModel):
    prompt: str = ""
    attachments: list[AttachmentUpload] = Field(default_factory=list)


class AgentRun(BaseModel):
    """Необязательная задача к запуску и вложения (файлы run_inputs агента Конструктора)."""

    prompt: str = ""
    attachments: list[AttachmentUpload] = Field(default_factory=list)


class AgentPublish(BaseModel):
    audience: Literal["all", "selected"] = "all"
    fios: list[str] = Field(default_factory=list)


class QuestionAsk(BaseModel):
    title: str = ""
    questions: list[QuestionItem]


class QuestionReply(BaseModel):
    answers: list[QuestionAnswer] = Field(default_factory=list)
    skipped: bool = False


class ToolUse(BaseModel):
    """Вход хука preToolUse: какой инструмент агент вызывает и с чем."""

    tool_name: str = ""
    tool_input: dict[str, Any] = Field(default_factory=dict)


class ApprovalDecision(BaseModel):
    allow: bool
    remember: bool = False


def _title_from(prompt: str) -> str:
    first = next((line.strip() for line in prompt.splitlines() if line.strip()), "Новый агент")
    first = first.lstrip("#").strip() or "Новый агент"
    return first if len(first) <= TITLE_CHARS else first[: TITLE_CHARS - 1].rstrip() + "…"


def _runnable_config(config_id: str) -> PlatformConfig:
    config = find_config(config_id.strip())
    if config is None:
        raise HTTPException(status_code=404, detail=f"Конфигурация не найдена: {config_id}")
    if not config.runnable:
        raise HTTPException(
            status_code=400,
            detail=config.error or f"У конфигурации «{config.title}» нет entry в config.json",
        )
    return config


def _decoded_attachments(config: PlatformConfig, uploads: list[AttachmentUpload]) -> list[DecodedFile]:
    if not uploads:
        return []
    if not config.attachments:
        raise HTTPException(status_code=400, detail=f"«{config.title}» не принимает вложения")
    try:
        return attachments.decode(uploads)
    except AttachmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _constructor_instruction(agent_id: str) -> tuple[str, str]:
    if not USER_ID_PATTERN.fullmatch(agent_id):
        raise HTTPException(status_code=400, detail="Некорректный id агента")
    try:
        row = fetch_agent_detail(agent_id)
    except Exception as exc:
        message = str(exc).splitlines()[0] or "база недоступна"
        raise HTTPException(status_code=502, detail=f"База Constructor недоступна: {message}") from exc
    detail = agent_detail(row) if row is not None else None
    if detail is None:
        raise HTTPException(status_code=404, detail="Опубликованный агент не найден")
    if not detail.prompt.strip():
        raise HTTPException(status_code=400, detail="У агента нет инструкции")
    return detail.title, detail.prompt.strip()


def _constructor_brief(workflow_id: str) -> ConstructorBrief | None:
    """План агента Конструктора из public.workflows. None — такой записи нет."""
    if not USER_ID_PATTERN.fullmatch(workflow_id):
        return None
    try:
        row = fetch_agent_run(workflow_id)
    except Exception as exc:
        message = str(exc).splitlines()[0] or "база недоступна"
        raise HTTPException(status_code=502, detail=f"База Constructor недоступна: {message}") from exc
    if row is None:
        return None
    try:
        return build_brief(row)
    except BriefError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


LABEL_PLAN = "Задача на план"
LABEL_RUN = "Запуск по плану"
LABEL_RERUN = "Запуск по плану с историей прошлого прогона"


def _remember_run(session_id: str) -> None:
    session = store.get(session_id)
    agent = store.get_agent(session.agent_id) if session else None
    if session is None or agent is None:
        return
    before = agent.runs
    run = store.record_last_run(session_id)
    if run is None:
        return
    shared.publish(agent, session.config_title, added_runs=agent.runs - before)
    if run.status == "finished" and profile.needs_profile(agent):
        profile.schedule(agent.id, session.config_title)


def _after_plan(session_id: str, config: PlatformConfig) -> None:
    """План готов: он становится инструкцией агента, и в той же сессии начинается выполнение."""
    session = store.get(session_id)
    store.release(session_id)
    if session is None or session.status != "running":
        return
    if not session.plan:
        store.finish(session_id, "error", "Агент не составил план — инструкция не создана")
        return
    workspace = store.workspace(session_id)
    agent = store.set_agent_plan(session.agent_id, session.plan, workspace)
    if agent is not None:
        shared.publish(agent, config.title)
    start_turn(
        session_id,
        config,
        run_prompt(session.plan, workspace),
        session.agent_title,
        label=LABEL_RUN,
        on_done=lambda: _remember_run(session_id),
    )


def _start_planning(
    session: PlatformSession, config: PlatformConfig, task: str, files: list[Attachment]
) -> None:
    store.hold(session.id)
    start_turn(
        session.id,
        config,
        planning_prompt(task),
        session.agent_title,
        files,
        mode="plan",
        label=LABEL_PLAN,
        shown=task.strip(),
        on_done=lambda: _after_plan(session.id, config),
    )


def _plan_agent(session: PlatformSession, config: PlatformConfig) -> bool:
    return config.plan_instruction and session.source == "custom"


@router.get("/configs")
def get_configs() -> dict[str, object]:
    return {
        "items": [item.public() for item in list_configs()],
        "root": str(configs_root()),
    }


@router.get("/agents")
def get_agents(config_id: str = "", stored: bool = False) -> dict[str, object]:
    """Без config_id — локальные агенты. С config_id плановой конфигурации — ещё и общие из базы.

    stored=1 — чтение turbotest.agents, без записи.
    """
    if stored:
        items, error = shared.stored_agents()
        return {
            "items": items,
            "shared": {"enabled": shared.enabled(), "source": shared.source(), "error": error},
        }
    local = store.list_agents()
    if not config_id:
        return {"items": [item.model_dump() for item in local]}
    config = find_config(config_id)
    own = [agent for agent in local if agent.config_id == config_id]
    if config is None or not config.plan_instruction:
        return {"items": [item.model_dump() for item in own]}
    items, error = shared.list_agents(config_id, own, config.title)
    return {"items": items, "shared": {"enabled": shared.enabled(), "source": shared.source(), "error": error}}


def _local_device(summary: dict[str, object]) -> dict[str, object]:
    return {**summary, "author": shared.author_name(), "author_host": shared.host_name(), "local": True}


@router.get("/sessions")
def get_sessions(config_id: str = "", limit: int = 50, scope: Literal["local", "all"] = "local") -> dict[str, object]:
    """scope=all — ещё и запуски других компьютеров из общей базы (turbotest.runs)."""
    limit = max(1, min(limit, 500))
    local = [_local_device(item.summary()) for item in store.list(config_id, limit)]
    if scope == "local":
        return {"items": local}
    rows, error = reader.list_runs(limit)
    known = {item["id"] for item in local}
    host = shared.host_name()
    remote = [
        {**row, "local": row["author_host"] == host}
        for row in rows
        if row["id"] not in known and (not config_id or row["config_id"] == config_id)
    ]
    items = sorted(local + remote, key=lambda item: parse_stamp(str(item["updated_at"])), reverse=True)[:limit]
    return {"items": items, "host": host, "history_error": error}


def _source(session_id: str) -> PlatformSession | RemoteRun:
    """Свой запуск — из памяти и диска, чужой — из общей базы, только для просмотра."""
    session = store.get(session_id)
    if session is not None:
        return session
    remote = reader.load(session_id)
    if remote is None:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    return remote


@router.get("/sessions/{session_id}")
def get_session(session_id: str, since: int = 0) -> dict[str, object]:
    found = _source(session_id)
    session = found.session if isinstance(found, RemoteRun) else found
    body: dict[str, object] = {
        "session": session.summary(),
        "events": [event.model_dump() for event in session.events if event.rev > since],
    }
    if isinstance(found, RemoteRun):
        body["remote"] = {"author": found.author, "host": found.host}
    else:
        running = session.status == "running"
        pending = questions.pending(session_id) if running else None
        body["question"] = pending.model_dump() if pending else None
        approval = approvals.pending(session_id) if running else None
        body["approval"] = approval.model_dump() if approval else None
    return body


@router.get("/sessions/{session_id}/trace")
def get_trace(session_id: str, since: int = 0) -> dict[str, object]:
    found = _source(session_id)
    if isinstance(found, RemoteRun):
        return trace_view(found.insights, since)
    return store.trace_since(session_id, since)


@router.get("/sessions/{session_id}/metrics")
def get_metrics(session_id: str, since: float = 0) -> dict[str, object]:
    found = _source(session_id)
    if isinstance(found, RemoteRun):
        return {**metrics_view(found.insights, since, []), **machine(), **found.machine}
    return {**store.metrics_since(session_id, since), **machine()}


@router.get("/sessions/{session_id}/context")
def get_context(session_id: str) -> dict[str, object]:
    found = _source(session_id)
    if isinstance(found, RemoteRun):
        return context_view(found.insights.model_copy(deep=True))
    return store.context(session_id)


@router.get("/sessions/{session_id}/files/{path:path}", response_model=None)
def get_file(session_id: str, path: str) -> FileResponse | Response:
    found = _source(session_id)
    if isinstance(found, RemoteRun):
        body = reader.file(session_id, path)
        if body is None:
            raise HTTPException(status_code=404, detail="Файл не найден")
        kind = mimetypes.guess_type(PurePosixPath(path).name)[0] or "application/octet-stream"
        return Response(content=body, media_type=kind)
    target = attachments.resolve(store.workspace(session_id), path)
    if target is None:
        raise HTTPException(status_code=404, detail="Файл не найден")
    return FileResponse(target)


@router.post("/sessions")
def post_session(body: SessionCreate) -> dict[str, object]:
    config = _runnable_config(body.config_id)
    files = _decoded_attachments(config, body.attachments)
    if body.source == "constructor":
        agent_id = body.constructor_agent_id.strip()
        title, prompt = _constructor_instruction(agent_id)
    else:
        prompt = body.prompt.strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="Пустой промпт")
        title = body.title.strip() or _title_from(prompt)
        planned = config.plan_instruction
        agent_id = store.create_agent(
            title=title,
            instruction="" if planned else prompt,
            config_id=config.id,
            request=prompt if planned else "",
            author=shared.author_name(),
        ).id
    session = store.create_session(
        config_id=config.id,
        config_title=config.title,
        source=body.source,
        agent_id=agent_id,
        agent_title=title,
        prompt=prompt,
    )
    saved = attachments.save(store.workspace(session.id), files)
    try:
        if _plan_agent(session, config):
            _start_planning(session, config, prompt, saved)
        else:
            start_turn(session.id, config, prompt, title, saved)
    except ConfigNotRunnable as exc:
        store.release(session.id)
        store.finish(session.id, "error", str(exc))
    return store.get(session.id).summary()  # type: ignore[union-attr]


@router.get("/publish-users")
def get_publish_users() -> dict[str, object]:
    """ФИО со страницы входа оркестратора — тот же список, что подсказка «Показывать в списке выбора»."""
    try:
        items = list_login_users()
    except LibraryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"items": items}


@router.post("/agents/{agent_id}/publish")
def post_agent_publish(agent_id: str, body: AgentPublish | None = None) -> dict[str, object]:
    """Положить агента конфигурации 2 в оркестратор.

    audience=all — в библиотеку (владелец Ильченко, её видит каталог).
    audience=selected — копия выбранным пользователям со страницы входа.
    Инструкция — готовый план. Если на этом компьютере его нет, берём запись из turbotest.agents.
    """
    payload = body or AgentPublish()
    agent = store.get_agent(agent_id)
    known = find_config(agent.config_id) if agent else None
    if agent is None or (known is not None and known.plan_instruction):
        remote = shared.fetch_agent(agent_id)
        if remote is not None:
            agent = remote
    if agent is None:
        raise HTTPException(status_code=404, detail="Агент не найден")
    config = find_config(agent.config_id)
    if config is None or not config.plan_instruction:
        raise HTTPException(status_code=400, detail="В библиотеку публикуется агент конфигурации 2")
    if not agent.instruction.strip():
        raise HTTPException(status_code=400, detail="У агента ещё нет инструкции — план не составлен")
    try:
        workflow_ids = publish_to_library(agent, audience=payload.audience, fios=payload.fios)
    except LibraryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    constructor_catalog.request_refresh()
    return {
        "workflow_id": workflow_ids[0],
        "workflow_ids": workflow_ids,
        "title": agent.title,
        "audience": payload.audience,
    }


@router.get("/constructor-agents/{workflow_id}")
def get_constructor_agent(workflow_id: str) -> dict[str, object]:
    """Агент, сформированный в Конструкторе, и план, с которым его запустит платформа."""
    brief = _constructor_brief(workflow_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="Агент не найден в базе Constructor")
    return brief.model_dump()


def _run_constructor_agent(brief: ConstructorBrief, body: AgentRun) -> dict[str, object]:
    config = _runnable_config(CONSTRUCTOR_CONFIG_ID)
    files = _decoded_attachments(config, body.attachments)
    task = body.prompt.strip()
    session = store.create_session(
        config_id=config.id,
        config_title=config.title,
        source="constructor",
        agent_id=brief.id,
        agent_title=brief.title,
        prompt=task or brief.plan,
    )
    workspace = store.workspace(session.id)
    saved = attachments.save(workspace, files)
    prompt = run_prompt(brief.plan, workspace)
    if task:
        prompt = f"{prompt}\n\n## Задача этого запуска\n{task}"
    try:
        start_turn(session.id, config, prompt, brief.title, saved, label=LABEL_RUN, shown=task or None)
    except ConfigNotRunnable as exc:
        store.finish(session.id, "error", str(exc))
    return store.get(session.id).summary()  # type: ignore[union-attr]


@router.post("/agents/{agent_id}/runs")
def post_agent_run(agent_id: str, body: AgentRun | None = None) -> dict[str, object]:
    """Новый запуск агента: его инструкция, а для plan_instruction — ещё история прошлого прогона.

    Агента другого пользователя (или более свежую версию своего) сначала берём из общей базы.
    Нет такого агента TurboTester — это агент Конструктора: план собирается из public.workflows.
    """
    payload = body or AgentRun()
    agent = store.get_agent(agent_id)
    known = find_config(agent.config_id) if agent else None
    if agent is None or (known is not None and known.plan_instruction):
        remote = shared.fetch_agent(agent_id)
        agent = store.import_agent(remote) if remote is not None else store.get_agent(agent_id)
    if agent is None:
        brief = _constructor_brief(agent_id)
        if brief is not None:
            return _run_constructor_agent(brief, payload)
        raise HTTPException(status_code=404, detail="Агент не найден")
    config = _runnable_config(agent.config_id)
    if not agent.instruction.strip():
        raise HTTPException(status_code=400, detail="У агента ещё нет инструкции — план не составлен")
    planned = config.plan_instruction
    session = store.create_session(
        config_id=config.id,
        config_title=config.title,
        source="custom",
        agent_id=agent.id,
        agent_title=agent.title,
        prompt=(agent.request or agent.instruction) if planned else agent.instruction,
    )
    if planned:
        prompt = run_prompt(agent.instruction, store.workspace(session.id), agent.last_run)
        label = LABEL_RERUN if agent.last_run is not None else LABEL_RUN
    else:
        prompt, label = agent.instruction, ""
    remember = (lambda: _remember_run(session.id)) if config.plan_instruction else None
    start_turn(session.id, config, prompt, agent.title, label=label, on_done=remember)
    return store.get(session.id).summary()  # type: ignore[union-attr]


@router.delete("/agents/{agent_id}")
def delete_agent(agent_id: str) -> dict[str, object]:
    """Удалить агента у всех: локально и в общей базе. Его прогоны остаются в истории."""
    agent = store.get_agent(agent_id)
    remote = shared.fetch_agent(agent_id)
    owner = remote or agent
    if owner is None:
        raise HTTPException(status_code=404, detail="Агент не найден")
    if owner.author and owner.author != shared.author_name():
        raise HTTPException(status_code=403, detail=f"Удалить агента может только автор — {owner.author}")
    if store.agent_running(agent_id):
        raise HTTPException(status_code=409, detail="Агент сейчас работает — остановите запуск и удалите снова")
    try:
        shared.delete(agent_id)
    except shared.SharedUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"{exc}. Агент не удалён — попробуйте позже") from exc
    store.delete_agent(agent_id)
    return {"deleted": True}


@router.post("/agents/{agent_id}/profile")
def post_agent_profile(agent_id: str) -> dict[str, object]:
    """Заново заполнить паспорт и иконку облачным агентом (для старых агентов и после ошибки)."""
    agent = store.get_agent(agent_id)
    if agent is None:
        remote = shared.fetch_agent(agent_id)
        agent = store.import_agent(remote) if remote is not None else None
    if agent is None:
        raise HTTPException(status_code=404, detail="Агент не найден")
    config = find_config(agent.config_id)
    if config is None or not config.plan_instruction:
        raise HTTPException(status_code=400, detail="Паспорт заполняется только у агентов плановых конфигураций")
    if not agent.instruction.strip():
        raise HTTPException(status_code=400, detail="У агента ещё нет плана — паспорт заполнять не по чему")
    if agent.profile_status != "pending" and not profile.schedule(agent.id, config.title):
        raise HTTPException(status_code=503, detail="Облачный агент недоступен: проверьте CURSOR_API_KEY")
    return {"profile_status": "pending"}


class ToolTestCreate(BaseModel):
    tool: str


@router.post("/tool-tests")
def post_tool_test(body: ToolTestCreate) -> dict[str, object]:
    """Тестовый запуск инструмента служебным агентом. Сессия только в памяти: никуда не записывается."""
    spec = get_tool(body.tool.strip())
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Инструмент не найден: {body.tool}")
    config = _runnable_config(TESTER_CONFIG_ID)
    title = f"Тест: {spec.title or spec.name}"
    session = store.create_session(
        config_id=config.id,
        config_title=config.title,
        source="custom",
        agent_id="",
        agent_title=title,
        prompt=spec.name,
        ephemeral=True,
        test_tool=spec.name,
    )
    try:
        start_turn(session.id, config, tool_test_prompt(spec), title, label="Задача тестировщика")
    except ConfigNotRunnable as exc:
        store.finish(session.id, "error", str(exc))
    return store.get(session.id).summary()  # type: ignore[union-attr]


@router.post("/sessions/{session_id}/messages")
def post_message(session_id: str, body: SessionMessage) -> dict[str, object]:
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    prompt = body.prompt.strip()
    if not prompt and not body.attachments:
        raise HTTPException(status_code=400, detail="Пустой промпт")
    if session.status == "running" or not wait_idle(session_id):
        raise HTTPException(status_code=409, detail="Агент ещё работает — дождитесь ответа или остановите")
    config = _runnable_config(session.config_id)
    files = _decoded_attachments(config, body.attachments)
    saved = attachments.save(store.workspace(session_id), files)
    executing = session.plan_turn == 0 or bool(session.plan)
    remember = (lambda: _remember_run(session_id)) if _plan_agent(session, config) and executing else None
    start_turn(session_id, config, prompt, session.agent_title, saved, on_done=remember)
    return store.get(session_id).summary()  # type: ignore[union-attr]


@router.post("/sessions/{session_id}/cancel")
def post_cancel(session_id: str) -> dict[str, object]:
    if store.get(session_id) is None:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    questions.cancel(session_id)
    for dropped in approvals.cancel(session_id):
        store.settle_approval(session_id, dropped.id, "cancelled")
    return {"cancelling": cancel_turn(session_id)}


# Вопросы агента: ставит и ждёт MCP-сервер конфигурации (ask_user / ask_choice), отвечает экран сессии.
@router.get("/sessions/{session_id}/questions")
def get_open_question(session_id: str) -> dict[str, object]:
    """Открытый вопрос: раннер не завершает ход, пока на него не ответили."""
    pending = questions.pending(session_id)
    return {"question": pending.model_dump() if pending else None}


@router.post("/sessions/{session_id}/questions")
def post_question(session_id: str, body: QuestionAsk) -> dict[str, object]:
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    if session.status != "running":
        raise HTTPException(status_code=409, detail="Сессия не выполняется — спрашивать некого")
    try:
        question = questions.ask(session_id, body.title, body.questions)
    except QuestionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    store.trace(session_id, "runner→platform", "вопрос человеку", text=body.title, data=question.model_dump())
    return question.model_dump()


@router.get("/sessions/{session_id}/questions/{question_id}")
def wait_question(session_id: str, question_id: str, wait: float = 0) -> dict[str, object]:
    try:
        return questions.wait(session_id, question_id, min(wait, WAIT_SECONDS))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Вопрос не найден или снят") from exc


@router.post("/sessions/{session_id}/questions/{question_id}/answer")
def post_answer(session_id: str, question_id: str, body: QuestionReply) -> dict[str, object]:
    if store.get(session_id) is None:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    try:
        text = questions.answer(session_id, question_id, body.answers, skipped=body.skipped)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Вопрос не найден или снят") from exc
    except QuestionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # В ленту ответ не пишем: его показывает карточка вопроса из результата ask_user / ask_choice,
    # а событие посреди хода разрезало бы ещё не дошедший текст агента.
    store.trace(session_id, "user→platform", "ответ на вопрос", text=text)
    return {"ok": True}


# Разрешения: хук preToolUse конфигурации спрашивает, можно ли выполнить действие, экран сессии отвечает.
@router.post("/sessions/{session_id}/approvals")
def post_approval(session_id: str, body: ToolUse) -> dict[str, object]:
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    request = classify(body.tool_name, body.tool_input)
    if request is None:
        return {"status": "allowed", "permission": "allow"}
    if session.status != "running":
        return hook_reply("cancelled")
    if approvals.remembered(session_id, request):
        store.trace(session_id, "platform→runner", "разрешено ранее", text=request.subject)
        return {"status": "allowed", "permission": "allow"}
    approvals.ask(session_id, request)
    store.note_approval(
        session_id, approval_id=request.id, kind=request.kind, title=request.title,
        subject=request.subject, preview=request.preview,
    )
    return {"status": "waiting", "id": request.id}


@router.get("/sessions/{session_id}/approvals/{approval_id}")
def wait_approval(session_id: str, approval_id: str, wait: float = 0) -> dict[str, object]:
    try:
        outcome, expired_now = approvals.wait(session_id, approval_id, min(wait, APPROVAL_WAIT_SECONDS))
    except KeyError:
        return hook_reply("cancelled")
    if expired_now:
        store.settle_approval(session_id, approval_id, "expired")
    return hook_reply(outcome)


@router.post("/sessions/{session_id}/approvals/{approval_id}/decision")
def post_approval_decision(session_id: str, approval_id: str, body: ApprovalDecision) -> dict[str, object]:
    if store.get(session_id) is None:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    try:
        approvals.decide(session_id, approval_id, allow=body.allow, remember=body.remember)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Запрос не найден или снят") from exc
    except ApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    store.settle_approval(
        session_id, approval_id, "allowed" if body.allow else "denied", remember=body.allow and body.remember
    )
    return {"ok": True}
