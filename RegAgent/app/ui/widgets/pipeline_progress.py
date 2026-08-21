from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, MINT, app_font
from app.ui.widgets.user_menu import HEADER_OVERLAY_WIDTH

CREATION_STEPS: tuple[tuple[str, str], ...] = (
    ("upload", "Загрузка"),
    ("review", "Обзор"),
    ("functions", "Функции"),
    ("passport", "Паспорт"),
    ("design", "Сборка"),
    ("demo", "Пробный прогон"),
    ("publish", "Публикация"),
)

PHASE_TO_STEP: dict[str, int] = {
    "intake": 0,
    "review": 1,
    "functions": 2,
    "readiness": 3,
    "passport": 3,
    "design": 4,
    "playbook": 4,
    "demo": 5,
    "schedule": 6,
    "published": 6,
    "failed": 5,
}

CREATION_FLOW_PAGES = frozenset(
    {"create", "review", "process", "passport", "clarify", "demo", "schedule"}
)

PIPELINE_STATUS: dict[str, str] = {
    "intake": "Распознаём документ…",
    "functions": "Анализируем функции регламента…",
    "passport": "Формируем паспорт агента…",
    "passport_questions": "Готовим уточняющие вопросы…",
    "playbook": "Собираем сценарий…",
    "playbook_repair": "Исправляем сценарий…",
    "demo": "Пробный прогон…",
    "demo_open": "Подключаем агента…",
    "demo_run": "Выполняем пробный прогон…",
}

ADVANCE_MESSAGES: dict[str, str] = {
    "intake": "Документ загружен — проверьте текст регламента",
    "functions": "Функции определены — переходим дальше",
    "passport": "Паспорт готов — проверьте поля",
    "playbook": "Сценарий собран — можно запустить демо",
    "demo": "Пробный прогон завершён",
}


def phase_to_step(phase: str) -> int:
    return PHASE_TO_STEP.get(phase, 0)


def status_for_pipeline_step(step: str) -> str:
    return PIPELINE_STATUS.get(step, "ИИ обрабатывает запрос…")


