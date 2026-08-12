from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent, QFont, QTextCursor
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.workflow import storage
from app.workflow.document import (
    MAX_IMAGES,
    SUPPORTED_SUFFIXES,
    compose_document,
    supported_filter_label,
)
from app.workflow.models import AttachedFile, WorkflowRecord
from app.workflow.prompts import plan_summary_text
from app.workflow.service import (
    ArtifactsWorker,
    ClarifyWorker,
    ExecuteWorker,
    FilesWorker,
    PlanWorker,
    start_worker,
)
from app.ui.theme import app_font

_PRIMARY = """
QPushButton {
    background: #06483D; color: #F7FBFA; border: none;
    border-radius: 16px; padding: 0 18px;
}
QPushButton:hover { background: #08745F; }
QPushButton:disabled { background: #9DB3AD; color: #EEF3F1; }
"""

_SECONDARY = """
QPushButton {
    background: #E4EFEA; color: #06483D; border: 1px solid #BFD8CF;
    border-radius: 16px; padding: 0 18px;
}
QPushButton:hover { background: #D3E7DF; }
QPushButton:disabled { background: #EEF3F1; color: #9DB3AD; }
"""

_FIELD = """
QLineEdit, QPlainTextEdit {
    background: #FFFFFF; color: #101817;
    border: 1px solid #D0DFD8; border-radius: 14px;
    padding: 10px 14px; selection-background-color: #08745F;
}
QLineEdit:focus, QPlainTextEdit:focus { border: 1px solid #08745F; }
"""

_CARD = """
QFrame#card {
    background: #FFFFFF; border: 1px solid #D7E6DF; border-radius: 16px;
}
"""

_QCARD = """
QFrame#qcard {
    background: #FFF7E9; border: 2px solid #F0C98A; border-radius: 16px;
}
"""

_ANSWER_FIELD = """
QPlainTextEdit {
    background: #FFFFFF; color: #101817;
    border: 1px solid #E0C08A; border-radius: 12px;
    padding: 8px 12px; selection-background-color: #08745F;
}
QPlainTextEdit:focus { border: 1px solid #08745F; }
"""

_LOG = """
QPlainTextEdit {
    background: #0F1F1B; color: #D7EBE3;
    border: 1px solid #1F3A32; border-radius: 14px; padding: 12px;
}
"""

_PHASE_LABELS = {
    "document": "1 · Документ",
    "plan": "2 · Планирование",
    "clarify": "3 · Уточнения",
    "ready": "4 · Готов к реализации",
    "executing": "5 · Выполнение",
    "done": "6 · Готово",
}

_PHASE_STYLE_IDLE = (
    "color: #06483D; background: #E3F3EC; border-radius: 10px; padding: 4px 12px;"
)
_PHASE_STYLE_BUSY = (
    "color: #8A4B00; background: #FFE7C2; border-radius: 10px; padding: 4px 12px;"
)
_ACTIVITY_STYLE = (
    "color: #8A4B00; background: #FFF1DC; border: 1px solid #F0C98A;"
    "border-radius: 10px; padding: 4px 12px;"
)


def _section(title: str) -> QLabel:
    label = QLabel(title)
    label.setFont(app_font(13, QFont.Weight.DemiBold))
    label.setStyleSheet("color: #06483D; background: transparent;")
    return label


_DROP_IDLE = """
QFrame#drop {
    background: #F3F8F5; border: 2px dashed #B7D0C6; border-radius: 16px;
}
"""
_DROP_ACTIVE = """
QFrame#drop {
    background: #E3F3EC; border: 2px dashed #08745F; border-radius: 16px;
}
"""

_LIST = """
QListWidget {
    background: #FFFFFF; border: 1px solid #D0DFD8; border-radius: 14px;
    padding: 4px; outline: none;
}
QListWidget::item {
    padding: 8px 10px; border-radius: 8px; color: #101817;
}
QListWidget::item:selected {
    background: #E3F3EC; color: #06483D;
}
"""


