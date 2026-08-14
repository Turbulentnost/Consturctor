from __future__ import annotations

import re
from pathlib import Path
from threading import Thread

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QFontMetrics,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QButtonGroup,
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
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.api_client import ApiClient, ApiError, PassportSession, WorkflowPlan, WorkflowPlanStep, WorkflowRecord
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, scroll_bar_qss

SUPPORTED_SUFFIXES = {
    ".txt", ".md", ".markdown", ".csv", ".json", ".xml", ".html", ".htm",
    ".yaml", ".yml", ".log", ".pdf", ".docx", ".png", ".jpg", ".jpeg", ".gif", ".webp",
}

_PRIMARY = """
QPushButton {
    background: #08745F; color: #FFFFFF; border: none;
    border-radius: 14px; padding: 0 18px;
}
QPushButton:hover { background: #0A8670; }
QPushButton:disabled { background: #A8C8BF; color: #EAF7F3; }
"""
_SECONDARY = """
QPushButton {
    background: #FFFFFF; color: #06483D;
    border: 1px solid rgba(16,24,23,0.12);
    border-radius: 14px; padding: 0 16px;
}
QPushButton:hover { background: #F4F7F6; }
QPushButton:disabled { background: #F4F7F6; color: #9DB3AD; }
"""
_CARD = """
QFrame#WorkflowCard {
    background: #FFFFFF;
    border: 1px solid rgba(16,24,23,0.10);
    border-radius: 18px;
}
"""
_QCARD = """
QFrame#qcard {
    background: #FFF8EF;
    border: 1px solid #F0DFC2;
    border-radius: 16px;
}
"""
_ANSWER_FIELD = """
QPlainTextEdit {
    background: #FFFFFF; color: #101817;
    border: 1px solid rgba(16,24,23,0.10);
    border-radius: 12px;
    padding: 8px 12px;
    selection-background-color: #08745F;
}
"""
_CUSTOM_ANSWER_FIELD = """
QLineEdit {
    background: #FFFFFF; color: #101817;
    border: 1px solid rgba(16,24,23,0.10);
    border-radius: 10px;
    padding: 6px 10px;
    selection-background-color: #08745F;
}
QLineEdit:disabled {
    background: #F4F7F6;
    color: #9DB3AD;
}
"""
_RADIO_OPTION = """
QRadioButton {
    color: #101817;
    background: transparent;
    spacing: 8px;
    padding: 3px 0;
}
QRadioButton::indicator {
    width: 15px;
    height: 15px;
}
QRadioButton::indicator:unchecked {
    border: 1px solid #6E7D79;
    border-radius: 8px;
    background: #FFFFFF;
}
QRadioButton::indicator:checked {
    border: 1px solid #6E7D79;
    border-radius: 8px;
    background: #B8C2BE;
}
"""
_REASONING = """
QPlainTextEdit {
    background: #F7FAF9; color: #3A4A46;
    border: 1px solid #EAF1EE;
    border-radius: 14px;
    padding: 12px;
}
"""
_LIST = """
QListWidget {
    background: #FFFFFF;
    border: 1px solid rgba(16,24,23,0.10);
    border-radius: 14px;
    padding: 4px;
    outline: none;
}
QListWidget::item { padding: 8px 10px; border-radius: 10px; color: #101817; }
QListWidget::item:selected { background: rgba(8,116,95,0.10); color: #06483D; }
"""
_CLIP_BTN = """
QToolButton {
    background: #FFFFFF;
    color: #06483D;
    border: 1px solid rgba(16,24,23,0.12);
    border-radius: 10px;
    padding: 4px 8px;
    font-size: 16px;
}
QToolButton:hover { background: #F4F7F6; border-color: #08745F; }
QToolButton:disabled { color: #9DB3AD; }
"""
_PHASE_STYLE_IDLE = (
    "color: #06483D; background: rgba(8,116,95,0.10);"
    "border-radius: 12px; padding: 6px 12px;"
)
_PHASE_STYLE_BUSY = (
    "color: #8A5300; background: #FFF8EF; border: 1px solid #F0DFC2;"
    "border-radius: 12px; padding: 6px 12px;"
)
_ACTIVITY_STYLE = (
    "color: #8A5300; background: #FFF8EF; border: 1px solid #F0DFC2;"
    "border-radius: 12px; padding: 6px 12px;"
)

_PHASE_PIPELINE = [
    ("document", "Материалы"),
    ("plan", "План"),
    ("clarify", "Уточнения"),
    ("ready", "Сборка"),
    ("tested", "Тестовый прогон"),
    ("done", "Готово"),
]
_PHASE_RANK = {
    "document": 0,
    "plan": 1,
    "clarify": 2,
    "ready": 3,
    "executing": 3,
    "tested": 4,
    "done": 5,
}


