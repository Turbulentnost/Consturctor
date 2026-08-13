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
    QTextCursor,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
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
    ("ready", "Готов"),
    ("done", "Готово"),
]
_PHASE_RANK = {
    "document": 0,
    "plan": 1,
    "clarify": 2,
    "ready": 3,
    "executing": 3,
    "done": 4,
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
    _async_ok = Signal(object, str)
    _async_fail = Signal(str)

    def __init__(self, api: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._api = api
        self._record: WorkflowRecord | None = None
        self._pending_paths: list[str] = []
        self._workflow_title = ""
        self._notes = ""
        self._question_fields: dict[str, QPlainTextEdit] = {}
        self._question_files: dict[str, list[str]] = {}
        self._question_file_labels: dict[str, QLabel] = {}
        self._results_dir = ""
        self._busy = False
        self._async_ok.connect(self._on_async_ok)
        self._async_fail.connect(self._on_async_fail)
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

        right_card = QFrame()
        right_card.setObjectName("WorkflowCard")
        right_card.setStyleSheet(_CARD)
        right_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        right_outer = QVBoxLayout(right_card)
        right_outer.setContentsMargins(16, 14, 16, 14)
        right_outer.setSpacing(8)

        self._phase_graph = NodeGraphWidget(mode="row")
        self._step_section = _section("Шаги плана")
        self._step_graph = NodeGraphWidget(mode="dag")
        self._step_section.setVisible(False)
        self._step_graph.setVisible(False)

        self._reasoning = QPlainTextEdit()
        self._reasoning.setReadOnly(True)
        self._reasoning.setFont(app_font(12))
        self._reasoning.setStyleSheet(_REASONING + scroll_bar_qss())
        self._reasoning.setPlaceholderText("Рассуждения модели…")
        self._reasoning.setMinimumHeight(0)
        self._reasoning.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._questions_card = QFrame()
        self._questions_card.setObjectName("qcard")
        self._questions_card.setStyleSheet(_QCARD)
        self._questions_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        card_layout = QVBoxLayout(self._questions_card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(8)
        self._q_header = QLabel("Уточнения — текст или файл 📎")
        self._q_header.setFont(app_font(12, QFont.Weight.DemiBold))
        self._q_header.setStyleSheet("color: #8A5300; background: transparent;")
        self._q_header.setWordWrap(True)
        self._questions_inner = QWidget()
        self._questions_inner.setStyleSheet("background: transparent;")
        self._questions_inner.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )
        self._questions_layout = QVBoxLayout(self._questions_inner)
        self._questions_layout.setContentsMargins(0, 0, 6, 0)
        self._questions_layout.setSpacing(8)
        q_scroll = _FitWidthScrollArea()
        q_scroll.setFrameShape(QFrame.Shape.NoFrame)
        q_scroll.setWidget(self._questions_inner)
        q_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }" + scroll_bar_qss()
        )
        self._q_scroll = q_scroll
        self._clarify_btn = self._mk_button("Отправить ответы", _PRIMARY, self._on_clarify, height=36)
        card_layout.addWidget(self._q_header)
        card_layout.addWidget(q_scroll, 1)
        clarify_row = QHBoxLayout()
        clarify_row.addStretch(1)
        clarify_row.addWidget(self._clarify_btn)
        card_layout.addLayout(clarify_row)
        self._questions_card.setVisible(False)

        # Средняя зона: рассуждения сверху, уточняющие вопросы ниже на всю ширину.
        self._mid_layout = QVBoxLayout()
        self._mid_layout.setSpacing(10)
        self._mid_layout.addWidget(_section("Рассуждения модели"))
        self._reasoning.setMinimumHeight(100)
        self._reasoning.setMaximumHeight(220)
        self._mid_layout.addWidget(self._reasoning, 1)
        self._mid_layout.addWidget(self._questions_card, 2)

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

        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        log_col = QVBoxLayout()
        log_col.setSpacing(4)
        log_col.addWidget(_section("Журнал"))
        log_col.addWidget(self._log)
        res_col = QVBoxLayout()
        res_col.setSpacing(4)
        res_col.addWidget(_section("Результат"))
        res_col.addWidget(self._results)
        res_col.addLayout(results_actions)
        bottom.addLayout(log_col, 1)
        bottom.addLayout(res_col, 1)

        right_outer.addWidget(self._phase_graph)
        right_outer.addWidget(self._step_section)
        right_outer.addWidget(self._step_graph)
        right_outer.addLayout(self._mid_layout, 1)
        right_outer.addLayout(bottom, 0)

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
        root.addWidget(right_card, 1)
        root.addLayout(actions)
        self._render_graphs()
        self._reasoning.setPlainText(reasoning_text(None))

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
        self._questions_card.setVisible(unanswered)
        # Без вопросов рассуждения занимают всю среднюю зону.
        self._reasoning.setMaximumHeight(220 if unanswered else 16777215)
        self._mid_layout.setStretchFactor(self._questions_card, 3 if unanswered else 0)
        self._exec_btn.setEnabled(bool(plan) and not unanswered and not self._busy)
        self._rerun_btn.setVisible(has_exec)
        self._fetch_btn.setEnabled(has_exec and not self._busy)
        self._open_dir_btn.setEnabled(bool(self._results_dir) or has_exec)
        self._render_graphs()

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
            self._step_graph.setVisible(False)
            self._step_graph.set_graph([])
            return
        self._step_section.setVisible(True)
        self._step_graph.setVisible(True)
        step_nodes: list[tuple[str, str, str]] = []
        for s in steps:
            sid = s.id or s.title or "step"
            label = s.title or sid
            if phase == "done":
                state = "done"
            elif phase == "executing":
                state = "active"
            elif phase in {"ready", "clarify"}:
                state = "idle"
            else:
                state = "idle"
            step_nodes.append((sid, label, state))
        edges: list[tuple[str, str]] = []
        for s in steps:
            if not s.id:
                continue
            for d in s.depends_on or []:
                edges.append((d, s.id))
        if not edges and len(steps) > 1:
            ordered = [s for level in _topo_levels(steps) for s in level]
            for i in range(len(ordered) - 1):
                a, b = ordered[i].id or f"s{i}", ordered[i + 1].id or f"s{i+1}"
                edges.append((a, b))
        self._step_graph.set_graph(step_nodes, edges)

    def _render_plan(self) -> None:
        self._reasoning.setPlainText(reasoning_text(self._record))
        if self._record and self._record.plan:
            self._build_questions(self._record.plan)
        else:
            self._clear_questions()
        self._render_graphs()

    def _build_questions(self, plan: WorkflowPlan) -> None:
        self._clear_questions()
        for i, q in enumerate(plan.unanswered(), start=1):
            bubble = QFrame()
            bubble.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            bubble.setStyleSheet(
                """
                QFrame {
                    background: #FFFFFF;
                    border: 1px solid rgba(16,24,23,0.08);
                    border-radius: 14px;
                }
                """
            )
            bubble_layout = QVBoxLayout(bubble)
            bubble_layout.setContentsMargins(12, 10, 12, 10)
            bubble_layout.setSpacing(8)
            label = QLabel(f"{i}. {q.question}")
            label.setFont(app_font(13, QFont.Weight.DemiBold))
            label.setWordWrap(True)
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            label.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
            if q.why:
                why = QLabel(q.why)
                why.setFont(app_font(11))
                why.setWordWrap(True)
                why.setMinimumWidth(0)
                why.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
                why.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
                bubble_layout.addWidget(label)
                bubble_layout.addWidget(why)
            else:
                bubble_layout.addWidget(label)

            field = QPlainTextEdit()
            field.setPlainText(q.answer)
            field.setFont(app_font(12))
            field.setFixedHeight(66)
            field.setStyleSheet(_ANSWER_FIELD)
            field.setPlaceholderText("Напишите ответ своими словами…")
            field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

            clip = QToolButton()
            clip.setText("📎")
            clip.setToolTip("Приложить файл к ответу")
            clip.setCursor(Qt.CursorShape.PointingHandCursor)
            clip.setFixedSize(40, 40)
            clip.setStyleSheet(_CLIP_BTN)
            qid = q.id
            clip.clicked.connect(lambda _=False, question_id=qid: self._on_attach_answer_file(question_id))

            answer_row = QHBoxLayout()
            answer_row.setSpacing(8)
            answer_row.addWidget(field, 1)
            answer_row.addWidget(clip, 0, Qt.AlignmentFlag.AlignTop)

            files_lbl = QLabel("")
            files_lbl.setFont(app_font(11))
            files_lbl.setWordWrap(True)
            files_lbl.setMinimumWidth(0)
            files_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            files_lbl.setStyleSheet("color: #08745F; background: transparent;")
            files_lbl.setVisible(False)

            bubble_layout.addLayout(answer_row)
            bubble_layout.addWidget(files_lbl)
            self._questions_layout.addWidget(bubble)
            self._question_fields[q.id] = field
            self._question_files[q.id] = []
            self._question_file_labels[q.id] = files_lbl
        self._questions_layout.addStretch(1)
        # Re-apply viewport width after content rebuild so labels wrap immediately.
        if hasattr(self, "_q_scroll") and self._q_scroll.viewport() is not None:
            width = max(1, self._q_scroll.viewport().width())
            self._questions_inner.setMaximumWidth(width)

    def _clear_questions(self) -> None:
        while self._questions_layout.count():
            item = self._questions_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._question_fields = {}
        self._question_files = {}
        self._question_file_labels = {}

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
            self._clarify_btn,
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
            self._workflow_title = result.title
            self._notes = result.notes or self._notes
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
                return self._api.plan_workflow(created.id)

            self._run_async("Планирование", create_and_plan)
            return

        self._append("→ Планирование через backend…\n")
        self._run_async("Планирование", lambda: self._api.plan_workflow(self._record.id))  # type: ignore[union-attr]

    def _on_clarify(self) -> None:
        if self._record is None or self._record.plan is None:
            return
        answers = {qid: field.toPlainText().strip() for qid, field in self._question_fields.items()}
        file_paths: list[str] = []
        file_question_ids: list[str] = []
        for qid, paths in self._question_files.items():
            for path in paths:
                file_paths.append(path)
                file_question_ids.append(qid)
        if not any(answers.values()) and not file_paths:
            QMessageBox.information(self, "Ответы", "Введите ответ или приложите файл.")
            return
        self._append("\n→ Отправляю ответы…\n")
        wid = self._record.id

        def work() -> WorkflowRecord:
            return self._api.clarify_workflow(
                wid,
                answers,
                file_paths=file_paths,
                file_question_ids=file_question_ids,
            )

        self._run_async("Уточнение плана", work)

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
        self._workflow_title = ""
        self._notes = ""
        self._reasoning.setPlainText(reasoning_text(None))
        self._log.clear()
        self._results.clear()
        self._results_dir = ""
        self._clear_questions()
        self._questions_card.setVisible(False)
        self._render_phase()
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
