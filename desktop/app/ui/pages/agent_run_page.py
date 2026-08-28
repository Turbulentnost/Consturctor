from __future__ import annotations

import json
from threading import Thread
from uuid import uuid4

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.api_client import ApiClient, ApiError, WorkflowRecord
from app.sdk_agent import CursorSdkBridge, CursorSdkUnavailable
from app.sdk_agent.files import prepare_sdk_workspace
from app.sdk_agent.prompt import build_sdk_prompt
from app.tools.hitl import (
    attach_pending_for,
    has_pending_for,
    install_confirm_host,
    register_inline_host,
    set_host_workflow_id,
)
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, scroll_bar_qss
from app.ui.widgets.cursor_feed import CursorFeedItem, format_collection_result, format_tool_detail
from app.ui.widgets.result_file_card import ResultFileCard


_PRIMARY = """
QPushButton {
    background: #08745F; color: #FFFFFF; border: none;
    border-radius: 14px; padding: 0 18px;
}
QPushButton:hover { background: #0A8670; }
QPushButton:disabled { background: #A8C8BF; color: #EAF7F3; }
"""

_CARD = """
QFrame#AgentRunCard {
    background: #FFFFFF;
    border: 1px solid rgba(16,24,23,0.10);
    border-radius: 18px;
}
"""

_INPUT = """
QPlainTextEdit {
    background: #FFFFFF; color: #101817;
    border: 1px solid rgba(16,24,23,0.10);
    border-radius: 12px;
    padding: 8px 12px;
    selection-background-color: #08745F;
}
"""

_TOOL_LABELS = {
    "web_search": "Поиск в интернете",
    "site_browser": "Просмотр сайта",
    "outlook.search_mail": "Поиск писем Outlook",
    "outlook.read_calendar": "Календарь Outlook",
    "outlook.create_event": "Встреча в Outlook",
    "browser.list_installed_browsers": "Список браузеров",
    "browser.open_browser": "Открытие браузера",
    "browser.search_web": "Поиск в интернете",
    "browser.open_page": "Чтение страницы",
    "browser.extract_table": "Таблицы со страницы",
    "browser.scroll_page": "Прокрутка страницы",
    "browser.click_link": "Переход по ссылке",
    "browser.navigate": "Открытие страницы",
    "browser.screenshot": "Скриншот браузера",
    "browser.get_page_html": "HTML страницы",
    "browser.dump_page_source": "Выгрузка HTML страницы",
    "browser.click": "Клик в браузере",
    "browser.type_text": "Ввод в браузере",
    "browser.press_key": "Клавиша в браузере",
    "browser.scroll": "Прокрутка браузера",
    "onec.search_documents": "Поиск документов 1С",
    "onec.get_document_card": "Карточка документа 1С",
    "onec.search_tasks": "Поиск задач 1С",
    "onec.get_task_card": "Карточка задачи 1С",
    "onec.meeting_service_notes": "Служебные записки на совещания",
    "onec.erp_tasks_current": "Текущие задачи 1С",
    "onec.erp_tasks_period": "Задачи 1С за период",
    "onec.erp_subordinate_tasks": "Задачи подчинённых 1С",
    "onec.docflow_tasks": "Задачи документооборота",
    "excel.list_files": "Файлы агента",
    "excel.read_workbook": "Чтение Excel",
    "excel.create_workbook": "Создание Excel",
    "excel.edit_workbook": "Изменение Excel",
    "workspace.powershell_run": "PowerShell в папке агента",
    "code.write_python": "Запись Python-кода",
    "code.run_python": "Запуск Python-кода",
    "agent.wait": "Пауза",
    "report.build_task_report": "Отчёт по поручениям",
    "report.build_meeting_summary": "Сводка совещания",
    "report.build_schedule_recommendations": "Рекомендации по графику",
    "turboproject": "Проекты TurboProject",
    "users.current": "Текущий пользователь",
    "users.list": "Список пользователей",
    "users.subordinates": "Подчинённые из erp_pm",
    "notify.send": "Уведомление",
    "agent.schedule": "Расписание агента",
    "agent.schedule.cancel": "Отмена расписания",
}


