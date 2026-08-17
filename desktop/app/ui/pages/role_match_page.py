from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from app.api_client import RegulationFragment, RegulationParseResult, RoleMatch, RoleMatchResult
from app.ui.pages.regulation_review_page import _table_widget
from app.ui.theme import (
    COLOR_CONTENT_MUTED,
    MAIN_TEXT,
    app_font,
    scroll_bar_qss,
)

_HIGH_CONFIDENCE = 0.85
_MAX_FUNCTION_TITLE_CHARS = 420
_TEMP = Path(__file__).resolve().parents[1] / "temp"
_CHECK_ICON_PATH = _TEMP / "зеленаягалочка.png"
_WARN_ICON_PATH = _TEMP / "внимание.png"

_MATCH_TYPE_LABELS: dict[str, str] = {
    "direct_role_mention": "Должность указана в тексте или заголовке",
    "inherited_from_section": "Роль унаследована из раздела документа",
    "assigned_action": "Фрагмент описывает выполняемое действие",
    "process_role_alias": "Совпадение с ролью в процессе",
    "department_relation": "Связь через подразделение",
    "interaction": "Взаимодействие с другой ролью",
    "related_artifact_or_system": "Упоминание артефакта или системы",
    "semantic_candidate": "Семантическое совпадение с должностью",
    "graph_relation": "Связь найдена через граф документа",
    "definition_link": "Термин связан с определением в документе",
    "actor_inheritance": "Исполнитель наследуется из связанного блока",
}


