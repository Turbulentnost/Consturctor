from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Signal

from app import config
from app.api import rest_client
from app.api.rest_client import RestApiError
from app.workflow import prompts, storage
from app.workflow.document import (
    DocumentError,
    collect_prompt_images,
    load_attachment,
    load_document,
)
from app.workflow.models import AttachedFile, WorkflowPlan, WorkflowRecord

_TERMINAL = {"FINISHED", "ERROR", "CANCELLED", "EXPIRED", "FAILED"}


@dataclass
class PhaseResult:
    agent_id: str = ""
    run_id: str = ""
    status: str = ""
    text: str = ""
    branch: str = ""
    pr_url: str = ""
    error: str = ""
    git: dict[str, Any] = field(default_factory=dict)


def resolve_model() -> str | None:
    preferred = config.model_id()
    try:
        models = rest_client.list_models()
    except RestApiError:
        return preferred or None
    ids: list[str] = []
    for model in models:
        mid = str(model.get("id") or "")
        if mid:
            ids.append(mid)
        aliases = {str(a) for a in (model.get("aliases") or [])}
        if preferred and (mid == preferred or preferred in aliases):
            return mid
    for mid in ids:
        if mid.startswith(preferred or "composer"):
            return mid
    return preferred or (ids[0] if ids else None)


def _extract_git(git: dict[str, Any] | None) -> tuple[str, str]:
    if not git:
        return "", ""
    branches = git.get("branches") or []
    if branches and isinstance(branches[0], dict):
        first = branches[0]
        return str(first.get("branch") or ""), str(first.get("prUrl") or first.get("pr_url") or "")
    return "", ""


def _format_event(event: str, payload: dict[str, Any]) -> str | None:
    if event == "assistant":
        return str(payload.get("text") or "") or None
    if event == "thinking":
        text = str(payload.get("text") or "")
        return f"\n[thinking] {text}" if text else None
    if event == "tool_call":
        name = payload.get("name") or "tool"
        status = payload.get("status") or ""
        return f"\n[tool] {name}: {status}\n"
    if event == "status":
        status = payload.get("status") or ""
        return f"\n[status] {status}\n" if status else None
    if event == "error":
        msg = payload.get("message") or payload.get("code") or "stream error"
        return f"\n[error] {msg}\n"
    return None


def _stream_run(
    agent_id: str,
    run_id: str,
    *,
    on_event: Callable[[str], None] | None,
    should_cancel: Callable[[], bool] | None,
) -> PhaseResult:
    result = PhaseResult(agent_id=agent_id, run_id=run_id)
    assistant_parts: list[str] = []
    got_terminal = False

    try:
        for event, payload in rest_client.iter_run_sse(
            agent_id, run_id, should_cancel=should_cancel
        ):
            if event == "assistant":
                assistant_parts.append(str(payload.get("text") or ""))
            line = _format_event(event, payload)
            if line and on_event:
                on_event(line)
            if event == "result":
                got_terminal = True
                result.status = str(payload.get("status") or "")
                if payload.get("text"):
                    result.text = str(payload.get("text"))
                result.git = payload.get("git") or {}
                result.branch, result.pr_url = _extract_git(result.git)
            if event == "error":
                result.error = str(payload.get("message") or payload.get("code") or "")
    except RestApiError as exc:
        # Stream may have expired/disconnected; fall back to polling terminal state.
        if not got_terminal and on_event:
            on_event(f"\n[stream] {exc.message} → читаю финальный статус\n")

    if not result.text:
        result.text = "".join(assistant_parts).strip()

    if not got_terminal:
        # Stream was unavailable/interrupted. Poll the run until it reaches a
        # terminal state so we don't lose the result if it was still RUNNING.
        result = _poll_until_terminal(
            agent_id,
            run_id,
            base=result,
            on_event=on_event,
            should_cancel=should_cancel,
        )

    return result