class AgentRunPage(QWidget):
    failed = Signal(str)
    _event_ready = Signal(object)
    _done = Signal(object)

    def __init__(self, api: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._api = api
        self._workflow: WorkflowRecord | None = None
        self._events: list[dict] = []
        self._event_seq = 0
        self._expanded_keys: set[str] = set()
        self._busy = False
        self._live_thinking: CursorFeedItem | None = None
        self._live_assistant: CursorFeedItem | None = None
        self._event_ready.connect(self._append_event)
        self._done.connect(self._on_done)
        self.failed.connect(self._show_error)
        self._hitl_cards: list[QWidget] = []
        install_confirm_host(self)
        self._build()
        register_inline_host(self, "")

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        wid = str(getattr(self._workflow, "id", "") or "")
        if wid:
            set_host_workflow_id(self, wid)
            attach_pending_for(wid)
            from app.ui.widgets.result_file_card import flush_pending_result_files

            flush_pending_result_files()

    def _build(self) -> None:
        self._title = QLabel("Агент")
        self._title.setFont(app_font(22, QFont.Weight.DemiBold))
        self._title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

        self._subtitle = QLabel("Напишите задачу — агент выполнит её сам.")
        self._subtitle.setFont(app_font(13))
        self._subtitle.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        body = QHBoxLayout()
        body.setSpacing(14)

        center_card = QFrame()
        center_card.setObjectName("AgentRunCard")
        center_card.setStyleSheet(_CARD)
        center = QVBoxLayout(center_card)
        center.setContentsMargins(16, 14, 16, 14)
        center.setSpacing(10)

        self._feed_layout = QVBoxLayout()
        self._feed_layout.setContentsMargins(14, 14, 14, 14)
        self._feed_layout.setSpacing(10)
        feed_inner = QWidget()
        feed_inner.setStyleSheet("background: transparent;")
        feed_inner.setLayout(self._feed_layout)
        self._feed_scroll = QScrollArea()
        self._feed_scroll.setWidgetResizable(True)
        self._feed_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._feed_scroll.setWidget(feed_inner)
        self._feed_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }" + scroll_bar_qss()
        )

        self._input = QPlainTextEdit()
        self._input.setFixedHeight(58)
        self._input.setPlaceholderText("Например: найди активные закупки по ключевым словам…")
        self._input.setFont(app_font(12))
        self._input.setStyleSheet(_INPUT)
        self._send = QPushButton("➤")
        self._send.setFixedSize(42, 42)
        self._send.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send.setStyleSheet(_PRIMARY)
        self._send.clicked.connect(self._submit)
        self._quick = QPushButton("Запустить типовую задачу")
        self._quick.setCursor(Qt.CursorShape.PointingHandCursor)
        self._quick.setFixedHeight(40)
        self._quick.setFont(app_font(12, QFont.Weight.DemiBold))
        self._quick.setStyleSheet(_PRIMARY)
        self._quick.clicked.connect(self._run_default_task)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        input_row.addWidget(self._input, 1)
        input_row.addWidget(self._send, 0, Qt.AlignmentFlag.AlignTop)

        center.addWidget(self._feed_scroll, 1)
        center.addWidget(self._quick, 0)
        center.addLayout(input_row, 0)

        side_card = QFrame()
        side_card.setObjectName("AgentRunCard")
        side_card.setStyleSheet(_CARD)
        side_card.setFixedWidth(260)
        side = QVBoxLayout(side_card)
        side.setContentsMargins(16, 16, 16, 16)
        side.setSpacing(10)
        side.addWidget(_section("Как это работает"))
        for text in ("Вы даёте задачу", "Агент сам открывает сайты", "Вы получаете результат"):
            side.addWidget(_side_item(text))
        side.addWidget(_section("Статус"))
        self._status = QLabel("Готов к работе")
        self._status.setWordWrap(True)
        self._status.setFont(app_font(12))
        self._status.setStyleSheet("color: #08745F; background: transparent;")
        side.addWidget(self._status)
        side.addStretch(1)

        body.addWidget(center_card, 1)
        body.addWidget(side_card, 0)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        root.addWidget(self._title)
        root.addWidget(self._subtitle)
        root.addLayout(body, 1)

    def start(self, workflow: WorkflowRecord) -> None:
        self._workflow = workflow
        name = workflow.title or "ИИ-агент"
        self._title.setText(name)
        self._subtitle.setText("Агент готов. Нажмите «Запустить типовую задачу» или напишите свою.")
        self._event_seq = 0
        self._expanded_keys = set()
        self._hitl_cards = []
        self._events = [
            {
                "type": "system",
                "text": f"Агент «{name}» готов к работе. Код и терминал не нужны — всё выполняется внутри приложения.",
                "event_key": self._next_event_key(),
            }
        ]
        self._busy = False
        self._send.setEnabled(True)
        self._quick.setEnabled(True)
        self._status.setText("Готов к работе")
        self._render()
        set_host_workflow_id(self, workflow.id)
        if not has_pending_for(workflow.id):
            QTimer.singleShot(250, self._run_default_task)

    def _default_task(self) -> str:
        title = (self._workflow.title if self._workflow else "") or "агент"
        # Без хардкода конкретной площадки — задача из цели агента.
        return (
            f"Выполни рабочую задачу агента «{title}» по инструкции "
            "и примеру тестового прогона. Покажи понятный результат."
        )

    def _run_default_task(self) -> None:
        if self._busy or self._workflow is None:
            return
        self._input.setPlainText(self._default_task())
        self._submit()

    def _submit(self) -> None:
        if self._workflow is None or self._busy:
            return
        message = self._input.toPlainText().strip()
        if not message:
            return
        self._input.clear()
        self._busy = True
        self._send.setEnabled(False)
        self._quick.setEnabled(False)
        self._status.setText("Агент работает…")
        self._append_event({"type": "user_message", "text": message})
        workflow_id = self._workflow.id

        def run() -> None:
            events: list[dict] = []
            run_id = ""

            def handle_sdk_event(payload: dict) -> None:
                if isinstance(payload, dict) and payload.get("type") not in {"ready", "done"}:
                    events.append(payload)
                self._event_ready.emit(payload)

            try:
                bridge = CursorSdkBridge()
                bridge.check_ready()
                has_token = bool(self._api.token)
                if has_token:
                    try:
                        record = self._api.start_local_agent_run(workflow_id, message=message)
                        run_id = record.id
                    except ApiError as exc:
                        from app.orchestrator.agents import is_local_workflow

                        if exc.is_auth:
                            self._api.set_token(None)
                            has_token = False
                            run_id = str(uuid4())
                        elif is_local_workflow(workflow_id):
                            has_token = False
                            run_id = str(uuid4())
                        else:
                            raise
                else:
                    run_id = str(uuid4())
                self._event_ready.emit({"type": "run", "run_id": run_id})
                run_cwd = bridge.workspace_cwd(workflow_id)
                prepare_sdk_workspace(
                    self._api,
                    workflow_id,
                    run_cwd,
                    workflow=self._workflow,
                )
                sdk_result = bridge.run(
                    prompt=build_sdk_prompt(self._workflow, message),
                    workflow_id=workflow_id,
                    cwd=run_cwd,
                    on_event=handle_sdk_event,
                    confirm_writes=True,
                )
                answer = str(sdk_result.get("answer") or "").strip()
                result = {
                    "answer": answer,
                    "run_id": run_id,
                    "work_result": {"text": answer},
                }
                if has_token:
                    try:
                        self._api.finish_local_agent_run(
                            workflow_id,
                            run_id,
                            status="ok",
                            answer=answer,
                            events=events,
                            message=message,
                        )
                    except ApiError as exc:
                        if not exc.is_auth:
                            raise
            except CursorSdkUnavailable as exc:
                if not self._api.token:
                    self.failed.emit(str(exc) or "Локальный Cursor SDK недоступен.")
                    return
                try:
                    result = self._api.stream_workflow_agent_run(
                        workflow_id,
                        message,
                        lambda payload: self._event_ready.emit(payload),
                    )
                except ApiError as stream_exc:
                    if stream_exc.is_auth:
                        self.failed.emit(
                            str(exc) or "Локальный Cursor SDK недоступен."
                        )
                        return
                    raise
            except ApiError as exc:
                self.failed.emit(exc.message)
                return
            except Exception as exc:  # noqa: BLE001
                if run_id and self._api.token:
                    try:
                        self._api.finish_local_agent_run(
                            workflow_id,
                            run_id,
                            status="error",
                            answer=str(exc),
                            events=events,
                            message=message,
                        )
                    except ApiError:
                        pass
                self.failed.emit(str(exc))
                return
            self._done.emit(result)

        Thread(target=run, daemon=True).start()

    def _next_event_key(self) -> str:
        self._event_seq += 1
        return f"e{self._event_seq}"

    def _ensure_thinking_placeholder(self) -> None:
        if self._events and self._events[-1].get("type") == "thinking":
            return
        self._append_event({"type": "thinking", "text": "Думает…"})

    def _on_expand_toggled(self, key: str, expanded: bool) -> None:
        if not key:
            return
        if expanded:
            self._expanded_keys.add(key)
        else:
            self._expanded_keys.discard(key)

    def _append_event(self, event: object) -> None:
        if not isinstance(event, dict):
            return
        friendly = _friendly_event(event)
        if friendly is None:
            return
        text = str(friendly.get("text") or friendly.get("message") or "").strip()
        event_type = str(friendly.get("type") or "")
        if event_type == "status":
            self._status.setText(text or "Агент работает…")
            return
        if event_type == "thinking":
            self._status.setText("Думает…")
            if self._events and self._events[-1].get("type") == "thinking":
                prev = self._events[-1]
                prev_text = str(prev.get("text") or "")
                if prev_text.strip() == "Думает…":
                    prev["text"] = text
                else:
                    prev["text"] = (prev_text + text).rstrip()
                if self._live_thinking is not None:
                    self._live_thinking.set_body_text(str(prev.get("text") or ""))
                    self._scroll_feed()
                    return
            friendly["event_key"] = self._next_event_key()
            self._events.append(friendly)
            self._add_feed_card(friendly)
            return
        if event_type == "agent_message":
            if self._events and self._events[-1].get("type") == "agent_message":
                prev = self._events[-1]
                prev_text = str(prev.get("text") or "")
                if text == prev_text or (text and text in prev_text):
                    return
                if prev_text and prev_text in text:
                    prev["text"] = text
                else:
                    prev["text"] = (prev_text + text).rstrip()
                if self._live_assistant is not None:
                    self._live_assistant.set_body_text(str(prev.get("text") or ""))
                    self._scroll_feed()
                    return
            friendly["event_key"] = self._next_event_key()
            self._events.append(friendly)
            self._add_feed_card(friendly)
            return
        if event_type == "work_result":
            if "event_key" not in friendly:
                friendly["event_key"] = self._next_event_key()
            self._events.append(friendly)
            self._add_feed_card(friendly)
            return
        if event_type == "tool_result":
            tool = str(friendly.get("tool") or "")
            for prev in reversed(self._events):
                if (
                    prev.get("type") == "tool"
                    and str(prev.get("tool") or "") == tool
                    and prev.get("result") is None
                ):
                    prev["result"] = friendly.get("result")
                    prev["summary"] = text
                    self._status.setText("Думает…")
                    self._render()
                    self._ensure_thinking_placeholder()
                    return
            friendly["type"] = "tool"
            friendly["arguments"] = {}
            friendly["event_key"] = self._next_event_key()
            self._events.append(friendly)
            self._status.setText("Думает…")
            self._render()
            self._ensure_thinking_placeholder()
            return
        if "event_key" not in friendly:
            friendly["event_key"] = self._next_event_key()
        self._events.append(friendly)
        self._render()

    def _on_done(self, result: object) -> None:
        self._busy = False
        self._send.setEnabled(True)
        self._quick.setEnabled(True)
        self._status.setText("Готово")
        work = result.get("work_result") if isinstance(result, dict) else None
        if not isinstance(work, dict):
            work = {}
        from app.tools.result_files import publish_answer_files
        from app.ui.widgets.result_file_card import flush_pending_result_files

        text = str(work.get("text") or (result.get("answer") if isinstance(result, dict) else "") or "").strip()
        publish_answer_files(
            workflow_id=str(getattr(self._workflow, "id", "") or ""),
            work=work,
            text=text,
        )
        flush_pending_result_files()
        already = any(
            ev.get("type") in {"work_result", "agent_message"}
            and text
            and text in str(ev.get("text") or "")
            for ev in self._events
        )
        if text and not already:
            self._append_event(_work_result_event(work, text))
        elif not text:
            self._append_event({"type": "system", "text": "Прогон завершён. Результат не получен."})
        self._append_event({"type": "system", "text": "Можно дать следующую задачу."})

    def _show_error(self, message: str) -> None:
        self._busy = False
        self._send.setEnabled(True)
        self._quick.setEnabled(True)
        self._status.setText("Ошибка")
        self._append_event({"type": "error", "message": message})

    def attach_hitl_card(self, card: QWidget) -> None:
        if card not in self._hitl_cards:
            self._hitl_cards.append(card)
        stretch = None
        if self._feed_layout.count():
            last = self._feed_layout.itemAt(self._feed_layout.count() - 1)
            if last is not None and last.widget() is None and last.spacerItem() is not None:
                stretch = self._feed_layout.takeAt(self._feed_layout.count() - 1)
        self._feed_layout.addWidget(card)
        if stretch is not None:
            self._feed_layout.addItem(stretch)
        else:
            self._feed_layout.addStretch(1)
        self._scroll_feed()

    def _clear_feed(self) -> None:
        self._live_thinking = None
        self._live_assistant = None
        while self._feed_layout.count():
            item = self._feed_layout.takeAt(0)
            widget = item.widget()
            if widget is not None and widget in self._hitl_cards:
                continue
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _add_feed_card(self, event: dict) -> None:
        # Drop trailing stretch, append card, put stretch back — no full rebuild.
        stretch = None
        if self._feed_layout.count():
            last = self._feed_layout.itemAt(self._feed_layout.count() - 1)
            if last is not None and last.widget() is None and last.spacerItem() is not None:
                stretch = self._feed_layout.takeAt(self._feed_layout.count() - 1)
        card = _event_card(event, expanded=_feed_expanded(event, self._expanded_keys))
        if hasattr(card, "expand_toggled"):
            card.expand_toggled.connect(self._on_expand_toggled)
        self._feed_layout.addWidget(card)
        if str(event.get("type") or "") == "thinking":
            self._live_thinking = card
        elif str(event.get("type") or "") == "agent_message":
            self._live_assistant = card
        if stretch is not None:
            self._feed_layout.addItem(stretch)
        else:
            self._feed_layout.addStretch(1)
        self._scroll_feed()

    def _scroll_feed(self) -> None:
        QTimer.singleShot(
            0,
            lambda: self._feed_scroll.verticalScrollBar().setValue(
                self._feed_scroll.verticalScrollBar().maximum()
            ),
        )

    def _render(self) -> None:
        self._clear_feed()
        for event in self._events:
            card = _event_card(event, expanded=_feed_expanded(event, self._expanded_keys))
            if hasattr(card, "expand_toggled"):
                card.expand_toggled.connect(self._on_expand_toggled)
            self._feed_layout.addWidget(card)
            if str(event.get("type") or "") == "thinking":
                self._live_thinking = card
            elif str(event.get("type") or "") == "agent_message":
                self._live_assistant = card
        for card in self._hitl_cards:
            self._feed_layout.addWidget(card)
        self._feed_layout.addStretch(1)
        self._scroll_feed()


