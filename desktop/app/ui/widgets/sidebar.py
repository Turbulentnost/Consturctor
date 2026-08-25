from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Thread

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.chat.models import ChatThread
from app.ui.theme import (
    COLOR_ACTIVE_BG,
    COLOR_ACTIVE_FG,
    ICON_CHAT,
    MINT,
    MINT_SOFT,
    NAV_ITEM_HEIGHT,
    NAV_ITEM_RADIUS,
    SIDEBAR_BOTTOM,
    SIDEBAR_COLLAPSED,
    SIDEBAR_EXPANDED,
    SIDEBAR_MIDDLE,
    SIDEBAR_PADDING_X,
    SIDEBAR_TOP,
    TEXT_LIGHT,
    TEXT_MUTED,
    app_font,
    circular_pixmap,
    nerd_font,
)
from app.ui.widgets.fio_suggest import FioSuggestEdit

SIDEBAR_GREEN = SIDEBAR_MIDDLE
INACTIVE_PILL = QColor(91, 160, 143, 72)
INACTIVE_HOVER = QColor(112, 190, 169, 96)
INACTIVE_PRESSED = QColor(55, 120, 103, 120)
ITEM_GAP = 8
ICON_SIZE = 20
# Extra right inset so the white active pill does not visually bleed into content.
SIDEBAR_PAD_LEFT = SIDEBAR_PADDING_X
SIDEBAR_PAD_RIGHT = 28
_TEMP = Path(__file__).resolve().parents[1] / "temp"

# Filename prefixes: серый* = active/pressed, белый* = inactive.
_ICON_STEMS = {
    "plus": "плюс",
    "home": "главная",
    "kpi": "кпи",
    "dashboard": "дашборд",
    "files": "files",
}


def dialog_ids_match(thread_id: str, peer_id: str, active_id: str, active_peer: str = "") -> bool:
    left = {item for item in (thread_id, peer_id) if item}
    right = {item for item in (active_id, active_peer) if item}
    return bool(left & right)


def short_fio(fio: str) -> str:
    parts = [part for part in (fio or "").replace(".", " ").split() if part]
    if not parts:
        return ""
    last = parts[0]
    initials = " ".join(f"{part[0].upper()}." for part in parts[1:])
    return f"{last} {initials}".strip()


def _initials(fio: str) -> str:
    parts = [part for part in (fio or "").replace(".", " ").split() if part]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:1].upper()
    return (parts[0][:1] + parts[1][:1]).upper()


def _tint_pixmap(src: QPixmap, color: QColor) -> QPixmap:
    if src.isNull():
        return QPixmap()
    out = QPixmap(src.size())
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    p.drawPixmap(0, 0, src)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(out.rect(), color)
    p.end()
    return out


