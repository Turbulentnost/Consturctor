from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app import config
from app.workflow.service import HealthWorker, start_worker
from app.ui.pages.saved_page import SavedWorkflowsPage
from app.ui.pages.workflow_page import WorkflowPage
from app.ui.theme import (
    COLOR_CONTENT_BG,
    COLOR_CONTENT_MUTED,
    CONTENT_PADDING_TOP,
    CONTENT_PADDING_X,
    MAIN_TEXT,
    app_font,
)
from app.ui.widgets.sidebar import GlassSidebar


class MainContentWidget(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._radius = 28.0

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.0, 0.0, -0.5, -0.5)
        r = self._radius

        path = QPainterPath()
        path.moveTo(rect.left(), rect.top())
        path.lineTo(rect.right() - r, rect.top())
        path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + r)
        path.lineTo(rect.right(), rect.bottom() - r)
        path.quadTo(rect.right(), rect.bottom(), rect.right() - r, rect.bottom())
        path.lineTo(rect.left(), rect.bottom())
        path.closeSubpath()

        p.fillPath(path, COLOR_CONTENT_BG)
        p.setPen(QPen(QColor(0, 0, 0, 12), 1))
        p.drawPath(path)
        p.end()


class MainShell(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._jobs: list = []

        self.sidebar = GlassSidebar(self)
        self.sidebar.page_changed.connect(self._on_page_changed)

        self._pages = QStackedWidget()
        self._page_workflow = WorkflowPage()
        self._page_saved = SavedWorkflowsPage()
        self._pages.addWidget(self._page_workflow)
        self._pages.addWidget(self._page_saved)
        self._page_index = {"workflow": 0, "saved": 1}
        self._page_workflow.saved.connect(lambda _id: self._page_saved.refresh())
        self._page_saved.open_requested.connect(self._on_open_workflow)

        self._brand = QLabel("Cursor Constructor")
        self._brand.setFont(app_font(16, QFont.Weight.DemiBold))
        self._brand.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

        self._model_label = QLabel(f"model: {config.model_id()} · cloud")
        self._model_label.setFont(app_font(13))
        self._model_label.setStyleSheet(
            f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;"
        )

        self._health_label = QLabel("проверка ключа…")
        self._health_label.setFont(app_font(12, QFont.Weight.Medium))
        self._health_label.setStyleSheet("color: #A86D22; background: transparent;")

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(18)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        col.addWidget(self._brand)
        col.addWidget(self._model_label)
        header.addLayout(col, 1)
        header.addWidget(self._health_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self._content = MainContentWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(
            CONTENT_PADDING_X,
            CONTENT_PADDING_TOP,
            CONTENT_PADDING_X,
            30,
        )
        content_layout.setSpacing(24)
        content_layout.addLayout(header)
        content_layout.addWidget(self._pages, 1)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.sidebar, 0)
        root.addWidget(self._content, 1)

        self.sidebar.set_active_key("workflow", animate=False)
        QTimer.singleShot(0, self.refresh_health)

    def refresh_health(self) -> None:
        if not config.api_key():
            self._health_label.setText("CURSOR_API_KEY не задан · desktop/.env")
            self._health_label.setStyleSheet("color: #B00020; background: transparent;")
            return
        worker = HealthWorker()
        worker.succeeded.connect(self._on_me)
        worker.failed.connect(self._on_me_fail)
        self._jobs.append(start_worker(worker))

    def _on_me(self, who: str) -> None:
        self._health_label.setText(f"API ok · {who}" if who else "API ok")
        self._health_label.setStyleSheet("color: #2D7A5E; background: transparent;")

    def _on_me_fail(self, message: str) -> None:
        self._health_label.setText(message)
        self._health_label.setStyleSheet("color: #B00020; background: transparent;")

    def _on_page_changed(self, key: str) -> None:
        idx = self._page_index.get(key, 0)
        self._pages.setCurrentIndex(idx)
        if key == "saved":
            self._page_saved.refresh()

    def _on_open_workflow(self, record: object) -> None:
        self._page_workflow.load_record(record)
        self.sidebar.set_active_key("workflow", animate=False)
        self._pages.setCurrentIndex(self._page_index["workflow"])