def _friendly_event(event: dict) -> dict | None:
    """Keep user-facing messages plus expandable thinking/tool blocks."""
    event_type = str(event.get("type") or "system")
    if event_type == "run":
        return None
    if event_type == "tool_request":
        tool = str(event.get("tool") or "")
        label = _TOOL_LABELS.get(tool, tool or "инструмент")
        return {"type": "status", "text": f"Вызываю {label}…"}
    if event_type == "status":
        text = str(event.get("text") or "").strip()
        return {"type": "status", "text": text or "Агент работает…"}
    if event_type in {"decision", "progress"}:
        text = str(event.get("text") or "").strip()
        return {"type": "system", "text": text} if text else None
    if event_type == "plan":
        text = str(event.get("text") or "").strip()
        return {"type": "plan", "title": "План", "text": text} if text else None
    if event_type == "thinking":
        text = str(event.get("text") or "").strip()
        if text and (text.startswith("{") or "traceback" in text.casefold()):
            text = "Агент анализирует задачу…"
        return {"type": "thinking", "text": text or "Агент анализирует задачу…"}
    if event_type == "assistant":
        text = _visible_assistant_text(str(event.get("text") or ""))
        return {"type": "agent_message", "text": text} if text else None
    if event_type == "tool_call":
        tool = str(event.get("tool") or "")
        label = _TOOL_LABELS.get(tool, tool or "внешний источник")
        arguments = event.get("arguments") if isinstance(event.get("arguments"), dict) else {}
        return {
            "type": "tool",
            "tool": tool,
            "title": label,
            "arguments": arguments,
            "result": None,
            "text": f"Смотрю данные через «{label}»",
        }
    if event_type == "tool_result":
        tool = str(event.get("tool") or "")
        result = event.get("result") if isinstance(event.get("result"), dict) else {}
        label = _TOOL_LABELS.get(tool, tool or "внешний источник")
        return {
            "type": "tool_result",
            "tool": tool,
            "title": label,
            "result": result,
            "text": _summarize_tool_result(tool, result),
        }
    if event_type == "work_result":
        text = str(event.get("text") or "").strip()
        payload = _work_result_event(event, text) if text else None
        return payload
    if event_type == "agent_message":
        text = str(event.get("text") or "").strip()
        return {"type": "agent_message", "text": text} if text else None
    if event_type == "user_message":
        return event
    if event_type == "error":
        return event
    if event_type == "system":
        return event
    if event_type == "done":
        return None
    return None


