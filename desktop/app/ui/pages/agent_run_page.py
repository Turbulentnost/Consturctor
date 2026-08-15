from __future__ import annotations

import json
from threading import Thread

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
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, scroll_bar_qss


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
    "onec.get_document_card": "Карточка документа 1С",
    "onec.search_tasks": "Поиск задач 1С",
    "onec.get_task_card": "Карточка задачи 1С",
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
        self._busy = False
        self._progress_body: QLabel | None = None
        self._event_ready.connect(self._append_event)
        self._done.connect(self._on_done)
        self.failed.connect(self._show_error)
        self._build()

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
        self._events = [
            {
                "type": "system",
                "text": f"Агент «{name}» готов к работе. Код и терминал не нужны — всё выполняется внутри приложения.",
            }
        ]
        self._busy = False
        self._send.setEnabled(True)
        self._quick.setEnabled(True)
        self._status.setText("Готов к работе")
        self._render()
        # Автозапуск типовой задачи — пользователь сразу видит результат.
        QTimer.singleShot(250, self._run_default_task)

    def _default_task(self) -> str:
        title = (self._workflow.title if self._workflow else "") or "агент"
        # Без хардкода конкретной площадки — задача из цели агента.
        return (
            f"Выполни рабочую задачу агента «{title}» по правилам из его плана "
            "и покажи понятный результат."
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
            try:
                result = self._api.stream_workflow_agent_run(
                    workflow_id,
                    message,
                    lambda payload: self._event_ready.emit(payload),
                )
            except ApiError as exc:
                self.failed.emit(exc.message)
                return
            self._done.emit(result)

        Thread(target=run, daemon=True).start()

    def _append_event(self, event: object) -> None:
        if not isinstance(event, dict):
            return
        friendly = _friendly_event(event)
        if friendly is None:
            return
        text = str(friendly.get("text") or friendly.get("message") or "").strip()
        if friendly.get("type") == "status":
            self._status.setText(text or "Агент работает…")
            # One live progress card — update in place, do not stack clones.
            if self._events and self._events[-1].get("type") == "status":
                self._events[-1] = friendly
                if self._progress_body is not None:
                    self._progress_body.setText(text)
                    return
            else:
                self._events.append(friendly)
            self._render()
            return
        self._events.append(friendly)
        self._render()

    def _on_done(self, _result: object) -> None:
        self._busy = False
        self._send.setEnabled(True)
        self._quick.setEnabled(True)
        self._status.setText("Готово")
        self._append_event({"type": "system", "text": "Готово. Можно дать следующую задачу."})

    def _show_error(self, message: str) -> None:
        self._busy = False
        self._send.setEnabled(True)
        self._quick.setEnabled(True)
        self._status.setText("Ошибка")
        self._append_event({"type": "error", "message": message})

    def _clear_feed(self) -> None:
        self._progress_body = None
        while self._feed_layout.count():
            item = self._feed_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _render(self) -> None:
        self._clear_feed()
        for event in self._events:
            card, progress_body = _event_card(event)
            if event.get("type") == "status" and progress_body is not None:
                self._progress_body = progress_body
            self._feed_layout.addWidget(card)
        self._feed_layout.addStretch(1)
        QTimer.singleShot(
            0,
            lambda: self._feed_scroll.verticalScrollBar().setValue(
                self._feed_scroll.verticalScrollBar().maximum()
            ),
        )


def _friendly_event(event: dict) -> dict | None:
    """Hide raw tool payloads / code; keep only user-facing messages."""
    event_type = str(event.get("type") or "system")
    if event_type == "run":
        return None
    if event_type == "tool_request":
        tool = str(event.get("tool") or "")
        label = _TOOL_LABELS.get(tool, tool or "инструмент")
        return {"type": "status", "text": f"Выполняю на этом ПК: «{label}»…"}
    if event_type == "status":
        text = str(event.get("text") or "").strip()
        return {"type": "status", "text": text[:280] or "Агент работает…"}
    if event_type == "thinking":
        text = str(event.get("text") or "").strip()
        if text and not text.startswith("{") and "traceback" not in text.casefold():
            return {"type": "status", "text": text[:280]}
        return {"type": "status", "text": "Агент анализирует задачу…"}
    if event_type == "tool_call":
        tool = str(event.get("tool") or "")
        label = _TOOL_LABELS.get(tool, "внешний источник")
        return {"type": "status", "text": f"Смотрю данные через «{label}»…"}
    if event_type == "tool_result":
        tool = str(event.get("tool") or "")
        result = event.get("result") if isinstance(event.get("result"), dict) else {}
        summary = _summarize_tool_result(tool, result)
        return {"type": "system", "text": summary} if summary else None
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
    # Drop unknown technical events.
    return None


def _summarize_tool_result(tool: str, result: dict) -> str:
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


def _event_card(event: dict) -> tuple[QWidget, QLabel | None]:
    event_type = str(event.get("type") or "system")
    text = str(event.get("text") or event.get("message") or "")
    heading = {
        "status": "Прогресс",
        "agent_message": "Агент",
        "user_message": "Вы",
        "error": "Ошибка",
        "system": "Система",
    }.get(event_type, "Система")
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    if event_type == "user_message":
        row.addStretch(1)
    card = QFrame()
    card.setMaximumWidth(720)
    bg = {
        "user_message": "rgba(8,116,95,0.09)",
        "status": "#F7FAF9",
        "error": "#FFF5F5",
    }.get(event_type, "#FFFFFF")
    card.setStyleSheet(
        f"""
        QFrame {{
            background: {bg};
            border: 1px solid rgba(8,116,95,0.14);
            border-radius: 16px;
        }}
        """
    )
    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 10, 14, 10)
    title = QLabel(heading)
    title.setFont(app_font(12, QFont.Weight.DemiBold))
    title.setStyleSheet("color: #08745F; background: transparent;")
    body = QLabel(text)
    body.setWordWrap(True)
    body.setFont(app_font(12))
    body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    body.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
    layout.addWidget(title)
    layout.addWidget(body)
    row.addWidget(card)
    if event_type != "user_message":
        row.addStretch(1)
    wrap = QWidget()
    wrap.setStyleSheet("background: transparent;")
    wrap.setLayout(row)
    return wrap, (body if event_type == "status" else None)
