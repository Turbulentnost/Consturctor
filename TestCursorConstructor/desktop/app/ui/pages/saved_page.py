from __future__ import annotations

import os

from PySide6.QtCore import Qt, QProcess, QProcessEnvironment, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.workflow import storage
from app.workflow.models import WorkflowRecord
from app.ui.theme import app_font

_PRIMARY = """
QPushButton {
    background: #06483D; color: #F7FBFA; border: none;
    border-radius: 16px; padding: 0 16px;
}
QPushButton:hover { background: #08745F; }
QPushButton:disabled { background: #9DB3AD; color: #EEF3F1; }
"""

_SECONDARY = """
QPushButton {
    background: #E4EFEA; color: #06483D; border: 1px solid #BFD8CF;
    border-radius: 16px; padding: 0 16px;
}
QPushButton:hover { background: #D3E7DF; }
"""

_LIST = """
QListWidget {
    background: #FFFFFF; border: 1px solid #D0DFD8;
    border-radius: 16px; padding: 6px; outline: none;
}
QListWidget::item { padding: 10px 12px; border-radius: 10px; color: #101817; }
QListWidget::item:selected { background: #E3F3EC; color: #06483D; }
"""

_PHASE_HINT = {
    "document": "черновик",
    "plan": "план строится",
    "clarify": "нужны ответы",
    "ready": "готов к реализации",
    "executing": "выполняется",
    "done": "готово",
}