def _visible_assistant_text(text: str) -> str:
    """Show the agent's written answer, not constructor_tool fences."""
    cleaned = (text or "").replace("\ufffd", "")
    if "```constructor_tool" in cleaned or "```tool" in cleaned:
        parts: list[str] = []
        skip = False
        for line in cleaned.splitlines():
            fence = line.strip()
            if fence.startswith("```constructor_tool") or fence.startswith("```tool"):
                skip = True
                continue
            if skip and fence.startswith("```"):
                skip = False
                continue
            if not skip:
                parts.append(line)
        cleaned = "\n".join(parts)
    return cleaned.strip()


def _work_result_event(work: dict, text: str) -> dict:
    extras: list[str] = [text]
    for item in work.get("files") or []:
        extras.append(f"Файл: {item}")
    for item in work.get("actions") or []:
        extras.append(f"Действие: {item}")
    for item in work.get("notifications") or []:
        extras.append(f"Уведомление: {item}")
    return {"type": "work_result", "title": "Результат", "text": "\n".join(extras).strip()}


def _summarize_tool_result(tool: str, result: dict) -> str:
    friendly = format_collection_result(result)
    if friendly:
        return friendly
    if tool == "site_browser":
        n = int(result.get("cards_count") or len(result.get("cards") or []) or 0)
        title = str(result.get("title") or "").strip()
        url = str(result.get("url") or "").strip()
        if n:
            return f"Нашла на сайте {n} позиций" + (f" ({title})" if title else "") + "."
        if url:
            return f"Открыла страницу {url}."
        return "Просмотрела сайт."
    if tool == "web_search":
        n = len(result.get("results") or [])
        return f"Нашла {n} результатов в поиске." if n else "Поиск не дал результатов."
    # Never dump JSON/code to the user.
    try:
        raw = json.dumps(result, ensure_ascii=False)
    except Exception:
        raw = ""
    if len(raw) > 20:
        return "Данные получены."
    return ""


