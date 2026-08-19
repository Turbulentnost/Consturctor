"""Human-in-the-loop: запись — только после подтверждения на странице агента."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QEventLoop, QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font

AUTONOMY_LEVEL = 1
HUMAN_REJECTED = "отклонено человеком"

_NEVER_CONFIRM = frozenset({"notify.send", "notify"})

_READ_EXACT = frozenset(
    {
        "web_search",
        "site_browser",
        "browser.search_web",
        "browser.open_page",
        "browser.list_installed_browsers",
        "browser.screenshot",
        "browser.get_page_html",
        "outlook.search_mail",
        "outlook.read_calendar",
        "excel.list_files",
        "excel.read_workbook",
        "onec.odata_catalog",
        "onec.odata_get",
        "onec.sql_query",
        "onec.erp_tasks_current",
        "onec.erp_tasks_period",
        "onec.erp_subordinate_tasks",
        "onec.docflow_tasks",
        "onec.meeting_service_notes",
        "agent.wait",
        "turboproject",
        "users.list",
        "users.current",
        "users.subordinates",
        "agent.schedule",
        "agent.schedule.cancel",
    }
)
_READ_PREFIXES = ("onec.search_", "onec.get_", "imap.")

_host: "_ConfirmHost | None" = None
_away_notify: Callable[[str, str, str], None] | None = None
_inline_hosts: dict[int, tuple[QWidget, str]] = {}
_pending: list["_PendingConfirm"] = []

_CARD_QSS = """
QFrame#HitlCard {
    background: #E8F3FB;
    border: 1px solid #B7D4E8;
    border-radius: 16px;
}
"""
_ACCEPT_QSS = """
QPushButton {
    background: #08745F; color: #FFFFFF; border: none;
    border-radius: 12px; padding: 8px 16px;
}
QPushButton:hover { background: #0A8670; }
QPushButton:disabled { background: #A8C8BF; color: #EAF7F3; }
"""
_REJECT_QSS = """
QPushButton {
    background: #FFFFFF; color: #9B1C1C;
    border: 1px solid rgba(155,28,28,0.35);
    border-radius: 12px; padding: 8px 16px;
}
QPushButton:hover { background: #FFF4F4; }
QPushButton:disabled { background: #F4F7F6; color: #9DB3AD; border-color: rgba(16,24,23,0.10); }
"""


def never_confirm(name: str) -> bool:
    return (name or "").strip() in _NEVER_CONFIRM


def is_read_tool(name: str) -> bool:
    tool = (name or "").strip()
    if tool in _NEVER_CONFIRM or tool in _READ_EXACT:
        return True
    return any(tool.startswith(prefix) for prefix in _READ_PREFIXES)


def needs_confirmation(name: str) -> bool:
    if never_confirm(name):
        return False
    return not is_read_tool(name)


def workflow_id_from_arguments(arguments: dict | None) -> str:
    args = arguments if isinstance(arguments, dict) else {}
    ctx = args.get("runtime_context") if isinstance(args.get("runtime_context"), dict) else {}
    return str(
        args.get("workflow_id")
        or args.get("agent_id")
        or ctx.get("workflow_id")
        or ctx.get("agent_id")
        or ""
    ).strip()


_TOOL_EXPLAIN: dict[str, tuple[str, str]] = {
    "onec.odata_post": (
        "Запись в 1С",
        "Создаёт новый документ или элемент справочника в 1С. Это изменение базы, не чтение.",
    ),
    "onec.odata_patch": (
        "Изменение в 1С",
        "Меняет уже существующий объект в 1С. Указанные поля будут перезаписаны.",
    ),
    "onec.attach_file": (
        "Файл в 1С",
        "Прикрепляет файл из папки агента к документу в 1С.",
    ),
    "outlook.send_mail": (
        "Отправка письма",
        "Отправляет письмо через Outlook. Получатели его увидят сразу.",
    ),
    "email.send": (
        "Отправка письма",
        "Отправляет письмо через Outlook. Получатели его увидят сразу.",
    ),
    "email.create_draft": (
        "Черновик письма",
        "Создаёт черновик в Outlook. Письмо ещё не уйдёт, пока его не отправят.",
    ),
    "excel.create_workbook": (
        "Создание Excel",
        "Создаёт новую книгу Excel в папке агента.",
    ),
    "excel.edit_workbook": (
        "Изменение Excel",
        "Правит существующую книгу Excel в папке агента.",
    ),
    "code.write_python": (
        "Запись кода",
        "Сохраняет Python-файл в папке агента.",
    ),
    "code.run_python": (
        "Запуск кода",
        "Запускает Python-скрипт на этом компьютере.",
    ),
    "workspace.powershell_run": (
        "Команда PowerShell",
        "Выполняет команду PowerShell в папке агента.",
    ),
    "browser.click": (
        "Клик в браузере",
        "Нажимает элемент на открытой странице.",
    ),
    "browser.type_text": (
        "Ввод в браузере",
        "Вводит текст в поле на открытой странице.",
    ),
    "browser.navigate": (
        "Переход в браузере",
        "Открывает указанный адрес в браузере агента.",
    ),
    "plan_export": (
        "Выгрузка с ЭТП",
        "Ищет закупки по ключам и сохраняет Excel на рабочий стол.",
    ),
}

_ENTITY_KINDS = (
    ("Document_", "документ"),
    ("Catalog_", "справочник"),
    ("InformationRegister_", "регистр сведений"),
    ("AccumulationRegister_", "регистр накопления"),
    ("ChartOfCharacteristicTypes_", "план видов характеристик"),
    ("Enum_", "перечисление"),
)


def _human_entity(entity: str) -> str:
    raw = str(entity or "").strip()
    if not raw:
        return ""
    kind = "объект 1С"
    name = raw
    for prefix, label in _ENTITY_KINDS:
        if raw.startswith(prefix):
            kind = label
            name = raw[len(prefix) :]
            break
    name = name.replace("_", " ").strip()
    if name:
        return f"{kind} «{name}»"
    return kind


def _body_facts(body: object) -> list[str]:
    if not isinstance(body, dict):
        return []
    facts: list[str] = []
    number = str(body.get("Number") or body.get("Номер") or "").strip()
    if number:
        facts.append(f"номер {number}")
    date = str(body.get("Date") or body.get("Дата") or "").strip()
    if date:
        facts.append(f"дата {date}")
    posted = body.get("Posted")
    if posted is False:
        facts.append("черновик, без проведения")
    elif posted is True:
        facts.append("с проведением")
    comment = str(body.get("Comment") or body.get("Комментарий") or "").strip()
    if comment:
        clipped = comment if len(comment) <= 220 else comment[:217].rstrip() + "…"
        facts.append(f"комментарий: {clipped}")
    return facts


def explain_tool(name: str, arguments: dict | None = None) -> tuple[str, str]:
    """Человеческое название и что сделает этот вызов."""
    tool = (name or "").strip()
    args = arguments if isinstance(arguments, dict) else {}
    title, base = _TOOL_EXPLAIN.get(
        tool,
        (tool or "инструмент", "Выполнит действие во внешней системе. Без подтверждения операция не пройдёт."),
    )
    extra: list[str] = []
    if tool in {"onec.odata_post", "onec.odata_patch"}:
        entity = _human_entity(str(args.get("entity") or args.get("entitySet") or ""))
        if entity:
            verb = "создать" if tool == "onec.odata_post" else "изменить"
            extra.append(f"Сейчас агент хочет {verb} {entity}.")
        extra.extend(_body_facts(args.get("body")))
        ref_key = str(args.get("ref_key") or args.get("Ref_Key") or "").strip()
        if tool == "onec.odata_patch" and ref_key:
            extra.append(f"объект {ref_key}")
    elif tool == "onec.attach_file":
        filename = str(args.get("filename") or "").strip()
        if filename:
            extra.append(f"Файл: {filename}.")
    elif tool in {"outlook.send_mail", "email.send", "email.create_draft"}:
        to = args.get("to") or args.get("recipients") or args.get("email")
        subject = str(args.get("subject") or args.get("тема") or "").strip()
        if to:
            extra.append(f"Кому: {to}.")
        if subject:
            extra.append(f"Тема: {subject}.")
    parts = [base]
    if extra:
        parts.append(" ".join(extra))
    return title, " ".join(part for part in parts if part).strip()


def host_is_eligible(*, wanted: str, host_workflow_id: str, visible: bool) -> bool:
    """Синий блок только на видимой formation/run. Чужой агент не перехватывает."""
    if not visible:
        return False
    if wanted and host_workflow_id and host_workflow_id != wanted:
        return False
    return True


def page_is_in_view(host: QWidget) -> bool:
    if host is None or not host.isVisible():
        return False
    window = host.window()
    if window is None or not window.isVisible() or bool(window.isMinimized()):
        return False
    return True


def install_confirm_host(parent: QObject | None = None) -> None:
    global _host
    if _host is None:
        _host = _ConfirmHost(parent)


def set_reveal_callback(callback: Callable[[], None] | None) -> None:
    """Сохранено для совместимости. Окно больше не поднимаем сами."""
    _ = callback


def set_away_notify_callback(callback: Callable[[str, str, str], None] | None) -> None:
    global _away_notify
    _away_notify = callback


def register_inline_host(host: QWidget, workflow_id: str = "") -> None:
    _inline_hosts[id(host)] = (host, str(workflow_id or "").strip())


def set_host_workflow_id(host: QWidget, workflow_id: str) -> None:
    wid = str(workflow_id or "").strip()
    _inline_hosts[id(host)] = (host, wid)
    if wid:
        attach_pending_for(wid)


def unregister_inline_host(host: QWidget) -> None:
    _inline_hosts.pop(id(host), None)


def has_pending_for(workflow_id: str) -> bool:
    wanted = str(workflow_id or "").strip()
    return any(item.workflow_id == wanted and not item.answered for item in _pending)


def attach_pending_for(workflow_id: str) -> None:
    wanted = str(workflow_id or "").strip()
    if not wanted:
        return
    host = _active_inline_host(wanted)
    if host is None:
        return
    attach = getattr(host, "attach_hitl_card", None)
    if not callable(attach):
        return
    for item in _pending:
        if item.workflow_id != wanted or item.attached:
            continue
        attach(item.card)
        item.attached = True


def _active_inline_host(workflow_id: str = "") -> QWidget | None:
    wanted = str(workflow_id or "").strip()
    unbound: QWidget | None = None
    for host, wid in reversed(list(_inline_hosts.values())):
        if not hasattr(host, "attach_hitl_card"):
            continue
        visible = page_is_in_view(host)
        if not host_is_eligible(wanted=wanted, host_workflow_id=wid, visible=visible):
            continue
        if wanted and wid == wanted:
            return host
        if wanted and not wid:
            unbound = host
            continue
        if not wanted:
            return host
    return unbound


@dataclass
class _PendingConfirm:
    workflow_id: str
    card: QWidget
    attached: bool = False
    answered: bool = False


class HitlConfirmCard(QFrame):
    accepted = Signal()
    rejected = Signal()

    def __init__(
        self,
        tool: str,
        preview: str,
        parent: QWidget | None = None,
        arguments: dict | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("HitlCard")
        self.setStyleSheet(_CARD_QSS)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        human_title, explanation = explain_tool(tool, arguments)
        title = QLabel(f"Агент хочет: {human_title}")
        title.setFont(app_font(13, QFont.Weight.DemiBold))
        title.setWordWrap(True)
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        tech = QLabel(f"Инструмент «{tool}».")
        tech.setFont(app_font(11))
        tech.setWordWrap(True)
        tech.setStyleSheet("color: #5B6B74; background: transparent;")
        what = QLabel(explanation)
        what.setFont(app_font(12))
        what.setWordWrap(True)
        what.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        what.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        body = QLabel(preview or "")
        body.setFont(app_font(11))
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        hint = QLabel("Разрешить выполнение? Без подтверждения операция будет отклонена.")
        hint.setFont(app_font(11))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #5B6B74; background: transparent;")
        self._status = QLabel("")
        self._status.setFont(app_font(11, QFont.Weight.DemiBold))
        self._status.setStyleSheet("color: #08745F; background: transparent;")
        self._status.hide()
        self._reject = QPushButton("не принимать")
        self._reject.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reject.setFixedHeight(34)
        self._reject.setFont(app_font(12, QFont.Weight.DemiBold))
        self._reject.setStyleSheet(_REJECT_QSS)
        self._accept = QPushButton("принять")
        self._accept.setCursor(Qt.CursorShape.PointingHandCursor)
        self._accept.setFixedHeight(34)
        self._accept.setMinimumWidth(110)
        self._accept.setFont(app_font(12, QFont.Weight.DemiBold))
        self._accept.setStyleSheet(_ACCEPT_QSS)
        self._reject.clicked.connect(self.rejected.emit)
        self._accept.clicked.connect(self.accepted.emit)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 4, 0, 0)
        buttons.setSpacing(8)
        buttons.addWidget(self._reject, 0)
        buttons.addStretch(1)
        buttons.addWidget(self._accept, 0)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        lay.addWidget(title)
        lay.addWidget(tech)
        lay.addWidget(what)
        if preview:
            params = QLabel("Параметры запроса")
            params.setFont(app_font(11, QFont.Weight.DemiBold))
            params.setStyleSheet("color: #5B6B74; background: transparent;")
            lay.addWidget(params)
            lay.addWidget(body)
        lay.addWidget(hint)
        lay.addWidget(self._status)
        lay.addLayout(buttons)

    def set_resolved(self, accepted: bool) -> None:
        self._reject.setEnabled(False)
        self._accept.setEnabled(False)
        self._status.setText("Принято" if accepted else "Отклонено")
        self._status.setStyleSheet(
            ("color: #08745F; background: transparent;" if accepted else "color: #9B1C1C; background: transparent;")
        )
        self._status.show()


def confirm_level1_tool(tool: str, arguments: dict | None = None) -> bool:
    """True — можно вызывать инструмент."""
    if not needs_confirmation(tool):
        return True
    if QApplication.instance() is None:
        return False
    return _bridge().confirm(tool, arguments or {})


class _ConfirmHost(QObject):
    asked = Signal(str, object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._ok = False
        self.asked.connect(self._on_ask, Qt.ConnectionType.BlockingQueuedConnection)

    def confirm(self, tool: str, arguments: dict) -> bool:
        preview = _preview_arguments(arguments)
        workflow_id = workflow_id_from_arguments(arguments)
        app = QApplication.instance()
        if app is not None and QThread.currentThread() is app.thread():
            return self._show(tool, preview, workflow_id, arguments)
        self.asked.emit(tool, (preview, workflow_id, arguments))
        return self._ok

    @Slot(str, object)
    def _on_ask(self, tool: str, payload: object) -> None:
        preview, workflow_id, arguments = "", "", {}
        if isinstance(payload, tuple) and len(payload) >= 2:
            preview = str(payload[0] or "")
            workflow_id = str(payload[1] or "")
            if len(payload) >= 3 and isinstance(payload[2], dict):
                arguments = payload[2]
        else:
            preview = str(payload or "")
        self._ok = self._show(tool, preview, workflow_id, arguments)

    def _show(self, tool: str, preview: str, workflow_id: str, arguments: dict | None = None) -> bool:
        loop = QEventLoop(self)
        answered = False
        accepted = False
        card = HitlConfirmCard(tool, preview, arguments=arguments)
        item = _PendingConfirm(workflow_id=workflow_id, card=card, attached=False)
        _pending.append(item)

        def _accept() -> None:
            nonlocal answered, accepted
            answered = True
            accepted = True
            item.answered = True
            card.set_resolved(True)
            loop.quit()

        def _reject() -> None:
            nonlocal answered, accepted
            answered = True
            accepted = False
            item.answered = True
            card.set_resolved(False)
            loop.quit()

        card.accepted.connect(_accept)
        card.rejected.connect(_reject)

        host = _active_inline_host(workflow_id)
        if host is not None:
            attach = getattr(host, "attach_hitl_card", None)
            if callable(attach):
                attach(card)
                item.attached = True
        else:
            _notify_away(workflow_id, tool, preview, arguments)

        while not answered:
            loop.exec()
        if item in _pending:
            _pending.remove(item)
        return accepted


def _notify_away(
    workflow_id: str,
    tool: str,
    preview: str,
    arguments: dict | None = None,
) -> None:
    if _away_notify is None:
        return
    title, explanation = explain_tool(tool, arguments)
    body = f"{title}. {explanation}"
    if preview:
        body = f"{body}\n{preview}"
    try:
        _away_notify(workflow_id, tool, body)
    except Exception:  # noqa: BLE001
        pass


def _bridge() -> _ConfirmHost:
    global _host
    app = QApplication.instance()
    if _host is None:
        _host = _ConfirmHost()
        if app is not None and _host.thread() is not app.thread():
            _host.moveToThread(app.thread())
    return _host


def _preview_arguments(arguments: dict) -> str:
    if not arguments:
        return ""
    skip = {"runtime_context", "workflow_id", "agent_id"}
    shown = {key: value for key, value in arguments.items() if key not in skip}
    if not shown:
        return ""
    try:
        text = json.dumps(shown, ensure_ascii=False, indent=2, default=str)
    except TypeError:
        text = str(shown)
    if len(text) > 4000:
        return text[:4000].rstrip() + "…"
    return text