class RoleMatchPage(QWidget):
    back_requested = Signal()
    finish_requested = Signal()
    decision_requested = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._result: RoleMatchResult | None = None
        self._regulation: RegulationParseResult | None = None
        self._matches: list[RoleMatch] = []
        self._index = 0
        self._reviewed_ids: set[str] = set()
        self._fragment_widgets: dict[str, QWidget] = {}

        self._stack = QStackedWidget()

        self._wizard = QWidget()
        wizard_layout = QVBoxLayout(self._wizard)
        wizard_layout.setContentsMargins(0, 0, 0, 0)
        wizard_layout.setSpacing(14)

        self._title = QLabel("Проверка функций должности")
        self._title.setFont(app_font(30, QFont.Weight.DemiBold))
        self._title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

        self._subtitle = QLabel("")
        self._subtitle.setFont(app_font(14))
        self._subtitle.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        self._found_badge = _icon_status_badge(
            "#E8F7F0",
            "#06483D",
            "Найдено 0 функций",
            _load_temp_icon(_CHECK_ICON_PATH, 16),
        )
        self._review_badge = _icon_status_badge(
            "#FFF4E5",
            "#9A5B00",
            "Нужно проверить 0",
            _load_temp_icon(_WARN_ICON_PATH, 16),
        )
        status_row.addWidget(self._found_badge)
        status_row.addWidget(self._review_badge)
        status_row.addStretch(1)
        self._progress_label = QLabel("0 из 0")
        self._progress_label.setFont(app_font(13, QFont.Weight.DemiBold))
        self._progress_label.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedWidth(120)
        self._progress_bar.setFixedHeight(6)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setStyleSheet(
            """
            QProgressBar {
                background: rgba(6,72,61,0.12);
                border: none;
                border-radius: 3px;
            }
            QProgressBar::chunk {
                background: #08745F;
                border-radius: 3px;
            }
            """
        )
        status_row.addWidget(self._progress_label)
        status_row.addWidget(self._progress_bar)

        self._card_host = QVBoxLayout()
        self._card_host.setContentsMargins(0, 0, 0, 0)
        self._card_host.setSpacing(12)

        card_scroll_content = QWidget()
        card_scroll_content.setStyleSheet("background: transparent;")
        card_scroll_content.setLayout(self._card_host)

        self._card_scroll = QScrollArea()
        self._card_scroll.setWidgetResizable(True)
        self._card_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._card_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._card_scroll.setWidget(card_scroll_content)
        self._card_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }" + scroll_bar_qss()
        )

        self._reviewed_label = QLabel("Проверен 0 из 0")
        self._reviewed_label.setFont(app_font(13))
        self._reviewed_label.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        wizard_layout.addWidget(self._title)
        wizard_layout.addWidget(self._subtitle)
        wizard_layout.addLayout(status_row)
        wizard_layout.addSpacing(4)
        wizard_layout.addWidget(self._card_scroll, 1)
        wizard_layout.addWidget(self._reviewed_label)

        self._document = QWidget()
        doc_layout = QVBoxLayout(self._document)
        doc_layout.setContentsMargins(0, 0, 0, 0)
        doc_layout.setSpacing(12)

        doc_header = QHBoxLayout()
        self._doc_back = QPushButton("← К фрагментам")
        self._doc_back.setFlat(True)
        self._doc_back.setCursor(Qt.CursorShape.PointingHandCursor)
        self._doc_back.setFont(app_font(13, QFont.Weight.DemiBold))
        self._doc_back.setStyleSheet(
            """
            QPushButton {
                color: #06483D;
                background: transparent;
                border: none;
                text-align: left;
                padding: 0;
            }
            QPushButton:hover { color: #08745F; }
            """
        )
        self._doc_back.clicked.connect(self._show_wizard)
        doc_header.addWidget(self._doc_back)
        doc_header.addStretch(1)

        self._doc_title = QLabel("Документ")
        self._doc_title.setFont(app_font(22, QFont.Weight.DemiBold))
        self._doc_title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        self._doc_content = QVBoxLayout(scroll_content)
        self._doc_content.setContentsMargins(0, 0, 0, 0)
        self._doc_content.setSpacing(12)

        self._doc_scroll = QScrollArea()
        self._doc_scroll.setWidgetResizable(True)
        self._doc_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._doc_scroll.setWidget(scroll_content)
        self._doc_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }" + scroll_bar_qss()
        )

        doc_layout.addLayout(doc_header)
        doc_layout.addWidget(self._doc_title)
        doc_layout.addWidget(self._doc_scroll, 1)

        self._stack.addWidget(self._wizard)
        self._stack.addWidget(self._document)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._stack)

    def set_result(
        self,
        result: RoleMatchResult,
        regulation: RegulationParseResult | None = None,
    ) -> None:
        preserve_index = (
            self._result is not None
            and self._result.run_id == result.run_id
            and self._matches
        )
        old_index = self._index if preserve_index else 0

        self._result = result
        self._regulation = regulation
        self._matches = _ordered_matches(result.matches)
        self._index = min(old_index, max(0, len(self._matches) - 1))
        if not preserve_index:
            self._reviewed_ids.clear()
        self._stack.setCurrentWidget(self._wizard)
        self._build_document_view()
        self._render()

    def _render(self) -> None:
        if self._result is None:
            return

        total = len(self._matches)
        subtitle = f"{self._result.canonical_title}" + (
            f" · {self._result.department}" if self._result.department else ""
        )
        diagnostics = (self._result.audit or {}).get("diagnostics") if self._result.audit else None
        if isinstance(diagnostics, dict):
            sections = diagnostics.get("candidateSections") if isinstance(diagnostics.get("candidateSections"), dict) else {}
            subtitle += (
                f" · проверено фрагментов {diagnostics.get('fragmentsTotal', 0)}"
                f" · кандидатов {diagnostics.get('candidatesTotal', 0)}"
                f" · разделов {len(sections)}"
            )
        self._subtitle.setText(subtitle)
        needs_review = sum(1 for match in self._matches if _needs_user_review(match))
        _set_badge_text(self._found_badge, f"Найдено {total} функций")
        _set_badge_text(self._review_badge, f"Нужно проверить {needs_review}")
        self._review_badge.setVisible(needs_review > 0)

        if total == 0:
            self._progress_label.setText("0 из 0")
            self._progress_bar.setValue(0)
            self._reviewed_label.setText("Проверен 0 из 0")
            self._clear_card_host()
            self._card_host.addWidget(_empty_card())
            return

        current = self._index + 1
        self._progress_label.setText(f"{current} из {total}")
        self._progress_bar.setMaximum(total)
        self._progress_bar.setValue(current)
        reviewed = len(self._reviewed_ids)
        self._reviewed_label.setText(f"Проверен {reviewed} из {total}")

        self._clear_card_host()
        self._card_host.addWidget(self._build_card(self._matches[self._index]))
        self._card_scroll.verticalScrollBar().setValue(0)

    def _build_card(self, match: RoleMatch) -> QWidget:
        card = QFrame()
        card.setObjectName("RoleMatchCard")
        card.setStyleSheet(
            """
            QFrame#RoleMatchCard {
                background: #FFFFFF;
                border: 1px solid rgba(16,24,23,0.10);
                border-radius: 20px;
            }
            """
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)

        meta = QLabel(f"ФРАГМЕНТ СО СТРАНИЦЫ {match.fragment.page}")
        meta.setFont(app_font(11, QFont.Weight.DemiBold))
        meta.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        layout.addWidget(meta)

        text = QLabel(_function_title(match))
        text.setWordWrap(True)
        _keep_label_inside_width(text)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text.setFont(app_font(24, QFont.Weight.DemiBold))
        text.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        layout.addWidget(text)

        detail_lines = _function_detail_lines(match)
        if detail_lines:
            detail_title = QLabel("Детали функции")
            detail_title.setFont(app_font(14, QFont.Weight.DemiBold))
            detail_title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
            layout.addWidget(detail_title)
            for line in detail_lines:
                label = QLabel(line)
                label.setWordWrap(True)
                _keep_label_inside_width(label)
                label.setFont(app_font(13))
                label.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
                layout.addWidget(label)

        why_title = QLabel("Почему найдено")
        why_title.setFont(app_font(14, QFont.Weight.DemiBold))
        why_title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        layout.addWidget(why_title)

        check_icon = _load_temp_icon(_CHECK_ICON_PATH, 16)
        for reason in _reason_lines(match):
            row = QHBoxLayout()
            row.setSpacing(8)
            mark = QLabel()
            mark.setFixedSize(16, 16)
            mark.setStyleSheet("background: transparent;")
            if not check_icon.isNull():
                mark.setPixmap(check_icon)
            else:
                mark.setText("✓")
                mark.setFont(app_font(13, QFont.Weight.DemiBold))
                mark.setStyleSheet("color: #08745F; background: transparent;")
            label = QLabel(reason)
            label.setWordWrap(True)
            _keep_label_inside_width(label)
            label.setFont(app_font(13))
            label.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
            row.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(label, 1)
            wrap = QWidget()
            wrap.setLayout(row)
            layout.addWidget(wrap)

        self._add_evidence_cards(layout, match)

        confidence_label, confidence_color = _confidence_label(match.confidence)
        conf = QLabel(f"Уверенность: {confidence_label} · {match.confidence * 100:.0f}%")
        conf.setFont(app_font(13, QFont.Weight.DemiBold))
        conf.setStyleSheet(f"color: {confidence_color}; background: transparent;")
        layout.addWidget(conf)

        doc_link = QPushButton("Показать в документе")
        doc_link.setFlat(True)
        doc_link.setCursor(Qt.CursorShape.PointingHandCursor)
        doc_link.setFont(app_font(13, QFont.Weight.DemiBold))
        doc_link.setStyleSheet(
            """
            QPushButton {
                color: #06483D;
                background: transparent;
                border: none;
                text-decoration: underline;
                padding: 0;
                text-align: left;
            }
            QPushButton:hover { color: #08745F; }
            """
        )
        doc_link.clicked.connect(self._show_document_for_current)
        doc_row = QHBoxLayout()
        doc_row.addWidget(doc_link)
        doc_row.addStretch(1)
        layout.addLayout(doc_row)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        back = QPushButton("Назад")
        back.setFixedHeight(40)
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.setFont(app_font(13, QFont.Weight.DemiBold))
        back.setStyleSheet(_secondary_button_qss())
        back.clicked.connect(self._on_footer_back)
        actions.addWidget(back)
        actions.addStretch(1)

        reject = QPushButton("Не относится")
        reject.setFixedHeight(40)
        reject.setCursor(Qt.CursorShape.PointingHandCursor)
        reject.setFont(app_font(13, QFont.Weight.DemiBold))
        reject.setStyleSheet(_outline_button_qss())
        reject.clicked.connect(self._on_reject)
        actions.addWidget(reject)

        primary = QPushButton(self._primary_label())
        primary.setFixedHeight(40)
        primary.setCursor(Qt.CursorShape.PointingHandCursor)
        primary.setFont(app_font(13, QFont.Weight.DemiBold))
        primary.setStyleSheet(_primary_button_qss())
        primary.clicked.connect(self._on_primary_action)
        actions.addWidget(primary)
        layout.addLayout(actions)
        return card

    def _primary_label(self) -> str:
        if not self._matches:
            return "Завершить"
        if self._index >= len(self._matches) - 1:
            return "Завершить"
        if _is_high_confidence(self._matches[self._index]):
            return "Продолжить"
        return "Подтвердить"

    def _current_match(self) -> RoleMatch | None:
        if not self._matches or self._index >= len(self._matches):
            return None
        return self._matches[self._index]

    def _on_primary_action(self) -> None:
        if not self._matches:
            self.finish_requested.emit()
            return
        match = self._current_match()
        if match is None:
            self.finish_requested.emit()
            return
        if self._index >= len(self._matches) - 1:
            self._mark_reviewed(match.match_id)
            if _should_persist_accept(match):
                self.decision_requested.emit(match.match_id, "accepted")
            self.finish_requested.emit()
            return
        self._mark_reviewed(match.match_id)
        if _should_persist_accept(match):
            self.decision_requested.emit(match.match_id, "accepted")
        self._index += 1
        self._render()

    def _on_reject(self) -> None:
        match = self._current_match()
        if match is None:
            return
        self._mark_reviewed(match.match_id)
        if match.status != "rejected":
            self.decision_requested.emit(match.match_id, "rejected")
        if self._index >= len(self._matches) - 1:
            self.finish_requested.emit()
            return
        self._index += 1
        self._render()

    def _on_footer_back(self) -> None:
        if self._index > 0:
            self._index -= 1
            self._render()
            return
        self.back_requested.emit()

    def _go_previous(self) -> None:
        if self._index <= 0:
            return
        self._index -= 1
        self._render()

    def _mark_reviewed(self, match_id: str) -> None:
        self._reviewed_ids.add(match_id)

    def _build_document_view(self) -> None:
        while self._doc_content.count():
            item = self._doc_content.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._fragment_widgets.clear()

        if self._regulation is None:
            empty = QLabel("Документ недоступен")
            empty.setFont(app_font(14))
            empty.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
            self._doc_content.addWidget(empty)
            self._doc_content.addStretch(1)
            return

        self._doc_title.setText(self._regulation.file_name)
        pages: dict[int, list] = {}
        for fragment in self._regulation.fragments:
            pages.setdefault(fragment.page, []).append(fragment)
        for page in sorted(pages):
            page_widget, page_fragments = _document_page_widget(page, pages[page])
            self._fragment_widgets.update(page_fragments)
            self._doc_content.addWidget(page_widget)
        self._doc_content.addStretch(1)

    def _show_document_for_current(self) -> None:
        match = self._current_match()
        if match is None or self._regulation is None:
            return
        self._stack.setCurrentWidget(self._document)
        self._highlight_fragment(match.fragment_id)
        QTimer.singleShot(0, lambda: self._scroll_to_fragment(match.fragment_id))

    def _show_document_fragment(self, fragment_id: str) -> None:
        if not fragment_id or self._regulation is None:
            return
        self._stack.setCurrentWidget(self._document)
        self._highlight_fragment(fragment_id)
        QTimer.singleShot(0, lambda: self._scroll_to_fragment(fragment_id))

    def _add_evidence_cards(self, layout: QVBoxLayout, match: RoleMatch) -> None:
        items = _proof_items(match, self._regulation)
        if not items:
            return
        evidence_title = QLabel("Доказательства из документа")
        evidence_title.setFont(app_font(16, QFont.Weight.DemiBold))
        evidence_title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        layout.addWidget(evidence_title)

        for item in items:
            card = QFrame()
            card.setObjectName("EvidenceCard")
            card.setStyleSheet(
                """
                QFrame#EvidenceCard {
                    background: #FFFFFF;
                    border: 1px solid rgba(16,24,23,0.10);
                    border-radius: 14px;
                }
                """
            )
            row = QHBoxLayout(card)
            row.setContentsMargins(14, 12, 14, 12)
            row.setSpacing(12)

            icon = _document_icon_label()
            row.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)

            body = QVBoxLayout()
            body.setSpacing(5)
            source = QLabel(item["source"])
            source.setWordWrap(True)
            _keep_label_inside_width(source)
            source.setFont(app_font(12, QFont.Weight.DemiBold))
            source.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
            body.addWidget(source)

            quote = QLabel(f"«{item['quote']}»")
            quote.setWordWrap(True)
            _keep_label_inside_width(quote)
            quote.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            quote.setFont(app_font(13))
            quote.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
            body.addWidget(quote)

            if item.get("note"):
                note = QLabel(item["note"])
                note.setWordWrap(True)
                _keep_label_inside_width(note)
                note.setFont(app_font(11))
                note.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
                body.addWidget(note)
            row.addLayout(body, 1)

            side = QVBoxLayout()
            side.setSpacing(8)
            badge = QLabel(item["badge"])
            badge.setFont(app_font(11, QFont.Weight.DemiBold))
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setStyleSheet(_evidence_badge_qss(item["kind"]))
            side.addWidget(badge)

            button = QPushButton("Открыть фрагмент")
            button.setFixedHeight(32)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFont(app_font(11, QFont.Weight.DemiBold))
            button.setStyleSheet(_small_outline_button_qss())
            fragment_id = item["fragment_id"]
            button.clicked.connect(lambda _checked=False, fid=fragment_id: self._show_document_fragment(fid))
            side.addWidget(button)
            side.addStretch(1)
            row.addLayout(side)
            layout.addWidget(card)

    def _show_wizard(self) -> None:
        self._clear_highlights()
        self._stack.setCurrentWidget(self._wizard)

    def _scroll_to_fragment(self, fragment_id: str) -> None:
        widget = self._fragment_widgets.get(fragment_id)
        if widget is None:
            return
        self._doc_scroll.ensureWidgetVisible(widget, 80, 80)

    def _highlight_fragment(self, fragment_id: str) -> None:
        self._clear_highlights()
        widget = self._fragment_widgets.get(fragment_id)
        if widget is None:
            return
        widget.setStyleSheet(
            """
            QFrame#DocumentFragment {
                background: rgba(8,116,95,0.12);
                border: 2px solid #08745F;
                border-radius: 10px;
            }
            """
        )

    def _clear_highlights(self) -> None:
        for widget in self._fragment_widgets.values():
            widget.setStyleSheet(
                """
                QFrame#DocumentFragment {
                    background: transparent;
                    border: 1px solid transparent;
                    border-radius: 10px;
                }
                """
            )

    def _clear_card_host(self) -> None:
        while self._card_host.count():
            item = self._card_host.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()


