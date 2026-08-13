from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Thread

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.api_client import ApiClient, ApiError, PassportSession, WorkflowRecord
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, scroll_bar_qss

SUPPORTED_SUFFIXES = {
    ".txt", ".md", ".markdown", ".csv", ".json", ".xml", ".html", ".htm",
    ".yaml", ".yml", ".log", ".pdf", ".docx", ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".xlsx", ".xls",
}

_STAGES = [
    ("document", "Материалы"),
    ("plan", "План"),
    ("clarify", "Уточнения"),
    ("ready", "Сборка workflow"),
    ("executing", "Тестовый прогон"),
    ("done", "Готово"),
]
_PHASE_RANK = {
    "document": 0,
    "plan": 1,
    "clarify": 2,
    "ready": 3,
    "executing": 4,
    "done": 5,
}

_SEND_BTN = """
QToolButton {
    background: #08745F; color: #FFFFFF; border: none;
    border-radius: 20px;
}
QToolButton:hover { background: #0A8670; }
QToolButton:disabled { background: #A8C8BF; }
"""
_CLIP_BTN = """
QToolButton {
    background: transparent; color: #6B7773; border: none;
    font-size: 18px;
}
QToolButton:hover { color: #08745F; }
"""
_COMPOSER = """
QLineEdit {
    background: #FFFFFF; color: #101817;
    border: 1px solid rgba(16,24,23,0.10);
    border-radius: 22px;
    padding: 10px 14px;
    selection-background-color: #08745F;
}
QLineEdit:focus { border: 1px solid #08745F; }
"""
_CHIP = """
QFrame#filechip {
    background: #F1F5F3;
    border: 1px solid rgba(16,24,23,0.08);
    border-radius: 12px;
}
"""
_SECONDARY = """
QPushButton {
    background: #F1F5F3; color: #06483D; border: none;
    border-radius: 12px; padding: 8px 14px; text-align: left;
}
QPushButton:hover { background: #E4EDE9; }
"""
@dataclass
class FeedEvent:
    title: str
    body: str
    time: str
    action: str = ""
    action_key: str = ""