class DropZone(QFrame):
    files_dropped = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("drop")
        self.setAcceptDrops(True)
        self.setStyleSheet(_DROP_IDLE)
        self.setMinimumHeight(96)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)
        title = QLabel("Перетащите файлы сюда")
        title.setFont(app_font(13, QFont.Weight.DemiBold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #06483D; background: transparent; border: none;")
        hint = QLabel(
            "или «Загрузить файлы» · текст, pdf/docx, картинки "
            f"(png/jpg/gif/webp, до {MAX_IMAGES} шт.)"
        )
        hint.setFont(app_font(11))
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("color: #6B7773; background: transparent; border: none;")
        hint.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(hint)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet(_DROP_ACTIVE)
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.setStyleSheet(_DROP_IDLE)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self.setStyleSheet(_DROP_IDLE)
        paths = []
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local:
                paths.append(local)
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()


class WorkflowPage(QWidget):
    saved = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._record: WorkflowRecord | None = None
        self._attachments: list[AttachedFile] = []
        self._worker: QWidget | None = None
        self._jobs: list = []
        self._question_fields: dict[str, QLineEdit] = {}
        self._results_dir: str = ""
        self._build()
        self._render_phase()
        self._render_attachments()

    # ---- construction -----------------------------------------------------

    def _build(self) -> None:
        title = QLabel("Конструктор workflow")
        title.setFont(app_font(26, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #101817; background: transparent;")

        self._phase = QLabel("")
        self._phase.setFont(app_font(12, QFont.Weight.DemiBold))
        self._phase.setStyleSheet(_PHASE_STYLE_IDLE)

        self._activity = QLabel("")
        self._activity.setFont(app_font(12, QFont.Weight.DemiBold))
        self._activity.setStyleSheet(_ACTIVITY_STYLE)
        self._activity.setVisible(False)

        self._busy_timer = QTimer(self)
        self._busy_timer.setInterval(400)
        self._busy_timer.timeout.connect(self._tick_activity)
        self._busy_base = "Обращение к агенту"
        self._busy_n = 0

        header = QHBoxLayout()
        header.addWidget(title, 1)
        header.addWidget(self._activity, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self._phase, 0, Qt.AlignmentFlag.AlignVCenter)

        # left column: inputs (scrollable)
        left_inner = QWidget()
        left = QVBoxLayout(left_inner)
        left.setContentsMargins(0, 0, 8, 0)
        left.setSpacing(10)

        self._name = QLineEdit()
        self._name.setPlaceholderText("Название workflow")
        self._name.setFont(app_font(13))
        self._name.setFixedHeight(42)
        self._name.setStyleSheet(_FIELD)

        self._drop = DropZone()
        self._drop.files_dropped.connect(self._load_paths)

        self._upload_btn = QPushButton("Загрузить файлы…")
        self._upload_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._upload_btn.setFixedHeight(38)
        self._upload_btn.setFont(app_font(12, QFont.Weight.DemiBold))
        self._upload_btn.setStyleSheet(_SECONDARY)
        self._upload_btn.clicked.connect(self._on_pick_files)

        self._remove_btn = QPushButton("Удалить")
        self._remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._remove_btn.setFixedHeight(38)
        self._remove_btn.setFont(app_font(12, QFont.Weight.DemiBold))
        self._remove_btn.setStyleSheet(_SECONDARY)
        self._remove_btn.clicked.connect(self._on_remove_file)

        self._clear_files_btn = QPushButton("Очистить")
        self._clear_files_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_files_btn.setFixedHeight(38)
        self._clear_files_btn.setFont(app_font(12, QFont.Weight.DemiBold))
        self._clear_files_btn.setStyleSheet(_SECONDARY)
        self._clear_files_btn.clicked.connect(self._on_clear_files)

        file_actions = QHBoxLayout()
        file_actions.setSpacing(8)
        file_actions.addWidget(self._upload_btn, 1)
        file_actions.addWidget(self._remove_btn)
        file_actions.addWidget(self._clear_files_btn)

        self._files = QListWidget()
        self._files.setFont(app_font(12))
        self._files.setStyleSheet(_LIST)
        self._files.setMinimumHeight(110)
        self._files.setMaximumHeight(160)

        self._files_hint = QLabel("Файлы не загружены.")
        self._files_hint.setFont(app_font(11))
        self._files_hint.setStyleSheet("color: #6B7773; background: transparent;")
        self._files_hint.setWordWrap(True)

        self._doc = QPlainTextEdit()
        self._doc.setPlaceholderText("Впишите здесь текст задачи / ТЗ — или загрузите файлы выше…")
        self._doc.setFont(app_font(12))
        self._doc.setMinimumHeight(120)
        self._doc.setStyleSheet(_FIELD)

        left.addWidget(_section("Workflow"))
        left.addWidget(self._name)
        left.addWidget(_section("Файлы"))
        left.addWidget(self._drop)
        left.addLayout(file_actions)
        left.addWidget(self._files)
        left.addWidget(self._files_hint)
        left.addWidget(_section("Текст задачи / ТЗ"))
        left.addWidget(self._doc)

        left.addStretch(1)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        left_scroll.setWidget(left_inner)
        left_scroll.setFixedWidth(430)

        # right column: plan + questions + log
        self._plan_view = QPlainTextEdit()
        self._plan_view.setReadOnly(True)
        self._plan_view.setFont(app_font(12))
        self._plan_view.setStyleSheet(_FIELD)
        self._plan_view.setPlaceholderText("Здесь появится план после фазы планирования.")

        # questions card (shown under the plan when the agent has open questions)
        self._questions_card = QFrame()
        self._questions_card.setObjectName("qcard")
        self._questions_card.setStyleSheet(_QCARD)
        card_layout = QVBoxLayout(self._questions_card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(8)

        self._q_header = QLabel("Вопросы агента — впишите ответы в окошки ниже")
        self._q_header.setFont(app_font(13, QFont.Weight.DemiBold))
        self._q_header.setStyleSheet("color: #8A4B00; background: transparent;")
        self._q_header.setWordWrap(True)

        self._questions_inner = QWidget()
        self._questions_inner.setStyleSheet("background: transparent;")
        self._questions_layout = QVBoxLayout(self._questions_inner)
        self._questions_layout.setContentsMargins(0, 0, 6, 0)
        self._questions_layout.setSpacing(10)

        q_scroll = QScrollArea()
        q_scroll.setWidgetResizable(True)
        q_scroll.setFrameShape(QFrame.Shape.NoFrame)
        q_scroll.setWidget(self._questions_inner)
        q_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self._clarify_btn = self._mk_button("Отправить ответы агенту", _PRIMARY, self._on_clarify)

        card_layout.addWidget(self._q_header)
        card_layout.addWidget(q_scroll, 1)
        clarify_row = QHBoxLayout()
        clarify_row.addStretch(1)
        clarify_row.addWidget(self._clarify_btn)
        card_layout.addLayout(clarify_row)
        self._questions_card.setVisible(False)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(app_font(11))
        self._log.setStyleSheet(_LOG)
        self._log.setPlaceholderText("Стрим агента…")

        # results (files produced by the run, downloaded from artifacts/)
        self._results_header = _section("Результат (файлы)")
        self._results = QListWidget()
        self._results.setFont(app_font(12))
        self._results.setMaximumHeight(120)
        self._results.setStyleSheet(_LIST)
        self._results.itemDoubleClicked.connect(self._open_result_item)

        self._fetch_btn = self._mk_button("Скачать файлы результата", _SECONDARY, self._on_fetch_results)
        self._open_dir_btn = self._mk_button("Открыть папку", _SECONDARY, self._open_results_folder)
        results_actions = QHBoxLayout()
        results_actions.addWidget(self._fetch_btn)
        results_actions.addWidget(self._open_dir_btn)
        results_actions.addStretch(1)
        self._results_actions_row = results_actions

        right = QVBoxLayout()
        right.setSpacing(10)
        right.addWidget(_section("План"))
        right.addWidget(self._plan_view, 2)
        right.addWidget(self._questions_card, 3)
        right.addWidget(_section("Стрим"))
        right.addWidget(self._log, 2)
        right.addWidget(self._results_header)
        right.addWidget(self._results, 1)
        right.addLayout(results_actions)

        body = QHBoxLayout()
        body.setSpacing(16)
        body.addWidget(left_scroll, 0)
        body.addLayout(right, 1)

        # action bar (clarify button lives inside the questions card)
        self._plan_btn = self._mk_button("Спланировать", _PRIMARY, self._on_plan)
        self._exec_btn = self._mk_button("Запустить", _PRIMARY, self._on_execute)
        self._rerun_btn = self._mk_button("Запустить снова", _SECONDARY, lambda: self._on_execute(reexecute=True))
        self._save_btn = self._mk_button("Сохранить", _SECONDARY, self._on_save)
        self._cancel_btn = self._mk_button("Отменить", _SECONDARY, self._on_cancel)
        self._new_btn = self._mk_button("Новый", _SECONDARY, self._on_new)
        self._cancel_btn.setEnabled(False)

        self._status = QLabel("")
        self._status.setFont(app_font(12))
        self._status.setStyleSheet("color: #2D7A5E; background: transparent;")
        self._status.setWordWrap(True)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        for btn in (
            self._plan_btn,
            self._exec_btn,
            self._rerun_btn,
            self._save_btn,
            self._cancel_btn,
            self._new_btn,
        ):
            actions.addWidget(btn)
        actions.addStretch(1)
        actions.addWidget(self._status, 1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)
        root.addLayout(header)
        root.addLayout(body, 1)
        root.addLayout(actions)

    def _mk_button(self, text: str, style: str, slot) -> QPushButton:
        btn = QPushButton(text)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedHeight(36)
        btn.setFont(app_font(12, QFont.Weight.DemiBold))
        btn.setStyleSheet(style)
        btn.clicked.connect(slot)
        return btn

    # ---- record lifecycle -------------------------------------------------

    def load_record(self, record: WorkflowRecord) -> None:
        self._record = record
        self._name.setText(record.name)
        self._attachments = list(record.attachments)
        self._doc.setPlainText(record.notes)
        self._render_attachments()
        self._log.clear()
        if record.last_result:
            self._log.setPlainText(record.last_result)
        self._render_plan()
        self._render_phase()
        self._status.setText(f"Загружен workflow · {record.phase}")

    def _ensure_record(self) -> WorkflowRecord:
        if self._record is None:
            self._record = WorkflowRecord.create(
                name=self._name.text().strip() or "Без названия",
                document_text="",
                document_name="",
            )
        return self._record

    def _sync_record_inputs(self) -> None:
        rec = self._ensure_record()
        rec.name = self._name.text().strip() or "Без названия"
        rec.notes = self._doc.toPlainText().strip()
        rec.attachments = list(self._attachments)
        name, text = compose_document(rec.attachments, rec.notes)
        rec.document_name = name
        rec.document_text = text
        # GitHub не используется: план и выполнение живут без репозитория.
        rec.repo_url = ""
        rec.starting_ref = ""
        rec.auto_create_pr = False

    def _render_attachments(self) -> None:
        self._files.clear()
        images = 0
        for att in self._attachments:
            if att.kind == "image":
                images += 1
                label = f"[img] {att.name}"
            else:
                chars = len(att.text or "")
                label = f"[txt] {att.name}  ·  {chars} симв."
            item = QListWidgetItem(label)
            tip = att.path or att.name
            if att.mime_type:
                tip = f"{tip}\n{att.mime_type}"
            item.setToolTip(tip)
            self._files.addItem(item)
        n = len(self._attachments)
        if n == 0:
            self._files_hint.setText(
                "Файлы не загружены — добавьте документы/картинки или введите заметки."
            )
        else:
            extra = f", из них картинок: {images}" if images else ""
            warn = ""
            if images > MAX_IMAGES:
                warn = f" (в API уйдёт только первые {MAX_IMAGES} картинок)"
            self._files_hint.setText(f"Загружено файлов: {n}{extra}{warn}")

    # ---- rendering --------------------------------------------------------

    def _render_phase(self) -> None:
        phase = self._record.phase if self._record else "document"
        self._phase.setText(_PHASE_LABELS.get(phase, phase))
        plan = self._record.plan if self._record else None
        unanswered = bool(plan and plan.unanswered())

        has_exec = bool(self._record and self._record.exec_agent_id)
        self._questions_card.setVisible(unanswered)
        self._exec_btn.setEnabled(bool(plan) and not unanswered)
        self._rerun_btn.setVisible(has_exec)
        self._fetch_btn.setEnabled(has_exec)
        self._open_dir_btn.setEnabled(has_exec)

    def _render_plan(self) -> None:
        if self._record and self._record.plan:
            self._plan_view.setPlainText(plan_summary_text(self._record.plan))
            self._build_questions(self._record.plan)
        else:
            self._plan_view.clear()

    def _build_questions(self, plan) -> None:
        while self._questions_layout.count():
            item = self._questions_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._question_fields = {}

        unanswered = plan.unanswered()
        if not unanswered:
            return

        for i, q in enumerate(unanswered, start=1):
            label = QLabel(f"{i}. {q.question}")
            label.setFont(app_font(12, QFont.Weight.DemiBold))
            label.setWordWrap(True)
            label.setStyleSheet("color: #1D2A26; background: transparent;")
            field = QPlainTextEdit()
            field.setPlainText(q.answer)
            field.setFont(app_font(12))
            field.setFixedHeight(64)
            field.setStyleSheet(_ANSWER_FIELD)
            field.setPlaceholderText("Ваш ответ…")
            self._questions_layout.addWidget(label)
            self._questions_layout.addWidget(field)
            self._question_fields[q.id] = field
        self._questions_layout.addStretch(1)

    # ---- busy state -------------------------------------------------------

    def _set_busy(self, busy: bool, base: str = "Обращение к агенту") -> None:
        for btn in (
            self._plan_btn,
            self._clarify_btn,
            self._exec_btn,
            self._rerun_btn,
            self._save_btn,
            self._new_btn,
            self._upload_btn,
            self._remove_btn,
            self._clear_files_btn,
        ):
            btn.setEnabled(not busy)
        self._cancel_btn.setEnabled(busy)
        self._drop.setEnabled(not busy)
        self._files.setEnabled(not busy)
        self._doc.setEnabled(not busy)
        if busy:
            self._busy_base = base
            self._busy_n = 0
            self._activity.setVisible(True)
            self._tick_activity()
            self._busy_timer.start()
            self._phase.setStyleSheet(_PHASE_STYLE_BUSY)
        else:
            self._busy_timer.stop()
            self._activity.setVisible(False)
            self._phase.setStyleSheet(_PHASE_STYLE_IDLE)
            self._render_phase()

    def _tick_activity(self) -> None:
        self._busy_n = (self._busy_n % 3) + 1
        self._activity.setText(f"● {self._busy_base}{'.' * self._busy_n}")

    def _on_worker_finished(self) -> None:
        # Bound method (not a lambda) so Qt runs it on the GUI thread via a
        # queued connection — required because it stops a QTimer.
        self._set_busy(False)

    def _append(self, text: str) -> None:
        self._log.moveCursor(QTextCursor.MoveOperation.End)
        self._log.insertPlainText(text)
        self._log.moveCursor(QTextCursor.MoveOperation.End)

    def _on_ids(self, agent_id: str, run_id: str) -> None:
        self._status.setText(f"agent={agent_id} · run={run_id}")
        self._append(f"\n--- agent {agent_id} / run {run_id} ---\n")
        short = run_id[-6:] if run_id else ""
        self._busy_base = f"Агент работает · run …{short}" if short else "Агент работает"

    def _fail(self, message: str) -> None:
        self._status.setText(message)
        self._status.setStyleSheet("color: #B00020; background: transparent;")
        self._append(f"\n[error] {message}\n")

    def _ok(self, message: str) -> None:
        self._status.setText(message)
        self._status.setStyleSheet("color: #2D7A5E; background: transparent;")

    # ---- actions ----------------------------------------------------------

    def _on_pick_files(self) -> None:
        patterns = " ".join(f"*{s}" for s in sorted(SUPPORTED_SUFFIXES))
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Выберите файлы",
            "",
            f"{supported_filter_label()} ({patterns});;Все файлы (*)",
        )
        if paths:
            self._load_paths(paths)

    def _load_paths(self, paths: list[str]) -> None:
        cleaned = [p for p in paths if p and Path(p).is_file()]
        if not cleaned:
            return
        self._status.setText(f"Чтение файлов… ({len(cleaned)})")
        worker = FilesWorker(cleaned)
        worker.succeeded.connect(self._on_files_loaded)
        worker.failed.connect(self._fail)
        self._jobs.append(start_worker(worker))

    def _on_files_loaded(self, loaded: object, warning: str = "") -> None:
        if not isinstance(loaded, list):
            return
        existing = {(a.name, a.text) for a in self._attachments}
        added = 0
        for item in loaded:
            if not isinstance(item, AttachedFile):
                continue
            key = (item.name, item.text)
            if key in existing:
                continue
            self._attachments.append(item)
            existing.add(key)
            added += 1
        self._render_attachments()
        if not self._name.text().strip() and self._attachments:
            self._name.setText(self._attachments[0].name.rsplit(".", 1)[0])
        if warning:
            self._status.setText(warning)
            self._status.setStyleSheet("color: #A86D22; background: transparent;")
        else:
            self._ok(f"Добавлено файлов: {added}")

    def _on_remove_file(self) -> None:
        row = self._files.currentRow()
        if row < 0 or row >= len(self._attachments):
            QMessageBox.information(self, "Файлы", "Выберите файл в списке.")
            return
        del self._attachments[row]
        self._render_attachments()
        self._ok("Файл удалён")

    def _on_clear_files(self) -> None:
        if not self._attachments:
            return
        self._attachments.clear()
        self._render_attachments()
        self._ok("Список файлов очищен")

    def _on_plan(self) -> None:
        self._sync_record_inputs()
        rec = self._ensure_record()
        has_images = any(a.kind == "image" for a in rec.attachments)
        if not rec.document_text.strip() and not has_images:
            QMessageBox.warning(
                self,
                "Документ",
                "Загрузите файлы (текст/pdf/docx/картинки) или введите заметки.",
            )
            return
        # Re-compose so image placeholders are in document_text for the prompt.
        name, text = compose_document(rec.attachments, rec.notes)
        rec.document_name = name
        rec.document_text = text
        rec.phase = "plan"
        self._log.clear()
        n_img = sum(1 for a in rec.attachments if a.kind == "image")
        self._append(
            f"→ Отправляю материалы агенту для планирования "
            f"({len(rec.attachments)} файл(ов), картинок: {min(n_img, MAX_IMAGES)})…\n"
        )
        self._ok("Планирование…")
        self._set_busy(True, "Планирование")
        worker = PlanWorker(rec)
        worker.event.connect(self._append)
        worker.ids.connect(self._on_ids)
        worker.succeeded.connect(self._on_plan_done)
        worker.failed.connect(self._fail)
        worker.finished.connect(self._on_worker_finished)
        self._worker = worker
        self._jobs.append(start_worker(worker))

    def _on_plan_done(self, record: object) -> None:
        if isinstance(record, WorkflowRecord):
            self._record = record
            self._render_plan()
            self._render_phase()
            unresolved = record.plan.unanswered() if record.plan else []
            if unresolved:
                self._ok(f"План готов · {len(unresolved)} вопрос(ов)")
            else:
                self._ok("План готов · можно реализовывать")
            self.saved.emit(record.id)

    def _on_clarify(self) -> None:
        if self._record is None or self._record.plan is None:
            return
        answers = {qid: field.toPlainText().strip() for qid, field in self._question_fields.items()}
        if not any(answers.values()):
            QMessageBox.information(self, "Ответы", "Введите хотя бы один ответ.")
            return
        self._append("\n→ Отправляю ответы, обновляю план…\n")
        self._ok("Уточнение плана…")
        self._set_busy(True, "Уточнение плана")
        worker = ClarifyWorker(self._record, answers)
        worker.event.connect(self._append)
        worker.ids.connect(self._on_ids)
        worker.succeeded.connect(self._on_plan_done)
        worker.failed.connect(self._fail)
        worker.finished.connect(self._on_worker_finished)
        self._worker = worker
        self._jobs.append(start_worker(worker))

    def _on_execute(self, reexecute: bool = False) -> None:
        if self._record is None or self._record.plan is None:
            QMessageBox.information(self, "План", "Сначала постройте план.")
            return
        self._sync_record_inputs()
        self._append("\n→ Запускаю агента (реализация по плану, без репозитория)…\n")
        self._ok("Выполнение…")
        self._set_busy(True, "Реализация")
        worker = ExecuteWorker(self._record, reexecute=reexecute)
        worker.event.connect(self._append)
        worker.ids.connect(self._on_ids)
        worker.succeeded.connect(self._on_execute_done)
        worker.failed.connect(self._fail)
        worker.finished.connect(self._on_worker_finished)
        self._worker = worker
        self._jobs.append(start_worker(worker))

    def _on_execute_done(self, record: object) -> None:
        if isinstance(record, WorkflowRecord):
            self._record = record
            self._ok(f"{record.phase} · получаю файлы результата…")
            self._render_phase()
            self.saved.emit(record.id)
            # Auto-download produced files from the cloud VM (artifacts/).
            self._on_fetch_results()

    # ---- results (artifacts) ----------------------------------------------

    def _on_fetch_results(self) -> None:
        rec = self._record
        if rec is None or not rec.exec_agent_id:
            QMessageBox.information(self, "Результат", "Сначала запустите реализацию.")
            return
        self._results.clear()
        self._append("\n→ Скачиваю файлы результата из artifacts/…\n")
        self._fetch_btn.setEnabled(False)
        worker = ArtifactsWorker(rec.exec_agent_id, rec.id)
        worker.progress.connect(self._append)
        worker.succeeded.connect(self._on_results_ready)
        worker.failed.connect(self._fail)
        worker.finished.connect(lambda: self._fetch_btn.setEnabled(True))
        self._jobs.append(start_worker(worker))

    def _on_results_ready(self, dest_dir: str, files: object) -> None:
        self._results_dir = dest_dir
        self._results.clear()
        paths = files if isinstance(files, list) else []
        if not paths:
            self._append(
                "\n[результат] Файлов в artifacts/ нет. Для новых запусков агент кладёт "
                "итог в artifacts/ — нажмите «Запустить снова», чтобы получить файлы.\n"
            )
            self._ok("Готово · файлов результата нет")
            return
        for p in paths:
            item = QListWidgetItem(Path(p).name)
            item.setData(Qt.ItemDataRole.UserRole, p)
            item.setToolTip(p)
            self._results.addItem(item)
        self._ok(f"Файлов результата: {len(paths)}")
        self._append(f"\n[результат] Скачано в: {dest_dir}\n")

    def _open_result_item(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _open_results_folder(self) -> None:
        folder = getattr(self, "_results_dir", "")
        if not folder and self._record is not None:
            folder = str(storage.outputs_dir(self._record.id))
        if folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _on_save(self) -> None:
        self._sync_record_inputs()
        rec = self._ensure_record()
        if not rec.attachments and not rec.notes.strip() and not rec.document_text.strip():
            QMessageBox.warning(self, "Сохранение", "Нечего сохранять — добавьте файлы или заметки.")
            return
        storage.save_workflow(rec)
        self._ok("Сохранено")
        self.saved.emit(rec.id)

    def _on_cancel(self) -> None:
        if self._worker is not None and hasattr(self._worker, "request_cancel"):
            self._worker.request_cancel()
            self._ok("Отмена…")

    def _on_new(self) -> None:
        self._record = None
        self._attachments.clear()
        self._name.clear()
        self._doc.clear()
        self._render_attachments()
        self._plan_view.clear()
        self._log.clear()
        self._build_questions_clear()
        self._render_phase()
        self._ok("Новый workflow")

    def _build_questions_clear(self) -> None:
        while self._questions_layout.count():
            item = self._questions_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._question_fields = {}
        self._questions_card.setVisible(False)