def _ordered_matches(matches: list[RoleMatch]) -> list[RoleMatch]:
    visible = [match for match in matches if match.status != "rejected"]
    return sorted(visible, key=lambda item: (item.fragment.page, -item.confidence, item.match_id))


def _document_page_widget(page: int, fragments: list[RegulationFragment]) -> tuple[QWidget, dict[str, QWidget]]:
    card = QFrame()
    card.setObjectName("DocumentPage")
    card.setStyleSheet(
        """
        QFrame#DocumentPage {
            background: #FFFFFF;
            border: 1px solid rgba(16,24,23,0.10);
            border-radius: 18px;
        }
        """
    )
    layout = QVBoxLayout(card)
    layout.setContentsMargins(28, 24, 28, 28)
    layout.setSpacing(8)
    title = QLabel(f"Страница {page}")
    title.setFont(app_font(13, QFont.Weight.DemiBold))
    title.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
    layout.addWidget(title)
    widgets: dict[str, QWidget] = {}
    for fragment in fragments:
        widget = _document_fragment_widget(fragment)
        widgets[fragment.fragment_id] = widget
        layout.addWidget(widget)
    return card, widgets


def _document_fragment_widget(fragment: RegulationFragment) -> QWidget:
    frame = QFrame()
    frame.setObjectName("DocumentFragment")
    frame.setProperty("fragment_id", fragment.fragment_id)
    frame.setStyleSheet(
        """
        QFrame#DocumentFragment {
            background: transparent;
            border: 1px solid transparent;
            border-radius: 10px;
        }
        """
    )
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(10, 6, 10, 6)
    layout.setSpacing(4)
    if fragment.kind == "table" and fragment.table is not None:
        layout.addWidget(_table_widget(fragment))
    else:
        text = QLabel(fragment.text or "")
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text.setFont(app_font(13))
        text.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        layout.addWidget(text)
    return frame


