from __future__ import annotations

from pathlib import Path
from threading import Thread

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

from app.api_client import ApiClient, ApiError, WorkflowPlan, WorkflowRecord
from app.ui.theme import app_font

SUPPORTED_SUFFIXES = {
    ".txt", ".md", ".markdown", ".csv", ".json", ".xml", ".html", ".htm",
    ".yaml", ".yml", ".log", ".pdf", ".docx", ".png", ".jpg", ".jpeg", ".gif", ".webp",
}
MAX_IMAGES = 5

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
"""
_LOG = """
QPlainTextEdit {
    background: #0F1F1B; color: #D7EBE3;
    border: 1px solid #1F3A32; border-radius: 14px; padding: 12px;
}
"""
_LIST = """
QListWidget {
    background: #FFFFFF; border: 1px solid #D0DFD8; border-radius: 14px;
    padding: 4px; outline: none;
}
QListWidget::item { padding: 8px 10px; border-radius: 8px; color: #101817; }
QListWidget::item:selected { background: #E3F3EC; color: #06483D; }
"""
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
_PHASE_LABELS = {
    "document": "1 · Документ",
    "plan": "2 · Планирование",
    "clarify": "3 · Уточнения",
    "ready": "4 · Готов к реализации",
    "executing": "5 · Выполнение",
    "done": "6 · Готово",
}
_PHASE_STYLE_IDLE = "color: #06483D; background: #E3F3EC; border-radius: 10px; padding: 4px 12px;"
_PHASE_STYLE_BUSY = "color: #8A4B00; background: #FFE7C2; border-radius: 10px; padding: 4px 12px;"
_ACTIVITY_STYLE = (
    "color: #8A4B00; background: #FFF1DC; border: 1px solid #F0C98A;"
    "border-radius: 10px; padding: 4px 12px;"
)


def _section(title: str) -> QLabel:
    label = QLabel(title)
    label.setFont(app_font(13, QFont.Weight.DemiBold))
    label.setStyleSheet("color: #06483D; background: transparent;")
    return label


def plan_summary_text(plan: WorkflowPlan) -> str:
    lines = [f"# {plan.title or 'План'}", "", f"**Цель:** {plan.goal or '—'}", ""]
    if plan.steps:
        lines.append("**Шаги:**")
        for step in plan.steps:
            lines.append(f"- `{step.id}` {step.title}")
            if step.action:
                lines.append(f"  - {step.action}")
        lines.append("")
    if plan.test_criteria:
        lines.append("**Тесты:**")
        lines.extend(f"- {c}" for c in plan.test_criteria)
        lines.append("")
    unanswered = plan.unanswered()
    if unanswered:
        lines.append("**Открытые вопросы:**")
        for q in unanswered:
            lines.append(f"- `{q.id}` {q.question}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


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
        title = QLabel("Перетащите файлы сюда")
        title.setFont(app_font(13, QFont.Weight.DemiBold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #06483D; background: transparent; border: none;")
        hint = QLabel("или «Загрузить файлы» · текст, pdf/docx, картинки")
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
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.toLocalFile()]
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()


class WorkflowPage(QWidget):
    saved = Signal(str)
    _async_ok = Signal(object, str)
    _async_fail = Signal(str)

    def __init__(self, api: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._api = api
        self._record: WorkflowRecord | None = None
        self._pending_paths: list[str] = []
        self._question_fields: dict[str, QPlainTextEdit] = {}
        self._results_dir = ""
        self._busy = False
        self._async_ok.connect(self._on_async_ok)
        self._async_fail.connect(self._on_async_fail)
        self._build()
        self._render_phase()

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
        header.addWidget(self._activity)
        header.addWidget(self._phase)

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
        self._drop.files_dropped.connect(self._add_paths)

        self._upload_btn = self._mk_button("Загрузить файлы…", _SECONDARY, self._on_pick_files)
        self._remove_btn = self._mk_button("Удалить", _SECONDARY, self._on_remove_file)
        self._clear_files_btn = self._mk_button("Очистить", _SECONDARY, self._on_clear_files)
        file_actions = QHBoxLayout()
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
        self._doc.setPlaceholderText("Впишите текст задачи / ТЗ — или загрузите файлы…")
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

        self._plan_view = QPlainTextEdit()
        self._plan_view.setReadOnly(True)
        self._plan_view.setFont(app_font(12))
        self._plan_view.setStyleSheet(_FIELD)
        self._plan_view.setPlaceholderText("Здесь появится план после фазы планирования.")

        self._questions_card = QFrame()
        self._questions_card.setObjectName("qcard")
        self._questions_card.setStyleSheet(_QCARD)
        card_layout = QVBoxLayout(self._questions_card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        self._q_header = QLabel("Вопросы агента — впишите ответы ниже")
        self._q_header.setFont(app_font(13, QFont.Weight.DemiBold))
        self._q_header.setStyleSheet("color: #8A4B00; background: transparent;")
        self._q_header.setWordWrap(True)
        self._questions_inner = QWidget()
        self._questions_layout = QVBoxLayout(self._questions_inner)
        self._questions_layout.setContentsMargins(0, 0, 6, 0)
        q_scroll = QScrollArea()
        q_scroll.setWidgetResizable(True)
        q_scroll.setFrameShape(QFrame.Shape.NoFrame)
        q_scroll.setWidget(self._questions_inner)
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

        right = QVBoxLayout()
        right.setSpacing(10)
        right.addWidget(_section("План"))
        right.addWidget(self._plan_view, 2)
        right.addWidget(self._questions_card, 3)
        right.addWidget(_section("Стрим"))
        right.addWidget(self._log, 2)
        right.addWidget(_section("Результат (файлы)"))
        right.addWidget(self._results, 1)
        right.addLayout(results_actions)

        body = QHBoxLayout()
        body.addWidget(left_scroll, 0)
        body.addLayout(right, 1)

        self._plan_btn = self._mk_button("Спланировать", _PRIMARY, self._on_plan)
        self._exec_btn = self._mk_button("Запустить", _PRIMARY, self._on_execute)
        self._rerun_btn = self._mk_button(
            "Запустить снова", _SECONDARY, lambda: self._on_execute(reexecute=True)
        )
        self._new_btn = self._mk_button("Новый", _SECONDARY, self._on_new)

        self._status = QLabel("")
        self._status.setFont(app_font(12))
        self._status.setStyleSheet("color: #2D7A5E; background: transparent;")
        self._status.setWordWrap(True)

        actions = QHBoxLayout()
        for btn in (self._plan_btn, self._exec_btn, self._rerun_btn, self._new_btn):
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

    def load_record(self, record: WorkflowRecord) -> None:
        self._record = record
        self._pending_paths = []
        self._name.setText(record.title)
        self._doc.setPlainText(record.notes)
        self._render_attachments_from_record()
        self._log.clear()
        if record.last_result:
            self._log.setPlainText(record.last_result)
        self._render_plan()
        self._render_phase()
        self._ok(f"Загружен workflow · {record.phase}")

    def _render_attachments_from_record(self) -> None:
        self._files.clear()
        for att in self._record.attachments or [] if self._record else []:
            kind = "img" if att.kind == "image" else "txt"
            self._files.addItem(QListWidgetItem(f"[{kind}] {att.name}"))
        for path in self._pending_paths:
            self._files.addItem(QListWidgetItem(f"[new] {Path(path).name}"))
        n = (len(self._record.attachments or []) if self._record else 0) + len(self._pending_paths)
        self._files_hint.setText("Файлы не загружены." if n == 0 else f"Файлов: {n}")

    def _render_phase(self) -> None:
        phase = self._record.phase if self._record else "document"
        self._phase.setText(_PHASE_LABELS.get(phase, phase))
        plan = self._record.plan if self._record else None
        unanswered = bool(plan and plan.unanswered())
        has_exec = bool(self._record and self._record.exec_agent_id)
        self._questions_card.setVisible(unanswered)
        self._exec_btn.setEnabled(bool(plan) and not unanswered and not self._busy)
        self._rerun_btn.setVisible(has_exec)
        self._fetch_btn.setEnabled(has_exec and not self._busy)
        self._open_dir_btn.setEnabled(bool(self._results_dir) or has_exec)

    def _render_plan(self) -> None:
        if self._record and self._record.plan:
            self._plan_view.setPlainText(plan_summary_text(self._record.plan))
            self._build_questions(self._record.plan)
        else:
            self._plan_view.clear()
            self._clear_questions()

    def _build_questions(self, plan: WorkflowPlan) -> None:
        self._clear_questions()
        for i, q in enumerate(plan.unanswered(), start=1):
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

    def _clear_questions(self) -> None:
        while self._questions_layout.count():
            item = self._questions_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._question_fields = {}

    def _set_busy(self, busy: bool, base: str = "Обращение к агенту") -> None:
        self._busy = busy
        for btn in (
            self._plan_btn,
            self._clarify_btn,
            self._exec_btn,
            self._rerun_btn,
            self._new_btn,
            self._upload_btn,
            self._remove_btn,
            self._clear_files_btn,
        ):
            btn.setEnabled(not busy)
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

    def _append(self, text: str) -> None:
        self._log.moveCursor(QTextCursor.MoveOperation.End)
        self._log.insertPlainText(text)
        self._log.moveCursor(QTextCursor.MoveOperation.End)

    def _ok(self, message: str) -> None:
        self._status.setText(message)
        self._status.setStyleSheet("color: #2D7A5E; background: transparent;")

    def _fail(self, message: str) -> None:
        self._status.setText(message)
        self._status.setStyleSheet("color: #B00020; background: transparent;")
        self._append(f"\n[error] {message}\n")

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
            self._name.setText(result.title)
            self._render_attachments_from_record()
            self._render_plan()
            self._render_phase()
            self.saved.emit(result.id)
            if label.startswith("Планирование") or label.startswith("Уточнение"):
                n = len(result.plan.unanswered()) if result.plan else 0
                self._ok(f"План готов · вопросов: {n}" if n else "План готов · можно реализовывать")
            elif label.startswith("Реализация"):
                self._ok(f"{result.phase} · можно скачать артефакты")
                if result.last_result:
                    self._append("\n" + result.last_result + "\n")
                self._on_fetch_results()
            else:
                self._ok("Готово")
        elif isinstance(result, tuple) and len(result) == 2:
            dest_dir, files = result
            self._results_dir = str(dest_dir)
            self._results.clear()
            for path in files:
                item = QListWidgetItem(Path(path).name)
                item.setData(Qt.ItemDataRole.UserRole, path)
                self._results.addItem(item)
            self._ok(f"Файлов результата: {len(files)}")
            self._append(f"\n[результат] {dest_dir}\n")

    def _on_async_fail(self, message: str) -> None:
        self._set_busy(False)
        self._fail(message)

    def _on_pick_files(self) -> None:
        patterns = " ".join(f"*{s}" for s in sorted(SUPPORTED_SUFFIXES))
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Выберите файлы", "", f"Документы ({patterns});;Все файлы (*)"
        )
        if paths:
            self._add_paths(paths)

    def _add_paths(self, paths: list[str]) -> None:
        for path in paths:
            if path and Path(path).is_file() and path not in self._pending_paths:
                suffix = Path(path).suffix.lower()
                if suffix and suffix not in SUPPORTED_SUFFIXES:
                    continue
                self._pending_paths.append(path)
        if not self._name.text().strip() and self._pending_paths:
            self._name.setText(Path(self._pending_paths[0]).stem)
        self._render_attachments_from_record()
        self._ok(f"Выбрано файлов: {len(self._pending_paths)}")

    def _on_remove_file(self) -> None:
        row = self._files.currentRow()
        attached_n = len(self._record.attachments or []) if self._record else 0
        if row < 0:
            return
        if row < attached_n:
            QMessageBox.information(
                self,
                "Файлы",
                "Уже загруженные на сервер файлы нельзя удалить по одному — "
                "создайте новый workflow.",
            )
            return
        idx = row - attached_n
        if 0 <= idx < len(self._pending_paths):
            del self._pending_paths[idx]
            self._render_attachments_from_record()

    def _on_clear_files(self) -> None:
        self._pending_paths.clear()
        self._render_attachments_from_record()

    def _on_plan(self) -> None:
        notes = self._doc.toPlainText().strip()
        if self._record is None:
            if not notes and not self._pending_paths:
                QMessageBox.warning(self, "Документ", "Добавьте файлы или текст задачи.")
                return
            self._append("→ Создаю workflow и запускаю планирование…\n")

            def create_and_plan() -> WorkflowRecord:
                created = self._api.create_workflow(notes=notes, file_paths=self._pending_paths)
                return self._api.plan_workflow(created.id)

            self._run_async("Планирование", create_and_plan)
            return

        self._append("→ Планирование через backend…\n")
        self._run_async("Планирование", lambda: self._api.plan_workflow(self._record.id))  # type: ignore[union-attr]

    def _on_clarify(self) -> None:
        if self._record is None or self._record.plan is None:
            return
        answers = {qid: field.toPlainText().strip() for qid, field in self._question_fields.items()}
        if not any(answers.values()):
            QMessageBox.information(self, "Ответы", "Введите хотя бы один ответ.")
            return
        self._append("\n→ Отправляю ответы…\n")
        wid = self._record.id
        self._run_async("Уточнение плана", lambda: self._api.clarify_workflow(wid, answers))

    def _on_execute(self, reexecute: bool = False) -> None:
        if self._record is None or self._record.plan is None:
            QMessageBox.information(self, "План", "Сначала постройте план.")
            return
        self._append("\n→ Запускаю реализацию…\n")
        wid = self._record.id
        self._run_async(
            "Реализация",
            lambda: self._api.execute_workflow(wid, reexecute=reexecute),
        )

    def _on_fetch_results(self) -> None:
        if self._record is None or not self._record.exec_agent_id:
            return
        wid = self._record.id
        self._append("\n→ Скачиваю артефакты…\n")

        def work():
            result = self._api.download_workflow_artifacts(wid)
            return result.dest_dir, result.files

        self._run_async("Скачивание", work)

    def _open_result_item(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _open_results_folder(self) -> None:
        if self._results_dir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._results_dir))

    def _on_new(self) -> None:
        self._record = None
        self._pending_paths.clear()
        self._name.clear()
        self._doc.clear()
        self._plan_view.clear()
        self._log.clear()
        self._results.clear()
        self._results_dir = ""
        self._clear_questions()
        self._questions_card.setVisible(False)
        self._render_attachments_from_record()
        self._render_phase()
        self._ok("Новый workflow")
