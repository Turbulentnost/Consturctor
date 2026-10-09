"""Агенты и сессии платформы. Живут в памяти, на диск пишутся в PLATFORM_DATA_DIR."""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.config import settings
from app.platform.attachments import Attachment
from app.platform.passport import AgentPassport

logger = logging.getLogger(__name__)

SessionStatus = Literal["running", "finished", "error", "cancelled"]
AgentSource = Literal["custom", "constructor"]

_STREAMED = {"assistant", "thinking"}
_SAVE_EVERY_SECONDS = 1.5
# Полезная нагрузка одной записи журнала взаимодействия (ответы инструментов бывают огромными).
TRACE_DATA_CHARS = 30_000
# Текст элемента контекста храним с обрезкой, полный размер — в chars.
CONTEXT_TEXT_CHARS = 1_500
METRICS_LIMIT = 7_200
SPIKE_LIMIT = 400
# История прогона идёт в промпт следующего запуска: держим её компактной.
RUN_ARGS_CHARS = 600
RUN_RESULT_CHARS = 1_200
RUN_ANSWER_CHARS = 3_000
RUN_STEPS_LIMIT = 60
# Отделяет задачу пользователя от служебного текста, который платформа дописывает к ходу планирования.
PLANNING_SEPARATOR = "\n\n---\n"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_stamp(value: str) -> datetime:
    try:
        stamp = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[:limit]}… [ещё {len(text) - limit} симв.]"


def _int(value: Any) -> int:
    return int(value) if isinstance(value, (int, float)) and value > 0 else 0


def _tool_fields(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(event.get("name") or ""),
        "status": str(event.get("status") or ""),
        "call_id": str(event.get("callId") or ""),
        "args": str(event.get("args") or ""),
        "result": str(event.get("result") or ""),
        "args_chars": _int(event.get("argsChars")),
        "result_chars": _int(event.get("resultChars")),
    }


def _write_atomic(target: Path, text: str) -> bool:
    """Записать через .tmp. В Windows файл может держать открытым другой процесс
    (антивирус, индексатор, читатель), тогда replace временно отказывает — повторяем."""
    temp = target.with_suffix(".tmp")
    for attempt in range(8):
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            temp.write_text(text, encoding="utf-8")
            temp.replace(target)
            return True
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))
        except OSError as exc:
            logger.warning("platform: не сохранён %s: %s", target.name, exc)
            return False
    logger.warning("platform: %s занят другим процессом, сохраню при следующем изменении", target.name)
    return False


# У каждого запуска своя рабочая папка, поэтому в сохранённых плане и истории её путь
# заменён меткой, а в промпт нового запуска подставляется уже его папка.
WORKSPACE_MARK = "<рабочая папка>"


def _escaped(path: Path) -> str:
    return json.dumps(str(path), ensure_ascii=False)[1:-1]


def _workspace_pattern(workspace: Path) -> re.Pattern[str]:
    exact = {str(workspace), workspace.as_posix(), _escaped(workspace)}
    variants = [re.escape(item) for item in sorted(exact, key=len, reverse=True)]
    variants.append(rf"[^\s\"'`()<>]*?workspaces[\\/]+{re.escape(workspace.name)}")
    return re.compile("|".join(variants), re.IGNORECASE)


def detach_workspace(text: str, workspace: Path) -> str:
    return _workspace_pattern(workspace).sub(WORKSPACE_MARK, text) if text else text


def attach_workspace(text: str, workspace: Path, *, escaped: bool = False) -> str:
    path = _escaped(workspace) if escaped else str(workspace)
    return text.replace(WORKSPACE_MARK, path)


class RunStep(BaseModel):
    """Вызов инструмента в прогоне: что вызвали, с чем и что получили."""

    turn: int
    name: str
    status: str
    args: str = ""
    result: str = ""


class LastRun(BaseModel):
    """История последнего прогона агента — уходит в промпт следующего запуска."""

    session_id: str
    status: str
    finished_at: str
    prompt_turns: int = 0
    steps: list[RunStep] = Field(default_factory=list)
    answer: str = ""
    error: str = ""


class PlatformAgent(BaseModel):
    """Агент, созданный на платформе: его промпт — это инструкция."""

    id: str
    title: str
    instruction: str
    config_id: str
    created_at: str
    # Для конфигураций с plan_instruction: исходная задача пользователя, файл плана и прошлый прогон.
    request: str = ""
    plan_path: str = ""
    last_run: LastRun | None = None
    author: str = ""
    updated_at: str = ""
    runs: int = 0
    # Паспорт и иконку заполняет облачный агент Cursor после первого успешного прогона.
    passport: AgentPassport | None = None
    icon_svg: str = ""
    profile_status: Literal["", "pending", "ready", "error"] = ""
    profile_error: str = ""