class _FitWidthScrollArea(QScrollArea):
    """Scroll area that does not demand content size and forces children to wrap."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(140)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(320, 220)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(160, 140)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        inner = self.widget()
        if inner is not None:
            # Cap width so QLabel word-wrap computes height inside the viewport.
            inner.setMaximumWidth(max(1, self.viewport().width()))


def _section(title: str) -> QLabel:
    label = QLabel(title)
    label.setFont(app_font(13, QFont.Weight.DemiBold))
    label.setStyleSheet("color: #06483D; background: transparent;")
    return label


def _card_heading(title: str, hint: str = "") -> QWidget:
    wrap = QWidget()
    wrap.setStyleSheet("background: transparent;")
    col = QVBoxLayout(wrap)
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(2)
    heading = QLabel(title)
    heading.setFont(app_font(15, QFont.Weight.DemiBold))
    heading.setStyleSheet("color: #06483D; background: transparent;")
    col.addWidget(heading)
    if hint:
        sub = QLabel(hint)
        sub.setFont(app_font(11))
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        col.addWidget(sub)
    return wrap


def _strip_json_blob(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"```json[\s\S]*?```", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"```[\s\S]*?```", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start and (end - start) > 40:
        candidate = cleaned[start : end + 1].strip()
        if candidate.startswith("{") and ('"steps"' in candidate or '"goal"' in candidate):
            cleaned = (cleaned[:start] + cleaned[end + 1 :]).strip()
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def _visible_live_text(text: str) -> str:
    visible = _strip_json_blob(text).strip()
    if (
        not visible
        or visible.lstrip().startswith("{")
        or "```json" in visible.lower()
        or '"steps"' in visible
    ):
        return ""
    return visible


def reasoning_text(record: WorkflowRecord | None) -> str:
    if record is None:
        return "Загрузите материалы и нажмите «Спланировать» — здесь появятся рассуждения модели."
    lines: list[str] = []
    plan = record.plan
    if plan:
        if plan.title:
            lines.append(f"План: {plan.title}")
        if plan.goal:
            lines.append(f"Цель: {plan.goal}")
        if plan.constraints:
            lines.append("Ограничения:")
            lines.extend(f"• {c}" for c in plan.constraints)
        prose = _strip_json_blob(plan.raw_text or "")
        if prose:
            lines.append("")
            lines.append(prose[:4000])
        unanswered = plan.unanswered()
        if unanswered:
            lines.append("")
            lines.append("Почему нужны уточнения:")
            for q in unanswered:
                why = (q.why or "").strip() or "нужно для безопасной реализации"
                lines.append(f"• {q.question}\n  → {why}")
    if record.last_result:
        lines.append("")
        lines.append("Результат выполнения:")
        lines.append(record.last_result.strip()[:5000])
    if not lines:
        phase = record.phase or "document"
        if phase in {"document", "plan"}:
            return "Агент готовит план…"
        return "Рассуждения пока пустые."
    return "\n".join(lines).strip()


def _topo_levels(steps: list[WorkflowPlanStep]) -> list[list[WorkflowPlanStep]]:
    ids = {s.id for s in steps if s.id}
    indeg = {s.id: 0 for s in steps if s.id}
    deps: dict[str, list[str]] = {s.id: [] for s in steps if s.id}
    for s in steps:
        if not s.id:
            continue
        for d in s.depends_on or []:
            if d in ids and d != s.id:
                indeg[s.id] = indeg.get(s.id, 0) + 1
                deps.setdefault(d, []).append(s.id)
    ready = [s for s in steps if s.id and indeg.get(s.id, 0) == 0]
    levels: list[list[WorkflowPlanStep]] = []
    seen: set[str] = set()
    while ready:
        levels.append(ready)
        nxt: list[WorkflowPlanStep] = []
        for s in ready:
            seen.add(s.id)
            for child_id in deps.get(s.id, []):
                indeg[child_id] -= 1
                if indeg[child_id] <= 0 and child_id not in seen:
                    child = next((x for x in steps if x.id == child_id), None)
                    if child is not None:
                        nxt.append(child)
        ready = nxt
    leftovers = [s for s in steps if s.id and s.id not in seen]
    if leftovers:
        levels.append(leftovers)
    orphan = [s for s in steps if not s.id]
    if orphan:
        levels.append(orphan)
    return levels or [steps]


def _quick_answers_for_question(question) -> list[str]:
    options = [str(item).strip() for item in getattr(question, "options", []) or [] if str(item).strip()]
    if options:
        return options[:4]
    text = (question.question or "").lower()
    if any(word in text for word in ("система", "интерфейс", "api", "ui", "интеграц")):
        return [
            "Через API",
            "Через UI",
            "Через интеграционную шину",
            "Нужно уточнить у владельца системы",
        ]
    if any(word in text for word in ("срок", "когда", "дата", "время")):
        return ["В течение 1 рабочего дня", "В день получения", "До окончания срока подачи", "Нужно уточнить"]
    if any(word in text for word in ("кто", "роль", "ответственный", "исполнитель")):
        return ["Инициатор заявки", "Ответственный менеджер", "Руководитель подразделения", "Нужно уточнить"]
    return ["По регламенту", "Вручную ответственным", "Автоматически агентом", "Нужно уточнить"]


def _format_step_item(index: int, step: WorkflowPlanStep) -> str:
    lines = [f"{index}. {step.title or step.id or 'Шаг'}"]
    if step.action:
        lines.append(step.action)
    if step.done_when:
        lines.append(f"Готово: {step.done_when}")
    if step.depends_on:
        lines.append(f"Зависит от: {', '.join(step.depends_on)}")
    return "\n".join(lines)


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        child = item.widget()
        if child is not None:
            child.deleteLater()
            continue
        child_layout = item.layout()
        if child_layout is not None:
            _clear_layout(child_layout)
            child_layout.deleteLater()


def _phase_step_widget(label: str, state: str) -> QWidget:
    row = QFrame()
    row.setStyleSheet("background: transparent;")
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    dot = QLabel("✓" if state == "done" else "●" if state == "active" else "○")
    dot.setFixedWidth(20)
    dot.setFont(app_font(13, QFont.Weight.DemiBold))
    color = "#08745F" if state == "done" else "#F0A202" if state == "active" else "#9DB3AD"
    dot.setStyleSheet(f"color: {color}; background: transparent;")
    text = QLabel(label)
    text.setWordWrap(True)
    text.setFont(app_font(12, QFont.Weight.DemiBold if state == "active" else QFont.Weight.Medium))
    text.setStyleSheet(f"color: {MAIN_TEXT.name() if state != 'idle' else COLOR_CONTENT_MUTED.name()}; background: transparent;")
    layout.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
    layout.addWidget(text, 1)
    return row


class NodeGraphWidget(QWidget):
    """Connected labeled circles; completed nodes are green.

    mode='row' — горизонтальный степпер (фазы).
    mode='dag' — уровни по зависимостям (шаги плана); простая цепочка тоже в ряд.
    """

    def __init__(self, parent: QWidget | None = None, *, mode: str = "row") -> None:
        super().__init__(parent)
        self._mode = mode if mode in {"row", "dag"} else "row"
        self._nodes: list[tuple[str, str, str]] = []  # id, label, state
        self._edges: list[tuple[str, str]] = []
        self.setFixedHeight(84 if self._mode == "row" else 96)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_graph(self, nodes: list[tuple[str, str, str]], edges: list[tuple[str, str]] | None = None) -> None:
        self._nodes = list(nodes)
        self._edges = list(edges or [])
        levels = _layout_levels(self._nodes, self._edges, mode=self._mode)
        rows = max(1, len(levels))
        if self._mode == "row" or rows == 1:
            height = 84
        else:
            height = min(120, 56 + rows * 52)
        self.setFixedHeight(height)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.setPen(QPen(QColor("#E3EDE9"), 1.0))
        painter.setBrush(QColor("#F7FAF9"))
        painter.drawRoundedRect(rect, 16, 16)
        if not self._nodes:
            painter.setPen(QColor("#9DB3AD"))
            painter.setFont(app_font(12))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Граф появится после планирования")
            return

        levels = _layout_levels(self._nodes, self._edges, mode=self._mode)
        node_pos: dict[str, QPointF] = {}
        r = 14.0
        margin_x = 36.0
        margin_y = 16.0
        row_h = 64.0
        width = max(1.0, float(self.width()))
        label_font = app_font(10, QFont.Weight.DemiBold)
        fm = QFontMetrics(label_font)

        for row_i, row in enumerate(levels):
            n = max(1, len(row))
            usable = width - 2 * margin_x
            step = usable / n
            y = margin_y + row_i * row_h + 18
            for col_i, (nid, _label, _state) in enumerate(row):
                x = margin_x + step * (col_i + 0.5)
                node_pos[nid] = QPointF(x, y)

        # connectors behind nodes
        pen_idle = QPen(QColor("#D0DDD8"), 2.4)
        pen_done = QPen(QColor("#08745F"), 2.6)
        pen_idle.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen_done.setCapStyle(Qt.PenCapStyle.RoundCap)
        edge_pairs = list(self._edges)
        if not edge_pairs and len(levels) == 1 and len(levels[0]) > 1:
            row = levels[0]
            edge_pairs = [(row[i][0], row[i + 1][0]) for i in range(len(row) - 1)]
        state_by_id = {nid: state for nid, _label, state in self._nodes}
        for a, b in edge_pairs:
            if a not in node_pos or b not in node_pos:
                continue
            p1, p2 = node_pos[a], node_pos[b]
            done_edge = state_by_id.get(a) == "done" and state_by_id.get(b) in {"done", "active"}
            painter.setPen(pen_done if done_edge else pen_idle)
            painter.drawLine(p1, p2)

        for nid, label, state in self._nodes:
            center = node_pos.get(nid)
            if center is None:
                continue
            if state == "done":
                fill, ring = QColor("#08745F"), QColor("#065A4A")
                text_color = QColor("#06483D")
            elif state == "active":
                fill, ring = QColor("#F0A202"), QColor("#C47E00")
                text_color = QColor("#8A5300")
            else:
                fill, ring = QColor("#FFFFFF"), QColor("#B7C7C1")
                text_color = QColor("#7A8F88")
            painter.setBrush(fill)
            painter.setPen(QPen(ring, 2.2))
            painter.drawEllipse(center, r, r)
            if state == "done":
                painter.setPen(QPen(QColor("#FFFFFF"), 2.0))
                painter.drawLine(
                    QPointF(center.x() - 5, center.y() + 1),
                    QPointF(center.x() - 1.5, center.y() + 5),
                )
                painter.drawLine(
                    QPointF(center.x() - 1.5, center.y() + 5),
                    QPointF(center.x() + 6, center.y() - 4),
                )
            slot = max(52.0, (width - 2 * margin_x) / max(1, len(levels[0] if levels else [1])) - 8)
            text = fm.elidedText(label, Qt.TextElideMode.ElideRight, int(slot))
            tw = fm.horizontalAdvance(text)
            painter.setFont(label_font)
            painter.setPen(text_color)
            painter.drawText(
                QRectF(center.x() - tw / 2, center.y() + r + 6, tw + 2, fm.height() + 2),
                text,
            )


def _layout_levels(
    nodes: list[tuple[str, str, str]],
    edges: list[tuple[str, str]],
    *,
    mode: str,
) -> list[list[tuple[str, str, str]]]:
    if not nodes:
        return []
    if mode == "row" or _is_simple_chain(nodes, edges):
        # Сохраняем порядок узлов как передали (фазы / линейный план).
        return [nodes]
    return _group_nodes(nodes, edges)


def _is_simple_chain(nodes: list[tuple[str, str, str]], edges: list[tuple[str, str]]) -> bool:
    if len(nodes) <= 1:
        return True
    ids = [n[0] for n in nodes]
    id_set = set(ids)
    outs: dict[str, list[str]] = {i: [] for i in ids}
    ins: dict[str, int] = {i: 0 for i in ids}
    for a, b in edges:
        if a in id_set and b in id_set and a != b:
            outs[a].append(b)
            ins[b] += 1
    if not edges:
        return True
    # Цепочка: у каждого <=1 вход и <=1 выход, ровно один старт.
    if any(len(outs[i]) > 1 or ins[i] > 1 for i in ids):
        return False
    starts = [i for i in ids if ins[i] == 0]
    return len(starts) == 1


def _group_nodes(
    nodes: list[tuple[str, str, str]],
    edges: list[tuple[str, str]],
) -> list[list[tuple[str, str, str]]]:
    if not edges:
        return [nodes]
    ids = [n[0] for n in nodes]
    by_id = {n[0]: n for n in nodes}
    indeg = {i: 0 for i in ids}
    outs: dict[str, list[str]] = {i: [] for i in ids}
    for a, b in edges:
        if a in indeg and b in indeg and a != b:
            indeg[b] += 1
            outs[a].append(b)
    ready = [i for i in ids if indeg[i] == 0]
    levels: list[list[tuple[str, str, str]]] = []
    seen: set[str] = set()
    while ready:
        levels.append([by_id[i] for i in ready if i in by_id])
        nxt: list[str] = []
        for i in ready:
            seen.add(i)
            for j in outs.get(i, []):
                indeg[j] -= 1
                if indeg[j] <= 0 and j not in seen:
                    nxt.append(j)
        ready = nxt
    rest = [by_id[i] for i in ids if i not in seen]
    if rest:
        levels.append(rest)
    return levels or [nodes]


class WorkflowPage(QWidget):
    saved = Signal(str)
    saved_record = Signal(object)
    launch_requested = Signal(object)
    _async_ok = Signal(object, str)
    _async_fail = Signal(str)
    _stream_event = Signal(str, str)

    def __init__(self, api: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._api = api
        self._record: WorkflowRecord | None = None
        self._pending_paths: list[str] = []
        self._workflow_title = ""
        self._notes = ""
        self._question_fields: dict[str, QLineEdit] = {}
        self._question_files: dict[str, list[str]] = {}
        self._question_file_labels: dict[str, QLabel] = {}
        self._answer_group: QButtonGroup | None = None
        self._current_question_id = ""
        self._chat_files: list[str] = []
        self._selected_quick_answer = ""
        self._thinking_expanded = False
        self._thinking_text = ""
        self._live_label = ""
        self._live_lines: list[str] = []
        self._stream_messages: list[tuple[str, str]] = []
        self._results_dir = ""
        self._busy = False
        self._live_title_label: QLabel | None = None
        self._live_body_label: QLabel | None = None
        self._feed_render_timer = QTimer(self)
        self._feed_render_timer.setSingleShot(True)
        self._feed_render_timer.setInterval(120)
        self._feed_render_timer.timeout.connect(self._render_feed)
        self._async_ok.connect(self._on_async_ok)
        self._async_fail.connect(self._on_async_fail)
        self._stream_event.connect(self.append_stream_event)
        self._build()
        self._render_phase()

    def _build(self) -> None:
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        title = QLabel("Конструктор workflow")
        title.setFont(app_font(22, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

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
        header.setSpacing(10)
        header.addWidget(title, 1)
        header.addWidget(self._activity, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self._phase, 0, Qt.AlignmentFlag.AlignVCenter)

        body = QHBoxLayout()
        body.setSpacing(14)

        self._phase_graph = NodeGraphWidget(mode="row")
        self._step_section = _section("Шаги плана")
        self._step_list = QListWidget()
        self._step_list.setFont(app_font(11))
        self._step_list.setWordWrap(True)
        self._step_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self._step_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._step_list.setStyleSheet(_LIST + scroll_bar_qss())
        self._step_list.setMinimumHeight(120)
        self._step_list.setMaximumHeight(260)
        self._step_section.setVisible(False)
        self._step_list.setVisible(False)

        center_card = QFrame()
        center_card.setObjectName("WorkflowCard")
        center_card.setStyleSheet(_CARD)
        center_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        center = QVBoxLayout(center_card)
        center.setContentsMargins(16, 14, 16, 14)
        center.setSpacing(10)

        self._feed_layout = QVBoxLayout()
        self._feed_layout.setContentsMargins(14, 14, 14, 14)
        self._feed_layout.setSpacing(10)
        feed_inner = QWidget()
        feed_inner.setStyleSheet("background: transparent;")
        feed_inner.setLayout(self._feed_layout)
        self._feed_scroll = _FitWidthScrollArea()
        self._feed_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._feed_scroll.setWidget(feed_inner)
        self._feed_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }" + scroll_bar_qss())

        self._questions_card = QFrame()
        self._questions_card.setObjectName("qcard")
        self._questions_card.setStyleSheet(_QCARD)
        self._questions_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._questions_layout = QVBoxLayout(self._questions_card)
        self._questions_layout.setContentsMargins(12, 10, 12, 10)
        self._questions_layout.setSpacing(8)
        self._questions_card.setVisible(False)

        self._chat_input = QPlainTextEdit()
        self._chat_input.setFixedHeight(58)
        self._chat_input.setPlaceholderText("Напишите сообщение агенту...")
        self._chat_input.setFont(app_font(12))
        self._chat_input.setStyleSheet(_ANSWER_FIELD)
        self._attach_btn = QToolButton()
        self._attach_btn.setText("📎")
        self._attach_btn.setToolTip("Приложить файл")
        self._attach_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._attach_btn.setFixedSize(42, 42)
        self._attach_btn.setStyleSheet(_CLIP_BTN)
        self._attach_btn.clicked.connect(self._on_attach_chat_files)
        self._send_btn = QPushButton("➤")
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.setFixedSize(42, 42)
        self._send_btn.setStyleSheet(_PRIMARY)
        self._send_btn.clicked.connect(self._submit_chat)
        self._chat_files_label = QLabel("")
        self._chat_files_label.setFont(app_font(11))
        self._chat_files_label.setWordWrap(True)
        self._chat_files_label.setStyleSheet("color: #08745F; background: transparent;")
        self._chat_files_label.setVisible(False)
        input_row = QHBoxLayout()
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(8)
        input_row.addWidget(self._attach_btn, 0, Qt.AlignmentFlag.AlignTop)
        input_row.addWidget(self._chat_input, 1)
        input_row.addWidget(self._send_btn, 0, Qt.AlignmentFlag.AlignTop)
        self._input_bar = QWidget()
        self._input_bar.setStyleSheet("background: transparent;")
        self._input_bar.setLayout(input_row)
        self._next_btn = QPushButton("Сохранить")
        self._next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._next_btn.setFixedHeight(46)
        self._next_btn.setStyleSheet(_PRIMARY)
        self._next_btn.clicked.connect(self._on_save_requested)
        self._next_btn.setVisible(False)
        self._tests_ok = False

        center.addWidget(self._feed_scroll, 1)
        center.addWidget(self._questions_card, 0)
        center.addWidget(self._chat_files_label, 0)
        center.addWidget(self._input_bar, 0)
        center.addWidget(self._next_btn, 0)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(app_font(11))
        self._log.setStyleSheet(_REASONING + scroll_bar_qss())
        self._log.setFixedHeight(72)

        self._results = QListWidget()
        self._results.setFont(app_font(12))
        self._results.setFixedHeight(72)
        self._results.setStyleSheet(_LIST + scroll_bar_qss())
        self._results.itemDoubleClicked.connect(self._open_result_item)
        self._fetch_btn = self._mk_button("Скачать", _SECONDARY, self._on_fetch_results, height=32)
        self._open_dir_btn = self._mk_button("Папка", _SECONDARY, self._open_results_folder, height=32)
        results_actions = QHBoxLayout()
        results_actions.setSpacing(8)
        results_actions.addWidget(self._fetch_btn)
        results_actions.addWidget(self._open_dir_btn)
        results_actions.addStretch(1)

        side_card = QFrame()
        side_card.setObjectName("WorkflowCard")
        side_card.setStyleSheet(_CARD)
        side_card.setFixedWidth(250)
        side = QVBoxLayout(side_card)
        side.setContentsMargins(16, 16, 16, 16)
        side.setSpacing(12)
        side.addWidget(_section("Этапы работы"))
        self._phase_steps_widget = QWidget()
        self._phase_steps_widget.setStyleSheet("background: transparent;")
        self._phase_steps_layout = QVBoxLayout(self._phase_steps_widget)
        self._phase_steps_layout.setContentsMargins(0, 0, 0, 0)
        self._phase_steps_layout.setSpacing(10)
        side.addWidget(self._phase_steps_widget, 0)
        side.addWidget(self._step_section, 0)
        side.addWidget(self._step_list, 0)
        side.addStretch(1)

        body.addWidget(center_card, 1)
        body.addWidget(side_card, 0)

        self._plan_btn = self._mk_button("Спланировать", _PRIMARY, self._on_plan, height=36)
        self._exec_btn = self._mk_button("Запустить", _PRIMARY, self._on_execute, height=36)
        self._rerun_btn = self._mk_button(
            "Запустить снова", _SECONDARY, lambda: self._on_execute(reexecute=True), height=36
        )
        self._new_btn = self._mk_button("Новый", _SECONDARY, self._on_new, height=36)

        self._status = QLabel("")
        self._status.setFont(app_font(12, QFont.Weight.Medium))
        self._status.setStyleSheet("color: #2D7A5E; background: transparent;")
        self._status.setWordWrap(True)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.addWidget(self._status, 1)
        for btn in (self._new_btn, self._rerun_btn, self._plan_btn, self._exec_btn):
            actions.addWidget(btn)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        root.addLayout(header)
        root.addLayout(body, 1)
        root.addLayout(actions)
        self._render_graphs()
        self._render_feed()

    def _mk_button(self, text: str, style: str, slot, *, height: int = 36) -> QPushButton:
        btn = QPushButton(text)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedHeight(height)
        btn.setMinimumWidth(120 if height >= 40 else 0)
        btn.setFont(app_font(12, QFont.Weight.DemiBold))
        btn.setStyleSheet(style)
        btn.clicked.connect(slot)
        return btn

    def load_record(self, record: WorkflowRecord) -> None:
        self._record = record
        self._pending_paths = []
        self._workflow_title = record.title
        self._notes = record.notes
        self._log.clear()
        if record.last_result:
            self._log.setPlainText(record.last_result)
        self._render_plan()
        self._render_phase()
        self._ok(f"Загружен workflow · {record.phase}")

    def start_from_passport(self, session: PassportSession, *, auto_plan: bool = True) -> None:
        """Заполнить конструктор workflow из готового паспорта и запустить планирование."""
        self._on_new()
        title = (session.passport.name or session.bp_name or "ИИ-агент").strip()
        self._workflow_title = title
        self._notes = _notes_from_passport(session)
        self._append(f"→ Паспорт «{title}» загружен в конструктор workflow.\n")
        if auto_plan:
            self._on_plan()

    def _render_phase(self) -> None:
        phase = self._record.phase if self._record else "document"
        labels = {k: v for k, v in _PHASE_PIPELINE}
        self._phase.setText(labels.get(phase, phase))
        plan = self._record.plan if self._record else None
        unanswered = bool(plan and plan.unanswered())
        has_exec = bool(self._record and self._record.exec_agent_id)
        can_save = bool(
            self._record
            and self._record.phase == "tested"
            and self._tests_ok
            and not self._busy
        )
        assembly_ready = bool(
            self._record and self._record.phase == "ready" and not unanswered
        )
        self._questions_card.setVisible(unanswered)
        self._input_bar.setVisible(not can_save and not unanswered)
        self._chat_files_label.setVisible(bool(self._chat_files) and not can_save)
        self._next_btn.setText("Сохранить")
        self._next_btn.setVisible(can_save)
        self._exec_btn.setEnabled(bool(plan) and not unanswered and not self._busy)
        self._exec_btn.setVisible(assembly_ready or (has_exec and phase in {"ready", "tested"}))
        self._rerun_btn.setVisible(has_exec)
        self._fetch_btn.setEnabled(has_exec and not self._busy)
        self._open_dir_btn.setEnabled(bool(self._results_dir) or has_exec)
        self._render_graphs()
        self._render_phase_steps()

    def _on_save_requested(self) -> None:
        if self._record is None:
            return
        if not self._tests_ok:
            QMessageBox.information(
                self,
                "Тесты",
                "Сначала дождитесь успешного тестового прогона.",
            )
            return
        wid = self._record.id
        self._append("\n→ Сохраняю агента в «Мои агенты»…\n")

        def work() -> WorkflowRecord:
            return self._api.publish_workflow(wid)

        self._run_async("Публикация", work)

    def _on_launch_requested(self) -> None:
        if self._record is not None:
            self.launch_requested.emit(self._record)

    def _render_graphs(self) -> None:
        phase = self._record.phase if self._record else "document"
        rank = _PHASE_RANK.get(phase, 0)
        phase_nodes: list[tuple[str, str, str]] = []
        for i, (pid, label) in enumerate(_PHASE_PIPELINE):
            if i < rank:
                state = "done"
            elif i == rank:
                state = "active"
            else:
                state = "idle"
            if phase == "done" and pid == "done":
                state = "done"
            phase_nodes.append((pid, label, state))
        phase_edges = [
            (_PHASE_PIPELINE[i][0], _PHASE_PIPELINE[i + 1][0])
            for i in range(len(_PHASE_PIPELINE) - 1)
        ]
        self._phase_graph.set_graph(phase_nodes, phase_edges)

        plan = self._record.plan if self._record else None
        steps = list(plan.steps or []) if plan else []
        if not steps:
            self._step_section.setVisible(False)
            self._step_list.setVisible(False)
            self._step_list.clear()
            return
        self._step_section.setVisible(True)
        self._step_list.setVisible(True)
        self._step_list.clear()
        for index, step in enumerate(steps, start=1):
            item = QListWidgetItem(_format_step_item(index, step))
            item.setSizeHint(QSize(0, 78))
            self._step_list.addItem(item)

    def _render_plan(self) -> None:
        if self._record and self._record.plan:
            self._build_questions(self._record.plan)
        else:
            self._clear_questions()
        self._render_graphs()
        self._render_feed()

    def append_stream_event(self, event_type: str, text: str) -> None:
        if event_type == "thinking":
            self._thinking_text += text
        elif event_type == "decision":
            self._ok(text)
            if text.strip():
                self._live_lines.append(text.strip())
        elif event_type in {"assistant", "message"}:
            visible = _visible_live_text(text)
            if visible and self._busy:
                self._live_lines.append(visible)
            elif visible:
                self._stream_messages.append(("agent_message", visible))
        elif event_type == "system":
            self._live_label = text.strip() or self._live_label
        # During stream: update one live card in place. Full rebuild every token
        # stacked deleteLater widgets on top of each other (broken feed).
        if self._busy and self._live_body_label is not None:
            self._refresh_live_block_text()
            return
        self._schedule_feed_render()

    def _schedule_feed_render(self) -> None:
        if self._busy:
            if not self._feed_render_timer.isActive():
                self._feed_render_timer.start()
            return
        self._feed_render_timer.stop()
        self._render_feed()

    def _clear_feed_layout(self) -> None:
        self._live_title_label = None
        self._live_body_label = None
        while self._feed_layout.count():
            item = self._feed_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _render_feed(self) -> None:
        self._feed_render_timer.stop()
        self._clear_feed_layout()
        if self._record is not None:
            title = self._record.title or "ИИ-агент"
            self._feed_layout.addWidget(self._message_bubble(f"Workflow «{title}» открыт.", kind="system"))
            reasoning = reasoning_text(self._record)
            if reasoning:
                self._feed_layout.addWidget(self._message_bubble(reasoning, kind="agent_message"))
        if self._busy:
            self._feed_layout.addWidget(self._live_block())
        for kind, text in self._stream_messages:
            if kind == "decision":
                continue
            if text.strip():
                self._feed_layout.addWidget(self._message_bubble(text, kind=kind))
        self._feed_layout.addStretch(1)
        QTimer.singleShot(
            0,
            lambda: self._feed_scroll.verticalScrollBar().setValue(
                self._feed_scroll.verticalScrollBar().maximum()
            ),
        )

    def _message_bubble(self, text: str, *, kind: str) -> QWidget:
        user = kind == "user_message"
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        if user:
            row.addStretch(1)
        bubble = QFrame()
        bubble.setMaximumWidth(720)
        bubble.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        color = {
            "user_message": "rgba(8,116,95,0.09)",
            "decision": "#FFF8EF",
            "system": "#F7FAF9",
        }.get(kind, "#FFFFFF")
        bubble.setStyleSheet(
            f"""
            QFrame {{
                background: {color};
                border: 1px solid rgba(8,116,95,0.14);
                border-radius: 16px;
            }}
            """
        )
        layout = QVBoxLayout(bubble)
        layout.setContentsMargins(14, 10, 14, 10)
        if kind == "decision":
            heading = QLabel("Промежуточное решение")
            heading.setFont(app_font(12, QFont.Weight.DemiBold))
            heading.setStyleSheet("color: #8A5300; background: transparent;")
            layout.addWidget(heading)
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        label.setFont(app_font(12))
        label.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        layout.addWidget(label)
        row.addWidget(bubble, 0, Qt.AlignmentFlag.AlignTop)
        if not user:
            row.addStretch(1)
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        wrap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        wrap.setLayout(row)
        return wrap

    def _live_lines_text(self) -> str:
        lines = list(dict.fromkeys(line for line in self._live_lines if line.strip()))
        thinking = _visible_live_text(self._thinking_text)
        if thinking and thinking not in lines:
            lines.append(thinking)
        if not lines:
            lines.append("Агент формирует ответ в реальном времени...")
        return "\n\n".join(lines[-4:])

    def _refresh_live_block_text(self) -> None:
        if self._live_title_label is not None:
            self._live_title_label.setText(self._live_label or "Агент работает")
        if self._live_body_label is not None:
            self._live_body_label.setText(self._live_lines_text())
            QTimer.singleShot(
                0,
                lambda: self._feed_scroll.verticalScrollBar().setValue(
                    self._feed_scroll.verticalScrollBar().maximum()
                ),
            )

    def _live_block(self) -> QWidget:
        card = QFrame()
        card.setMaximumWidth(720)
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        card.setStyleSheet(
            """
            QFrame {
                background: #FFFFFF;
                border: 1px solid rgba(8,116,95,0.18);
                border-radius: 16px;
            }
            """
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)
        title = QLabel(self._live_label or "Агент работает")
        title.setFont(app_font(12, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #08745F; background: transparent;")
        layout.addWidget(title)

        body = QLabel(self._live_lines_text())
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        body.setFont(app_font(12))
        body.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        layout.addWidget(body)
        self._live_title_label = title
        self._live_body_label = body

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(card, 0, Qt.AlignmentFlag.AlignTop)
        row.addStretch(1)
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        wrap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        wrap.setLayout(row)
        return wrap

    def _thinking_block(self) -> QWidget:
        card = QFrame()
        card.setMaximumWidth(720)
        card.setStyleSheet(
            """
            QFrame {
                background: #FFFFFF;
                border: 1px solid rgba(8,116,95,0.14);
                border-radius: 16px;
            }
            """
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)
        toggle = QPushButton(("Thinking ▾" if self._thinking_expanded else "Thinking ▸") + " Агент размышляет")
        toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        toggle.setFont(app_font(12, QFont.Weight.DemiBold))
        toggle.setStyleSheet(
            """
            QPushButton {
                text-align: left;
                border: none;
                background: transparent;
                color: #08745F;
                padding: 0;
            }
            """
        )
        toggle.clicked.connect(self._toggle_thinking)
        layout.addWidget(toggle)
        if self._thinking_expanded:
            visible_text = _strip_json_blob(self._thinking_text).strip()
            if (
                not visible_text
                or visible_text.lstrip().startswith("{")
                or "```json" in visible_text.lower()
                or '"steps"' in visible_text
            ):
                visible_text = "Агент формирует план. Подробности появятся после структурирования ответа."
            text = QLabel(visible_text)
            text.setWordWrap(True)
            text.setFont(app_font(12))
            text.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
            layout.addWidget(text)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(card)
        row.addStretch(1)
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        wrap.setLayout(row)
        return wrap

    def _toggle_thinking(self) -> None:
        self._thinking_expanded = not self._thinking_expanded
        self._render_feed()

    def _render_phase_steps(self) -> None:
        while self._phase_steps_layout.count():
            item = self._phase_steps_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        phase = self._record.phase if self._record else "document"
        rank = _PHASE_RANK.get(phase, 0)
        for index, (pid, label) in enumerate(_PHASE_PIPELINE):
            if phase == "done" and pid == "done":
                state = "done"
            elif index < rank:
                state = "done"
            elif index == rank:
                state = "active"
            else:
                state = "idle"
            self._phase_steps_layout.addWidget(_phase_step_widget(label, state))

    def _build_questions(self, plan: WorkflowPlan) -> None:
        self._clear_questions()
        unanswered = plan.unanswered()
        if not unanswered:
            self._questions_card.setVisible(False)
            return
        question = unanswered[0]
        self._current_question_id = question.id
        title = QLabel("Агенту нужно уточнение")
        title.setFont(app_font(12, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #8A5300; background: transparent;")
        question_label = QLabel(question.question)
        question_label.setFont(app_font(13, QFont.Weight.DemiBold))
        question_label.setWordWrap(True)
        question_label.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        self._questions_layout.addWidget(title)
        self._questions_layout.addWidget(question_label)
        if question.why:
            why = QLabel(question.why)
            why.setFont(app_font(11))
            why.setWordWrap(True)
            why.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
            self._questions_layout.addWidget(why)
        group = QButtonGroup(self._questions_card)
        self._answer_group = group
        group.setExclusive(True)
        variants = _quick_answers_for_question(question)
        for answer in variants:
            option = QRadioButton(answer)
            option.setCursor(Qt.CursorShape.PointingHandCursor)
            option.setFont(app_font(12))
            option.setStyleSheet(_RADIO_OPTION)
            option.toggled.connect(
                lambda checked=False, value=answer: self._select_quick_answer(value) if checked else None
            )
            group.addButton(option)
            self._questions_layout.addWidget(option)

        custom_row = QHBoxLayout()
        custom_row.setSpacing(8)
        custom_option = QRadioButton("Свой вариант")
        custom_option.setCursor(Qt.CursorShape.PointingHandCursor)
        custom_option.setFont(app_font(12))
        custom_option.setStyleSheet(_RADIO_OPTION)
        custom_input = QLineEdit()
        custom_input.setPlaceholderText("Напишите свой ответ")
        custom_input.setFont(app_font(12))
        custom_input.setStyleSheet(_CUSTOM_ANSWER_FIELD)
        custom_attach = QToolButton()
        custom_attach.setText("📎")
        custom_attach.setToolTip("Приложить документ к своему варианту")
        custom_attach.setCursor(Qt.CursorShape.PointingHandCursor)
        custom_attach.setFixedSize(34, 34)
        custom_attach.setStyleSheet(_CLIP_BTN)
        self._question_fields[question.id] = custom_input
        group.addButton(custom_option)
        custom_row.addWidget(custom_option, 0)
        custom_row.addWidget(custom_input, 1)
        custom_row.addWidget(custom_attach, 0)
        self._questions_layout.addLayout(custom_row)

        custom_option.toggled.connect(
            lambda checked=False, field=custom_input: self._select_custom_answer(field.text(), field)
            if checked
            else None
        )
        custom_input.textEdited.connect(
            lambda value, option=custom_option, field=custom_input: self._edit_custom_answer(value, option, field)
        )
        custom_attach.clicked.connect(
            lambda _checked=False, option=custom_option: self._attach_custom_answer_file(option)
        )

        hint = QLabel("Выберите вариант или заполните последнюю строку своим ответом.")
        hint.setFont(app_font(11))
        hint.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        self._questions_layout.addWidget(hint)
        next_row = QHBoxLayout()
        next_row.setContentsMargins(0, 4, 0, 0)
        next_row.addStretch(1)
        next_btn = QPushButton("Далее")
        next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        next_btn.setFixedHeight(36)
        next_btn.setMinimumWidth(120)
        next_btn.setFont(app_font(12, QFont.Weight.DemiBold))
        next_btn.setStyleSheet(_PRIMARY)
        next_btn.clicked.connect(self._submit_question_answer)
        next_row.addWidget(next_btn)
        self._questions_layout.addLayout(next_row)
        self._questions_card.setVisible(True)

    def _clear_questions(self) -> None:
        _clear_layout(self._questions_layout)
        self._question_fields = {}
        self._question_files = {}
        self._question_file_labels = {}
        if self._answer_group is not None:
            self._answer_group.deleteLater()
            self._answer_group = None
        self._current_question_id = ""
        self._selected_quick_answer = ""

    def _select_quick_answer(self, answer: str) -> None:
        self._selected_quick_answer = answer
        field = self._question_fields.get(self._current_question_id)
        if isinstance(field, QLineEdit):
            field.clear()

    def _select_custom_answer(self, answer: str, field: QLineEdit) -> None:
        del answer
        self._selected_quick_answer = ""
        field.setFocus()

    def _edit_custom_answer(self, answer: str, option: QRadioButton, field: QLineEdit) -> None:
        if not option.isChecked():
            option.setChecked(True)
        self._select_custom_answer(answer, field)

    def _attach_custom_answer_file(self, option: QRadioButton) -> None:
        option.setChecked(True)
        self._on_attach_chat_files()

    def _on_attach_chat_files(self) -> None:
        if not self._current_question_id:
            QMessageBox.information(self, "Файл", "Файл можно приложить к текущему вопросу агента.")
            return
        patterns = " ".join(f"*{s}" for s in sorted(SUPPORTED_SUFFIXES))
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Файл к ответу",
            "",
            f"Документы ({patterns});;Все файлы (*)",
        )
        if not paths:
            return
        for path in paths:
            if path and Path(path).is_file() and path not in self._chat_files:
                suffix = Path(path).suffix.lower()
                if suffix and suffix not in SUPPORTED_SUFFIXES:
                    continue
                self._chat_files.append(path)
        names = [Path(path).name for path in self._chat_files]
        self._chat_files_label.setText("📎 " + ", ".join(names))
        self._chat_files_label.setVisible(bool(names))
        self._ok(f"К ответу приложено: {len(self._chat_files)}")

    def _submit_chat(self) -> None:
        text = self._current_answer_text()
        if self._current_question_id:
            self._submit_question_answer()
            return
        if text:
            self._stream_messages.append(("user_message", text))
            self._chat_input.clear()
            self._render_feed()
            self._ok("Сообщение сохранено в ленте. Для запуска используйте этапы workflow.")

    def _submit_question_answer(self) -> None:
        if not self._current_question_id:
            return
        text = self._current_answer_text()
        if not text and not self._chat_files:
            QMessageBox.information(self, "Ответ", "Выберите вариант, заполните свой ответ или приложите файл.")
            return
        self._on_clarify()

    def _current_answer_text(self) -> str:
        if self._current_question_id:
            field = self._question_fields.get(self._current_question_id)
            if isinstance(field, QLineEdit):
                custom = field.text().strip()
                if custom:
                    return custom
            if self._selected_quick_answer.strip():
                return self._selected_quick_answer.strip()
        return self._chat_input.toPlainText().strip()

    def _on_attach_answer_file(self, question_id: str) -> None:
        patterns = " ".join(f"*{s}" for s in sorted(SUPPORTED_SUFFIXES))
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Файл к ответу",
            "",
            f"Документы ({patterns});;Все файлы (*)",
        )
        if not paths:
            return
        bucket = self._question_files.setdefault(question_id, [])
        for path in paths:
            if path and Path(path).is_file() and path not in bucket:
                suffix = Path(path).suffix.lower()
                if suffix and suffix not in SUPPORTED_SUFFIXES:
                    continue
                bucket.append(path)
        label = self._question_file_labels.get(question_id)
        if label is not None:
            names = [Path(p).name for p in bucket]
            label.setText("📎 " + ", ".join(names))
            label.setVisible(bool(names))
        self._ok(f"К ответу приложено: {len(bucket)}")

    def _set_busy(self, busy: bool, base: str = "Обращение к агенту") -> None:
        self._busy = busy
        for btn in (
            self._plan_btn,
            self._send_btn,
            self._attach_btn,
            self._exec_btn,
            self._rerun_btn,
            self._new_btn,
        ):
            btn.setEnabled(not busy)
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
        cleaned = (text or "").strip()
        if not cleaned:
            return
        self._stream_messages.append(("system", cleaned))
        self._schedule_feed_render()

    def _ok(self, message: str) -> None:
        self._status.setText(message)
        self._status.setStyleSheet("color: #2D7A5E; background: transparent;")

    def _fail(self, message: str) -> None:
        self._status.setText(message)
        self._status.setStyleSheet("color: #B00020; background: transparent;")
        self._append(f"\n[error] {message}\n")

    def _run_async(self, label: str, fn) -> None:
        self._thinking_text = ""
        self._thinking_expanded = False
        self._live_label = label
        self._live_lines = []
        self._set_busy(True, label)
        self._render_feed()

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
            self._thinking_text = ""
            self._live_lines = []
            self._live_label = ""
            self._render_plan()
            self._render_phase()
            self.saved.emit(result.id)
            # Черновик убираем только после publish (phase=done).
            if result.phase == "done":
                self.saved_record.emit(result)
            if label.startswith("Планирование") or label.startswith("Уточнение"):
                n = len(result.plan.unanswered()) if result.plan else 0
                self._ok(f"План готов · вопросов: {n}" if n else "План готов · можно реализовывать")
            elif label.startswith("Реализация"):
                self._tests_ok = False
                self._ok(f"{result.phase} · скачиваю артефакты и гоняю проверки")
                if result.last_result:
                    self._append("\n" + result.last_result + "\n")
                self._on_fetch_results()
            elif label.startswith("Публикация"):
                self._ok("Сохранено в «Мои агенты»")
                self._append(
                    "\n✓ Агент опубликован. Откройте «Мои агенты» → «Запустить».\n"
                )
            else:
                self._ok("Готово")
        elif isinstance(result, tuple) and len(result) == 2 and result[0] == "__live_ok__":
            self._tests_ok = True
            self._append("\n✓ Live-проверка web_search завершена — можно сохранить агента.\n")
            self._ok("Тесты пройдены · можно сохранить")
            self._render_phase()
            self._render_feed()
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
            self._thinking_text = ""
            self._live_lines = []
            self._live_label = ""
            self._evaluate_tests_and_verify(list(files))
            self._render_feed()
            self._render_phase()

    def _on_async_fail(self, message: str) -> None:
        self._set_busy(False)
        self._thinking_text = ""
        self._live_lines = []
        self._live_label = ""
        self._render_feed()
        self._fail(message)

    def _on_plan(self) -> None:
        notes = (self._notes or "").strip()
        if self._record is None:
            if not notes and not self._pending_paths:
                QMessageBox.warning(
                    self,
                    "Документ",
                    "Нет материалов для планирования. Откройте workflow из паспорта агента "
                    "или из «Мои workflow».",
                )
                return
            self._append("→ Создаю workflow и запускаю планирование…\n")

            def create_and_plan() -> WorkflowRecord:
                created = self._api.create_workflow(notes=notes, file_paths=self._pending_paths)
                return self._api.stream_plan_workflow(
                    created.id,
                    lambda event_type, text: self._stream_event.emit(event_type, text),
                )

            self._run_async("Планирование", create_and_plan)
            return

        self._append("→ Планирование через backend…\n")
        self._run_async(
            "Планирование",
            lambda: self._api.stream_plan_workflow(
                self._record.id,  # type: ignore[union-attr]
                lambda event_type, text: self._stream_event.emit(event_type, text),
            ),
        )

    def _on_clarify(self) -> None:
        if self._record is None or self._record.plan is None:
            return
        qid = self._current_question_id
        text = self._current_answer_text()
        answers = {qid: text} if qid and text else {}
        file_paths = list(self._chat_files)
        file_question_ids = [qid for _ in file_paths if qid]
        if not any(answers.values()) and not file_paths:
            QMessageBox.information(self, "Ответы", "Введите ответ или приложите файл.")
            return
        self._append("\n→ Отправляю ответы…\n")
        wid = self._record.id
        self._questions_card.setVisible(False)
        self._clear_questions()

        def work() -> WorkflowRecord:
            return self._api.stream_clarify_workflow(
                wid,
                answers,
                lambda event_type, text: self._stream_event.emit(event_type, text),
                file_paths=file_paths,
                file_question_ids=file_question_ids,
            )

        self._run_async("Уточнение плана", work)
        self._chat_input.clear()
        self._chat_files = []
        self._chat_files_label.clear()
        self._chat_files_label.setVisible(False)

    def _on_execute(self, reexecute: bool = False) -> None:
        if self._record is None or self._record.plan is None:
            QMessageBox.information(self, "План", "Сначала постройте план.")
            return
        self._append("\n→ Запускаю реализацию…\n")
        wid = self._record.id
        self._run_async(
            "Реализация",
            lambda: self._api.stream_execute_workflow(
                wid,
                lambda event_type, text: self._stream_event.emit(event_type, text),
                reexecute=reexecute,
            ),
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

    def _evaluate_tests_and_verify(self, files: list[str]) -> None:
        """Parse RESULT.md / last_result and run live web_search smoke test."""
        blob_parts: list[str] = []
        if self._record and self._record.last_result:
            blob_parts.append(self._record.last_result)
        for path in files:
            name = Path(path).name.lower()
            if name in {"result.md", "results.md", "readme.md"}:
                try:
                    blob_parts.append(Path(path).read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    continue
        blob = "\n".join(blob_parts)
        upper = blob.upper()
        explicit_fail = "TESTS: FAIL" in upper
        explicit_pass = "TESTS: PASS" in upper
        if explicit_fail:
            self._tests_ok = False
            self._append("\n✗ Тесты: FAIL — исправьте реализацию и запустите снова.\n")
            self._ok("Тесты не прошли")
            self._render_phase()
            return
        self._tests_ok = explicit_pass
        if explicit_pass:
            self._append("\n✓ Тесты по артефактам: PASS. Запускаю live web_search…\n")
        else:
            self._append("\n… В RESULT.md нет TESTS: PASS — запускаю live web_search.\n")

        if self._record is None:
            return
        wid = self._record.id
        title = self._record.title or "агент"
        message = (
            f"Сделай live тестовый прогон через web_search по теме «{title}». "
            "Верни понятный список результатов."
        )

        def live() -> None:
            try:
                self._api.stream_workflow_agent_run(
                    wid,
                    message,
                    lambda payload: self._stream_event.emit(
                        str(payload.get("type") or "message"),
                        str(
                            payload.get("text")
                            or payload.get("message")
                            or payload.get("tool")
                            or ""
                        ),
                    ),
                )
                self._async_ok.emit(("__live_ok__", []), "Live-проверка")
            except Exception as exc:  # noqa: BLE001
                # Fixture PASS already allows save; live failure is non-blocking then.
                if explicit_pass:
                    self._async_ok.emit(("__live_ok__", []), "Live-проверка")
                else:
                    self._async_fail.emit(str(getattr(exc, "message", None) or exc))

        Thread(target=live, daemon=True).start()
        self._set_busy(True, "Live-проверка web_search")
        if explicit_pass:
            self._render_phase()

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
        self._workflow_title = ""
        self._notes = ""
        self._thinking_text = ""
        self._thinking_expanded = False
        self._stream_messages = []
        self._chat_input.clear()
        self._chat_files = []
        self._chat_files_label.clear()
        self._chat_files_label.setVisible(False)
        self._log.clear()
        self._results.clear()
        self._results_dir = ""
        self._tests_ok = False
        self._clear_questions()
        self._questions_card.setVisible(False)
        self._render_phase()
        self._render_feed()
        self._ok("Новый workflow")


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