def _load_nav_icon(filename: str) -> QPixmap:
    path = _TEMP / filename
    if not path.exists() or path.stat().st_size <= 0:
        return QPixmap()
    pm = QPixmap(str(path))
    if pm.isNull():
        return QPixmap()
    return pm.scaled(
        ICON_SIZE,
        ICON_SIZE,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _load_icon_pair(kind: str) -> tuple[QPixmap, QPixmap]:
    """Return (inactive/белый*, active/серый*)."""
    if kind == "files":
        # Single source files.png is grey; tint white for the inactive state.
        src = _load_nav_icon("files.png")
        if src.isNull():
            return QPixmap(), QPixmap()
        return _tint_pixmap(src, QColor("#FFFFFF")), src
    stem = _ICON_STEMS.get(kind)
    if not stem:
        return QPixmap(), QPixmap()
    white_name = f"белый{stem}.png"
    grey_name = f"серый{stem}.png"
    # Active / pressed → серый*
    active = _load_nav_icon(grey_name)
    # Inactive → белый* (tint to pure white: source assets are mid-grey)
    white_src = _load_nav_icon(white_name)
    shape = white_src if not white_src.isNull() else active
    inactive = _tint_pixmap(shape, QColor("#FFFFFF")) if not shape.isNull() else QPixmap()
    return inactive, active


@dataclass(frozen=True)
class NavItem:
    key: str
    label: str
    icon: str


class NavigationItem(QWidget):
    clicked = Signal(str)

    def __init__(
        self,
        item: NavItem,
        *,
        icon_inactive: QPixmap,
        icon_active: QPixmap,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.item = item
        self._icon_inactive = icon_inactive
        self._icon_active = icon_active
        self._active = False
        self._hover = False
        self._pressed = False
        self._collapsed = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(NAV_ITEM_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setToolTip(item.label)

    def set_active(self, active: bool) -> None:
        if self._active == active:
            return
        self._active = active
        self.update()

    def set_collapsed(self, collapsed: bool) -> None:
        if self._collapsed == collapsed:
            return
        self._collapsed = collapsed
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self._pressed = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._pressed and event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit(self.item.key)
        self._pressed = False
        self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect.adjusted(0, 1, 0, -1), NAV_ITEM_RADIUS, NAV_ITEM_RADIUS)

        if self._active:
            fill = COLOR_ACTIVE_BG
            text = COLOR_ACTIVE_FG
        elif self._pressed:
            fill = INACTIVE_PRESSED
            text = TEXT_LIGHT
        elif self._hover:
            fill = INACTIVE_HOVER
            text = TEXT_LIGHT
        else:
            fill = INACTIVE_PILL
            text = TEXT_MUTED

        p.fillPath(path, fill)
        icon_x = rect.center().x() if self._collapsed else rect.left() + 18
        self._draw_icon(p, icon_x, rect.center().y(), text)
        if not self._collapsed:
            # Integer text box keeps glyphs on the pixel grid (less blur than QRectF).
            p.setPen(text)
            p.setFont(app_font(14, QFont.Weight.Medium if not self._active else QFont.Weight.DemiBold))
            text_rect = self.rect().adjusted(44, 0, -12, 0)
            p.drawText(
                text_rect,
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                self.item.label,
            )
        p.end()

    def _draw_icon(self, p: QPainter, cx: float, cy: float, color: QColor) -> None:
        # Pressed or selected → серый*; otherwise → белый*
        use_active = self._active or self._pressed
        icon = self._icon_active if use_active else self._icon_inactive
        if icon.isNull():
            p.setPen(color)
            p.setFont(nerd_font(16))
            p.drawText(
                QRectF(cx - 12, cy - 12, 24, 24),
                int(Qt.AlignmentFlag.AlignCenter),
                ICON_CHAT,
            )
            return
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        x = int(cx - icon.width() / 2)
        y = int(cy - icon.height() / 2)
        p.drawPixmap(x, y, icon)


class SidebarSearch(QWidget):
    expand_requested = Signal()

    def __init__(
        self,
        fetch_suggestions: Callable[[str], list[str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._collapsed = False
        self._hover = False
        self.setFixedHeight(NAV_ITEM_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.IBeamCursor)

        icon = _load_nav_icon("search.png")
        self._icon = _tint_pixmap(icon, QColor("#FFFFFF")) if not icon.isNull() else QPixmap()
        self._icon_label = QLabel()
        self._icon_label.setFixedSize(ICON_SIZE, ICON_SIZE)
        self._icon_label.setStyleSheet("background: transparent;")
        if not self._icon.isNull():
            self._icon_label.setPixmap(self._icon)

        self.edit = FioSuggestEdit(
            fetch_suggestions,
            self,
            popup_min_width=0,
            open_on_focus=False,
        )
        self.edit.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.edit.setPlaceholderText("ФИО")
        self.edit.setFont(app_font(13))
        self.edit.setStyleSheet(
            """
            QLineEdit {
                background: transparent;
                border: none;
                color: #EAF7F3;
                padding: 0 4px 0 0;
                selection-background-color: #0a4a38;
            }
            QLineEdit::placeholder {
                color: #A8C8BF;
            }
            """
        )
        self.edit.set_popup_anchor(self)

        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(16, 0, 12, 0)
        self._row.setSpacing(10)
        self._row.addWidget(self._icon_label, 0, Qt.AlignmentFlag.AlignVCenter)
        self._row.addWidget(self.edit, 1)

    def set_collapsed(self, collapsed: bool) -> None:
        if self._collapsed == collapsed:
            return
        self._collapsed = collapsed
        self.edit.setVisible(not collapsed)
        if collapsed:
            self.edit.hide_suggestions()
            self._row.setContentsMargins(0, 0, 0, 0)
            self._row.setAlignment(self._icon_label, Qt.AlignmentFlag.AlignCenter)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self._row.setContentsMargins(16, 0, 12, 0)
            self._row.setAlignment(self._icon_label, Qt.AlignmentFlag.AlignVCenter)
            self.setCursor(Qt.CursorShape.IBeamCursor)
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            if self._collapsed:
                self.expand_requested.emit()
            else:
                self.edit.setFocus(Qt.FocusReason.MouseFocusReason)
                self.edit.open_suggestions()
        super().mousePressEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect.adjusted(0, 1, 0, -1), NAV_ITEM_RADIUS, NAV_ITEM_RADIUS)
        fill = INACTIVE_HOVER if self._hover or self.edit.hasFocus() else INACTIVE_PILL
        p.fillPath(path, fill)
        p.end()


class ChatPeerItem(QWidget):
    clicked = Signal(str)

    def __init__(
        self,
        thread_id: str,
        title: str,
        *,
        peer_id: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.thread_id = thread_id
        self.peer_id = peer_id
        self._title = title
        self._short = short_fio(title) or title
        self._initials = _initials(title)
        self._pixmap = QPixmap()
        self._active = False
        self._hover = False
        self._pressed = False
        self._collapsed = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(NAV_ITEM_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setToolTip(title)

    def bind(self, thread_id: str, title: str, *, peer_id: str = "") -> None:
        self.thread_id = thread_id
        self.peer_id = peer_id
        if title != self._title:
            self._title = title
            self._short = short_fio(title) or title
            self._initials = _initials(title)
            self.setToolTip(title)
            if self._pixmap.isNull():
                self.update()
        self.update()

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = circular_pixmap(pixmap, 28) if not pixmap.isNull() else QPixmap()
        self.update()

    def set_active(self, active: bool) -> None:
        if self._active == active:
            return
        self._active = active
        self.update()

    def set_collapsed(self, collapsed: bool) -> None:
        if self._collapsed == collapsed:
            return
        self._collapsed = collapsed
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self._pressed = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._pressed and event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit(self.thread_id)
        self._pressed = False
        self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect.adjusted(0, 1, 0, -1), NAV_ITEM_RADIUS, NAV_ITEM_RADIUS)

        if self._active:
            fill = COLOR_ACTIVE_BG
            text = COLOR_ACTIVE_FG
            avatar_bg = QColor("#0A4A38")
            avatar_fg = QColor("#FFFFFF")
        elif self._pressed:
            fill = INACTIVE_PRESSED
            text = TEXT_LIGHT
            avatar_bg = QColor(98, 224, 190, 70)
            avatar_fg = TEXT_LIGHT
        elif self._hover:
            fill = INACTIVE_HOVER
            text = TEXT_LIGHT
            avatar_bg = QColor(98, 224, 190, 70)
            avatar_fg = TEXT_LIGHT
        else:
            fill = Qt.GlobalColor.transparent
            text = TEXT_MUTED
            avatar_bg = QColor(98, 224, 190, 55)
            avatar_fg = TEXT_LIGHT

        if fill != Qt.GlobalColor.transparent:
            p.fillPath(path, fill)

        avatar = 28
        cx = rect.center().x() if self._collapsed else rect.left() + 22
        cy = rect.center().y()
        left = int(cx - avatar / 2)
        top = int(cy - avatar / 2)
        if not self._pixmap.isNull():
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            p.drawPixmap(left, top, self._pixmap)
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(avatar_bg)
            p.drawEllipse(left, top, avatar, avatar)
            p.setPen(avatar_fg)
            p.setFont(app_font(10, QFont.Weight.DemiBold))
            p.drawText(
                QRectF(left, top, avatar, avatar),
                int(Qt.AlignmentFlag.AlignCenter),
                self._initials,
            )
        if not self._collapsed:
            p.setPen(text)
            p.setFont(app_font(13, QFont.Weight.Medium if not self._active else QFont.Weight.DemiBold))
            p.drawText(
                self.rect().adjusted(44, 0, -10, 0),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                self._short,
            )
        p.end()


class GlassSidebar(QWidget):
    page_changed = Signal(str)
    collapse_toggled = Signal(bool)
    dialog_selected = Signal(str)
    fio_search_chosen = Signal(str)

    _avatar_ready = Signal(str, object)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        search_users: Callable[[str], list[str]] | None = None,
        fetch_avatar: Callable[[str], QPixmap] | None = None,
    ) -> None:
        super().__init__(parent)
        self._search_users = search_users or (lambda _query: [])
        self._fetch_avatar = fetch_avatar
        self._avatar_inflight: set[str] = set()
        self._avatar_ready.connect(self._on_avatar_ready)
        self._items = [
            NavItem("create", "Создать", "plus"),
            NavItem("agents", "Мои агенты", "home"),
            NavItem("files", "Файлы", "files"),
            NavItem("kpi", "KPI", "kpi"),
            NavItem("dashboard", "Мой дашборд", "dashboard"),
        ]
        self._active_key = "create"
        self._active_dialog_id = ""
        self._active_peer_id = ""
        self._collapsed = False
        self._buttons: dict[str, NavigationItem] = {}
        self._peer_items: dict[str, ChatPeerItem] = {}
        self.setFixedWidth(SIDEBAR_EXPANDED)
        self.setMinimumHeight(400)
        logo_path = Path(__file__).resolve().parents[1] / "temp" / "logo.png"
        self._logo = QPixmap(str(logo_path)) if logo_path.exists() else QPixmap()
        self._build_layout()
        self.set_active_key("create", animate=False)

    def items(self) -> list[NavItem]:
        return list(self._items)

    def active_key(self) -> str:
        return self._active_key

    def set_active_key(self, key: str, *, animate: bool = True) -> None:
        if key not in self._buttons:
            return
        self._active_key = key
        self._active_dialog_id = ""
        self._active_peer_id = ""
        for item_key, button in self._buttons.items():
            button.set_active(item_key == key)
        self._sync_peer_active()
        self.hide_search_suggestions()
        self.page_changed.emit(key)

    def is_collapsed(self) -> bool:
        return self._collapsed

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(SIDEBAR_EXPANDED if not self._collapsed else SIDEBAR_COLLAPSED, 600)

    def toggle_collapsed(self) -> None:
        self._apply_collapsed(not self._collapsed)

    def _apply_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        width = SIDEBAR_COLLAPSED if collapsed else SIDEBAR_EXPANDED
        self.setFixedWidth(width)
        self._sync_margins()

        self._title.setVisible(not collapsed)
        # Center logo when title is hidden; keep left-aligned brand row when expanded.
        self._header.setStretch(0, 1 if collapsed else 0)
        self._header.setStretch(3, 1 if collapsed else 0)

        for button in self._buttons.values():
            button.set_collapsed(collapsed)
        self._search.set_collapsed(collapsed)
        for item in self._peer_items.values():
            item.set_collapsed(collapsed)
        if collapsed:
            self.hide_search_suggestions()

        self.collapse_toggled.emit(collapsed)
        self.update()

    def _sync_margins(self) -> None:
        if self._collapsed:
            self._root.setContentsMargins(12, 22, 12, 22)
        else:
            self._root.setContentsMargins(SIDEBAR_PAD_LEFT, 22, SIDEBAR_PAD_RIGHT, 22)

    def _build_layout(self) -> None:
        self._root = QVBoxLayout(self)
        self._sync_margins()
        self._root.setSpacing(0)

        self._header = QHBoxLayout()
        self._header.setContentsMargins(0, 0, 0, 0)
        self._header.setSpacing(12)
        self._header.addStretch(0)

        self._logo_label = QLabel()
        self._logo_label.setFixedSize(36, 36)
        self._logo_label.setScaledContents(False)
        self._logo_label.setStyleSheet("background: transparent; border-radius: 18px;")
        if not self._logo.isNull():
            self._logo_label.setPixmap(circular_pixmap(self._logo, 36))
        self._header.addWidget(self._logo_label)

        self._title = QLabel("turbobot")
        self._title.setFont(app_font(18, QFont.Weight.DemiBold))
        self._title.setStyleSheet("color: #EAF7F3; background: transparent;")
        self._title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._title.setMinimumWidth(0)
        self._header.addWidget(self._title, 1)
        self._header.addStretch(0)

        self._root.addLayout(self._header)
        self._root.addSpacing(22)

        self._search = SidebarSearch(self._search_users)
        self._search.expand_requested.connect(self._expand_for_search)
        self._search.edit.fio_chosen.connect(self._on_fio_chosen)
        self._root.addWidget(self._search)
        self._root.addSpacing(ITEM_GAP)

        nav = QVBoxLayout()
        nav.setContentsMargins(0, 0, 0, 0)
        nav.setSpacing(ITEM_GAP)
        for item in self._items:
            inactive_icon, active_icon = _load_icon_pair(item.icon)
            button = NavigationItem(
                item,
                icon_inactive=inactive_icon,
                icon_active=active_icon,
            )
            button.clicked.connect(self.set_active_key)
            nav.addWidget(button)
            self._buttons[item.key] = button
        self._root.addLayout(nav)
        self._root.addSpacing(12)

        self._divider = QFrame()
        self._divider.setFixedHeight(1)
        self._divider.setStyleSheet("background: rgba(234, 247, 243, 0.22); border: none;")
        self._root.addWidget(self._divider)
        self._root.addSpacing(10)

        self._peers_host = QWidget()
        self._peers_host.setStyleSheet("background: transparent;")
        self._peers_layout = QVBoxLayout(self._peers_host)
        self._peers_layout.setContentsMargins(0, 0, 0, 0)
        self._peers_layout.setSpacing(ITEM_GAP)
        self._peers_layout.addStretch(1)

        self._peers_scroll = QScrollArea()
        self._peers_scroll.setWidgetResizable(True)
        self._peers_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._peers_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._peers_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._peers_scroll.setWidget(self._peers_host)
        self._peers_scroll.setStyleSheet(
            """
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical {
                background: transparent;
                width: 8px;
                margin: 4px 0;
            }
            QScrollBar::handle:vertical {
                background: rgba(255,255,255,0.25);
                border-radius: 4px;
                min-height: 24px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            """
        )
        self._root.addWidget(self._peers_scroll, 1)

    def hide_search_suggestions(self) -> None:
        if hasattr(self, "_search"):
            self._search.edit.hide_suggestions()

    def highlight_dialog(self, thread_id: str, peer_id: str = "") -> None:
        self._active_key = "chat"
        self._active_dialog_id = thread_id
        self._active_peer_id = peer_id
        for button in self._buttons.values():
            button.set_active(False)
        self._sync_peer_active()

    def _is_dialog_active(self, thread_id: str, peer_id: str = "") -> bool:
        return dialog_ids_match(
            thread_id,
            peer_id,
            self._active_dialog_id,
            self._active_peer_id,
        )

    def set_dialogs(self, threads: list[ChatThread]) -> None:
        pool: dict[str, ChatPeerItem] = {}
        for item in self._peer_items.values():
            pool[item.thread_id] = item
            if item.peer_id and item.peer_id not in pool:
                pool[item.peer_id] = item

        while self._peers_layout.count() > 1:
            self._peers_layout.takeAt(0)

        used: set[int] = set()
        next_items: dict[str, ChatPeerItem] = {}
        for thread in threads:
            peer_id = thread.peer_id or ("" if thread.id.startswith("thr-") else thread.id)
            item = None
            for key in (thread.id, peer_id):
                found = pool.get(key) if key else None
                if found is not None and id(found) not in used:
                    item = found
                    break
            if item is None:
                title = (thread.title or "").strip().casefold()
                if title:
                    for found in pool.values():
                        if id(found) in used:
                            continue
                        if found._title.strip().casefold() == title:
                            item = found
                            break
            if item is None:
                item = ChatPeerItem(thread.id, thread.title, peer_id=peer_id)
                item.clicked.connect(self._on_peer_clicked)
            else:
                item.bind(thread.id, thread.title, peer_id=peer_id)
            item.set_collapsed(self._collapsed)
            item.set_active(self._is_dialog_active(thread.id, peer_id))
            used.add(id(item))
            self._peers_layout.insertWidget(self._peers_layout.count() - 1, item)
            next_items[thread.id] = item
            self._queue_avatar(peer_id)

        for item in self._peer_items.values():
            if id(item) not in used:
                item.setParent(None)
                item.deleteLater()
        self._peer_items = next_items

    def _sync_peer_active(self) -> None:
        for item in self._peer_items.values():
            item.set_active(self._is_dialog_active(item.thread_id, item.peer_id))

    def _queue_avatar(self, peer_id: str) -> None:
        if not peer_id or self._fetch_avatar is None:
            return
        from app.chat.avatars import peek_avatar

        cached = peek_avatar(peer_id)
        if cached is not None:
            self._apply_avatar(peer_id, cached)
            return
        if peer_id in self._avatar_inflight:
            return
        self._avatar_inflight.add(peer_id)
        Thread(target=self._load_avatar_bg, args=(peer_id,), daemon=True).start()

    def _load_avatar_bg(self, peer_id: str) -> None:
        try:
            pixmap = self._fetch_avatar(peer_id) if self._fetch_avatar is not None else QPixmap()
        except Exception:
            pixmap = QPixmap()
        self._avatar_ready.emit(peer_id, pixmap)

    def _on_avatar_ready(self, peer_id: str, pixmap: object) -> None:
        self._avatar_inflight.discard(peer_id)
        if isinstance(pixmap, QPixmap):
            self._apply_avatar(peer_id, pixmap)

    def _apply_avatar(self, peer_id: str, pixmap: QPixmap) -> None:
        if pixmap.isNull():
            return
        for item in self._peer_items.values():
            if item.peer_id == peer_id:
                item.set_pixmap(pixmap)

    def _on_peer_clicked(self, thread_id: str) -> None:
        item = self._peer_items.get(thread_id)
        peer_id = item.peer_id if item is not None else ""
        self.highlight_dialog(thread_id, peer_id)
        self.hide_search_suggestions()
        self.dialog_selected.emit(thread_id)

    def _on_fio_chosen(self, fio: str) -> None:
        self._search.edit.blockSignals(True)
        self._search.edit.clear()
        self._search.edit.blockSignals(False)
        self.hide_search_suggestions()
        self.fio_search_chosen.emit(fio)

    def _expand_for_search(self) -> None:
        if self._collapsed:
            self.toggle_collapsed()
        self._search.edit.setFocus(Qt.FocusReason.MouseFocusReason)
        self._search.edit.open_suggestions()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())

        gradient = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        gradient.setColorAt(0.0, SIDEBAR_TOP)
        gradient.setColorAt(0.45, SIDEBAR_MIDDLE)
        gradient.setColorAt(1.0, SIDEBAR_BOTTOM)
        p.fillRect(rect, gradient)

        glow = QRadialGradient(rect.left() + 56, rect.top() + 70, 145)
        glow.setColorAt(0.0, MINT_SOFT)
        glow.setColorAt(1.0, QColor(98, 224, 190, 0))
        p.fillRect(rect, glow)

        p.setPen(QPen(QColor(MINT.red(), MINT.green(), MINT.blue(), 34), 1))
        p.drawLine(rect.right() - 0.5, rect.top() + 18, rect.right() - 0.5, rect.bottom() - 18)
        p.end()