class SessionEvent(BaseModel):
    seq: int
    rev: int
    turn: int
    type: str
    text: str = ""
    name: str = ""
    status: str = ""
    call_id: str = ""
    args: str = ""
    result: str = ""
    # Полный размер до обрезки превью раннером — для оценки контекста.
    args_chars: int = 0
    result_chars: int = 0
    attachments: list[Attachment] = Field(default_factory=list)
    # Подпись промпта, который собрала платформа: «Задача на план», «Запуск по плану».
    label: str = ""
    # call_id вызова task: событие — шаг подагента, а не основного агента.
    parent: str = ""


class PlatformSession(BaseModel):
    id: str
    config_id: str
    config_title: str
    source: AgentSource
    agent_id: str
    agent_title: str
    prompt: str
    status: SessionStatus = "running"
    error: str = ""
    sdk_agent_id: str = ""
    turns: int = 0
    # Номер хода планирования (0 — сессия без плана) и полученный план в markdown.
    plan_turn: int = 0
    plan: str = ""
    rev: int = 0
    # Снимок запуска: модель и команда конфигурации на момент старта, не текущий config.json.
    model: str = ""
    entry: list[str] = Field(default_factory=list)
    config_manifest: dict[str, Any] = Field(default_factory=dict)
    # Тестовый запуск инструмента: живёт только в памяти — без файла сессии, общей истории и списков.
    ephemeral: bool = False
    test_tool: str = ""
    created_at: str
    updated_at: str
    events: list[SessionEvent] = Field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return self.model_dump(exclude={"events", "config_manifest"})


class TraceEntry(BaseModel):
    """Запись журнала взаимодействия: кто кому что передал."""

    seq: int
    rev: int
    at: str
    turn: int
    dir: str
    kind: str
    text: str = ""
    data: str = ""
    count: int = 1


class MetricSample(BaseModel):
    t: float
    turn: int
    cpu: float
    ram: float
    ram_mb: float
    gpu: float | None = None
    # Скорость диска процессов агента, МБ/с. Доли диска в процентах Windows по процессу не отдаёт.
    disk: float = 0
    disk_read: float = 0
    disk_write: float = 0
    processes: int = 0
    # Скорость генерации модели, токенов/с: оценка по символам ответа, размышлений и аргументов вызовов.
    gen: float | None = None


class SpikeMark(BaseModel):
    """Один скачок метрики: значение и уровень, от которого он вырос."""

    metric: str
    value: float
    baseline: float


class SpikeEvent(BaseModel):
    """Процессы в момент скачка. Следующий, даже более сильный, не заменяет эту запись."""

    t: float
    turn: int
    marks: list[SpikeMark]
    processes: list[dict[str, Any]] = Field(default_factory=list)


class ContextItem(BaseModel):
    id: str
    turn: int
    type: str
    label: str
    chars: int
    text: str


class ContextSnapshot(BaseModel):
    """Что лежало в контексте агента после шага: id элементов и их размер на тот момент."""

    seq: int
    at: str
    turn: int
    reason: str
    # Тип шага, после которого снят снимок: user, thinking, assistant, tool_call, tool_result.
    kind: str = ""
    items: list[tuple[str, int]] = Field(default_factory=list)
    usage: dict[str, int] | None = None


class SessionInsights(BaseModel):
    trace: list[TraceEntry] = Field(default_factory=list)
    trace_rev: int = 0
    metrics: list[MetricSample] = Field(default_factory=list)
    spikes: list[SpikeEvent] = Field(default_factory=list)
    context_items: dict[str, ContextItem] = Field(default_factory=dict)
    contexts: list[ContextSnapshot] = Field(default_factory=list)
    usage_by_turn: dict[int, dict[str, int]] = Field(default_factory=dict)
    tools: list[str] = Field(default_factory=list)


class SessionStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, PlatformSession] = {}
        self._agents: dict[str, PlatformAgent] = {}
        self._insights: dict[str, SessionInsights] = {}
        self._processes: dict[str, list[dict[str, Any]]] = {}
        # Символы, которые модель выдала с прошлого замера метрик: из них сэмплер считает скорость генерации.
        self._generated: dict[str, int] = {}
        # seq события размышления/ответа, которое ещё дописывается: снимок — когда шаг закончится.
        self._open_step: dict[str, int] = {}
        # Сессии, где за этим ходом сразу идёт следующий: успешный конец хода не завершает сессию.
        self._held: set[str] = set()
        self._saved_at: dict[str, float] = {}
        self._loaded = False

    # -- диск ---------------------------------------------------------------
    @property
    def root(self) -> Path:
        return Path(settings.platform_data_dir)

    def workspace(self, session_id: str) -> Path:
        path = self.root / "workspaces" / session_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def sdk_store_dir(self, config_id: str) -> Path:
        path = self.root / "sdk-store" / config_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def load(self) -> None:
        with self._lock:
            if self._loaded:
                return
            self._loaded = True
            agents_file = self.root / "agents.json"
            if agents_file.is_file():
                try:
                    for raw in json.loads(agents_file.read_text(encoding="utf-8")):
                        agent = PlatformAgent.model_validate(raw)
                        if agent.profile_status == "pending":
                            agent.profile_status = "error"
                            agent.profile_error = "Паспорт не дописан: сервер перезапускался"
                        self._agents[agent.id] = agent
                except (OSError, ValueError) as exc:
                    logger.warning("platform agents.json unreadable: %s", exc)
            folder = self.root / "sessions"
            if not folder.is_dir():
                return
            for path in folder.glob("*.json"):
                if path.name.endswith(".insights.json"):
                    continue
                try:
                    session = PlatformSession.model_validate_json(path.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    logger.warning("platform session %s unreadable: %s", path.name, exc)
                    continue
                if session.status == "running":
                    session.status = "error"
                    session.error = "Запуск прерван перезапуском сервера"
                for event in session.events:
                    if event.type == "user" and event.turn == session.plan_turn and session.plan_turn:
                        event.text = event.text.split(PLANNING_SEPARATOR, 1)[0]
                owner = self._agents.get(session.agent_id)
                if owner is not None and owner.passport is not None:
                    session.agent_title = owner.title
                self._sessions[session.id] = session

    def reset(self) -> None:
        with self._lock:
            self._sessions.clear()
            self._agents.clear()
            self._insights.clear()
            self._processes.clear()
            self._open_step.clear()
            self._held.clear()
            self._saved_at.clear()
            self._loaded = False

    def _insights_path(self, session_id: str) -> Path:
        return self.root / "sessions" / f"{session_id}.insights.json"

    def _insights_for(self, session_id: str) -> SessionInsights:
        insights = self._insights.get(session_id)
        if insights is None:
            path = self._insights_path(session_id)
            insights = SessionInsights()
            if path.is_file():
                try:
                    insights = SessionInsights.model_validate_json(path.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    logger.warning("platform insights %s unreadable: %s", path.name, exc)
            self._insights[session_id] = insights
        return insights

    def _save_insights(self, session_id: str, *, force: bool = False) -> None:
        session = self._sessions.get(session_id)
        if session is not None and session.ephemeral:
            return
        key = f"insights:{session_id}"
        now = time.monotonic()
        if not force and now - self._saved_at.get(key, 0.0) < _SAVE_EVERY_SECONDS:
            return
        self._saved_at[key] = now
        insights = self._insights.get(session_id)
        if insights is None:
            return
        if not _write_atomic(self._insights_path(session_id), insights.model_dump_json()):
            self._saved_at.pop(key, None)

    def _save_session(self, session: PlatformSession, *, force: bool = False, snapshot_files: bool = False) -> None:
        if session.ephemeral:
            return
        now = time.monotonic()
        if not force and now - self._saved_at.get(session.id, 0.0) < _SAVE_EVERY_SECONDS:
            return
        self._saved_at[session.id] = now
        if not _write_atomic(self.root / "sessions" / f"{session.id}.json", session.model_dump_json()):
            self._saved_at.pop(session.id, None)
        self._remember(session, snapshot_files=snapshot_files)

    def _save_agents(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = [agent.model_dump() for agent in self._agents.values()]
        (self.root / "agents.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # -- агенты -------------------------------------------------------------
    def create_agent(
        self, *, title: str, instruction: str, config_id: str, request: str = "", author: str = ""
    ) -> PlatformAgent:
        self.load()
        with self._lock:
            stamp = _now()
            agent = PlatformAgent(
                id=str(uuid4()),
                title=title,
                instruction=instruction,
                config_id=config_id,
                created_at=stamp,
                request=request,
                author=author,
                updated_at=stamp,
            )
            self._agents[agent.id] = agent
            self._save_agents()
            return agent

    def import_agent(self, remote: PlatformAgent) -> PlatformAgent:
        """Агент из общей базы заменяет локальную копию: база — общая правда для всех пользователей."""
        self.load()
        with self._lock:
            agent = remote.model_copy(deep=True)
            if agent.instruction:
                folder = self.root / "plans"
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / f"{agent.id}.plan.md"
                path.write_text(agent.instruction, encoding="utf-8")
                agent.plan_path = str(path)
            self._agents[agent.id] = agent
            self._save_agents()
            return agent

    def list_agents(self) -> list[PlatformAgent]:
        self.load()
        with self._lock:
            return sorted(self._agents.values(), key=lambda a: a.created_at, reverse=True)

    def get_agent(self, agent_id: str) -> PlatformAgent | None:
        self.load()
        with self._lock:
            return self._agents.get(agent_id)

    def agent_running(self, agent_id: str) -> bool:
        self.load()
        with self._lock:
            return any(s.agent_id == agent_id and s.status == "running" for s in self._sessions.values())

    def delete_agent(self, agent_id: str) -> bool:
        """Убрать агента и его план. Прогоны остаются в истории: это статистика, а не часть агента."""
        self.load()
        with self._lock:
            if self._agents.pop(agent_id, None) is None:
                return False
            (self.root / "plans" / f"{agent_id}.plan.md").unlink(missing_ok=True)
            self._save_agents()
            return True

    def set_agent_plan(
        self, agent_id: str, plan: str, workspace: Path | None = None
    ) -> PlatformAgent | None:
        """План становится инструкцией агента и сохраняется рядом с данными платформы как .plan.md."""
        if workspace is not None:
            plan = detach_workspace(plan, workspace)
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                return None
            folder = self.root / "plans"
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{agent_id}.plan.md"
            path.write_text(plan, encoding="utf-8")
            agent.instruction = plan
            agent.plan_path = str(path)
            agent.updated_at = _now()
            self._save_agents()
            return agent

    def set_agent_profile(
        self,
        agent_id: str,
        *,
        status: Literal["pending", "ready", "error"],
        passport: AgentPassport | None = None,
        icon_svg: str = "",
        error: str = "",
    ) -> PlatformAgent | None:
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                return None
            agent.profile_status = status
            agent.profile_error = error
            if status == "ready":
                agent.passport = passport
                agent.icon_svg = icon_svg
                if passport is not None and passport.name:
                    agent.title = passport.name
                    for session in self._sessions.values():
                        if session.agent_id == agent_id and session.agent_title != agent.title:
                            session.agent_title = agent.title
                            self._save_session(session, force=True)
                agent.updated_at = _now()
            self._save_agents()
            return agent.model_copy(deep=True)

    def record_last_run(self, session_id: str) -> LastRun | None:
        """Запомнить у агента прогон сессии: все ходы после планирования, их вызовы и итог."""
        with self._lock:
            session = self._sessions.get(session_id)
            agent = self._agents.get(session.agent_id) if session else None
            if session is None or agent is None:
                return None
            events = [e for e in session.events if e.turn > session.plan_turn and not e.parent]
            if not any(e.type == "user" for e in events):
                return None
            workspace = self.root / "workspaces" / session.id
            steps = [
                RunStep(
                    turn=e.turn,
                    name=e.name or "инструмент",
                    status=e.status,
                    args=_clip(detach_workspace(e.args, workspace), RUN_ARGS_CHARS),
                    result=_clip(detach_workspace(e.result, workspace), RUN_RESULT_CHARS),
                )
                for e in events
                if e.type == "tool" and e.name != "createPlan"
            ]
            if len(steps) > RUN_STEPS_LIMIT:
                steps = steps[:RUN_STEPS_LIMIT]
            last_turn = max(e.turn for e in events)
            answer = "".join(e.text for e in events if e.type == "assistant" and e.turn == last_turn)
            run = LastRun(
                session_id=session.id,
                status=session.status,
                finished_at=_now(),
                prompt_turns=sum(1 for e in events if e.type == "user"),
                steps=steps,
                answer=_clip(detach_workspace(answer, workspace), RUN_ANSWER_CHARS),
                error=session.error,
            )
            if agent.last_run is None or agent.last_run.session_id != session.id:
                agent.runs += 1
            agent.last_run = run
            agent.updated_at = run.finished_at
            self._save_agents()
            return run

    # -- цепочка ходов ------------------------------------------------------
    def hold(self, session_id: str) -> None:
        with self._lock:
            self._held.add(session_id)

    def release(self, session_id: str) -> None:
        with self._lock:
            self._held.discard(session_id)

    # -- сессии -------------------------------------------------------------
    def create_session(
        self,
        *,
        config_id: str,
        config_title: str,
        source: AgentSource,
        agent_id: str,
        agent_title: str,
        prompt: str,
        ephemeral: bool = False,
        test_tool: str = "",
    ) -> PlatformSession:
        self.load()
        with self._lock:
            stamp = _now()
            session = PlatformSession(
                id=str(uuid4()),
                config_id=config_id,
                config_title=config_title,
                source=source,
                agent_id=agent_id,
                agent_title=agent_title,
                prompt=prompt,
                ephemeral=ephemeral,
                test_tool=test_tool,
                created_at=stamp,
                updated_at=stamp,
            )
            self._sessions[session.id] = session
            self._save_session(session, force=True)
            return session

    def get(self, session_id: str) -> PlatformSession | None:
        self.load()
        with self._lock:
            return self._sessions.get(session_id)

    def list(self, config_id: str = "", limit: int = 50) -> list[PlatformSession]:
        self.load()
        with self._lock:
            items = [
                s
                for s in self._sessions.values()
                if not s.ephemeral and (not config_id or s.config_id == config_id)
            ]
        items.sort(key=lambda s: s.updated_at, reverse=True)
        return items[:limit]

    def note_launch(self, session_id: str, *, model: str, entry: list[str], config_path: str) -> None:
        """Запомнить конфигурацию, с которой реально стартует этот ход."""
        from app.platform.history import read_manifest

        manifest = read_manifest(config_path)
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            session.model = model
            session.entry = list(entry)
            session.config_manifest = manifest

    def begin_turn(
        self,
        session_id: str,
        prompt: str,
        attachments: list[Attachment] | None = None,
        *,
        label: str = "",
        planning: bool = False,
        shown: str | None = None,
    ) -> PlatformSession:
        """shown — что увидит пользователь в чате; агенту и в трассировку уходит полный prompt."""
        files = list(attachments or [])
        with self._lock:
            session = self._sessions[session_id]
            session.turns += 1
            session.status = "running"
            session.error = ""
            if planning:
                session.plan_turn = session.turns
            self._open_step.pop(session_id, None)
            event = {"type": "user", "text": prompt if shown is None else shown, "attachments": files, "label": label}
            self._append(session, event)
            self._save_session(session, force=True)
            self.trace(
                session_id,
                "user→platform",
                "prompt",
                text=prompt,
                data={"attachments": [item.model_dump() for item in files]} if files else None,
            )
            insights = self._insights_for(session_id)
            label = "Инструкция" if session.turns == 1 else f"Сообщение пользователя (ход {session.turns})"
            text = prompt
            if files:
                text += "\n\nВложения: " + ", ".join(
                    f"{item.name} ({'изображение' if item.image else item.mime})" for item in files
                )
            self._context_item(insights, f"{session.turns}:user", session.turns, "user", label, text, len(text))
            self._step_snapshot(session, "user", "промпт")
            self._save_insights(session_id, force=True)
            return session

    # -- взаимодействие, ресурсы, контекст ----------------------------------
    def trace(
        self,
        session_id: str,
        direction: str,
        kind: str,
        *,
        text: str = "",
        data: Any = None,
        merge: bool = False,
    ) -> None:
        """Записать шаг взаимодействия. merge склеивает подряд идущие дельты одного вида."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            insights = self._insights_for(session_id)
            payload = ""
            if data is not None:
                payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, default=str)
                payload = _clip(payload, TRACE_DATA_CHARS)
            last = insights.trace[-1] if insights.trace else None
            insights.trace_rev += 1
            if (
                merge
                and last is not None
                and last.count > 0
                and last.dir == direction
                and last.kind == kind
                and last.turn == session.turns
                and not last.data
            ):
                last.text += text
                last.count += 1
                last.rev = insights.trace_rev
            else:
                insights.trace.append(
                    TraceEntry(
                        seq=len(insights.trace) + 1,
                        rev=insights.trace_rev,
                        at=_now(),
                        turn=session.turns,
                        dir=direction,
                        kind=kind,
                        text=text,
                        data=payload,
                    )
                )
            self._save_insights(session_id)

    def add_metric(
        self,
        session_id: str,
        sample: MetricSample,
        processes: list[dict[str, Any]],
        spike_marks: list[tuple[str, float, float]] | None = None,
    ) -> None:
        with self._lock:
            if session_id not in self._sessions:
                return
            insights = self._insights_for(session_id)
            insights.metrics.append(sample)
            if len(insights.metrics) > METRICS_LIMIT:
                del insights.metrics[: len(insights.metrics) - METRICS_LIMIT]
            self._processes[session_id] = processes
            if spike_marks:
                insights.spikes.append(
                    SpikeEvent(
                        t=sample.t,
                        turn=sample.turn,
                        marks=[SpikeMark(metric=metric, value=value, baseline=baseline) for metric, value, baseline in spike_marks],
                        processes=[dict(item) for item in processes],
                    )
                )
                if len(insights.spikes) > SPIKE_LIMIT:
                    del insights.spikes[: len(insights.spikes) - SPIKE_LIMIT]
            self._save_insights(session_id)

    def set_tools(self, session_id: str, tools: list[str]) -> None:
        with self._lock:
            if session_id not in self._sessions:
                return
            self._insights_for(session_id).tools = [str(name) for name in tools]

    def set_usage(self, session_id: str, usage: dict[str, Any]) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            insights = self._insights_for(session_id)
            clean = {key: int(value) for key, value in usage.items() if isinstance(value, (int, float))}
            insights.usage_by_turn[session.turns] = clean
            for snapshot in reversed(insights.contexts):
                if snapshot.turn != session.turns:
                    break
                snapshot.usage = clean
            self._save_insights(session_id)

    def _close_step(self, session: PlatformSession) -> None:
        """Размышление или ответ закончились (пришёл шаг другого вида) — снимаем контекст."""
        seq = self._open_step.pop(session.id, None)
        if seq is None or seq > len(session.events):
            return
        kind = session.events[seq - 1].type
        self._step_snapshot(session, kind, "размышление" if kind == "thinking" else "ответ")

    def _step_snapshot(self, session: PlatformSession, kind: str, reason: str) -> None:
        """Контекст после шага: прошлые ходы + промпт + все шаги текущего хода из потока SDK."""
        turn = session.turns
        insights = self._insights_for(session.id)
        items: list[tuple[str, int]] = [(f"{turn}:user", len(self._turn_prompt(session, turn)))]
        for event in session.events:
            if event.turn != turn or event.parent:
                continue
            if event.type in _STREAMED and event.text:
                label = "Размышления" if event.type == "thinking" else "Ответ ассистента"
                parts = [(f"{turn}:e{event.seq}", event.type, label, event.text, len(event.text))]
            elif event.type == "tool":
                name = event.name or "инструмент"
                parts = [
                    (f"{turn}:e{event.seq}:args", "tool_call", f"{name} · аргументы", event.args, event.args_chars),
                    (f"{turn}:e{event.seq}:result", "tool_result", f"{name} · результат", event.result, event.result_chars),
                ]
            else:
                continue
            for item_id, item_type, label, text, chars in parts:
                size = chars or len(text)
                if not size:
                    continue
                known = insights.context_items.get(item_id)
                if known is None or known.chars != size:
                    self._context_item(insights, item_id, turn, item_type, label, text, size)
                items.append((item_id, size))
        self._snapshot(insights, turn, reason, items, kind)
        self._save_insights(session.id)

    @staticmethod
    def _turn_prompt(session: PlatformSession, turn: int) -> str:
        return next((e.text for e in session.events if e.type == "user" and e.turn == turn), "")

    @staticmethod
    def _context_item(
        insights: SessionInsights, item_id: str, turn: int, kind: str, label: str, text: str, chars: int
    ) -> None:
        insights.context_items[item_id] = ContextItem(
            id=item_id,
            turn=turn,
            type=kind,
            label=label,
            chars=chars,
            text=_clip(text, CONTEXT_TEXT_CHARS),
        )

    @staticmethod
    def _snapshot(
        insights: SessionInsights, turn: int, reason: str, current: list[tuple[str, int]], kind: str
    ) -> None:
        earlier = next((s for s in reversed(insights.contexts) if s.turn < turn), None)
        items: list[tuple[str, int]] = []
        if insights.tools:
            items.append(("tools", sum(len(name) + 2 for name in insights.tools)))
        if earlier is not None:
            items.extend(item for item in earlier.items if item[0] != "tools")
        items.extend(current)
        insights.contexts.append(
            ContextSnapshot(
                seq=len(insights.contexts) + 1,
                at=_now(),
                turn=turn,
                reason=reason,
                kind=kind,
                items=items,
                usage=insights.usage_by_turn.get(turn),
            )
        )

    def trace_since(self, session_id: str, since: int) -> dict[str, Any]:
        with self._lock:
            return trace_view(self._insights_for(session_id), since)

    def take_generated(self, session_id: str) -> int:
        with self._lock:
            return self._generated.pop(session_id, 0)

    def metrics_since(self, session_id: str, since: float) -> dict[str, Any]:
        with self._lock:
            return metrics_view(self._insights_for(session_id), since, self._processes.get(session_id, []))

    def context(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            return context_view(self._insights_for(session_id))

    def insights_copy(self, session_id: str) -> SessionInsights:
        with self._lock:
            return self._insights_for(session_id).model_copy(deep=True)

    def apply(self, session_id: str, event: dict[str, Any]) -> None:
        """Принять событие раннера: дельты текста склеиваются, вызовы обновляются по call_id."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            kind = str(event.get("type") or "")
            if kind == "agent":
                session.sdk_agent_id = str(event.get("agentId") or session.sdk_agent_id)
                self._touch(session)
            elif kind == "done":
                status = str(event.get("status") or "finished")
                agent_id = str(event.get("agentId") or "")
                if agent_id:
                    session.sdk_agent_id = agent_id
                self.finish(session_id, "cancelled" if status == "cancelled" else "error" if status == "error" else "finished")
                return
            elif event.get("parent"):
                if not self._apply_subagent(session, kind, str(event["parent"]), event):
                    return
            elif kind in _STREAMED:
                # Разрешения приходят от хука вне потока SDK (часто — на действие подагента) и не прерывают ответ.
                last = next((e for e in reversed(session.events) if not e.parent and e.type != "approval"), None)
                text = str(event.get("text") or "")
                self._generated[session_id] = self._generated.get(session_id, 0) + len(text)
                if last and last.type == kind and last.turn == session.turns:
                    last.text += text
                    session.rev += 1
                    last.rev = session.rev
                    self._touch(session)
                else:
                    self._close_step(session)
                    self._append(session, {"type": kind, "text": text})
                    self._open_step[session_id] = session.events[-1].seq
            elif kind == "tool_call":
                self._close_step(session)
                call_id = str(event.get("callId") or "")
                existing = next(
                    (
                        e
                        for e in reversed(session.events)
                        if call_id and e.call_id == call_id and e.turn == session.turns and not e.parent
                    ),
                    None,
                )
                fields = _tool_fields(event)
                before = existing.status if existing else ""
                if existing is None:
                    self._generated[session_id] = self._generated.get(session_id, 0) + fields["args_chars"]
                    self._append(session, {"type": "tool", **fields})
                    existing = session.events[-1]
                else:
                    for key, value in fields.items():
                        if value:
                            setattr(existing, key, value)
                    session.rev += 1
                    existing.rev = session.rev
                    self._touch(session)
                name = existing.name or "инструмент"
                if not before:
                    self._step_snapshot(session, "tool_call", f"вызов · {name}")
                if existing.status not in ("", "running") and before in ("", "running"):
                    failed = existing.status == "error"
                    self._step_snapshot(session, "tool_result", f"{'ошибка' if failed else 'результат'} · {name}")
            elif kind == "plan":
                self._close_step(session)
                session.plan = str(event.get("markdown") or "").strip()
                if not session.plan:
                    return
                self._append(session, {"type": "plan", "text": session.plan, "name": str(event.get("name") or "")})
            elif kind == "error":
                self._close_step(session)
                session.error = str(event.get("text") or "Ошибка запуска")
                self._append(session, {"type": "error", "text": session.error})
            elif kind == "status":
                self._append(session, {"type": "status", "text": str(event.get("text") or "")})
            else:
                return
            self._save_session(session)

    def _apply_subagent(self, session: PlatformSession, kind: str, parent: str, event: dict[str, Any]) -> bool:
        """Шаг подагента. В контекст основного агента он не попадает, поэтому без снимков контекста."""
        own = (e for e in reversed(session.events) if e.parent == parent)
        if kind in _STREAMED:
            text = str(event.get("text") or "")
            self._generated[session.id] = self._generated.get(session.id, 0) + len(text)
            last = next(own, None)
            if last and last.type == kind:
                last.text += text
                session.rev += 1
                last.rev = session.rev
                self._touch(session)
            else:
                self._append(session, {"type": kind, "text": text, "parent": parent})
            return True
        if kind != "tool_call":
            return False
        fields = _tool_fields(event)
        existing = next((e for e in own if fields["call_id"] and e.call_id == fields["call_id"]), None)
        if existing is None:
            self._generated[session.id] = self._generated.get(session.id, 0) + fields["args_chars"]
            self._append(session, {"type": "tool", "parent": parent, **fields})
            return True
        for key, value in fields.items():
            if value:
                setattr(existing, key, value)
        session.rev += 1
        existing.rev = session.rev
        self._touch(session)
        return True

    def note_approval(
        self, session_id: str, *, approval_id: str, kind: str, title: str, subject: str, preview: str = ""
    ) -> None:
        """Агент просит разрешения: событие висит со статусом waiting, пока человек не решит.

        Шаг ответа не закрываем: текст, который агент продолжит печатать, допишется к начатому.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            self._append(
                session,
                {
                    "type": "approval", "call_id": approval_id, "name": kind, "text": title,
                    "args": subject, "result": preview, "status": "waiting",
                },
            )
            self.trace(session_id, "agent→user", "запрос разрешения", data={"kind": kind, "subject": subject}, text=title)
            self._save_session(session, force=True)

    def settle_approval(self, session_id: str, approval_id: str, outcome: str, *, remember: bool = False) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            event = next((e for e in reversed(session.events) if e.type == "approval" and e.call_id == approval_id), None)
            if event is None or event.status == outcome:
                return
            event.status = outcome
            event.label = "до конца запуска" if remember else ""
            session.rev += 1
            event.rev = session.rev
            self._touch(session)
            self.trace(
                session_id, "user→platform", "решение по разрешению",
                data={"outcome": outcome, "remember": remember}, text=event.text,
            )
            self._save_session(session, force=True)

    def finish(self, session_id: str, status: SessionStatus, error: str = "") -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None or session.status != "running":
                return
            self._close_step(session)
            self._generated.pop(session_id, None)
            if status == "finished" and session_id in self._held:
                self._save_session(session, force=True)
                return
            session.status = status
            if error:
                session.error = error
                self._append(session, {"type": "error", "text": error})
            self._touch(session)
            self._save_session(session, force=True, snapshot_files=True)
            self._processes.pop(session_id, None)
            if session_id in self._insights:
                self._save_insights(session_id, force=True)

    def _append(self, session: PlatformSession, fields: dict[str, Any]) -> None:
        session.rev += 1
        session.events.append(
            SessionEvent(seq=len(session.events) + 1, rev=session.rev, turn=session.turns, **fields)
        )
        self._touch(session)

    def _remember(self, session: PlatformSession, *, snapshot_files: bool = False) -> None:
        """Отдать снимок в историю. В конце прогона — с файлами каталога и статистикой."""
        from app.platform.history import history

        workspace = self.root / "workspaces" / session.id if snapshot_files else None
        insights = self._insights_for(session.id).model_copy(deep=True) if snapshot_files else None
        history.submit(session.model_copy(deep=True), workspace, insights=insights)

    @staticmethod
    def _touch(session: PlatformSession) -> None:
        session.updated_at = _now()


# -- представления статистики: и для своих запусков, и для запусков из общей базы --
def trace_view(insights: SessionInsights, since: int) -> dict[str, Any]:
    entries = [e.model_dump() for e in insights.trace if e.rev > since]
    return {"rev": insights.trace_rev, "entries": entries}


def metrics_view(insights: SessionInsights, since: float, processes: list[dict[str, Any]]) -> dict[str, Any]:
    samples = [m.model_dump() for m in insights.metrics if m.t > since]
    spikes = insights.spikes
    if not spikes and insights.metrics:
        # Старые запуски писались без снимков: скачки восстанавливаются по ряду, процессов в них уже нет.
        from app.platform.metrics import spikes_from_samples

        spikes = spikes_from_samples(insights.metrics)
    return {
        "samples": samples,
        "processes": list(processes),
        "spikes": [item.model_dump() for item in spikes],
        # Точное число выходных токенов хода из итога SDK: по нему считается средняя скорость генерации.
        "output_tokens": {
            str(turn): usage["outputTokens"] for turn, usage in insights.usage_by_turn.items() if usage.get("outputTokens")
        },
    }


def context_view(insights: SessionInsights) -> dict[str, Any]:
    if insights.tools:
        SessionStore._context_item(
            insights,
            "tools",
            0,
            "tools",
            f"Определения инструментов ({len(insights.tools)})",
            ", ".join(insights.tools),
            sum(len(name) + 2 for name in insights.tools),
        )
    return {
        "items": {key: item.model_dump() for key, item in insights.context_items.items()},
        "snapshots": [s.model_dump() for s in insights.contexts],
    }


store = SessionStore()