def _poll_until_terminal(
    agent_id: str,
    run_id: str,
    *,
    base: PhaseResult,
    on_event: Callable[[str], None] | None,
    should_cancel: Callable[[], bool] | None,
    max_wait_s: float = 900.0,
    interval_s: float = 5.0,
) -> PhaseResult:
    import time

    result = base
    if not run_id:
        return result

    deadline = time.monotonic() + max_wait_s
    last_reported = ""
    while True:
        if should_cancel and should_cancel():
            break
        try:
            run = rest_client.get_run(agent_id, run_id)
        except RestApiError:
            break

        status = str(run.get("status") or "")
        if status and status != last_reported and on_event:
            on_event(f"\n[poll] статус: {status}\n")
            last_reported = status
        result.status = status or result.status
        if run.get("result"):
            result.text = str(run.get("result"))
        result.git = run.get("git") or result.git
        result.branch, result.pr_url = _extract_git(result.git)

        if status in _TERMINAL:
            break
        if time.monotonic() >= deadline:
            if on_event:
                on_event("\n[poll] превышено время ожидания результата\n")
            break
        time.sleep(interval_s)

    return result


def run_plan_phase(
    record: WorkflowRecord,
    *,
    on_event: Callable[[str], None] | None = None,
    on_ids: Callable[[str, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> WorkflowRecord:
    images = collect_prompt_images(record.attachments)
    has_text = bool((record.document_text or "").strip())
    if not has_text and not images:
        raise RestApiError("Нет материалов для планирования — загрузите файлы или заметки.")

    prompt = prompts.build_plan_prompt(
        document_text=record.document_text,
        document_name=record.document_name,
        image_count=len(images),
        attachment_names=[a.name for a in record.attachments],
    )
    model = resolve_model()
    if on_event and images:
        on_event(f"→ К промпту прикреплено изображений: {len(images)}\n")
    created = rest_client.create_agent(
        prompt=prompt,
        model_id=model,
        repo_url=None,  # planning needs no repo
        # NB: mode="agent" (not "plan"): plan mode emits its own plan artifact and
        # prose, ignoring our strict JSON contract. With no repo it can't touch code.
        mode="agent",
        name=record.name,
        images=images or None,
    )
    agent = created.get("agent") or {}
    run = created.get("run") or {}
    agent_id = str(agent.get("id") or "")
    run_id = str(run.get("id") or "")
    record.plan_agent_id = agent_id
    record.plan_run_id = run_id
    if on_ids:
        on_ids(agent_id, run_id)

    phase = _stream_run(agent_id, run_id, on_event=on_event, should_cancel=should_cancel)
    record.plan = prompts.parse_plan_from_text(phase.text)
    record.phase = "clarify" if record.plan.unanswered() else "ready"
    storage.save_workflow(record)
    return record


def run_clarify_phase(
    record: WorkflowRecord,
    answers: dict[str, str],
    *,
    on_event: Callable[[str], None] | None = None,
    on_ids: Callable[[str, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> WorkflowRecord:
    if record.plan is None:
        raise RestApiError("Нет плана для уточнения")
    for q in record.plan.open_questions:
        if q.id in answers:
            q.answer = answers[q.id]

    prompt = prompts.build_clarify_prompt(answers=answers, plan=record.plan)

    if record.plan_agent_id:
        run = rest_client.create_run(record.plan_agent_id, prompt=prompt, mode="agent")
        agent_id = record.plan_agent_id
        run_id = str(run.get("id") or "")
    else:
        created = rest_client.create_agent(
            prompt=prompt, model_id=resolve_model(), mode="agent", name=record.name
        )
        agent_id = str((created.get("agent") or {}).get("id") or "")
        run_id = str((created.get("run") or {}).get("id") or "")
        record.plan_agent_id = agent_id
    record.plan_run_id = run_id
    if on_ids:
        on_ids(agent_id, run_id)

    phase = _stream_run(agent_id, run_id, on_event=on_event, should_cancel=should_cancel)
    updated = prompts.parse_plan_from_text(phase.text)
    # keep answers even if agent dropped them
    prior = {q.id: q.answer for q in record.plan.open_questions if q.answer}
    for q in updated.open_questions:
        if not q.answer and q.id in prior:
            q.answer = prior[q.id]
    record.plan = updated
    record.phase = "clarify" if record.plan.unanswered() else "ready"
    storage.save_workflow(record)
    return record


def run_execute_phase(
    record: WorkflowRecord,
    *,
    reexecute: bool = False,
    on_event: Callable[[str], None] | None = None,
    on_ids: Callable[[str, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> WorkflowRecord:
    if record.plan is None:
        raise RestApiError("Нет плана для выполнения")

    if reexecute:
        prompt = prompts.build_reexecute_prompt(plan=record.plan)
    else:
        prompt = prompts.build_execute_prompt(
            plan=record.plan, document_text=record.document_text
        )

    # Reuse existing execution agent (keeps conversation context) when possible.
    if reexecute and record.exec_agent_id:
        try:
            run = rest_client.create_run(record.exec_agent_id, prompt=prompt, mode="agent")
            agent_id = record.exec_agent_id
            run_id = str(run.get("id") or "")
        except RestApiError:
            agent_id, run_id = _create_exec_agent(record, prompt)
    else:
        agent_id, run_id = _create_exec_agent(record, prompt)

    record.exec_agent_id = agent_id
    record.exec_run_id = run_id
    record.phase = "executing"
    storage.save_workflow(record)
    if on_ids:
        on_ids(agent_id, run_id)

    phase = _stream_run(agent_id, run_id, on_event=on_event, should_cancel=should_cancel)
    record.last_result = phase.text
    record.branch = phase.branch or record.branch
    record.pr_url = phase.pr_url or record.pr_url
    record.phase = "done" if phase.status == "FINISHED" else "ready"
    storage.save_workflow(record)
    return record


def _create_exec_agent(record: WorkflowRecord, prompt: str) -> tuple[str, str]:
    created = rest_client.create_agent(
        prompt=prompt,
        model_id=resolve_model(),
        repo_url=None,
        auto_create_pr=False,
        mode="agent",
        name=record.name,
    )
    agent_id = str((created.get("agent") or {}).get("id") or "")
    run_id = str((created.get("run") or {}).get("id") or "")
    return agent_id, run_id


# --- Qt workers -----------------------------------------------------------------


class PlanWorker(QObject):
    event = Signal(str)
    ids = Signal(str, str)
    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, record: WorkflowRecord) -> None:
        super().__init__()
        self._record = record
        self._cancel = False

    def request_cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            updated = run_plan_phase(
                self._record,
                on_event=self.event.emit,
                on_ids=self.ids.emit,
                should_cancel=lambda: self._cancel,
            )
            self.succeeded.emit(updated)
        except RestApiError as exc:
            self.failed.emit(exc.message)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class ClarifyWorker(QObject):
    event = Signal(str)
    ids = Signal(str, str)
    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, record: WorkflowRecord, answers: dict[str, str]) -> None:
        super().__init__()
        self._record = record
        self._answers = answers
        self._cancel = False

    def request_cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            updated = run_clarify_phase(
                self._record,
                self._answers,
                on_event=self.event.emit,
                on_ids=self.ids.emit,
                should_cancel=lambda: self._cancel,
            )
            self.succeeded.emit(updated)
        except RestApiError as exc:
            self.failed.emit(exc.message)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class ExecuteWorker(QObject):
    event = Signal(str)
    ids = Signal(str, str)
    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, record: WorkflowRecord, *, reexecute: bool = False) -> None:
        super().__init__()
        self._record = record
        self._reexecute = reexecute
        self._cancel = False

    def request_cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            updated = run_execute_phase(
                self._record,
                reexecute=self._reexecute,
                on_event=self.event.emit,
                on_ids=self.ids.emit,
                should_cancel=lambda: self._cancel,
            )
            self.succeeded.emit(updated)
        except RestApiError as exc:
            self.failed.emit(exc.message)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class ArtifactsWorker(QObject):
    """List + download an agent's artifacts into a local folder."""

    progress = Signal(str)
    succeeded = Signal(str, object)  # dest_dir, list[str] of downloaded paths
    failed = Signal(str)
    finished = Signal()

    def __init__(self, agent_id: str, workflow_id: str) -> None:
        super().__init__()
        self._agent_id = agent_id
        self._workflow_id = workflow_id

    def run(self) -> None:
        import os

        try:
            dest = storage.outputs_dir(self._workflow_id)
            items = rest_client.list_artifacts(self._agent_id)
            if not items:
                self.succeeded.emit(str(dest), [])
                self.progress.emit("Артефакты не найдены (агент не положил файлы в artifacts/).")
                return
            saved: list[str] = []
            for it in items:
                rel = str(it.get("path") or "")
                if not rel:
                    continue
                safe_name = rel.replace("artifacts/", "", 1).replace("/", "_").replace("\\", "_")
                target = os.path.join(str(dest), safe_name)
                try:
                    rest_client.download_artifact_to(self._agent_id, rel, target)
                    saved.append(target)
                    self.progress.emit(f"Скачан: {safe_name}")
                except RestApiError as exc:
                    self.progress.emit(f"Пропущен {safe_name}: {exc.message}")
            self.succeeded.emit(str(dest), saved)
        except RestApiError as exc:
            self.failed.emit(exc.message)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class LocalRunWorker(QObject):
    """Запустить готовый инструмент ЛОКАЛЬНО (без облака) и стримить вывод.

    Приложение вызывает лаунчер молча (RTS_NONINTERACTIVE=1): без pause и без
    авто-открытия — итоговый файл открывает само приложение.
    """

    progress = Signal(str)
    succeeded = Signal(str)  # путь к файлу-результату (может быть пустым)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, spec: dict[str, Any], *, extra_args: list[str] | None = None) -> None:
        super().__init__()
        self._spec = dict(spec or {})
        self._extra = list(extra_args or [])
        self._cancel = False
        self._proc: Any = None

    def request_cancel(self) -> None:
        self._cancel = True
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001
                pass

    def run(self) -> None:
        import os
        import subprocess
        import sys

        try:
            cwd = str(self._spec.get("cwd") or "")
            if not cwd or not os.path.isdir(cwd):
                self.failed.emit(f"Папка инструмента не найдена: {cwd or '(не задана)'}")
                return

            if os.name == "nt":
                bat = str(self._spec.get("bat") or "run.bat")
                cmd = ["cmd", "/c", bat, *self._extra]
            else:
                module = str(self._spec.get("module") or "")
                if not module:
                    self.failed.emit("Для этой ОС не задан module для запуска.")
                    return
                cmd = [sys.executable, "-m", module, "run", *self._extra]

            env = dict(os.environ)
            env["RTS_NONINTERACTIVE"] = "1"
            self.progress.emit(f"$ {' '.join(cmd)}\n")

            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            self._proc = subprocess.Popen(  # noqa: S603
                cmd,
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )
            assert self._proc.stdout is not None
            for line in self._proc.stdout:
                self.progress.emit(line.rstrip("\n"))
                if self._cancel:
                    break
            self._proc.wait()
            code = self._proc.returncode

            if self._cancel:
                self.failed.emit("Запуск отменён.")
                return
            if code == 0:
                out = str(self._spec.get("output") or "")
                out_path = os.path.join(cwd, out) if out else ""
                if out_path and os.path.exists(out_path):
                    self.succeeded.emit(out_path)
                else:
                    self.succeeded.emit("")
            else:
                self.failed.emit(f"Инструмент завершился с кодом {code}.")
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class HealthWorker(QObject):
    succeeded = Signal(str)
    failed = Signal(str)
    finished = Signal()

    def run(self) -> None:
        try:
            me = rest_client.get_me()
            who = (
                me.get("userEmail")
                or me.get("user_email")
                or me.get("apiKeyName")
                or me.get("api_key_name")
                or "ok"
            )
            self.succeeded.emit(str(who))
        except RestApiError as exc:
            self.failed.emit(exc.message)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class DocumentWorker(QObject):
    succeeded = Signal(str, str)  # name, text
    failed = Signal(str)
    finished = Signal()

    def __init__(self, path: str) -> None:
        super().__init__()
        self._path = path

    def run(self) -> None:
        try:
            name, text = load_document(self._path)
            self.succeeded.emit(name, text)
        except DocumentError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class FilesWorker(QObject):
    """Load one or many files into AttachedFile list."""

    succeeded = Signal(object, str)  # list[AttachedFile], optional warning
    failed = Signal(str)
    finished = Signal()

    def __init__(self, paths: list[str]) -> None:
        super().__init__()
        self._paths = list(paths)

    def run(self) -> None:
        try:
            loaded: list[AttachedFile] = []
            errors: list[str] = []
            for path in self._paths:
                try:
                    loaded.append(load_attachment(path))
                except DocumentError as exc:
                    errors.append(f"{Path(path).name}: {exc}")
            if not loaded:
                self.failed.emit("; ".join(errors) if errors else "Файлы не выбраны")
            else:
                warning = ("Часть файлов пропущена: " + "; ".join(errors)) if errors else ""
                self.succeeded.emit(loaded, warning)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


def start_worker(worker: QObject, slot_name: str = "run") -> tuple[QThread, QObject]:
    """Start worker on a QThread. Caller must keep the returned (thread, worker)."""
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(getattr(worker, slot_name))
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    return thread, worker