class _StepDot(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(22, 22)
        self._state = "idle"

    def set_state(self, state: str) -> None:
        self._state = state
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(1, 1, -1, -1)
        if self._state == "done":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(MINT)
            painter.drawEllipse(rect)
            painter.setPen(QPen(Qt.GlobalColor.white, 2))
            cx, cy = rect.center().x(), rect.center().y()
            painter.drawLine(int(cx - 4), int(cy), int(cx - 1), int(cy + 3))
            painter.drawLine(int(cx - 1), int(cy + 3), int(cx + 5), int(cy - 3))
        elif self._state == "active":
            painter.setPen(QPen(MINT, 2))
            painter.setBrush(Qt.GlobalColor.white)
            painter.drawEllipse(rect)
            inner = rect.adjusted(5, 5, -5, -5)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(MINT)
            painter.drawEllipse(inner)
        else:
            painter.setPen(QPen(QColor("#C5D4CF"), 1))
            painter.setBrush(Qt.GlobalColor.white)
            painter.drawEllipse(rect)
        painter.end()


class _StepCell(QWidget):
    def __init__(self, label: str, *, last: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._last = last
        self._dot = _StepDot()
        self._title = QLabel(label)
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setFont(app_font(11))
        self._title.setWordWrap(True)
        self._title.setMaximumWidth(92)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addStretch(1)
        row.addWidget(self._dot, 0, Qt.AlignmentFlag.AlignHCenter)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(self._title)

    def set_state(self, state: str) -> None:
        self._dot.set_state(state)
        if state == "done":
            color = MAIN_TEXT.name()
            weight = QFont.Weight.Medium
        elif state == "active":
            color = "#06483D"
            weight = QFont.Weight.DemiBold
        else:
            color = COLOR_CONTENT_MUTED.name()
            weight = QFont.Weight.Normal
        self._title.setFont(app_font(11, weight))
        self._title.setStyleSheet(f"color: {color}; background: transparent;")


class PipelineStepper(QFrame):
    """Горизонтальный stepper этапов создания агента."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PipelineStepper")
        self.setStyleSheet(
            """
            QFrame#PipelineStepper {
                background: rgba(255,255,255,0.72);
                border: 1px solid rgba(6,72,61,0.10);
                border-radius: 16px;
            }
            """
        )
        self._cells: list[_StepCell] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16 + HEADER_OVERLAY_WIDTH, 12)
        root.setSpacing(8)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(10)
        self._meta = QLabel("Создание агента")
        self._meta.setFont(app_font(13, QFont.Weight.DemiBold))
        self._meta.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        self._pct = QLabel("")
        self._pct.setFont(app_font(12))
        self._pct.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        meta_row.addWidget(self._meta, 0)
        meta_row.addWidget(self._pct, 0)
        meta_row.addStretch(1)
        root.addLayout(meta_row)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(5)
        self._bar.setStyleSheet(
            """
            QProgressBar {
                background: rgba(6,72,61,0.10);
                border: none;
                border-radius: 3px;
            }
            QProgressBar::chunk {
                background: #08745F;
                border-radius: 3px;
            }
            """
        )
        root.addWidget(self._bar)

        steps_row = QHBoxLayout()
        steps_row.setContentsMargins(0, 4, 0, 0)
        steps_row.setSpacing(0)
        last_index = len(CREATION_STEPS) - 1
        for index, (_key, title) in enumerate(CREATION_STEPS):
            cell = _StepCell(title, last=index == last_index)
            self._cells.append(cell)
            steps_row.addWidget(cell, 1)
        root.addLayout(steps_row)
        self.set_phase("intake", busy=False)

    def set_phase(self, phase: str, *, busy: bool = False) -> None:
        rank = phase_to_step(phase)
        total = len(CREATION_STEPS)
        for index, cell in enumerate(self._cells):
            if index < rank:
                cell.set_state("done")
            elif index == rank:
                cell.set_state("active")
            else:
                cell.set_state("idle")
        current = min(total, rank + 1)
        pct = int(round((rank / max(1, total - 1)) * 100))
        if phase == "published":
            pct = 100
            current = total
            for cell in self._cells:
                cell.set_state("done")
        self._pct.setText(f"Этап {current} из {total} · {pct}%")
        self._bar.setValue(pct)
        if busy and rank < len(self._cells):
            title = CREATION_STEPS[rank][1]
            self._meta.setText(f"{title}…")


class PipelineBusyPanel(QFrame):
    """Строка статуса и indeterminate progress во время SDK-запросов."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PipelineBusyPanel")
        self.setStyleSheet(
            """
            QFrame#PipelineBusyPanel {
                background: #EAF7F3;
                border: 1px solid rgba(8,116,95,0.22);
                border-radius: 12px;
            }
            """
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(12)
        self._message = QLabel("ИИ обрабатывает запрос…")
        self._message.setFont(app_font(13, QFont.Weight.Medium))
        self._message.setStyleSheet("color: #06483D; background: transparent;")
        self._message.setWordWrap(True)
        self._message.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._bar = QProgressBar()
        self._bar.setRange(0, 0)
        self._bar.setTextVisible(False)
        self._bar.setFixedWidth(120)
        self._bar.setFixedHeight(6)
        self._bar.setStyleSheet(
            """
            QProgressBar {
                background: rgba(6,72,61,0.14);
                border: none;
                border-radius: 3px;
            }
            QProgressBar::chunk {
                background: #08745F;
                border-radius: 3px;
            }
            """
        )
        lay.addWidget(self._message, 1)
        lay.addWidget(self._bar, 0, Qt.AlignmentFlag.AlignVCenter)
        self.hide()

    def show_message(self, text: str) -> None:
        self._message.setText(text or "ИИ обрабатывает запрос…")
        self.show()

    def hide_panel(self) -> None:
        self.hide()


class PipelineAdvanceBanner(QLabel):
    """Краткое сообщение после завершения этапа перед переходом."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWordWrap(True)
        self.setFont(app_font(13))
        self.setStyleSheet(
            """
            QLabel {
                color: #06483D;
                background: #F3FAF7;
                border: 1px solid rgba(8,116,95,0.18);
                border-radius: 10px;
                padding: 10px 14px;
            }
            """
        )
        self.hide()

    def show_message(self, text: str) -> None:
        if not text.strip():
            self.hide()
            return
        self.setText(text)
        self.show()

    def hide_banner(self) -> None:
        self.hide()
