from __future__ import annotations

from threading import Thread

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.api_client import ApiClient, ApiError, WorkflowRecord
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, scroll_bar_qss

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
    background: #FFFFFF; color: #06483D;
    border: 1px solid rgba(16,24,23,0.12);
    border-radius: 12px; padding: 0 16px;
}
QPushButton:hover { background: #F4F7F6; }
"""
_FIELD = """
QLineEdit, QTextEdit {
    background: #FFFFFF; color: #101817;
    border: 1px solid rgba(16,24,23,0.12);
    border-radius: 10px;
    padding: 8px 10px;
}
"""
_TOOL_ROW = """
QFrame#ToolRow {
    background: #FFFFFF;
    border: 1px solid rgba(16,24,23,0.08);
    border-radius: 10px;
}
"""


class AgentSettingsPage(QWidget):
    back_requested = Signal()
    save_requested = Signal(object)
    chat_requested = Signal(object)

    _loaded = Signal(object, object, object)
    _load_fail = Signal(str)

    def __init__(self, api: ApiClient | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._api = api
        self._record: WorkflowRecord | None = None
        self._tool_checks: dict[str, QCheckBox] = {}
        self._busy = False
        self._pending_save_ok = False

        self._loaded.connect(self._apply_loaded)
        self._load_fail.connect(self._show_error)

        title = QLabel("Доработка агента")
        title.setFont(app_font(28, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        subtitle = QLabel(
            "Измените инструкцию, типовую задачу и набор инструментов. "
            "После сохранения агент будет работать с новыми настройками."
        )
        subtitle.setWordWrap(True)
        subtitle.setFont(app_font(13))
        subtitle.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        self._back = QPushButton("Назад")
        self._back.setCursor(Qt.CursorShape.PointingHandCursor)
        self._back.setFixedHeight(36)
        self._back.setStyleSheet(_SECONDARY)
        self._back.clicked.connect(self.back_requested.emit)

        self._banner = QLabel("")
        self._banner.setWordWrap(True)
        self._banner.setFont(app_font(12, QFont.Weight.Medium))
        self._banner.hide()

        self._agent_title = QLineEdit()
        self._agent_title.setReadOnly(True)
        self._agent_title.setFont(app_font(14, QFont.Weight.DemiBold))
        self._agent_title.setStyleSheet(_FIELD)

        self._default_task = QTextEdit()
        self._default_task.setPlaceholderText("Типовая задача — подставляется в чат по кнопке «Типовая задача»")
        self._default_task.setFont(app_font(13))
        self._default_task.setFixedHeight(90)
        self._default_task.setStyleSheet(_FIELD)

        self._instructions = QTextEdit()
        self._instructions.setPlaceholderText(
            "Инструкция агента: как выполнять задачу, какие инструменты использовать, формат результата"
        )
        self._instructions.setFont(app_font(13))
        self._instructions.setMinimumHeight(160)
        self._instructions.setStyleSheet(_FIELD)

        tools_header = QHBoxLayout()
        tools_title = QLabel("Инструменты")
        tools_title.setFont(app_font(16, QFont.Weight.DemiBold))
        tools_title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        self._select_all = QPushButton("Все")
        self._select_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self._select_all.setFixedHeight(30)
        self._select_all.setStyleSheet(_SECONDARY)
        self._select_all.clicked.connect(lambda: self._set_all_tools(True))
        self._select_none = QPushButton("Снять")
        self._select_none.setCursor(Qt.CursorShape.PointingHandCursor)
        self._select_none.setFixedHeight(30)
        self._select_none.setStyleSheet(_SECONDARY)
        self._select_none.clicked.connect(lambda: self._set_all_tools(False))
        tools_header.addWidget(tools_title, 1)
        tools_header.addWidget(self._select_all)
        tools_header.addWidget(self._select_none)

        self._tools_layout = QVBoxLayout()
        self._tools_layout.setContentsMargins(0, 0, 0, 0)
        self._tools_layout.setSpacing(6)
        tools_inner = QWidget()
        tools_inner.setStyleSheet("background: transparent;")
        tools_inner.setLayout(self._tools_layout)
        tools_scroll = QScrollArea()
        tools_scroll.setWidgetResizable(True)
        tools_scroll.setFrameShape(QFrame.Shape.NoFrame)
        tools_scroll.setMinimumHeight(220)
        tools_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }" + scroll_bar_qss())
        tools_scroll.setWidget(tools_inner)

        self._save = QPushButton("Сохранить")
        self._save.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save.setFixedHeight(40)
        self._save.setFont(app_font(13, QFont.Weight.DemiBold))
        self._save.setStyleSheet(_PRIMARY)
        self._save.clicked.connect(self._on_save)

        self._chat = QPushButton("Открыть чат")
        self._chat.setCursor(Qt.CursorShape.PointingHandCursor)
        self._chat.setFixedHeight(40)
        self._chat.setStyleSheet(_SECONDARY)
        self._chat.clicked.connect(self._on_chat)

        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(self._chat)
        footer.addWidget(self._save)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(title, 1)
        header.addWidget(self._back, 0, Qt.AlignmentFlag.AlignRight)

        form = QVBoxLayout()
        form.setSpacing(10)
        form.addLayout(header)
        form.addWidget(subtitle)
        form.addWidget(self._banner)
        form.addWidget(QLabel("Агент"))
        form.addWidget(self._agent_title)
        form.addWidget(QLabel("Типовая задача"))
        form.addWidget(self._default_task)
        form.addWidget(QLabel("Инструкция (playbook)"))
        form.addWidget(self._instructions)
        form.addLayout(tools_header)
        form.addWidget(tools_scroll, 1)
        form.addLayout(footer)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 4, 8, 8)
        root.setSpacing(0)
        root.addLayout(form)

    def load(self, record: WorkflowRecord) -> None:
        self._record = record
        self._agent_title.setText(record.title or "ИИ-агент")
        self._set_busy(True, "Загружаю настройки…")
        if self._api is None:
            self._load_fail.emit("Нет подключения к backend")
            return

        def work() -> None:
            try:
                fresh = self._api.get_workflow(record.id)
                route = self._api.get_agent_route(record.id)
                catalog = self._api.list_agent_tools()
                self._loaded.emit(fresh, route, catalog)
            except ApiError as exc:
                self._load_fail.emit(exc.message)
            except Exception as exc:  # noqa: BLE001
                self._load_fail.emit(str(exc))

        Thread(target=work, daemon=True).start()

    def _apply_loaded(self, record: object, route: object, catalog: object) -> None:
        if not isinstance(record, WorkflowRecord):
            self._set_busy(False)
            return
        self._record = record
        local = dict(record.local_run or {})
        playbook = local.get("playbook") if isinstance(local.get("playbook"), dict) else {}
        self._instructions.setPlainText(str(playbook.get("instructions") or ""))
        default_task = ""
        if route is not None and hasattr(route, "default_task"):
            default_task = str(getattr(route, "default_task") or "")
        if not default_task:
            default_task = str(local.get("default_task") or "")
        self._default_task.setPlainText(default_task)

        selected: set[str] = set()
        if route is not None and getattr(route, "tools", None):
            selected = {str(x) for x in route.tools if str(x).strip()}
        if not selected:
            stored = local.get("tools")
            if isinstance(stored, list):
                selected = {str(x) for x in stored if str(x).strip()}

        self._clear_tools()
        tools = [item for item in catalog if isinstance(item, dict)] if isinstance(catalog, list) else []
        tools.sort(key=lambda item: str(item.get("name") or ""))
        if not tools:
            hint = QLabel("Каталог инструментов пуст — проверьте backend.")
            hint.setWordWrap(True)
            hint.setFont(app_font(12))
            hint.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
            self._tools_layout.addWidget(hint)
        else:
            for item in tools:
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                row = QFrame()
                row.setObjectName("ToolRow")
                row.setStyleSheet(_TOOL_ROW)
                lay = QHBoxLayout(row)
                lay.setContentsMargins(10, 8, 10, 8)
                check = QCheckBox(name)
                check.setFont(app_font(13))
                check.setChecked(name in selected if selected else True)
                desc = str(item.get("description") or "").strip()
                if desc:
                    check.setToolTip(desc)
                lay.addWidget(check, 1)
                self._tools_layout.addWidget(row)
                self._tool_checks[name] = check
        self._tools_layout.addStretch(1)
        self._set_busy(False)
        if getattr(self, "_pending_save_ok", False):
            self._pending_save_ok = False
            self._banner.setText("Настройки сохранены.")
            self._banner.setStyleSheet(
                "color: #08745F; background: #EAF7F3; border-radius: 10px; padding: 8px 10px;"
            )
            self._banner.show()

    def _show_error(self, message: str) -> None:
        self._set_busy(False)
        self._banner.setText(message or "Не удалось загрузить настройки")
        self._banner.setStyleSheet("color: #9B1C1C; background: #FFF4F4; border-radius: 10px; padding: 8px 10px;")
        self._banner.show()

    def _on_save(self) -> None:
        if self._record is None or self._api is None or self._busy:
            return
        selected = [name for name, check in self._tool_checks.items() if check.isChecked()]
        if not selected:
            self._banner.setText("Выберите хотя бы один инструмент.")
            self._banner.setStyleSheet("color: #9B1C1C; background: #FFF4F4; border-radius: 10px; padding: 8px 10px;")
            self._banner.show()
            return
        self._set_busy(True, "Сохраняю…")

        def work() -> None:
            try:
                wid = self._record.id  # type: ignore[union-attr]
                instructions = self._instructions.toPlainText().strip()
                default_task = self._default_task.toPlainText().strip()
                local = dict(self._record.local_run or {})  # type: ignore[union-attr]
                playbook = dict(local.get("playbook") or {}) if isinstance(local.get("playbook"), dict) else {}
                playbook["instructions"] = instructions
                if instructions:
                    playbook["demo_ok"] = True
                local["playbook"] = playbook
                local["tools"] = list(selected)
                self._api.update_workflow_local_run(wid, local)
                route_patch: dict = {"tools": selected, "source": "user_settings"}
                if default_task:
                    route_patch["default_task"] = default_task
                self._api.update_agent_route(wid, route_patch)
                fresh = self._api.get_workflow(wid)
                self._pending_save_ok = True
                self._loaded.emit(fresh, self._api.get_agent_route(wid), self._api.list_agent_tools())
                self.save_requested.emit(fresh)
            except ApiError as exc:
                self._load_fail.emit(exc.message)
            except Exception as exc:  # noqa: BLE001
                self._load_fail.emit(str(exc))

        Thread(target=work, daemon=True).start()

    def _on_chat(self) -> None:
        if self._record is not None:
            self.chat_requested.emit(self._record)

    def _set_all_tools(self, checked: bool) -> None:
        for check in self._tool_checks.values():
            check.setChecked(checked)

    def _clear_tools(self) -> None:
        self._tool_checks.clear()
        while self._tools_layout.count():
            item = self._tools_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _set_busy(self, busy: bool, phrase: str = "") -> None:
        self._busy = busy
        self._save.setEnabled(not busy)
        self._chat.setEnabled(not busy)
        self._back.setEnabled(not busy)
        self._save.setText("Сохраняю…" if busy else "Сохранить")
        if busy and phrase:
            self._banner.setText(phrase)
            self._banner.setStyleSheet("color: #08745F; background: #EAF7F3; border-radius: 10px; padding: 8px 10px;")
            self._banner.show()
        elif not busy:
            if self._banner.text().startswith("Загружаю") or self._banner.text().startswith("Сохраняю"):
                self._banner.hide()