def _needs_user_review(match: RoleMatch) -> bool:
    return match.requires_confirmation or match.status in {"pending", "probable"}


def _is_high_confidence(match: RoleMatch) -> bool:
    return match.confidence >= _HIGH_CONFIDENCE


def _should_persist_accept(match: RoleMatch) -> bool:
    if match.status == "accepted" and not match.requires_confirmation:
        return False
    return match.status != "accepted"


def _fragment_preview_text(match: RoleMatch, *, full: bool = False) -> str:
    fragment = match.fragment
    if fragment.cells:
        text = ". ".join(f"{key}: {value}" for key, value in fragment.cells.items() if value)
    else:
        text = fragment.text or "Пустой фрагмент"
    if full or len(text) <= 180:
        return text
    return text[:177].rstrip() + "…"


def _function_title(match: RoleMatch) -> str:
    function = match.function
    if function is not None:
        explicit = (getattr(function, "title", "") or "").strip()
        if explicit:
            cleaned = re.split(r"\s*→\s*", explicit, maxsplit=1)[0].strip()
            title = _as_title(cleaned, max_chars=_MAX_FUNCTION_TITLE_CHARS)
            if title and not _has_dangling_end(title):
                return title
        title_parts = []
        if function.action:
            title_parts.append(function.action[:1].upper() + function.action[1:])
        if function.object:
            obj = function.object.strip()
            # Не дублировать title/action в object.
            if function.action and obj.casefold().startswith(function.action.casefold()):
                obj = obj[len(function.action) :].strip(" —-:")
            if obj and obj.casefold() != (function.action or "").casefold():
                title_parts.append(obj)
        # recipient показываем в деталях, не в заголовке
        title = " ".join(part for part in title_parts if part).strip()
        if title and not _has_dangling_end(title):
            return _as_title(title, max_chars=_MAX_FUNCTION_TITLE_CHARS)
        source_title = _title_from_source_text(match)
        if source_title:
            return source_title
    full_text = _fragment_preview_text(match, full=True)
    contextual_title = _title_from_role_context(full_text, _role_terms(match))
    if contextual_title:
        return contextual_title

    role_title = _title_from_role_line(full_text, _role_terms(match))
    if role_title:
        return role_title

    fragment_lines = _meaningful_fragment_lines(match)
    for candidate in fragment_lines:
        if _looks_like_function_line(candidate):
            title = _as_title(candidate)
            if title:
                return title

    candidates: list[str] = list(fragment_lines)
    for signal in match.signals:
        quote = _clean_line(signal.quote)
        if quote and not _is_service_line(quote) and _looks_like_function_line(quote):
            candidates.append(quote)

    for candidate in candidates:
        title = _as_title(candidate)
        if title:
            return title
    return _fragment_preview_text(match, full=False)