class StageStepper(QWidget):
    """Vertical stages panel matching the mockup."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._active = 0
        self._rows: list[tuple[QFrame, QLabel, QLabel]] = []
        self.setFixedWidth(260)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(0)

        heading = QLabel("Этапы работы")
        heading.setFont(app_font(15, QFont.Weight.DemiBold))
        heading.setStyleSheet("color: #06483D; background: transparent;")
        root.addWidget(heading)
        root.addSpacing(14)

        self._list = QVBoxLayout()
        self._list.setSpacing(4)
        for _key, label in _STAGES:
            row, dot, text = self._make_row(label)
            self._rows.append((row, dot, text))
            self._list.addWidget(row)
        root.addLayout(self._list)
        root.addStretch(1)

        self._ready_label = QLabel("Готовность 0%")
        self._ready_label.setFont(app_font(12, QFont.Weight.DemiBold))
        self._ready_label.setStyleSheet("color: #06483D; background: transparent;")
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(6)
        self._bar.setStyleSheet(
            """
            QProgressBar {
                background: #E8EFEC; border: none; border-radius: 3px;
            }
            QProgressBar::chunk {
                background: #08745F; border-radius: 3px;
            }
            """
        )
        root.addWidget(self._ready_label)
        root.addSpacing(8)
        root.addWidget(self._bar)

        self.setStyleSheet(
            """
            StageStepper {
                background: #FFFFFF;
                border: 1px solid rgba(16,24,23,0.08);
                border-radius: 18px;
            }
            """
        )

    def _make_row(self, label: str) -> tuple[QFrame, QLabel, QLabel]:
        row = QFrame()
        row.setObjectName("stagerow")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(12)
        dot = QLabel("○")
        dot.setFixedSize(22, 22)
        dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dot.setFont(app_font(13, QFont.Weight.DemiBold))
        text = QLabel(label)
        text.setFont(app_font(13, QFont.Weight.Medium))
        text.setStyleSheet("background: transparent;")
        lay.addWidget(dot)
        lay.addWidget(text, 1)
        return row, dot, text

    def set_phase(self, phase: str) -> None:
        rank = _PHASE_RANK.get(phase, 0)
        if phase == "done":
            rank = len(_STAGES) - 1
        self._active = rank
        for i, (row, dot, text) in enumerate(self._rows):
            if i < rank or (phase == "done" and i <= rank):
                state = "done"
            elif i == rank:
                state = "active"
            else:
                state = "idle"
            if state == "done":
                row.setStyleSheet("QFrame#stagerow { background: transparent; border-radius: 12px; }")
                dot.setText("✓")
                dot.setStyleSheet(
                    "color: #FFFFFF; background: #08745F; border-radius: 11px;"
                )
                text.setStyleSheet("color: #06483D; background: transparent;")
            elif state == "active":
                row.setStyleSheet(
                    "QFrame#stagerow { background: #FFF4E5; border-radius: 12px; }"
                )
                dot.setText("●")
                dot.setStyleSheet(
                    "color: #FFFFFF; background: #F0A202; border-radius: 11px;"
                )
                text.setStyleSheet("color: #8A5300; background: transparent; font-weight: 600;")
            else:
                row.setStyleSheet("QFrame#stagerow { background: transparent; border-radius: 12px; }")
                dot.setText("○")
                dot.setStyleSheet(
                    "color: #9DB3AD; background: #F1F5F3; border-radius: 11px;"
                )
                text.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        pct = int(round((rank / max(1, len(_STAGES) - 1)) * 100))
        if phase == "done":
            pct = 100
        self._ready_label.setText(f"Готовность {pct}%")
        self._bar.setValue(pct)


class FeedItem(QFrame):
    action_clicked = Signal(str)

    def __init__(self, event: FeedEvent, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 4, 0, 10)
        row.setSpacing(12)

        avatar = QLabel("🤖")
        avatar.setFixedSize(36, 36)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet(
            "background: #EAF7F3; border-radius: 18px; font-size: 16px;"
        )

        col = QVBoxLayout()
        col.setSpacing(4)
        title = QLabel(event.title)
        title.setFont(app_font(12))
        title.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        body = QLabel(event.body)
        body.setFont(app_font(14, QFont.Weight.Medium))
        body.setWordWrap(True)
        body.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        col.addWidget(title)
        col.addWidget(body)
        if event.action:
            btn = QPushButton(event.action)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFont(app_font(12, QFont.Weight.DemiBold))
            btn.setStyleSheet(_SECONDARY)
            btn.setFixedHeight(36)
            key = event.action_key
            btn.clicked.connect(lambda _=False, k=key: self.action_clicked.emit(k))
            col.addWidget(btn, 0, Qt.AlignmentFlag.AlignLeft)

        time = QLabel(event.time)
        time.setFont(app_font(11))
        time.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        time.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)

        row.addWidget(avatar, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(col, 1)
        row.addWidget(time, 0, Qt.AlignmentFlag.AlignTop)


class WorkflowPage(QWidget):
    saved = Signal(str)
    saved_record = Signal(object)
    _async_ok = Signal(object, str)
    _async_fail = Signal(str)

    def __init__(self, api: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._api = api
        self._record: WorkflowRecord | None = None
        self._pending_paths: list[str] = []
        self._workflow_title = ""
        self._notes = ""
        self._results_dir = ""
        self._busy = False
        self._events: list[FeedEvent] = []
        self._pending_answers: dict[str, str] = {}
        self._async_ok.connect(self._on_async_ok)
        self._async_fail.connect(self._on_async_fail)
        self._build()
        self._render_all()

    def _build(self) -> None:
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        title = QLabel("Конструктор workflow")
        title.setFont(app_font(24, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

        # --- Center: agent feed -------------------------------------------------
        feed_card = QFrame()
        feed_card.setStyleSheet(
            """
            QFrame#feedcard {
                background: #FFFFFF;
                border: 1px solid rgba(16,24,23,0.08);
                border-radius: 18px;
            }
            """
        )
        feed_card.setObjectName("feedcard")
        feed_lay = QVBoxLayout(feed_card)
        feed_lay.setContentsMargins(20, 16, 20, 14)
        feed_lay.setSpacing(10)

        feed_title = QLabel("Работа агента")
        feed_title.setFont(app_font(15, QFont.Weight.DemiBold))
        feed_title.setStyleSheet("color: #06483D; background: transparent;")
        feed_lay.addWidget(feed_title)

        self._feed_inner = QWidget()
        self._feed_inner.setStyleSheet("background: transparent;")
        self._feed_layout = QVBoxLayout(self._feed_inner)
        self._feed_layout.setContentsMargins(0, 0, 8, 0)
        self._feed_layout.setSpacing(2)
        self._feed_layout.addStretch(1)

        feed_scroll = QScrollArea()
        feed_scroll.setWidgetResizable(True)
        feed_scroll.setFrameShape(QFrame.Shape.NoFrame)
        feed_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        feed_scroll.setWidget(self._feed_inner)
        feed_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }" + scroll_bar_qss()
        )
        feed_lay.addWidget(feed_scroll, 1)

        # file chips
        self._chips_wrap = QWidget()
        self._chips_wrap.setStyleSheet("background: transparent;")
        self._chips_layout = QHBoxLayout(self._chips_wrap)
        self._chips_layout.setContentsMargins(0, 0, 0, 0)
        self._chips_layout.setSpacing(8)
        self._chips_layout.addStretch(1)
        feed_lay.addWidget(self._chips_wrap)

        # composer
        composer_row = QHBoxLayout()
        composer_row.setSpacing(8)
        self._clip_btn = QToolButton()
        self._clip_btn.setText("📎")
        self._clip_btn.setFixedSize(40, 40)
        self._clip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clip_btn.setStyleSheet(_CLIP_BTN)
        self._clip_btn.setToolTip("Приложить файл")
        self._clip_btn.clicked.connect(self._on_pick_files)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Напишите сообщение агенту…")
        self._input.setFont(app_font(13))
        self._input.setFixedHeight(44)
        self._input.setStyleSheet(_COMPOSER)
        self._input.returnPressed.connect(self._on_send)

        self._send_btn = QToolButton()
        self._send_btn.setText("↑")
        self._send_btn.setFixedSize(40, 40)
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.setStyleSheet(_SEND_BTN)
        self._send_btn.clicked.connect(self._on_send)

        composer_row.addWidget(self._clip_btn)
        composer_row.addWidget(self._input, 1)
        composer_row.addWidget(self._send_btn)
        feed_lay.addLayout(composer_row)

        status_row = QHBoxLayout()
        status_row.setSpacing(12)
        self._agent_status = QLabel("● Готов к работе")
        self._agent_status.setFont(app_font(12))
        self._agent_status.setStyleSheet("color: #08745F; background: transparent;")
        self._run_btn = QPushButton("Запустить сборку")
        self._run_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._run_btn.setFont(app_font(12, QFont.Weight.DemiBold))
        self._run_btn.setFixedHeight(32)
        self._run_btn.setStyleSheet(
            """
            QPushButton {
                background: #08745F; color: #FFFFFF; border: none;
                border-radius: 12px; padding: 0 14px;
            }
            QPushButton:hover { background: #0A8670; }
            QPushButton:disabled { background: #A8C8BF; color: #EAF7F3; }
            """
        )
        self._run_btn.clicked.connect(self._on_run_clicked)
        self._run_btn.setVisible(False)
        status_row.addWidget(self._agent_status, 1)
        status_row.addWidget(self._run_btn, 0)
        feed_lay.addLayout(status_row)

        # hidden results list for downloads
        self._results = QListWidget()
        self._results.setVisible(False)
        self._results.itemDoubleClicked.connect(self._open_result_item)
        feed_lay.addWidget(self._results)

        self._stepper = StageStepper()

        body = QHBoxLayout()
        body.setSpacing(16)
        body.addWidget(feed_card, 1)
        body.addWidget(self._stepper, 0)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        root.addWidget(title)
        root.addLayout(body, 1)

        self._busy_timer = QTimer(self)
        self._busy_timer.setInterval(400)
        self._busy_timer.timeout.connect(self._tick_activity)
        self._busy_base = "Агент работает"
        self._busy_n = 0

    # --- public API ------------------------------------------------------------

    def load_record(self, record: WorkflowRecord) -> None:
        self._record = record
        self._pending_paths = []
        self._workflow_title = record.title
        self._notes = record.notes
        self._events = [
            FeedEvent(
                "Загрузка workflow",
                f"Открыт «{record.title}» · фаза {record.phase}",
                self._now(),
            )
        ]
        if record.plan:
            self._events.append(
                FeedEvent(
                    "План",
                    record.plan.goal or record.plan.title or "План загружен",
                    self._now(),
                    action="Показать шаги плана",
                    action_key="show_plan",
                )
            )
            for q in record.plan.unanswered():
                self._events.append(
                    FeedEvent(
                        "Уточнение",
                        q.question,
                        self._now(),
                        action="Ответить в поле ниже",
                        action_key=f"q:{q.id}",
                    )
                )
        if record.last_result:
            self._events.append(
                FeedEvent("Результат", record.last_result[:500], self._now())
            )
        self._render_chips()
        self._render_all()

    def start_from_passport(self, session: PassportSession, *, auto_plan: bool = True) -> None:
        self._on_new()
        title = (session.passport.name or session.bp_name or "ИИ-агент").strip()
        self._workflow_title = title
        self._notes = _notes_from_passport(session)
        self._push_event(
            "Анализ документа",
            f"Загружен паспорт «{title}». Готовлю план реализации…",
        )
        if auto_plan:
            self._on_plan()

    # --- render ----------------------------------------------------------------

    def _render_all(self) -> None:
        phase = self._record.phase if self._record else "document"
        self._stepper.set_phase(phase)
        self._rebuild_feed()
        plan = self._record.plan if self._record else None
        unanswered = bool(plan and plan.unanswered())
        can_run = bool(plan) and not unanswered and not self._busy
        self._run_btn.setVisible(can_run)
        self._run_btn.setEnabled(can_run)
        if self._record and self._record.exec_agent_id:
            self._run_btn.setText("Запустить снова")
        else:
            self._run_btn.setText("Запустить сборку")
        if self._busy:
            self._agent_status.setText("● Агент работает — можно отправить уточнение")
            self._agent_status.setStyleSheet("color: #08745F; background: transparent;")
        elif unanswered:
            self._agent_status.setText("● Нужны уточнения — напишите ответ ниже")
            self._agent_status.setStyleSheet("color: #C47E00; background: transparent;")
        elif plan and not unanswered:
            self._agent_status.setText("● План готов — можно запускать")
            self._agent_status.setStyleSheet("color: #08745F; background: transparent;")
        else:
            self._agent_status.setText("● Готов к работе")
            self._agent_status.setStyleSheet("color: #08745F; background: transparent;")

    def _rebuild_feed(self) -> None:
        while self._feed_layout.count():
            item = self._feed_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for event in self._events:
            widget = FeedItem(event)
            widget.action_clicked.connect(self._on_feed_action)
            self._feed_layout.addWidget(widget)
        self._feed_layout.addStretch(1)

    def _render_chips(self) -> None:
        while self._chips_layout.count():
            item = self._chips_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        names: list[str] = []
        if self._record:
            names.extend(att.name for att in (self._record.attachments or []) if att.name)
        names.extend(Path(p).name for p in self._pending_paths)
        for name in names[:8]:
            chip = QFrame()
            chip.setObjectName("filechip")
            chip.setStyleSheet(_CHIP)
            lay = QHBoxLayout(chip)
            lay.setContentsMargins(10, 4, 8, 4)
            lay.setSpacing(6)
            lbl = QLabel(name)
            lbl.setFont(app_font(11))
            lbl.setStyleSheet("background: transparent; color: #06483D;")
            lay.addWidget(lbl)
            self._chips_layout.addWidget(chip)
        self._chips_layout.addStretch(1)
        self._chips_wrap.setVisible(bool(names))

    def _push_event(self, title: str, body: str, *, action: str = "", action_key: str = "") -> None:
        self._events.append(
            FeedEvent(title=title, body=body, time=self._now(), action=action, action_key=action_key)
        )
        self._rebuild_feed()

    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%H:%M")

    # --- interactions ----------------------------------------------------------

    def _on_feed_action(self, key: str) -> None:
        if key == "show_plan" and self._record and self._record.plan:
            plan = self._record.plan
            lines = [f"{s.id}: {s.title}" for s in (plan.steps or [])]
            self._push_event("Шаги плана", "\n".join(lines) or plan.goal or "—")
        elif key == "run_plan":
            self._on_execute()
        elif key == "fetch":
            self._on_fetch_results()
        elif key.startswith("q:"):
            self._input.setFocus()

    def _on_pick_files(self) -> None:
        patterns = " ".join(f"*{s}" for s in sorted(SUPPORTED_SUFFIXES))
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Приложить файлы", "", f"Документы ({patterns});;Все файлы (*)"
        )
        for path in paths:
            if path and Path(path).is_file() and path not in self._pending_paths:
                suffix = Path(path).suffix.lower()
                if suffix and suffix not in SUPPORTED_SUFFIXES:
                    continue
                self._pending_paths.append(path)
        self._render_chips()

    def _on_send(self) -> None:
        text = self._input.text().strip()
        if not text and not self._pending_paths:
            return
        self._input.clear()
        if self._record and self._record.plan and self._record.plan.unanswered():
            # Treat as clarify answers: map text to all unanswered or first
            unanswered = self._record.plan.unanswered()
            answers = {q.id: text for q in unanswered}
            self._push_event("Вы", text or "Файл приложен")
            self._append_user_files_to_event()
            wid = self._record.id
            paths = list(self._pending_paths)
            qids = [unanswered[0].id] * len(paths) if unanswered and paths else []

            def work() -> WorkflowRecord:
                return self._api.clarify_workflow(
                    wid, answers, file_paths=paths, file_question_ids=qids
                )

            self._run_async("Уточнение плана", work)
            return

        if self._record is None:
            if text:
                self._notes = (self._notes + "\n" + text).strip() if self._notes else text
            self._push_event("Вы", text or "Материалы приложены")
            self._on_plan()
            return

        # Free-form message while plan ready → replan or execute hint
        self._push_event("Вы", text)
        if self._record.plan and not self._record.plan.unanswered():
            self._push_event(
                "Агент",
                "План уже готов. Нажмите «Запустить», чтобы собрать workflow, "
                "или уточните требования — пересоберу план.",
                action="Запустить сборку",
                action_key="run_plan",
            )
        else:
            self._on_plan()

    def _append_user_files_to_event(self) -> None:
        if self._pending_paths:
            names = ", ".join(Path(p).name for p in self._pending_paths)
            self._push_event("Вложения", names)

    def _set_busy(self, busy: bool, base: str = "Агент работает") -> None:
        self._busy = busy
        self._send_btn.setEnabled(True)  # allow clarify while working, per mockup
        self._clip_btn.setEnabled(True)
        if busy:
            self._busy_base = base
            self._busy_n = 0
            self._busy_timer.start()
            self._tick_activity()
        else:
            self._busy_timer.stop()
            self._render_all()

    def _tick_activity(self) -> None:
        self._busy_n = (self._busy_n % 3) + 1
        self._agent_status.setText(f"● {self._busy_base}{'.' * self._busy_n}")

    def _run_async(self, label: str, fn) -> None:
        self._set_busy(True, label)

        def work() -> None:
            try:
                result = fn()
                self._async_ok.emit(result, label)
            except ApiError as exc:
                self._async_fail.emit(exc.message)
            except Exception as exc:  # noqa: BLE001
                self._async_fail.emit(str(exc))

        Thread(target=work, daemon=True).start()

    def _on_async_ok(self, result: object, label: str) -> None:
        self._set_busy(False)
        if isinstance(result, WorkflowRecord):
            self._record = result
            self._pending_paths = []
            self._workflow_title = result.title
            self._notes = result.notes or self._notes
            self._render_chips()
            if label.startswith("Планирование"):
                n = len(result.plan.unanswered()) if result.plan else 0
                goal = (result.plan.goal if result.plan else "") or result.title
                self._push_event(
                    "План",
                    goal,
                    action="Показать шаги плана",
                    action_key="show_plan",
                )
                if n:
                    for q in result.plan.unanswered()[:3]:  # type: ignore[union-attr]
                        self._push_event(
                            "Уточнение",
                            q.question,
                            action="Ответить в поле ниже",
                            action_key=f"q:{q.id}",
                        )
                else:
                    self._push_event(
                        "Сборка workflow",
                        "План готов без открытых вопросов. Можно запускать реализацию.",
                        action="Запустить сборку",
                        action_key="run_plan",
                    )
            elif label.startswith("Уточнение"):
                n = len(result.plan.unanswered()) if result.plan else 0
                if n:
                    for q in result.plan.unanswered()[:2]:  # type: ignore[union-attr]
                        self._push_event("Уточнение", q.question)
                else:
                    self._push_event(
                        "Сборка workflow",
                        "Уточнения учтены. План готов к запуску.",
                        action="Запустить сборку",
                        action_key="run_plan",
                    )
            elif label.startswith("Реализация"):
                self._push_event(
                    "Тестовый прогон",
                    (result.last_result or "Реализация завершена.")[:800],
                    action="Скачать результат" if result.exec_agent_id else "",
                    action_key="fetch",
                )
                self._on_fetch_results()
            self.saved.emit(result.id)
            self.saved_record.emit(result)
            self._render_all()
        elif isinstance(result, tuple) and len(result) == 2:
            dest_dir, files = result
            self._results_dir = str(dest_dir)
            self._results.clear()
            for path in files:
                item = QListWidgetItem(Path(path).name)
                item.setData(Qt.ItemDataRole.UserRole, path)
                self._results.addItem(item)
            self._push_event(
                "Результат",
                f"Скачано файлов: {len(files)}\n{dest_dir}",
            )

    def _on_async_fail(self, message: str) -> None:
        self._set_busy(False)
        self._push_event("Ошибка", message)
        self._agent_status.setText("● Ошибка — попробуйте ещё раз")
        self._agent_status.setStyleSheet("color: #B00020; background: transparent;")

    def _on_plan(self) -> None:
        notes = (self._notes or "").strip()
        if self._record is None:
            if not notes and not self._pending_paths:
                QMessageBox.warning(
                    self,
                    "Документ",
                    "Нет материалов. Откройте workflow из паспорта агента.",
                )
                return
            self._push_event("Анализ документа", "Создаю workflow и запускаю планирование…")

            def create_and_plan() -> WorkflowRecord:
                created = self._api.create_workflow(notes=notes, file_paths=self._pending_paths)
                return self._api.plan_workflow(created.id)

            self._run_async("Планирование", create_and_plan)
            return
        self._push_event("План", "Пересобираю план…")
        self._run_async("Планирование", lambda: self._api.plan_workflow(self._record.id))  # type: ignore[union-attr]

    def _on_run_clicked(self) -> None:
        reexecute = bool(self._record and self._record.exec_agent_id)
        self._on_execute(reexecute=reexecute)

    def _on_execute(self, reexecute: bool = False) -> None:
        if self._record is None or self._record.plan is None:
            QMessageBox.information(self, "План", "Сначала постройте план.")
            return
        if self._record.plan.unanswered():
            QMessageBox.information(self, "Уточнения", "Сначала ответьте на вопросы агента.")
            return
        self._push_event("Сборка workflow", "Запускаю реализацию…")
        wid = self._record.id
        self._run_async(
            "Реализация",
            lambda: self._api.execute_workflow(wid, reexecute=reexecute),
        )

    def _on_fetch_results(self) -> None:
        if self._record is None or not self._record.exec_agent_id:
            return
        wid = self._record.id

        def work():
            result = self._api.download_workflow_artifacts(wid)
            return result.dest_dir, result.files

        self._run_async("Скачивание", work)

    def _open_result_item(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _on_new(self) -> None:
        self._record = None
        self._pending_paths.clear()
        self._workflow_title = ""
        self._notes = ""
        self._results_dir = ""
        self._events = []
        self._results.clear()
        self._render_chips()
        self._render_all()
        self._push_event(
            "Старт",
            "Опишите задачу или откройте паспорт агента — начну планирование.",
        )


def _notes_from_passport(session: PassportSession) -> str:
    passport = session.passport
    title = (passport.name or session.bp_name or "ИИ-агент").strip()
    text = (passport.text or "").strip()
    if not text:
        text = "\n".join(
            [
                f"ИИ-агент: {passport.name or '—'}",
                f"Цель: {passport.goal or '—'}",
                f"Триггер: {passport.trigger or '—'}",
                f"Получает: {passport.receives or '—'}",
                f"Проверяет: {passport.checks or '—'}",
                f"Принимает решения: {passport.decisions or '—'}",
                f"Может самостоятельно: {passport.can_autonomous or '—'}",
                f"Требует подтверждения человека: {passport.needs_human_approval or '—'}",
                f"Не может: {passport.forbidden or '—'}",
                f"Результат: {passport.result or '—'}",
            ]
        )
    lines = [
        f"# Паспорт ИИ-агента: {title}",
        "",
        "Составь план реализации ИИ-агента по согласованному паспорту.",
        "Не меняй смысл полей паспорта без уточняющих вопросов.",
        "В steps опиши конкретные шаги автоматизации процесса.",
        "",
        "## Паспорт",
        text,
    ]
    if session.excerpt.strip():
        lines.extend(["", "## Фрагмент регламента", session.excerpt.strip()[:4000]])
    if session.functions:
        lines.extend(["", "## Функции агента"])
        for item in session.functions:
            desc = f" — {item.description}" if item.description else ""
            lines.append(f"- {item.name}{desc}")
    return "\n".join(lines).strip() + "\n"