class SavedWorkflowsPage(QWidget):
    open_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._records: dict[str, WorkflowRecord] = {}
        self._proc: QProcess | None = None
        self._run_output = ""
        self._last_output = ""
        self._build()

    def _build(self) -> None:
        title = QLabel("Сохранённые workflow")
        title.setFont(app_font(26, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #101817; background: transparent;")

        refresh = QPushButton("Обновить")
        refresh.setFixedHeight(32)
        refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh.setFont(app_font(12, QFont.Weight.DemiBold))
        refresh.setStyleSheet(_SECONDARY)
        refresh.clicked.connect(self.refresh)

        header = QHBoxLayout()
        header.addWidget(title, 1)
        header.addWidget(refresh)

        self._list = QListWidget()
        self._list.setFont(app_font(13))
        self._list.setStyleSheet(_LIST)
        self._list.itemDoubleClicked.connect(lambda _i: self._on_open())

        self._detail = QLabel("Выберите workflow.")
        self._detail.setFont(app_font(12))
        self._detail.setWordWrap(True)
        self._detail.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._detail.setStyleSheet(
            "color: #33413C; background: #F4F8F6; border: 1px solid #D7E6DF;"
            "border-radius: 12px; padding: 12px 14px;"
        )
        self._detail.setMinimumWidth(360)

        self._run_btn = QPushButton("Запустить")
        self._run_btn.setFixedHeight(34)
        self._run_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._run_btn.setFont(app_font(12, QFont.Weight.DemiBold))
        self._run_btn.setStyleSheet(_PRIMARY)
        self._run_btn.clicked.connect(self._on_run)

        self._open_result_btn = QPushButton("Открыть отчёт")
        self._open_result_btn.setFixedHeight(34)
        self._open_result_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._open_result_btn.setFont(app_font(12, QFont.Weight.DemiBold))
        self._open_result_btn.setStyleSheet(_SECONDARY)
        self._open_result_btn.clicked.connect(self._on_open_result)
        self._open_result_btn.setEnabled(False)

        self._open_btn = QPushButton("Открыть в конструкторе")
        self._open_btn.setFixedHeight(34)
        self._open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._open_btn.setFont(app_font(12, QFont.Weight.DemiBold))
        self._open_btn.setStyleSheet(_SECONDARY)
        self._open_btn.clicked.connect(self._on_open)

        self._delete_btn = QPushButton("Удалить")
        self._delete_btn.setFixedHeight(34)
        self._delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._delete_btn.setFont(app_font(12, QFont.Weight.DemiBold))
        self._delete_btn.setStyleSheet(_SECONDARY)
        self._delete_btn.clicked.connect(self._on_delete)

        detail_actions = QHBoxLayout()
        detail_actions.addWidget(self._run_btn)
        detail_actions.addWidget(self._open_result_btn)
        detail_actions.addWidget(self._open_btn)
        detail_actions.addWidget(self._delete_btn)
        detail_actions.addStretch(1)

        self._status = QLabel("")
        self._status.setFont(app_font(12))
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color: #06483D; background: transparent;")

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(app_font(11))
        self._log.setPlaceholderText("Здесь появится ход выполнения запуска…")
        self._log.setStyleSheet(
            "QPlainTextEdit { background: #0E1A16; color: #CDE7DD;"
            "border: 1px solid #143229; border-radius: 12px; padding: 10px; }"
        )
        self._log.setMinimumHeight(160)

        right = QVBoxLayout()
        right.setSpacing(10)
        right.addWidget(self._detail, 1)
        right.addLayout(detail_actions)
        right.addWidget(self._status)
        right.addWidget(self._log, 1)

        body = QHBoxLayout()
        body.setSpacing(16)
        body.addWidget(self._list, 1)
        body.addLayout(right, 1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)
        root.addLayout(header)
        root.addLayout(body, 1)

        self._list.currentItemChanged.connect(lambda *_: self._render_detail())

    def refresh(self) -> None:
        self._list.clear()
        self._records = {}
        for record in storage.list_workflows():
            self._records[record.id] = record
            phase = _PHASE_HINT.get(record.phase, record.phase)
            item = QListWidgetItem(f"{record.name}\n{phase} · {record.updated_at[:19]}")
            item.setData(Qt.ItemDataRole.UserRole, record.id)
            self._list.addItem(item)
        if self._list.count() == 0:
            self._detail.setText("Пока нет сохранённых workflow. Создайте на вкладке «Конструктор».")

    def _current(self) -> WorkflowRecord | None:
        item = self._list.currentItem()
        if item is None:
            return None
        return self._records.get(str(item.data(Qt.ItemDataRole.UserRole)))

    def _render_detail(self) -> None:
        record = self._current()
        if record is None:
            return
        plan = record.plan
        lines = [
            f"<b>{record.name}</b>",
            f"фаза: {_PHASE_HINT.get(record.phase, record.phase)}",
        ]
        n_files = len(record.attachments)
        if n_files:
            lines.append(f"файлов: {n_files}")
        elif record.document_name:
            lines.append(f"документ: {record.document_name}")
        if plan:
            lines.append(f"шагов: {len(plan.steps)} · вопросов: {len(plan.unanswered())}")
            if plan.goal:
                lines.append(f"цель: {plan.goal}")
        runnable = bool(record.local_run.get("cwd"))
        lines.append(
            "<span style='color:#0A7A5F'>▶ можно запустить локально</span>"
            if runnable
            else "<span style='color:#9A6B00'>локальный запуск не настроен</span>"
        )
        self._detail.setText("<br>".join(lines))
        self._run_btn.setEnabled(runnable and self._proc is None)
        out = str(record.local_run.get("cwd") and record.local_run.get("output") or "")
        last = os.path.join(str(record.local_run.get("cwd") or ""), out) if out else ""
        self._open_result_btn.setEnabled(bool(last and os.path.exists(last)))

    def _on_open(self) -> None:
        record = self._current()
        if record is None:
            QMessageBox.information(self, "Workflow", "Выберите workflow.")
            return
        self.open_requested.emit(record)

    def _on_run(self) -> None:
        try:
            record = self._current()
            if record is None:
                QMessageBox.information(self, "Запуск", "Выберите workflow.")
                return
            spec = dict(record.local_run or {})
            cwd = str(spec.get("cwd") or "")
            if not cwd or not os.path.isdir(cwd):
                QMessageBox.warning(
                    self,
                    "Локальный запуск не настроен",
                    "Для этого workflow не привязан локальный инструмент.\n"
                    "Такие задачи (доступ к внешнему сайту) выполняются на вашей машине — "
                    "инструмент нужно сгенерировать и привязать в конструкторе.",
                )
                return
            if self._proc is not None:
                return

            bat = str(spec.get("bat") or "run.bat")
            out = str(spec.get("output") or "")
            self._run_output = os.path.join(cwd, out) if out else ""

            self._log.clear()
            self._status.setText(
                "Запуск… первый раз может занять несколько минут (установка окружения)."
            )
            self._run_btn.setEnabled(False)
            self._open_result_btn.setEnabled(False)

            # QProcess — родной для Qt механизм: работает в событийном цикле,
            # без Python-потоков и чтения pipe вручную (это устраняет нативные
            # сбои PySide6 на Windows при запуске подпроцесса из слота).
            env = QProcessEnvironment.systemEnvironment()
            env.insert("RTS_NONINTERACTIVE", "1")

            proc = QProcess(self)
            proc.setWorkingDirectory(cwd)
            proc.setProcessEnvironment(env)
            proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
            proc.readyReadStandardOutput.connect(self._on_proc_output)
            proc.finished.connect(self._on_proc_finished)
            proc.errorOccurred.connect(self._on_proc_error)
            self._proc = proc

            if os.name == "nt":
                proc.start("cmd", ["/c", bat])
            else:
                module = str(spec.get("module") or "")
                proc.start("bash", [bat] if not module else ["-c", f"python3 -m {module} run"])
        except Exception as exc:  # noqa: BLE001
            self._proc = None
            self._run_btn.setEnabled(True)
            self._status.setText(f"Не удалось запустить: {exc}")
            QMessageBox.critical(self, "Ошибка запуска", str(exc))

    def _on_proc_output(self) -> None:
        if self._proc is None:
            return
        data = bytes(self._proc.readAllStandardOutput()).decode("utf-8", "replace")
        text = data.replace("\r\n", "\n").rstrip("\n")
        if text:
            self._log.appendPlainText(text)

    def _on_proc_finished(self, exit_code: int, _status: object) -> None:
        self._proc = None
        self._run_btn.setEnabled(True)
        if exit_code == 0:
            out = self._run_output
            if out and os.path.exists(out):
                self._last_output = out
                self._status.setText(f"Готово. Отчёт: {out}")
                self._open_result_btn.setEnabled(True)
                self._open_file(out)
            else:
                self._status.setText("Готово, но файл-результат не найден. Смотрите лог выше.")
        else:
            self._status.setText(f"Инструмент завершился с кодом {exit_code}. Смотрите лог выше.")

    def _on_proc_error(self, _error: object) -> None:
        msg = self._proc.errorString() if self._proc is not None else "неизвестная ошибка"
        self._status.setText(f"Ошибка запуска процесса: {msg}")

    def _on_open_result(self) -> None:
        record = self._current()
        path = self._last_output
        if not path and record is not None:
            cwd = str(record.local_run.get("cwd") or "")
            out = str(record.local_run.get("output") or "")
            if cwd and out:
                path = os.path.join(cwd, out)
        if path and os.path.exists(path):
            self._open_file(path)
        else:
            QMessageBox.information(self, "Отчёт", "Файл отчёта пока не создан. Сначала нажмите «Запустить».")

    @staticmethod
    def _open_file(path: str) -> None:
        try:
            if os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                import subprocess
                subprocess.Popen(["xdg-open", path])
        except Exception:  # noqa: BLE001
            pass

    def _on_delete(self) -> None:
        record = self._current()
        if record is None:
            return
        confirm = QMessageBox.question(
            self, "Удалить", f"Удалить workflow «{record.name}»?"
        )
        if confirm == QMessageBox.StandardButton.Yes:
            storage.delete_workflow(record.id)
            self.refresh()