def _role_terms(match: RoleMatch) -> list[str]:
    terms: list[str] = []
    for signal in match.signals:
        for source in (signal.quote, signal.explanation):
            text = _clean_line(source)
            if not text:
                continue
            if ":" in text:
                text = text.rsplit(":", 1)[-1].strip()
            if 4 <= len(text) <= 80 and not _is_service_line(text) and not _is_context_term(text):
                terms.append(text)
    fallback_terms = (
        "промпт-инженер",
        "промпт-инженеров",
    )
    terms.extend(fallback_terms)
    unique: list[str] = []
    for term in terms:
        normalized = _normalize_text(term)
        if normalized and normalized not in {_normalize_text(item) for item in unique}:
            unique.append(term)
    return unique


def _title_from_role_context(text: str, role_terms: list[str]) -> str:
    sentences = _split_sentences(text)
    for index, sentence in enumerate(sentences):
        if "включая" not in sentence.casefold():
            continue
        nearby = " ".join(sentences[max(0, index - 1) : min(len(sentences), index + 2)])
        if role_terms and not _contains_any_term(nearby, role_terms):
            continue
        extracted = _extract_including_title(sentence)
        if extracted:
            return extracted
    return ""


def _title_from_role_line(text: str, role_terms: list[str]) -> str:
    if not role_terms:
        return ""
    for line in _meaningful_lines_from_text(text):
        if not _contains_any_term(line, role_terms):
            continue
        candidate = _text_after_role_term(line, role_terms) or _remove_role_terms(line, role_terms)
        if not _looks_like_function_line(candidate):
            continue
        title = _as_title(candidate)
        if title:
            return title
    return ""