def _section(text: str) -> QLabel:
    label = QLabel(text)
    label.setFont(app_font(13, QFont.Weight.DemiBold))
    label.setStyleSheet("color: #06483D; background: transparent;")
    return label


def _side_item(text: str) -> QLabel:
    label = QLabel(f"• {text}")
    label.setFont(app_font(12, QFont.Weight.Medium))
    label.setWordWrap(True)
    label.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
    return label


def _feed_expanded(event: dict, expanded_keys: set[str]) -> bool:
    kind = str(event.get("type") or "")
    key = str(event.get("event_key") or "")
    if key and key in expanded_keys:
        return True
    if kind in {"work_result", "result"}:
        return True
    if kind in {"tool", "tool_result"}:
        return event.get("result") is None
    return False


def _event_card(event: dict, *, expanded: bool = False) -> QWidget:
    event_type = str(event.get("type") or "system")
    if event_type == "file":
        return ResultFileCard(str(event.get("path") or event.get("text") or ""))
    key = str(event.get("event_key") or "")
    text = str(event.get("text") or event.get("message") or "")
    if event_type in {"tool", "tool_result"}:
        return CursorFeedItem(
            kind="tool",
            text=text,
            title=str(event.get("title") or event.get("tool") or "Инструмент"),
            detail=format_tool_detail(event.get("arguments"), event.get("result")),
            event_key=key,
            expanded=expanded,
            arguments=event.get("arguments"),
            result=event.get("result"),
        )
    if event_type == "thinking":
        return CursorFeedItem(
            kind="thinking",
            text=text,
            title="Thinking",
            detail=text,
            event_key=key,
            expanded=expanded,
        )
    if event_type == "plan":
        return CursorFeedItem(
            kind="plan",
            text=text,
            title="План",
            detail=text,
            event_key=key,
            expanded=expanded,
        )
    if event_type in {"work_result", "result"}:
        return CursorFeedItem(
            kind="result",
            text=text,
            title="Результат",
            detail=text,
            event_key=key,
            expanded=True,
        )
    kind = {
        "user_message": "user",
        "agent_message": "agent",
        "error": "error",
        "system": "system",
    }.get(event_type, "system")
    return CursorFeedItem(
        kind=kind,
        text=text,
        title="",
        detail=text,
        event_key=key,
        expanded=expanded,
    )
