from __future__ import annotations

import json
from threading import Thread

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QResizeEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.api_client import AgentRouteRecord, ApiClient, ApiError, WorkflowRecord
from app.config import backend_url
from app.tools.hitl import install_confirm_host, register_inline_host
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, scroll_bar_qss
from app.ui.widgets.cursor_feed import CursorFeedItem, format_collection_result, format_tool_detail


_PRIMARY = """
QPushButton {
    background: #08745F; color: #FFFFFF; border: none;
    border-radius: 12px; padding: 0 16px;
}
QPushButton:hover { background: #0A8670; }
QPushButton:disabled { background: #A8C8BF; color: #EAF7F3; }
"""

_SECONDARY = """
QPushButton {
    background: transparent; color: #08745F;
    border: 1px solid rgba(8,116,95,0.35);
    border-radius: 12px; padding: 0 14px;
}
QPushButton:hover { background: rgba(8,116,95,0.08); }
QPushButton:disabled { color: #A8C8BF; border-color: rgba(168,200,191,0.6); }
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

_FEED_BG = """
QScrollArea {
    background: #FAFCFB;
    border: 1px solid rgba(16,24,23,0.08);
    border-radius: 14px;
}
"""

_USER_BUBBLE = """
QFrame#AgentChatUserBubble {
    background: #08745F;
    border: none;
    border-radius: 18px 18px 4px 18px;
}
QFrame#AgentChatUserBubble QLabel,
QFrame#AgentChatUserBubble QTextBrowser {
    color: #FFFFFF;
    background: transparent;
    border: none;
}
"""

_AGENT_BUBBLE = """
QFrame#AgentChatAgentBubble {
    background: #FFFFFF;
    border: 1px solid rgba(16,24,23,0.10);
    border-radius: 4px 18px 18px 18px;
}
QFrame#AgentChatAgentBubble QLabel,
QFrame#AgentChatAgentBubble QTextBrowser {
    color: #101817;
    background: transparent;
    border: none;
}
"""

_META_BUBBLE = """
QFrame#AgentChatMetaBubble {
    background: #F6F8F7;
    border: 1px dashed rgba(16,24,23,0.14);
    border-radius: 12px;
}
"""

_SYSTEM_PILL = """
QFrame#AgentChatSystemPill {
    background: rgba(16,24,23,0.04);
    border: none;
    border-radius: 10px;
}
"""

_FEED_EVENT_TYPES = frozenset({"user_message", "agent_message", "work_result", "error", "system"})

_TOOL_LABELS = {
    "web_search": "Поиск в интернете",
    "site_browser": "Просмотр сайта",
    "plan_export": "Поиск по сайту и Excel",
    "outlook.search_mail": "Поиск писем Outlook",
    "outlook.read_calendar": "Календарь Outlook",
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
    "onec.docflow_assignments": "Поручения документооборота 1С",
    "onec.get_document_card": "Карточка документа 1С",
    "onec.search_tasks": "Поиск задач 1С",
    "onec.get_task_card": "Карточка задачи 1С",
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
    "users.list": "Список пользователей",
    "notify.send": "Уведомление",
    "agent.schedule": "Расписание агента",
    "agent.schedule.cancel": "Отмена расписания",
}


class AgentRunPage(QWidget):
    failed = Signal(str)
    _event_ready = Signal(object)
    _done = Signal(object)
    _ready_for_task = Signal()
    _act_ui_ready = Signal()

    def __init__(self, api: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._api = api
        self._workflow: WorkflowRecord | None = None
        self._route: AgentRouteRecord | None = None
        self._events: list[dict] = []
        self._event_seq = 0
        self._expanded_keys: set[str] = set()
        self._busy = False
        self._auto_run_pending = False
        self._live_thinking: CursorFeedItem | None = None
        self._live_assistant: CursorFeedItem | None = None
        self._event_ready.connect(self._append_event)
        self._done.connect(self._on_done)
        self._ready_for_task.connect(self._on_ready_for_task)
        self._act_ui_ready.connect(self._on_act_ui_ready)
        self.failed.connect(self._show_error)
        self._hitl_cards: list[QWidget] = []
        install_confirm_host(self)
        self._build()
        register_inline_host(self)

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
        self._feed_layout.setContentsMargins(12, 12, 12, 12)
        self._feed_layout.setSpacing(10)
        feed_inner = QWidget()
        feed_inner.setStyleSheet("background: transparent;")
        feed_inner.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        feed_inner.setLayout(self._feed_layout)
        self._feed_inner = feed_inner
        self._feed_scroll = QScrollArea()
        self._feed_scroll.setWidgetResizable(False)
        self._feed_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._feed_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._feed_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._feed_scroll.setWidget(feed_inner)
        self._feed_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._feed_scroll.setMinimumHeight(280)
        self._feed_scroll.setStyleSheet(_FEED_BG + scroll_bar_qss())

        self._input = QPlainTextEdit()
        self._input.setFixedHeight(52)
        self._input.setPlaceholderText("Например: найди активные закупки по ключевым словам…")
        self._input.setFont(app_font(12))
        self._input.setStyleSheet(_INPUT)
        self._send = QPushButton("➤")
        self._send.setFixedSize(40, 40)
        self._send.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send.setStyleSheet(_PRIMARY)
        self._send.clicked.connect(self._submit)
        self._quick = QPushButton("Типовая задача")
        self._quick.setCursor(Qt.CursorShape.PointingHandCursor)
        self._quick.setFixedHeight(40)
        self._quick.setFont(app_font(11, QFont.Weight.DemiBold))
        self._quick.setStyleSheet(_SECONDARY)
        self._quick.clicked.connect(self._run_default_task)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        input_row.addWidget(self._quick, 0)
        input_row.addWidget(self._input, 1)
        input_row.addWidget(self._send, 0, Qt.AlignmentFlag.AlignTop)

        center.addWidget(self._feed_scroll, 1)
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
        hint = QLabel("OData, Excel и LLM — здесь, не в ленте чата.")
        hint.setWordWrap(True)
        hint.setFont(app_font(10))
        hint.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        side.addWidget(hint)
        self._backend_label = QLabel("")
        self._backend_label.setWordWrap(True)
        self._backend_label.setFont(app_font(11))
        self._backend_label.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        side.addWidget(self._backend_label)
        side.addStretch(1)

        body.addWidget(center_card, 1)
        body.addWidget(side_card, 0)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        root.addWidget(self._title)
        root.addWidget(self._subtitle)
        root.addLayout(body, 1)

    def _bubble_max_width(self) -> int:
        viewport_w = self._feed_scroll.viewport().width()
        if viewport_w <= 0:
            viewport_w = max(320, self.width() - 320)
        return max(200, int(viewport_w * 0.72))

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._sync_feed_scroll_height()
        max_w = self._bubble_max_width()
        for idx in range(self._feed_layout.count()):
            item = self._feed_layout.itemAt(idx)
            widget = item.widget() if item is not None else None
            if widget is not None:
                _update_chat_row_width(widget, max_w)

    def _sync_feed_scroll_height(self) -> None:
        if not hasattr(self, "_feed_inner"):
            return
        viewport_w = self._feed_scroll.viewport().width()
        if viewport_w <= 0:
            viewport_w = max(200, self._feed_scroll.width() - 16)
        self._feed_inner.setFixedWidth(viewport_w)
        content_h = 16
        for idx in range(self._feed_layout.count()):
            item = self._feed_layout.itemAt(idx)
            if item is None or item.spacerItem() is not None:
                continue
            widget = item.widget()
            if widget is None:
                continue
            widget.setMaximumWidth(viewport_w)
            hint = widget.sizeHint()
            content_h += hint.height() + self._feed_layout.spacing()
        self._feed_inner.setFixedHeight(max(120, content_h))

    def start(self, workflow: WorkflowRecord, *, auto_run: bool = False) -> None:
        self._workflow = workflow
        self._route = workflow.agent_route
        self._auto_run_pending = auto_run
        name = self._agent_title(workflow)
        self._title.setText(name)
        self._subtitle.setText(
            "Напишите задачу или нажмите «Запустить типовую задачу». "
            "Итоговый ответ формирует LLM на backend (не шаблон)."
        )
        self._backend_label.setText(f"Backend: {self._api.base_url or backend_url()}")
        try:
            health = self._api.health()
            if health.llm_provider and health.llm_provider != "stub":
                self._backend_label.setText(
                    f"Backend: {self._api.base_url or backend_url()} · LLM: {health.llm_provider}"
                )
        except ApiError:
            pass
        self._event_seq = 0
        self._expanded_keys = set()
        self._hitl_cards = []
        self._events = [
            {
                "type": "system",
                "text": f"Агент «{name}» готов. Напишите задачу или нажмите «Типовая задача».",
                "event_key": self._next_event_key(),
            }
        ]
        self._busy = False
        self._send.setEnabled(True)
        self._quick.setEnabled(True)
        self._status.setText("Готов к работе")
        self._render()

        def prepare() -> None:
            route: AgentRouteRecord | None = None
            try:
                route = self._api.get_agent_route(workflow.id)
            except ApiError:
                route = workflow.agent_route
            if route and route.handler in {
                "assignments_action_tracker",
                "assignments_smart",
            }:
                try:
                    route = self._api.update_agent_route(
                        workflow.id,
                        {"handler": "act_porucheniya_registry", "source": "passport"},
                    )
                except ApiError:
                    pass
            self._route = route
            if route and route.handler == "act_porucheniya_registry":
                self._act_ui_ready.emit()
            else:
                self._ready_for_task.emit()

        Thread(target=prepare, daemon=True).start()

    def _on_act_ui_ready(self) -> None:
        self._input.setPlaceholderText(
            "Например: выгрузи ACT-реестр / только просроченные / ACT00-00088 / "
            "что добавить в Excel для отчёта PMO…"
        )
        self._subtitle.setText(
            "ACT-реестр: OData → Excel на рабочий стол. "
            "В чате — ваши сообщения и ответ агента; шаги выполнения — в «Статус» справа."
        )
        if self._auto_run_pending and not self._busy:
            task = self._default_task()
            if task:
                self._auto_run_pending = False
                self._input.setPlainText(task)
                self._run_default_task()
                return
        self._ready_for_task.emit()

    def _on_ready_for_task(self) -> None:
        task = self._default_task()
        if task:
            self._input.setPlainText(task)
        self._quick.setEnabled(bool(task) and not self._busy)
        if self._auto_run_pending and task and not self._busy:
            self._auto_run_pending = False
            self._run_default_task()

    def _agent_title(self, wf: WorkflowRecord) -> str:
        local = wf.local_run if isinstance(wf.local_run, dict) else {}
        passport = str(local.get("passport_title") or "").strip()
        if passport:
            if passport.casefold().startswith("ии-агент"):
                return passport
            return f"ИИ-агент: {passport}"
        plan_title = (wf.plan.title if wf.plan else "").strip()
        raw_title = (wf.title or "").strip()
        if plan_title and raw_title.lower().endswith((".docx", ".txt", ".pdf", ".doc")):
            return plan_title
        return raw_title or plan_title or "ИИ-агент"

    def _default_task(self) -> str:
        route = self._route
        if route and route.default_task.strip():
            return route.default_task.strip()
        wf = self._workflow
        if wf and wf.plan and (wf.plan.goal or "").strip():
            return wf.plan.goal.strip()
        title = (self._workflow.title if self._workflow else "") or "агент"
        return (
            f"Выполни рабочую задачу агента «{title}» по инструкции "
            "и примеру тестового прогона. Покажи понятный результат."
        )

    def _run_default_task(self) -> None:
        if self._busy or self._workflow is None:
            return
        task = self._default_task()
        if not task:
            self.failed.emit("У агента не задана типовая задача. Настройте agent_route в workflow.")
            return
        self._input.setPlainText(task)
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
        self._status.setText("Запускаю агента…")
        self._append_event({"type": "user_message", "text": message})
        workflow_id = self._workflow.id

        def run() -> None:
            try:
                result = self._api.stream_workflow_agent_run(
                    workflow_id,
                    message,
                    lambda payload: self._event_ready.emit(payload),
                    source="app",
                    auto_approve=True,
                )
            except ApiError as exc:
                self.failed.emit(exc.message)
                return
            except Exception as exc:  # noqa: BLE001
                self.failed.emit(str(exc) or "Ошибка запуска агента")
                return
            self._done.emit(result)

        Thread(target=run, daemon=True).start()

    def _next_event_key(self) -> str:
        self._event_seq += 1
        return f"e{self._event_seq}"

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

        if event_type in {"status", "progress"}:
            self._status.setText(text or "Агент работает…")
            return

        if event_type == "thinking":
            self._status.setText(text[:120] if text else "Думаю…")
            return

        if event_type == "tool":
            self._status.setText(text or "Выполняю шаг…")
            return

        if event_type == "tool_result":
            tool = str(friendly.get("tool") or "")
            summary = text or _summarize_tool_result(
                tool,
                friendly.get("result") if isinstance(friendly.get("result"), dict) else {},
            )
            if summary:
                self._status.setText(summary[:140])
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
                    self._sync_feed_scroll_height()
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
        if "event_key" not in friendly:
            friendly["event_key"] = self._next_event_key()
        if event_type not in _FEED_EVENT_TYPES:
            return
        self._events.append(friendly)
        self._add_feed_card(friendly)

    def _on_done(self, result: object) -> None:
        self._busy = False
        self._send.setEnabled(True)
        self._quick.setEnabled(True)
        self._status.setText("Готово")
        work = result.get("work_result") if isinstance(result, dict) else None
        if not isinstance(work, dict):
            work = {}
        text = str(work.get("text") or (result.get("answer") if isinstance(result, dict) else "") or "").strip()
        already = any(
            ev.get("type") in {"work_result", "agent_message"}
            and text
            and text in str(ev.get("text") or "")
            for ev in self._events
        )
        if text and not already:
            self._append_event(_work_result_event(work, text))
        elif not text:
            answer = ""
            if isinstance(result, dict):
                answer = str(result.get("answer") or "").strip()
            has_agent_reply = any(e.get("type") == "agent_message" for e in self._events)
            if answer and not has_agent_reply:
                self._append_event({"type": "agent_message", "text": answer})
            if not answer and not has_agent_reply:
                self._append_event({"type": "system", "text": "Прогон завершён. Результат не получен."})
        self._status.setText("Готово — можно задать следующую задачу")

    def _show_error(self, message: str) -> None:
        self._busy = False
        self._send.setEnabled(True)
        self._quick.setEnabled(True)
        text = (message or "Неизвестная ошибка").strip()
        status = text if len(text) <= 100 else text[:97] + "…"
        self._status.setText(f"Ошибка: {status}")
        self._append_event({"type": "error", "message": text})

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
        stretch_idx = -1
        if self._feed_layout.count():
            last = self._feed_layout.itemAt(self._feed_layout.count() - 1)
            if last is not None and last.widget() is None and last.spacerItem() is not None:
                stretch_idx = self._feed_layout.count() - 1
                self._feed_layout.takeAt(stretch_idx)
        card = _event_card(event, expanded=str(event.get("event_key") or "") in self._expanded_keys)
        card.expand_toggled.connect(self._on_expand_toggled)
        row = _wrap_chat_row(self, card, event)
        self._feed_layout.addWidget(row)
        if str(event.get("type") or "") in {"agent_message", "work_result"}:
            self._live_assistant = card
        self._feed_layout.addStretch(1)
        self._sync_feed_scroll_height()
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
            if str(event.get("type") or "") not in _FEED_EVENT_TYPES:
                continue
            card = _event_card(event, expanded=str(event.get("event_key") or "") in self._expanded_keys)
            card.expand_toggled.connect(self._on_expand_toggled)
            row = _wrap_chat_row(self, card, event)
            self._feed_layout.addWidget(row)
            if str(event.get("type") or "") in {"agent_message", "work_result"}:
                self._live_assistant = card
        self._feed_layout.addStretch(1)
        for card in self._hitl_cards:
            self._feed_layout.addWidget(card)
        QTimer.singleShot(0, self._sync_feed_scroll_height)
        self._scroll_feed()


def _friendly_event(event: dict) -> dict | None:
    """Keep user-facing messages plus expandable thinking/tool blocks."""
    event_type = str(event.get("type") or "system")
    if event_type == "run":
        return None
    if event_type == "tool_request":
        tool = str(event.get("tool") or "")
        label = _TOOL_LABELS.get(tool, tool or "инструмент")
        return {"type": "status", "text": f"Выполняю на этом ПК: «{label}»…"}
    if event_type in {"status", "decision", "progress"}:
        text = str(event.get("text") or "").strip()
        return {"type": "status", "text": text or "Агент работает…"}
    if event_type == "thinking":
        text = str(event.get("text") or "").strip()
        if text and (text.startswith("{") or "traceback" in text.casefold()):
            text = "Агент анализирует задачу…"
        if text.casefold().startswith("llm"):
            return {"type": "thinking", "text": text, "title": "LLM"}
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
        if payload is None:
            return None
        payload["type"] = "work_result"
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
    return {"type": "agent_message", "text": "\n".join(extras).strip()}


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
    if tool == "onec.search_documents":
        if str(result.get("source") or "") == "onec_readonly":
            return (
                "Сработала заглушка 1С (устаревший маршрут). "
                "Перезапустите backend (scripts\\start_all_local.cmd) и нажмите «Типовая задача» снова."
            )
        count = int(result.get("count") or len(result.get("documents") or []) or 0)
        return f"Найдено документов 1С: {count}." if count else "Документы 1С не найдены."
    if tool == "onec.docflow_assignments":
        count = int(result.get("count") or len(result.get("tasks") or []) or 0)
        return f"Загружено поручений из 1С: {count}."
    if tool == "excel.create_workbook":
        path = str(result.get("file") or result.get("path") or "").strip()
        if path:
            return f"Excel сохранён: {path}"
        return "Excel создан."
    if tool == "plan_export":
        count = int(result.get("count") or 0)
        path = str(result.get("file") or "").strip()
        if path:
            return f"Excel готов: {count} записей → {path}"
        return f"Поиск завершён: {count} записей." if count else "Поиск завершён."
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


def _chat_role(event: dict) -> tuple[str, str]:
    event_type = str(event.get("type") or "system")
    if event_type == "user_message":
        return "user", "Вы"
    if event_type in {"agent_message", "work_result"}:
        return "agent", "Агент"
    if event_type == "thinking":
        title = str(event.get("title") or "LLM")
        if title.casefold().startswith("llm"):
            return "agent_meta", "Агент · LLM"
        return "agent_meta", f"Агент · {title}"
    if event_type == "tool":
        title = str(event.get("title") or event.get("tool") or "инструмент")
        return "agent_meta", f"Агент · {title}"
    if event_type == "error":
        return "agent", "Ошибка"
    if event_type == "progress":
        return "agent_meta", "Агент · статус"
    return "system", "Система"


def _chat_avatar(role: str) -> QLabel:
    label = QLabel("Вы" if role == "user" else "AI")
    label.setFixedSize(30, 30)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setFont(app_font(10, QFont.Weight.DemiBold))
    if role == "user":
        label.setStyleSheet(
            "color: #FFFFFF; background: #065A4A; border-radius: 15px; border: none;"
        )
    else:
        label.setStyleSheet(
            "color: #08745F; background: #EAF7F3;"
            " border: 1px solid rgba(8,116,95,0.18); border-radius: 15px;"
        )
    return label


def _chat_name_badge(text: str, *, role: str) -> QLabel:
    label = QLabel(text)
    label.setFont(app_font(11, QFont.Weight.DemiBold))
    if role == "user":
        color = "#065A4A"
    elif role == "agent":
        color = "#08745F"
    else:
        color = COLOR_CONTENT_MUTED.name()
    label.setStyleSheet(f"color: {color}; background: transparent;")
    if role == "user":
        label.setAlignment(Qt.AlignmentFlag.AlignRight)
    elif role == "system":
        label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    else:
        label.setAlignment(Qt.AlignmentFlag.AlignLeft)
    return label


def _chat_bubble_frame(content: QWidget, *, object_name: str, stylesheet: str, max_width: int) -> QFrame:
    frame = QFrame()
    frame.setObjectName(object_name)
    frame.setStyleSheet(stylesheet)
    inner_max = max(160, max_width - 28)
    frame.setMaximumWidth(max_width)
    frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 10, 14, 10)
    layout.setSpacing(4)
    content.setMaximumWidth(inner_max)
    content.setMinimumWidth(0)
    content.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
    layout.addWidget(content)
    return frame


def _wrap_chat_row(page: "AgentRunPage", content: QWidget, event: dict) -> QWidget:
    role, caption = _chat_role(event)
    max_w = page._bubble_max_width()
    content.setMinimumWidth(0)
    content.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

    outer = QWidget()
    outer.setProperty("chat_row", True)
    outer.setProperty("chat_max_width", max_w)
    outer.setStyleSheet("background: transparent;")
    root = QVBoxLayout(outer)
    root.setContentsMargins(0, 0, 0, 10)
    root.setSpacing(0)

    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(10)

    column = QVBoxLayout()
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(6)

    if role == "user":
        row.addStretch(1)
        column.addWidget(
            _chat_bubble_frame(
                content,
                object_name="AgentChatUserBubble",
                stylesheet=_USER_BUBBLE,
                max_width=max_w,
            ),
            0,
            Qt.AlignmentFlag.AlignRight,
        )
        body = QWidget()
        body.setStyleSheet("background: transparent;")
        body.setLayout(column)
        row.addWidget(body, 0)
        row.addWidget(_chat_avatar("user"), 0, Qt.AlignmentFlag.AlignBottom)
    elif role == "agent":
        row.addWidget(_chat_avatar("agent"), 0, Qt.AlignmentFlag.AlignBottom)
        column.addWidget(
            _chat_bubble_frame(
                content,
                object_name="AgentChatAgentBubble",
                stylesheet=_AGENT_BUBBLE,
                max_width=max_w,
            ),
            0,
            Qt.AlignmentFlag.AlignLeft,
        )
        body = QWidget()
        body.setStyleSheet("background: transparent;")
        body.setLayout(column)
        row.addWidget(body, 0)
        row.addStretch(1)
    elif role == "agent_meta":
        row.addWidget(_chat_avatar("agent"), 0, Qt.AlignmentFlag.AlignTop)
        column.addWidget(_chat_name_badge(caption, role=role))
        column.addWidget(
            _chat_bubble_frame(
                content,
                object_name="AgentChatMetaBubble",
                stylesheet=_META_BUBBLE,
                max_width=max_w,
            ),
            0,
            Qt.AlignmentFlag.AlignLeft,
        )
        body = QWidget()
        body.setStyleSheet("background: transparent;")
        body.setLayout(column)
        row.addWidget(body, 0)
        row.addStretch(1)
    else:
        row.addStretch(1)
        meta = QVBoxLayout()
        meta.setSpacing(4)
        meta.addWidget(_chat_name_badge(caption, role=role), 0, Qt.AlignmentFlag.AlignHCenter)
        meta.addWidget(
            _chat_bubble_frame(
                content,
                object_name="AgentChatSystemPill",
                stylesheet=_SYSTEM_PILL,
                max_width=min(max_w, 420),
            ),
            0,
            Qt.AlignmentFlag.AlignHCenter,
        )
        box = QWidget()
        box.setLayout(meta)
        row.addWidget(box, 0)
        row.addStretch(1)

    root.addLayout(row)
    return outer


def _update_chat_row_width(row: QWidget, max_width: int) -> None:
    if not row.property("chat_row"):
        return
    row.setProperty("chat_max_width", max_width)
    for frame in row.findChildren(QFrame):
        name = frame.objectName()
        if name in {
            "AgentChatUserBubble",
            "AgentChatAgentBubble",
            "AgentChatMetaBubble",
            "AgentChatSystemPill",
        }:
            cap = 420 if name == "AgentChatSystemPill" else max_width
            frame.setMaximumWidth(cap)
            inner_max = max(160, cap - 28)
            layout = frame.layout()
            if layout is not None and layout.count() > 0:
                item = layout.itemAt(0)
                inner = item.widget() if item is not None else None
                if inner is not None:
                    inner.setMaximumWidth(inner_max)
                    inner.updateGeometry()
    row.updateGeometry()


def _event_card(event: dict, *, expanded: bool = False) -> CursorFeedItem:
    event_type = str(event.get("type") or "system")
    key = str(event.get("event_key") or "")
    text = str(event.get("text") or event.get("message") or "")
    if event_type == "tool":
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
        title = str(event.get("title") or "Thinking")
        return CursorFeedItem(
            kind="thinking",
            text=text,
            title="LLM" if "llm" in title.casefold() or text.casefold().startswith("llm") else title,
            detail=text,
            event_key=key,
            expanded=expanded,
        )
    kind = {
        "user_message": "user",
        "agent_message": "agent",
        "work_result": "agent",
        "error": "error",
        "system": "system",
        "progress": "system",
    }.get(event_type, "system")
    text_color = "#FFFFFF" if event_type == "user_message" else ""
    return CursorFeedItem(
        kind=kind,
        text=text,
        title="",
        detail=text,
        event_key=key,
        expanded=expanded,
        text_color=text_color,
    )