def _split_sentences(text: str) -> list[str]:
    normalized = " ".join(text.replace("\n", " ").split())
    if not normalized:
        return []
    sentences: list[str] = []
    start = 0
    for idx, char in enumerate(normalized):
        if char not in ".!?":
            continue
        sentence = normalized[start : idx + 1].strip()
        if sentence:
            sentences.append(sentence)
        start = idx + 1
    tail = normalized[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def _contains_any_term(text: str, terms: list[str]) -> bool:
    normalized = _normalize_text(text)
    return any(_normalize_text(term) in normalized for term in terms if _normalize_text(term))


def _remove_role_terms(text: str, role_terms: list[str]) -> str:
    cleaned = text
    for term in sorted(role_terms, key=len, reverse=True):
        normalized_term = _normalize_text(term)
        if not normalized_term:
            continue
        words = cleaned.split()
        kept = [word for word in words if normalized_term not in _normalize_text(word)]
        cleaned = " ".join(kept)
    return _clean_line(cleaned.strip(" :—-–,;"))


def _text_after_role_term(text: str, role_terms: list[str]) -> str:
    normalized_text = _normalize_text(text)
    for term in sorted(role_terms, key=len, reverse=True):
        normalized_term = _normalize_text(term)
        if not normalized_term:
            continue
        idx = normalized_text.find(normalized_term)
        if idx < 0:
            continue
        # Use the original text length as an approximation; terms are short and mostly ASCII hyphen-safe.
        return _clean_line(text[idx + len(term) :].strip(" :—-–,;"))
    return ""


def _extract_including_title(sentence: str) -> str:
    normalized = sentence.casefold()
    idx = normalized.find("включая")
    if idx < 0:
        return ""
    tail = sentence[idx + len("включая") :].strip(" ,.;:-")
    if not tail or _is_scope_line(tail):
        return ""
    tail = _normalize_function_noun(tail)
    return _as_title(tail)


def _normalize_function_noun(text: str) -> str:
    replacements = {
        "разработку": "Разработка",
        "настройку": "Настройка",
        "организацию": "Организация",
        "регистрацию": "Регистрация",
        "передачу": "Передача",
        "приёмку": "Приёмка",
        "приемку": "Приемка",
        "подготовку": "Подготовка",
        "проверку": "Проверка",
        "эксплуатацию": "Эксплуатация",
        "сопровождение": "Сопровождение",
    }
    parts = text.split(maxsplit=1)
    if not parts:
        return text
    first = parts[0].casefold()
    replacement = replacements.get(first)
    if not replacement:
        return text[:1].upper() + text[1:]
    suffix = f" {parts[1]}" if len(parts) > 1 else ""
    return replacement + suffix


def _meaningful_fragment_lines(match: RoleMatch) -> list[str]:
    text = _fragment_preview_text(match, full=True)
    return _meaningful_lines_from_text(text)


def _meaningful_lines_from_text(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace(";", "\n").splitlines():
        line = _clean_line(raw)
        if not line or _is_service_line(line):
            continue
        lines.append(line)
    return lines


def _title_from_source_text(match: RoleMatch) -> str:
    function = match.function
    candidates: list[str] = []
    if function is not None:
        candidates.extend(_clean_line(item.quote) for item in function.evidence if _clean_line(item.quote))
    candidates.extend(_meaningful_fragment_lines(match))
    for candidate in candidates:
        title = _as_title(candidate, max_chars=_MAX_FUNCTION_TITLE_CHARS)
        if title and not _has_dangling_end(title):
            return title
    return ""


def _has_dangling_end(text: str) -> bool:
    words = _clean_line(text).rstrip(".,;:—-–").casefold().split()
    if not words:
        return False
    return words[-1] in {
        "в",
        "во",
        "на",
        "по",
        "для",
        "с",
        "со",
        "к",
        "ко",
        "от",
        "до",
        "из",
        "за",
        "при",
        "о",
        "об",
        "и",
        "или",
        "что",
    }


def _as_title(text: str, *, max_chars: int = _MAX_FUNCTION_TITLE_CHARS) -> str:
    text = _clean_line(text)
    if not text or _is_service_line(text):
        return ""
    text = _strip_leading_number(text)
    parts = [part.strip() for part in text.split(".") if part.strip()]
    if parts:
        text = parts[0]
    if max_chars > 0 and len(text) > max_chars:
        text = text[: max_chars - 3].rstrip(" ,;:-") + "..."
    return text


def _clean_line(text: str) -> str:
    return " ".join(text.replace("\t", " ").split()).strip(" -•·")


def _normalize_text(text: str) -> str:
    normalized = _clean_line(text).replace("‑", "-").replace("–", "-")
    return normalized.replace("- ", "-").casefold()


def _strip_leading_number(text: str) -> str:
    idx = 0
    while idx < len(text) and (text[idx].isdigit() or text[idx] == "."):
        idx += 1
    if idx > 0 and idx < len(text) and text[idx].isspace():
        return text[idx:].strip()
    return text


def _looks_like_function_line(text: str) -> bool:
    normalized = text.casefold()
    action_markers = (
        "разрабаты",
        "оптимиз",
        "соглас",
        "обеспеч",
        "контрол",
        "выполн",
        "формир",
        "созда",
        "вед",
        "участв",
        "анализ",
        "провер",
        "отвеч",
        "подготавли",
        "настраива",
        "сопровожд",
        "внедря",
        "организ",
        "переда",
        "получа",
        "использ",
    )
    return any(marker in normalized for marker in action_markers)


def _is_service_line(text: str) -> bool:
    normalized = text.casefold()
    if len(text) < 4:
        return True
    if _is_scope_line(text):
        return True
    service_markers = (
        "регламент",
        "версия",
        "лист ",
        "сокращения",
        "термины",
        "общие положения",
        "рг-",
        "рси",
    )
    if any(marker in normalized for marker in service_markers):
        return True
    letters = [ch for ch in text if ch.isalpha()]
    if letters and sum(ch.isupper() for ch in letters) / len(letters) > 0.85:
        return True
    return False


def _is_context_term(text: str) -> bool:
    normalized = _normalize_text(text)
    context_terms = {
        "1с",
        "crm",
        "erp",
        "sap",
        "акт",
        "заявка",
        "договор",
        "счет",
        "счёт",
        "карточка сделки",
        "коммерческое предложение",
    }
    return normalized in context_terms


def _is_scope_line(text: str) -> bool:
    normalized = _normalize_text(text)
    scope_markers = (
        "требования регламента распространяются",
        "участвующие в",
        "регламент применяется",
        "настоящий регламент устанавливает",
        "назначение и область применения",
    )
    return any(marker in normalized for marker in scope_markers)


def _proof_items(
    match: RoleMatch,
    regulation: RegulationParseResult | None,
) -> list[dict[str, str]]:
    by_id = {fragment.fragment_id: fragment for fragment in (regulation.fragments if regulation else [])}
    items: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    function = match.function

    if function is not None:
        for evidence in function.evidence:
            quote = _clean_line(evidence.quote)
            if not quote or _is_weak_evidence_quote(quote):
                continue
            item = _proof_item(
                fragment_id=evidence.fragment_id or match.fragment_id,
                quote=quote,
                relation="direct_role_mention",
                note="Цитата из исходного документа",
                by_id=by_id,
            )
            key = (item["fragment_id"], item["quote"])
            if key not in seen:
                items.append(item)
                seen.add(key)

        for block in function.proof_chain:
            fragment_id = block.block_id or match.fragment_id
            quote = _clean_line(block.text or block.evidence)
            if not quote or _is_weak_evidence_quote(quote):
                quote = _fragment_text_by_id(fragment_id, by_id)
            if not quote:
                continue
            item = _proof_item(
                fragment_id=fragment_id,
                quote=quote,
                relation=block.relation,
                note=block.evidence,
                by_id=by_id,
            )
            key = (item["fragment_id"], item["quote"])
            if key not in seen:
                items.append(item)
                seen.add(key)

    if not items:
        for signal in match.signals:
            quote = _clean_line(signal.quote)
            if not quote or _is_weak_evidence_quote(quote):
                continue
            item = _proof_item(
                fragment_id=signal.fragment_id if hasattr(signal, "fragment_id") else match.fragment_id,
                quote=quote,
                relation=signal.match_type,
                note=signal.explanation,
                by_id=by_id,
            )
            key = (item["fragment_id"], item["quote"])
            if key not in seen:
                items.append(item)
                seen.add(key)

    if not items:
        quote = _fragment_preview_text(match, full=True)
        items.append(
            _proof_item(
                fragment_id=match.fragment_id,
                quote=quote,
                relation="graph_relation",
                note=match.explanation,
                by_id=by_id,
            )
        )

    return items[:5]


def _proof_item(
    *,
    fragment_id: str,
    quote: str,
    relation: str,
    note: str,
    by_id: dict[str, object],
) -> dict[str, str]:
    fragment = by_id.get(fragment_id)
    page = getattr(fragment, "page", None)
    section = getattr(fragment, "section", "") if fragment is not None else ""
    source_parts = []
    if section:
        source_parts.append(str(section))
    if page:
        source_parts.append(f"стр. {page}")
    source = " · ".join(source_parts) if source_parts else fragment_id
    badge, kind = _evidence_badge(relation)
    return {
        "fragment_id": fragment_id,
        "source": source,
        "quote": quote[:700],
        "badge": badge,
        "kind": kind,
        "note": _clean_line(note)[:300],
    }


def _fragment_text_by_id(fragment_id: str, by_id: dict[str, object]) -> str:
    fragment = by_id.get(fragment_id)
    if fragment is None:
        return ""
    cells = getattr(fragment, "cells", None) or {}
    if cells:
        return ". ".join(f"{key}: {value}" for key, value in cells.items() if value)
    return _clean_line(str(getattr(fragment, "text", "") or ""))


def _is_weak_evidence_quote(quote: str) -> bool:
    normalized = quote.casefold()
    weak = (
        "предыдущий смысловой блок",
        "следующий смысловой блок",
        "previous_block",
        "next_block",
        "parent_section",
    )
    return any(marker in normalized for marker in weak)


def _evidence_badge(relation: str) -> tuple[str, str]:
    relation = (relation or "").strip()
    if relation in {"direct_role_mention", "assigned_action"}:
        return "Прямое указание", "direct"
    if relation in {"actor_inheritance", "definition_of", "definition_link"}:
        return "Связь исполнителя", "actor"
    if relation in {"condition_for", "exception_for"}:
        return "Условие работы", "condition"
    if relation in {"previous_block", "next_block", "input_for", "same_process"}:
        return "Зависимость", "dependency"
    return "Связь графа", "graph"


def _evidence_badge_qss(kind: str) -> str:
    colors = {
        "direct": ("#E8F7F0", "#08745F"),
        "actor": ("#EEF4FF", "#2459A8"),
        "condition": ("#FFF4E5", "#B26A00"),
        "dependency": ("#EEF4FF", "#2459A8"),
        "graph": ("#F3F5F4", "#50605B"),
    }
    bg, fg = colors.get(kind, colors["graph"])
    return f"""
        QLabel {{
            color: {fg};
            background: {bg};
            border-radius: 10px;
            padding: 6px 10px;
        }}
    """


def _small_outline_button_qss() -> str:
    return """
        QPushButton {
            color: #06483D;
            background: #FFFFFF;
            border: 1px solid rgba(6,72,61,0.20);
            border-radius: 9px;
            padding: 0 10px;
        }
        QPushButton:hover {
            background: #F1F8F5;
            border-color: rgba(6,72,61,0.35);
        }
    """


def _function_detail_lines(match: RoleMatch) -> list[str]:
    function = match.function
    if function is None:
        return []
    lines: list[str] = []
    actor = function.actor.canonical_position or function.actor.text
    if actor:
        source = f" (из блока {function.actor.source_block_id})" if function.actor.source_block_id else ""
        lines.append(f"Исполнитель: {actor}{source}")
    if function.conditions:
        lines.append("Условия: " + "; ".join(function.conditions[:2]))
    if function.dependencies:
        deps = [
            dep.description or dep.block_id
            for dep in function.dependencies[:2]
            if dep.description or dep.block_id
        ]
        if deps:
            lines.append("Зависимости: " + "; ".join(deps))
    if function.explanation:
        lines.append(function.explanation)
    return lines[:5]


def _evidence_lines(match: RoleMatch) -> list[str]:
    function = match.function
    lines: list[str] = []
    if function is not None:
        for evidence in function.evidence[:4]:
            quote = _clean_line(evidence.quote)
            if quote:
                lines.append(f"{evidence.fragment_id}: «{quote}»")
        for block in function.proof_chain[:3]:
            if block.evidence:
                lines.append(f"{block.block_id}: {block.evidence}")
    if not lines:
        for signal in match.signals[:3]:
            quote = _clean_line(signal.quote)
            if quote:
                lines.append(f"{match.fragment_id}: «{quote}»")
    unique: list[str] = []
    for line in lines:
        if line not in unique:
            unique.append(line)
    return unique[:5]


def _reason_lines(match: RoleMatch) -> list[str]:
    lines: list[str] = []
    for signal in match.signals:
        text = signal.explanation.strip() or _MATCH_TYPE_LABELS.get(signal.match_type, signal.match_type)
        if text and text not in lines:
            lines.append(text)
    if not lines and match.explanation.strip():
        lines.append(match.explanation.strip())
    if not lines:
        lines.append("Фрагмент связан с выбранной должностью")
    return lines[:4]


def _confidence_label(confidence: float) -> tuple[str, str]:
    if confidence >= _HIGH_CONFIDENCE:
        return "высокая", "#08745F"
    if confidence >= 0.65:
        return "средняя", "#9A5B00"
    return "низкая", "#B44D4D"


def _load_temp_icon(path: Path, size: int) -> QPixmap:
    """Load PNG and punch out near-black background for light UI surfaces."""
    if not path.exists():
        return QPixmap()
    src = QImage(str(path))
    if src.isNull():
        return QPixmap()
    img = src.convertToFormat(QImage.Format.Format_ARGB32)
    for y in range(img.height()):
        for x in range(img.width()):
            c = QColor.fromRgba(img.pixel(x, y))
            if c.red() < 48 and c.green() < 48 and c.blue() < 48:
                c.setAlpha(0)
                img.setPixelColor(x, y, c)
    return QPixmap.fromImage(img).scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _icon_status_badge(bg: str, fg: str, text: str, icon: QPixmap) -> QWidget:
    badge = QFrame()
    badge.setObjectName("StatusBadge")
    badge.setStyleSheet(
        f"""
        QFrame#StatusBadge {{
            background: {bg};
            border-radius: 14px;
        }}
        """
    )
    layout = QHBoxLayout(badge)
    layout.setContentsMargins(10, 6, 12, 6)
    layout.setSpacing(6)

    icon_label = QLabel()
    icon_label.setObjectName("StatusBadgeIcon")
    icon_label.setFixedSize(16, 16)
    icon_label.setStyleSheet("background: transparent;")
    if not icon.isNull():
        icon_label.setPixmap(icon)
    layout.addWidget(icon_label)

    text_label = QLabel(text)
    text_label.setObjectName("StatusBadgeText")
    text_label.setFont(app_font(12, QFont.Weight.DemiBold))
    text_label.setStyleSheet(f"color: {fg}; background: transparent;")
    layout.addWidget(text_label)
    return badge


def _set_badge_text(badge: QWidget, text: str) -> None:
    text_label = badge.findChild(QLabel, "StatusBadgeText")
    if text_label is not None:
        text_label.setText(text)


def _empty_card() -> QWidget:
    card = QFrame()
    card.setStyleSheet(
        """
        QFrame {
            background: #FFFFFF;
            border: 1px solid rgba(16,24,23,0.10);
            border-radius: 20px;
        }
        """
    )
    layout = QVBoxLayout(card)
    layout.setContentsMargins(24, 24, 24, 24)
    label = QLabel("Связанные с должностью фрагменты не найдены.")
    label.setWordWrap(True)
    label.setFont(app_font(15))
    label.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
    layout.addWidget(label)
    return card


def _document_icon_label() -> QLabel:
    icon = QLabel()
    icon.setFixedSize(42, 42)
    icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
    icon.setStyleSheet(
        """
        QLabel {
            color: #06483D;
            background: #EEF8F4;
            border-radius: 10px;
        }
        """
    )
    pixmap = icon.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon).pixmap(22, 22)
    icon.setPixmap(pixmap)
    return icon


def _keep_label_inside_width(label: QLabel) -> None:
    label.setText(_soft_wrap_text(label.text()))
    label.setMinimumWidth(0)
    label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)


def _soft_wrap_text(text: str) -> str:
    def wrap_token(match: re.Match[str]) -> str:
        token = match.group(0)
        return re.sub(r"([\\/_:.-])", lambda sep: f"{sep.group(1)}\u200b", token)

    return re.sub(r"\S{28,}", wrap_token, text)


def _primary_button_qss() -> str:
    return """
    QPushButton {
        background: #06483D;
        color: #F7FBFA;
        border: none;
        border-radius: 20px;
        padding: 0 22px;
    }
    QPushButton:hover { background: #08745F; }
    """


def _secondary_button_qss() -> str:
    return """
    QPushButton {
        background: #EEF7F3;
        color: #06483D;
        border: none;
        border-radius: 20px;
        padding: 0 22px;
    }
    QPushButton:hover { background: #DFF5EC; }
    """


def _outline_button_qss() -> str:
    return """
    QPushButton {
        background: #FFFFFF;
        color: #101817;
        border: 1px solid rgba(16,24,23,0.18);
        border-radius: 20px;
        padding: 0 18px;
    }
    QPushButton:hover { background: #F7FAF9; }
    """
