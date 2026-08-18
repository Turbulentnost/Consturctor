from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Thread

from PySide6.QtCore import Qt, QSize, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
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
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.api_client import (
    ApiClient,
    ApiError,
    PassportSession,
    WorkflowOpenQuestion,
    WorkflowPlan,
    WorkflowRecord,
)
from app.tools.ac.workers import com_availability
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, scroll_bar_qss
from app.ui.widgets.markdown_body import MarkdownBody

SUPPORTED_SUFFIXES = {
    ".txt", ".md", ".markdown", ".csv", ".json", ".xml", ".html", ".htm",
    ".yaml", ".yml", ".log", ".pdf", ".docx", ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".xlsx", ".xls",
}

_STAGES = [
    ("document", "Материалы"),
    ("plan", "План"),
    ("clarify", "Уточнения"),
    ("ready", "Сборка workflow"),
    ("executing", "Тестовый прогон"),
    ("done", "Готово"),
]
_PHASE_RANK = {
    "document": 0,
    "plan": 1,
    "clarify": 2,
    "ready": 3,
    "executing": 4,
    "tested": 4,
    "done": 5,
}


def _merge_desktop_capability(
    local: dict[str, object],
    capability: dict[str, object],
) -> dict[str, object]:
    payload = dict(local)
    payload["desktop"] = dict(capability)
    return payload

_SEND_BTN = """
QToolButton {
    background: #08745F; color: #FFFFFF; border: none;
    border-radius: 20px;
}
QToolButton:hover { background: #0A8670; }
QToolButton:disabled { background: #A8C8BF; }
"""
_CLIP_BTN = """
QToolButton {
    background: transparent; color: #6B7773; border: none;
    font-size: 18px;
}
QToolButton:hover { color: #08745F; }
"""
_COMPOSER = """
QLineEdit {
    background: #FFFFFF; color: #101817;
    border: 1px solid rgba(16,24,23,0.10);
    border-radius: 22px;
    padding: 10px 14px;
    selection-background-color: #08745F;
}
QLineEdit:focus { border: 1px solid #08745F; }
"""
_CHIP = """
QFrame#filechip {
    background: #F1F5F3;
    border: 1px solid rgba(16,24,23,0.08);
    border-radius: 12px;
}
"""
_SECONDARY = """
QPushButton {
    background: #F1F5F3; color: #06483D; border: none;
    border-radius: 12px; padding: 8px 14px; text-align: left;
}
QPushButton:hover { background: #E4EDE9; }
"""
_PRIMARY = """
QPushButton {
    background: #08745F; color: #FFFFFF; border: none;
    border-radius: 12px; padding: 8px 16px;
}
QPushButton:hover { background: #0A8670; }
QPushButton:disabled { background: #A8C8BF; color: #EAF7F3; }
"""
_QCARD = """
QFrame#qcard {
    background: #FFF8EE;
    border: 1px solid #F0DFC2;
    border-radius: 16px;
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


def _quick_answers_for_question(question: WorkflowOpenQuestion) -> list[str]:
    options = [str(item).strip() for item in (question.options or []) if str(item).strip()]
    if options:
        return options[:4]
    text = (question.question or "").casefold()
    if "outlook" in text or "календар" in text:
        return ["Microsoft Outlook", "Google Calendar", "1С / внутренняя система", "Другое"]
    return ["Да", "Нет", "Пока неизвестно"]


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


def _visible_thinking(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return ""
    # drop raw JSON plan blobs from live thinking
    if cleaned.lstrip().startswith("{") and '"steps"' in cleaned:
        return ""
    if "```json" in cleaned.casefold():
        return ""
    return cleaned[-2500:]


class _WrappingLabel(QLabel):
    """QLabel that wraps inside constrained layouts (scroll feed / cards)."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, super().minimumSizeHint().height())

    def sizeHint(self) -> QSize:  # noqa: N802
        # Prefer parent/available width so layout doesn't grow to one long line.
        w = self.width()
        if w < 40:
            parent = self.parentWidget()
            w = parent.width() if parent is not None else 280
        w = max(120, w)
        return QSize(w, self.heightForWidth(w))


class _FitWidthScrollArea(QScrollArea):
    """Force children to wrap within the viewport width."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(320, 220)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(160, 140)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        inner = self.widget()
        if inner is not None:
            w = max(1, self.viewport().width())
            # Fixed width prevents children from expanding the feed to unwrapped text.
            inner.setFixedWidth(w)


def _strip_clarify_block(blob: str) -> str:
    """Remove CLARIFY questionnaire so it doesn't pollute blocker detection."""
    lines = []
    skipping = False
    for ln in (blob or "").splitlines():
        low = ln.strip().casefold()
        if low.startswith("clarify:"):
            skipping = True
            continue
        if skipping and (
            low.startswith("question:")
            or low.startswith("вопрос:")
            or low.startswith("options:")
            or low.startswith("варианты:")
            or low.startswith("-")
            or low.startswith("•")
            or re.match(r"^\d+[.)]", low)
        ):
            continue
        if skipping and not low:
            skipping = False
            continue
        if skipping:
            skipping = False
        lines.append(ln)
    return "\n".join(lines)


def _blocker_snippets(blob: str) -> list[str]:
    """Pull concrete failure reasons from RESULT / agent output."""
    text = _strip_clarify_block(blob)
    snippets: list[str] = []
    patterns = (
        r"(?im)^(?:[-*•]\s*)?(?:blocker|блокер|причина|error|ошибка)\s*[:：]\s*(.+)$",
        r"(?im)^(?:[-*•]\s*)?(?:blocked|не удалось|failed|fail(?:ed)?)\s*[:：-]?\s*(.+)$",
        r"(?im)(?:нет|missing|не задан[ао]?|отсутствует)\s+([A-Z][A-Z0-9_]{2,}|[\w./:-]{4,})",
        r"(?im)(?:connection reset|sso|unauthorized|403|401|timeout|timed out)[^\n.]{0,80}",
        r"(?im)live[^\n]{0,40}(?:blocked|недоступ|fail|не удалось)[^\n]{0,80}",
    )
    for pat in patterns:
        for m in re.finditer(pat, text):
            chunk = m.group(0).strip()
            chunk = re.sub(r"\s+", " ", chunk)
            if 8 <= len(chunk) <= 220 and "tests:" not in chunk.casefold():
                snippets.append(chunk)
            if len(snippets) >= 5:
                break
        if len(snippets) >= 5:
            break

    for ln in text.splitlines():
        low = ln.casefold()
        if not ln.strip() or ln.upper().startswith("TESTS:"):
            continue
        if any(
            tip in low
            for tip in (
                "blocked",
                "блокер",
                "нет ",
                "missing",
                "недоступ",
                "не задан",
                "credential",
                "учётк",
                "sso",
                "connection reset",
                "не хватает",
            )
        ):
            cleaned = re.sub(r"^[-•*\d.)|\s]+", "", ln).strip()
            cleaned = re.sub(r"\s+", " ", cleaned)
            if 12 <= len(cleaned) <= 220:
                snippets.append(cleaned)
        if len(snippets) >= 6:
            break

    seen: set[str] = set()
    out: list[str] = []
    for item in snippets:
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out[:4]


_ENV_LABELS = {
    "AZURE_CLIENT_ID": "Azure Client ID",
    "AZURE_CLIENT_SECRET": "Azure Client Secret",
    "AZURE_TENANT_ID": "Azure Tenant ID",
    "GRAPH_TOKEN": "токен Microsoft Graph",
    "OUTLOOK_USER": "учётка Outlook",
    "SITE_URL": "URL сайта",
}

_SERVER_SECRET_ENV = frozenset(
    {
        "ONEC_BASE_URL",
        "ONEC_URL",
        "ONEC_USER",
        "ONEC_PASSWORD",
        "ONEC_BASE",
        "ODATA_BASE_URL",
        "ODATA_USERNAME",
        "ODATA_PASSWORD",
        "CONSTRUCTOR_API_URL",
        "BACKEND_URL",
        "ERP_LOGIN",
        "ERP_PASSWORD",
        "IMAP_HOST",
        "IMAP_USERNAME",
        "IMAP_PASSWORD",
        "IMAP_PORT",
        "BASE_URL",
    }
)

_RESERVED_ENV = frozenset(
    {
        "TESTS",
        "PASS",
        "FAIL",
        "CLARIFY",
        "QUESTION",
        "OPTIONS",
        "RESULT",
        "BLOCKED",
        "LIVE",
        "HTTP",
        "HTTPS",
        "JSON",
        "TRUE",
        "FALSE",
        "NULL",
    }
)


def _missing_env_vars(text: str) -> list[str]:
    found: list[str] = []
    for m in re.finditer(
        r"(?:нет|missing|не задан[ао]?|отсутствует|нужен|требуется)\s+([A-Z][A-Z0-9_]{2,})",
        text or "",
        flags=re.IGNORECASE,
    ):
        name = m.group(1).upper()
        if name not in _RESERVED_ENV and name not in _SERVER_SECRET_ENV:
            found.append(name)
    for m in re.finditer(r"\b([A-Z][A-Z0-9_]{3,})\b", text or ""):
        name = m.group(1).upper()
        if name in _RESERVED_ENV or name in _SERVER_SECRET_ENV:
            continue
        if any(suf in name for suf in ("_URL", "_USER", "_PASSWORD", "_TOKEN", "_SECRET", "_ID", "_KEY", "_HOST")):
            found.append(name)
    seen: set[str] = set()
    out: list[str] = []
    for name in found:
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out[:5]


def _label_env(name: str) -> str:
    if name in _ENV_LABELS:
        return _ENV_LABELS[name]
    low = name.casefold()
    if "onec" in low or "1c" in low:
        if "url" in low:
            return f"URL базы 1С ({name})"
        if "user" in low or "login" in low:
            return f"логин 1С ({name})"
        if "pass" in low or "secret" in low:
            return f"пароль 1С ({name})"
        return f"параметр 1С ({name})"
    if "outlook" in low or "graph" in low or "azure" in low:
        if "url" in low:
            return f"URL Outlook / Graph ({name})"
        if "user" in low:
            return f"учётка Outlook ({name})"
        return f"доступ Microsoft/Outlook ({name})"
    if "url" in low or name.endswith("_HOST"):
        return f"URL системы ({name})"
    if "user" in low or "login" in low:
        return f"логин ({name})"
    if "pass" in low or "secret" in low or "token" in low:
        return f"секрет/токен ({name})"
    return name


def _detect_system(blob: str, blockers: list[str], context: str = "") -> str:
    low = " ".join([blob or "", " ".join(blockers), context or ""]).casefold()
    if any(k in low for k in ("onec", "1с", "1c", "odata")):
        return "1С"
    if any(k in low for k in ("outlook", "календар", "совещан", "graph", "win32com")):
        return "Outlook / календарь"
    if any(k in low for k in ("этп", "закупк", "тендер")):
        return "площадки закупок (ЭТП)"
    if any(k in low for k in ("imap", "почт", "email", "mail")):
        return "почты"
    # Host from URL in text
    m = re.search(r"https?://([^/\s]+)", blob or "")
    if m:
        return f"сайт {m.group(1)}"
    title = (context or "").strip()
    if title and len(title) <= 80:
        return f"агент «{title}»"
    return ""


def _question_from_blocker(
    blob: str,
    blockers: list[str],
    *,
    context: str = "",
) -> tuple[str, list[str], str]:
    """Concrete user-facing question + options — always name WHAT is missing."""
    focus = _strip_clarify_block(blob)
    low = focus.casefold()
    joined = " ".join(blockers).casefold()
    sample = blockers[0] if blockers else ""
    envs = _missing_env_vars(focus + "\n" + "\n".join(blockers))
    env_labels = [_label_env(e) for e in envs]
    system = _detect_system(focus, blockers, context)

    def why(extra: str = "") -> str:
        bits = []
        if sample:
            bits.append(sample if sample.casefold().startswith("блокер") else f"Блокер: {sample}")
        if env_labels:
            bits.append("Не хватает: " + ", ".join(env_labels))
        if extra:
            bits.append(extra)
        bits.append("Без этого ответа нельзя сохранить агента.")
        return " ".join(bits)

    need_list = ", ".join(env_labels[:3]) if env_labels else ""

    if system == "1С" or any(k in low or k in joined for k in ("onec", "1с", "1c", "odata")):
        return (
            "Live-проверка 1С с облака недоступна. URL и учётка OData задаются в backend/.env, "
            "не в чате. Как продолжить?",
            [
                "Подключаться к 1С через COM на этой машине",
                "Пока только fixtures / офлайн без live 1С",
                "OData уже в backend/.env — повторить проверку через onec.*",
                "Свой вариант — опишу режим проверки (без пароля)",
            ],
            why("Учётку 1С не вводите в чат — она в backend/.env."),
        )

    if system.startswith("Outlook") or any(
        k in low or k in joined for k in ("outlook", "календар", "совещан", "graph", "win32com", "через com")
    ):
        what = need_list or "способ доступа к календарю Outlook"
        return (
            f"Live-проверка Outlook/календаря не прошла — не хватает: {what}. Как подключаться?",
            [
                "Локальный Outlook через COM (win32com) на этой машине",
                "Microsoft Graph — дам tenant / Client ID / права календаря",
                "Пока только fixtures, без live Outlook",
                "Свой вариант — опишу доступ к Outlook",
            ],
            why("Нужен доступ именно к Outlook/календарю."),
        )

    if any(k in low or k in joined for k in ("sso", "azure", "credential", "учётк", "логин", "password", "токен", "auth")):
        target = system or "целевой системы проверки"
        return (
            f"Live-проверка {target} не прошла. Секреты в чат не вводите. Как продолжить?",
            [
                f"Перезапустить live к {target} на этой машине",
                f"Оставить только fixtures, без live к {target}",
                f"Свой вариант — опишу режим проверки {target} (без пароля)",
            ],
            why(f"Логин и пароль для {target} не спрашиваем в чате."),
        )

    if any(
        k in low or k in joined
        for k in ("url", "endpoint", "эндпоинт", "site_url", "http://", "https://", "base_url", "_url")
    ) and system != "1С":
        target = system or "проверяемой системы"
        url_what = next((lab for lab in env_labels if "url" in lab.casefold() or "URL" in lab), "") or (
            f"URL {target}"
        )
        return (
            f"Не хватает адреса: {url_what}. Какой рабочий URL указать для {target}?",
            [
                f"Впишу URL для {target} в своём варианте",
                f"Доступ к {target} только из внутренней сети — проверять с этой машины",
                f"URL для {target} пока нет — оставить fixtures",
                f"Свой вариант — опишу адрес для {target}",
            ],
            why(f"Нужен URL именно для {target}."),
        )

    if any(k in low or k in joined for k in ("connection reset", "timeout", "timed out", "недоступ", "network")):
        target = system or "внутреннего сервиса"
        return (
            f"{target} недоступен с облака (сеть/VPN). Как продолжить проверку {target}?",
            [
                f"Перезапустить live к {target} на этой машине (есть VPN/доступ)",
                f"Дам альтернативный URL / стенд для {target}",
                f"Оставить только fixtures, без live к {target}",
                f"Свой вариант — опишу доступ к {target}",
            ],
            why(f"Нужен доступ к {target} с вашей машины."),
        )

    if sample or system:
        target = system or "системы из блокера"
        detail = need_list or sample or target
        return (
            f"Проверка {target} остановилась. Не хватает: {detail}. Что можете дать?",
            [
                f"Опишу недостающие данные для {target} в своём варианте",
                f"Перезапустить live-проверку {target} на этой машине",
                f"Оставить только fixtures для {target}",
                "Свой вариант — уточню, чего именно не хватает",
            ],
            why(),
        )

    return (
        "Тестовый прогон не завершён. Выберите режим проверки — без пароля и URL OData.",
        [
            "Пока только fixtures, live отложить",
            "Перезапустить live на этой машине",
            "Свой вариант — уточню режим проверки (без пароля)",
        ],
        "Сборка без TESTS: PASS. Секреты в чат не вводите.",
    )


def _asks_server_secrets(value: str) -> bool:
    low = (value or "").casefold()
    return any(
        needle in low
        for needle in (
            "onec_base_url",
            "constructor_api",
            "odata_base",
            "odata_user",
            "odata_password",
            "парол",
            "логин 1с",
            "логин odata",
            "учётк",
            "url базы 1с",
            "url odata",
            "впишу url",
            "впишу url odata",
        )
    )


def _extract_post_build_question(
    blob: str,
    *,
    context: str = "",
) -> WorkflowOpenQuestion:
    """Build a clarification question after TESTS: FAIL from RESULT / agent output."""
    text = blob or ""
    lines = [ln.strip() for ln in text.splitlines()]
    blockers = _blocker_snippets(text)

    # Prefer structured block from execute prompt:
    # CLARIFY: / QUESTION: ... / OPTIONS: - ...
    structured_q = ""
    structured_opts: list[str] = []
    in_options = False
    for ln in lines:
        low = ln.casefold()
        if low.startswith("clarify:"):
            in_options = False
            continue
        if low.startswith("question:") or low.startswith("вопрос:"):
            structured_q = ln.split(":", 1)[1].strip()
            in_options = False
            continue
        if low.startswith("options:") or low.startswith("варианты:"):
            rest = ln.split(":", 1)[1].strip()
            in_options = True
            if rest:
                cleaned = re.sub(r"^[-•*\d.)\s]+", "", rest).strip()
                if cleaned:
                    structured_opts.append(cleaned)
            continue
        if in_options:
            if not ln or ln.upper().startswith("TESTS:"):
                in_options = False
                continue
            cleaned = re.sub(r"^[-•*\d.)\s]+", "", ln).strip()
            if cleaned:
                structured_opts.append(cleaned)
            if len(structured_opts) >= 4:
                in_options = False

    questions: list[str] = []
    if structured_q:
        questions.append(structured_q)
    else:
        for ln in lines:
            low = ln.casefold()
            if not ln or ln.upper().startswith("TESTS:"):
                continue
            cleaned = re.sub(r"^[\d]+[.)]\s*", "", ln)
            cleaned = re.sub(r"^[-•*]\s*", "", cleaned).strip()
            if "?" in cleaned and len(cleaned) >= 12 and cleaned.endswith("?"):
                # Skip useless meta questions about TESTS: PASS.
                if "tests: pass" in cleaned.casefold() or "tests:pass" in cleaned.casefold():
                    continue
                if "что нужно уточнить" in cleaned.casefold():
                    continue
                questions.append(cleaned)
            if len(questions) >= 3:
                break

    generic_q, generic_opts, generic_why = _question_from_blocker(
        text,
        blockers,
        context=context,
    )

    def _is_meta_question(value: str) -> bool:
        low = (value or "").casefold()
        return (
            "tests: pass" in low
            or "tests:pass" in low
            or "что нужно уточнить" in low
            or "довести проверку" in low
            or _asks_server_secrets(value)
            or len((value or "").strip()) < 12
        )

    primary = questions[0] if questions else generic_q
    used_generic = False
    if _is_meta_question(primary):
        primary = generic_q
        used_generic = True

    extras = [q for q in questions[1:3] if not _is_meta_question(q)]
    why = generic_why
    if extras:
        why = f"{why} Также: " + " · ".join(extras)

    options = structured_opts[:4] if structured_opts and not used_generic else generic_opts
    if options is structured_opts[:4] or (structured_opts and not used_generic):
        # Keep model options only if they look like concrete actions/facts.
        junk = ("указать url / систему", "уточнить критерии", "tests: pass")
        useful = [
            opt
            for opt in options
            if opt.strip()
            and not any(bad in opt.casefold() for bad in junk)
            and not _asks_server_secrets(opt)
        ]
        options = useful[:4] if len(useful) >= 2 else generic_opts

    return WorkflowOpenQuestion(
        id="post-build-q1",
        question=primary[:400],
        why=why[:500],
        options=options,
    )


@dataclass
class FeedEvent:
    title: str
    body: str
    time: str
    action: str = ""
    action_key: str = ""
    role: str = "agent"  # agent | user


class StageStepper(QWidget):
    """Vertical stages panel matching the mockup."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._active = 0
        self._rows: list[tuple[QFrame, QLabel, QLabel]] = []
        self.setFixedWidth(260)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(0)

        heading = QLabel("Этапы работы")
        heading.setFont(app_font(15, QFont.Weight.DemiBold))
        heading.setStyleSheet("color: #06483D; background: transparent;")
        root.addWidget(heading)
        root.addSpacing(14)

        self._list = QVBoxLayout()
        self._list.setSpacing(4)
        for _key, label in _STAGES:
            row, dot, text = self._make_row(label)
            self._rows.append((row, dot, text))
            self._list.addWidget(row)
        root.addLayout(self._list)
        root.addStretch(1)

        self._ready_label = QLabel("Готовность 0%")
        self._ready_label.setFont(app_font(12, QFont.Weight.DemiBold))
        self._ready_label.setStyleSheet("color: #06483D; background: transparent;")
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(6)
        self._bar.setStyleSheet(
            """
            QProgressBar {
                background: #E8EFEC; border: none; border-radius: 3px;
            }
            QProgressBar::chunk {
                background: #08745F; border-radius: 3px;
            }
            """
        )
        root.addWidget(self._ready_label)
        root.addSpacing(8)
        root.addWidget(self._bar)

        self.setStyleSheet(
            """
            StageStepper {
                background: #FFFFFF;
                border: 1px solid rgba(16,24,23,0.08);
                border-radius: 18px;
            }
            """
        )

    def _make_row(self, label: str) -> tuple[QFrame, QLabel, QLabel]:
        row = QFrame()
        row.setObjectName("stagerow")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(12)
        dot = QLabel("○")
        dot.setFixedSize(22, 22)
        dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dot.setFont(app_font(13, QFont.Weight.DemiBold))
        text = QLabel(label)
        text.setFont(app_font(13, QFont.Weight.Medium))
        text.setStyleSheet("background: transparent;")
        lay.addWidget(dot)
        lay.addWidget(text, 1)
        return row, dot, text

    def set_phase(self, phase: str) -> None:
        rank = _PHASE_RANK.get(phase, 0)
        if phase == "done":
            rank = len(_STAGES) - 1
        self._active = rank
        for i, (row, dot, text) in enumerate(self._rows):
            if i < rank or (phase == "done" and i <= rank):
                state = "done"
            elif i == rank:
                state = "active"
            else:
                state = "idle"
            if state == "done":
                row.setStyleSheet("QFrame#stagerow { background: transparent; border-radius: 12px; }")
                dot.setText("✓")
                dot.setStyleSheet(
                    "color: #FFFFFF; background: #08745F; border-radius: 11px;"
                )
                text.setStyleSheet("color: #06483D; background: transparent;")
            elif state == "active":
                row.setStyleSheet(
                    "QFrame#stagerow { background: #FFF4E5; border-radius: 12px; }"
                )
                dot.setText("●")
                dot.setStyleSheet(
                    "color: #FFFFFF; background: #F0A202; border-radius: 11px;"
                )
                text.setStyleSheet("color: #8A5300; background: transparent; font-weight: 600;")
            else:
                row.setStyleSheet("QFrame#stagerow { background: transparent; border-radius: 12px; }")
                dot.setText("○")
                dot.setStyleSheet(
                    "color: #9DB3AD; background: #F1F5F3; border-radius: 11px;"
                )
                text.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        pct = int(round((rank / max(1, len(_STAGES) - 1)) * 100))
        if phase == "done":
            pct = 100
        self._ready_label.setText(f"Готовность {pct}%")
        self._bar.setValue(pct)


class FeedItem(QFrame):
    action_clicked = Signal(str)

    def __init__(self, event: FeedEvent, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 4, 0, 10)
        row.setSpacing(12)

        is_user = event.role == "user" or event.title.strip().casefold() in {"вы", "you"}
        if is_user:
            avatar = QLabel("👤")
            avatar.setFixedSize(36, 36)
            avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
            avatar.setStyleSheet(
                "background: #E8EEF5; border-radius: 18px; font-size: 16px;"
            )
            bubble_bg = "rgba(8,116,95,0.10)"
            bubble_border = "rgba(8,116,95,0.16)"
            title_color = "#08745F"
        else:
            avatar = QLabel("🤖")
            avatar.setFixedSize(36, 36)
            avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
            avatar.setStyleSheet(
                "background: #EAF7F3; border-radius: 18px; font-size: 16px;"
            )
            bubble_bg = "transparent"
            bubble_border = "transparent"
            title_color = COLOR_CONTENT_MUTED.name()

        col = QVBoxLayout()
        col.setSpacing(4)
        title = _WrappingLabel(event.title)
        title.setFont(app_font(12))
        title.setStyleSheet(f"color: {title_color}; background: transparent;")

        if is_user:
            bubble = QFrame()
            bubble.setObjectName("userbubble")
            bubble.setMinimumWidth(0)
            bubble.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            bubble.setStyleSheet(
                f"""
                QFrame#userbubble {{
                    background: {bubble_bg};
                    border: 1px solid {bubble_border};
                    border-radius: 14px;
                }}
                """
            )
            bubble_lay = QVBoxLayout(bubble)
            bubble_lay.setContentsMargins(12, 8, 12, 8)
            bubble_lay.setSpacing(2)
            body = _WrappingLabel(event.body)
            body.setFont(app_font(14, QFont.Weight.Medium))
            body.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
            bubble_lay.addWidget(body)
            col.addWidget(title)
            col.addWidget(bubble)
        else:
            body = MarkdownBody(event.body, font_size=14, weight=QFont.Weight.Medium)
            col.addWidget(title)
            col.addWidget(body)

        if event.action:
            btn = QPushButton(event.action)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFont(app_font(12, QFont.Weight.DemiBold))
            btn.setStyleSheet(_SECONDARY)
            btn.setFixedHeight(36)
            key = event.action_key
            btn.clicked.connect(lambda _=False, k=key: self.action_clicked.emit(k))
            col.addWidget(btn, 0, Qt.AlignmentFlag.AlignLeft)

        time = QLabel(event.time)
        time.setFont(app_font(11))
        time.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        time.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)

        # Both sides stay on the left — messenger-style conversation.
        row.addWidget(avatar, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(col, 1)
        row.addWidget(time, 0, Qt.AlignmentFlag.AlignTop)


class WorkflowPage(QWidget):
    saved = Signal(str)
    saved_record = Signal(object)
    launch_requested = Signal(object)
    schedule_requested = Signal(object)
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
        self._passport_runtime: dict = {}
        self._results_dir = ""
        self._busy = False
        self._events: list[FeedEvent] = []
        self._pending_answers: dict[str, str] = {}
        self._tests_ok = False
        self._thinking_text = ""
        self._post_build_question: WorkflowOpenQuestion | None = None
        self._question_fields: dict[str, QLineEdit] = {}
        self._current_question_id = ""
        self._selected_quick_answer = ""
        self._answer_group: QButtonGroup | None = None
        self._async_ok.connect(self._on_async_ok)
        self._async_fail.connect(self._on_async_fail)
        self._stream_event.connect(self._on_stream_event)
        self._thinking_timer = QTimer(self)
        self._thinking_timer.setSingleShot(True)
        self._thinking_timer.setInterval(120)
        self._thinking_timer.timeout.connect(self._rebuild_feed)
        self._feed_stick_to_bottom = True
        self._feed_rebuilding = False
        self._build()
        self._render_all()

    def _build(self) -> None:
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        title = QLabel("Конструктор workflow")
        title.setFont(app_font(24, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

        # --- Center: agent feed -------------------------------------------------
        feed_card = QFrame()
        feed_card.setStyleSheet(
            """
            QFrame#feedcard {
                background: #FFFFFF;
                border: 1px solid rgba(16,24,23,0.08);
                border-radius: 18px;
            }
            """
        )
        feed_card.setObjectName("feedcard")
        feed_lay = QVBoxLayout(feed_card)
        feed_lay.setContentsMargins(20, 16, 20, 14)
        feed_lay.setSpacing(10)

        feed_title = QLabel("Работа агента")
        feed_title.setFont(app_font(15, QFont.Weight.DemiBold))
        feed_title.setStyleSheet("color: #06483D; background: transparent;")
        feed_lay.addWidget(feed_title)

        self._feed_inner = QWidget()
        self._feed_inner.setStyleSheet("background: transparent;")
        self._feed_inner.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._feed_layout = QVBoxLayout(self._feed_inner)
        self._feed_layout.setContentsMargins(0, 0, 8, 0)
        self._feed_layout.setSpacing(2)
        self._feed_layout.addStretch(1)

        feed_scroll = _FitWidthScrollArea()
        feed_scroll.setFrameShape(QFrame.Shape.NoFrame)
        feed_scroll.setWidget(self._feed_inner)
        feed_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }" + scroll_bar_qss()
        )
        self._feed_scroll = feed_scroll
        bar = feed_scroll.verticalScrollBar()
        bar.valueChanged.connect(self._sync_feed_scroll_state)
        bar.rangeChanged.connect(self._on_feed_range_changed)
        feed_lay.addWidget(feed_scroll, 1)

        # file chips
        self._chips_wrap = QWidget()
        self._chips_wrap.setStyleSheet("background: transparent;")
        self._chips_layout = QHBoxLayout(self._chips_wrap)
        self._chips_layout.setContentsMargins(0, 0, 0, 0)
        self._chips_layout.setSpacing(8)
        self._chips_layout.addStretch(1)
        feed_lay.addWidget(self._chips_wrap)

        # composer
        composer_row = QHBoxLayout()
        composer_row.setSpacing(8)
        self._clip_btn = QToolButton()
        self._clip_btn.setText("📎")
        self._clip_btn.setFixedSize(40, 40)
        self._clip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clip_btn.setStyleSheet(_CLIP_BTN)
        self._clip_btn.setToolTip("Приложить файл")
        self._clip_btn.clicked.connect(self._on_pick_files)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Напишите сообщение агенту…")
        self._input.setFont(app_font(13))
        self._input.setFixedHeight(44)
        self._input.setStyleSheet(_COMPOSER)
        self._input.returnPressed.connect(self._on_send)

        self._send_btn = QToolButton()
        self._send_btn.setText("↑")
        self._send_btn.setFixedSize(40, 40)
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.setStyleSheet(_SEND_BTN)
        self._send_btn.clicked.connect(self._on_send)

        composer_row.addWidget(self._clip_btn)
        composer_row.addWidget(self._input, 1)
        composer_row.addWidget(self._send_btn)
        feed_lay.addLayout(composer_row)

        status_row = QHBoxLayout()
        status_row.setSpacing(12)
        self._agent_status = QLabel("● Готов к работе")
        self._agent_status.setFont(app_font(12))
        self._agent_status.setWordWrap(True)
        self._agent_status.setStyleSheet("color: #08745F; background: transparent;")
        self._run_btn = QPushButton("Запустить сборку")
        self._run_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._run_btn.setFont(app_font(12, QFont.Weight.DemiBold))
        self._run_btn.setFixedHeight(32)
        self._run_btn.setStyleSheet(
            """
            QPushButton {
                background: #08745F; color: #FFFFFF; border: none;
                border-radius: 12px; padding: 0 14px;
            }
            QPushButton:hover { background: #0A8670; }
            QPushButton:disabled { background: #A8C8BF; color: #EAF7F3; }
            """
        )
        self._run_btn.clicked.connect(self._on_run_clicked)
        self._run_btn.setVisible(False)
        self._next_btn = QPushButton("Далее")
        self._next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._next_btn.setFont(app_font(12, QFont.Weight.DemiBold))
        self._next_btn.setFixedHeight(32)
        self._next_btn.setStyleSheet(
            """
            QPushButton {
                background: #08745F; color: #FFFFFF; border: none;
                border-radius: 12px; padding: 0 14px;
            }
            QPushButton:hover { background: #0A8670; }
            QPushButton:disabled { background: #A8C8BF; color: #EAF7F3; }
            """
        )
        self._next_btn.clicked.connect(self._on_schedule_requested)
        self._next_btn.setVisible(False)
        self._tests_ok = False
        status_row.addWidget(self._agent_status, 1)
        status_row.addWidget(self._run_btn, 0)
        status_row.addWidget(self._next_btn, 0)
        feed_lay.addLayout(status_row)

        # hidden results list for downloads
        self._results = QListWidget()
        self._results.setVisible(False)
        self._results.itemDoubleClicked.connect(self._open_result_item)
        feed_lay.addWidget(self._results)

        self._stepper = StageStepper()

        body = QHBoxLayout()
        body.setSpacing(16)
        body.addWidget(feed_card, 1)
        body.addWidget(self._stepper, 0)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        root.addWidget(title)
        root.addLayout(body, 1)

        self._busy_timer = QTimer(self)
        self._busy_timer.setInterval(400)
        self._busy_timer.timeout.connect(self._tick_activity)
        self._busy_base = "Агент работает"
        self._busy_n = 0

    # --- public API ------------------------------------------------------------

    def load_record(self, record: WorkflowRecord) -> None:
        self._record = record
        self._pending_paths = []
        self._workflow_title = record.title
        self._notes = record.notes
        local = dict(record.local_run or {})
        self._tests_ok = str(local.get("tests_status") or "").casefold() == "pass" and (
            record.phase == "tested"
            or str(local.get("exec_run_status") or "").upper() == "FINISHED"
        )
        if local.get("autonomy_level") or local.get("autonomy_policy"):
            self._passport_runtime = {
                "autonomy_level": int(local.get("autonomy_level") or 1),
                "autonomy_policy": str(local.get("autonomy_policy") or ""),
            }
        self._sync_desktop_capability(record.id, local)
        self._events = [
            FeedEvent(
                "Загрузка workflow",
                f"Открыт «{record.title}» · фаза {record.phase}",
                self._now(),
            )
        ]
        if record.plan:
            self._events.append(
                FeedEvent(
                    "План",
                    record.plan.goal or record.plan.title or "План загружен",
                    self._now(),
                    action="Показать шаги плана",
                    action_key="show_plan",
                )
            )
            first_q = next(iter(record.plan.unanswered()), None)
            if first_q is not None:
                self._events.append(
                    FeedEvent(
                        "Уточнение",
                        first_q.question,
                        self._now(),
                    )
                )
        if record.last_result:
            self._events.append(
                FeedEvent("Результат", record.last_result, self._now())
            )
        self._render_chips()
        self._render_all()

    def start_from_passport(self, session: PassportSession, *, auto_plan: bool = True) -> None:
        self._on_new()
        title = (session.passport.name or session.bp_name or "ИИ-агент").strip()
        self._workflow_title = title
        self._notes = _notes_from_passport(session)
        self._passport_runtime = {
            "autonomy_level": int(getattr(session.passport, "autonomy_level", 1) or 1),
            "autonomy_policy": (
                "Уровень 1: генерация текста, инструменты чтения и human-in-the-loop; "
                "запись и прочие операции только после подтверждения человека."
            ),
        }
        self._push_event(
            "Анализ документа",
            f"Загружен паспорт «{title}». Готовлю план реализации…",
        )
        if auto_plan:
            self._on_plan()

    def _persist_passport_runtime(self, record: WorkflowRecord) -> WorkflowRecord:
        if not self._passport_runtime:
            return record
        local = dict(record.local_run or {})
        level = int(self._passport_runtime.get("autonomy_level") or 1)
        policy = str(self._passport_runtime.get("autonomy_policy") or "")
        if int(local.get("autonomy_level") or 0) == level and str(local.get("autonomy_policy") or "") == policy:
            return record
        local["autonomy_level"] = level
        local["autonomy_policy"] = policy
        try:
            return self._api.update_workflow_local_run(record.id, local)
        except ApiError:
            return record

    def _desktop_capability_payload(self) -> dict[str, object]:
        capability = com_availability.describe_com_capability()
        return {"desktop": capability}

    def _merge_desktop_capability(self, local: dict[str, object]) -> dict[str, object]:
        return _merge_desktop_capability(local, self._desktop_capability_payload()["desktop"])

    def _ensure_desktop_capability(self, workflow_id: str, local: dict[str, object]) -> None:
        if not workflow_id:
            return
        try:
            updated = self._api.update_workflow_local_run(
                workflow_id,
                self._merge_desktop_capability(local),
            )
        except ApiError:
            return
        if self._record and self._record.id == updated.id:
            self._record = updated

    def _sync_desktop_capability(self, workflow_id: str, local: dict[str, object]) -> None:
        if not workflow_id:
            return
        capability = self._desktop_capability_payload()
        current = local.get("desktop") if isinstance(local.get("desktop"), dict) else {}
        if current == capability["desktop"]:
            return

        def run() -> None:
            try:
                updated = self._api.update_workflow_local_run(
                    workflow_id,
                    self._merge_desktop_capability(local),
                )
            except ApiError:
                return
            if self._record and self._record.id == updated.id:
                self._record = updated

        Thread(target=run, daemon=True).start()

    # --- render ----------------------------------------------------------------

    def _render_all(self) -> None:
        phase = self._record.phase if self._record else "document"
        self._stepper.set_phase(phase)
        self._rebuild_feed()
        plan = self._record.plan if self._record else None
        unanswered = bool(plan and plan.unanswered())
        can_run = bool(plan) and not unanswered and not self._busy and not self._post_build_question
        self._run_btn.setVisible(can_run)
        self._run_btn.setEnabled(can_run)
        if self._record and self._record.exec_agent_id:
            self._run_btn.setText("Запустить снова")
        else:
            self._run_btn.setText("Запустить сборку")
        can_next = bool(
            self._record
            and self._tests_ok
            and not self._busy
            and self._record.phase != "done"
        )
        self._next_btn.setVisible(can_next)
        self._next_btn.setEnabled(can_next)
        if self._post_build_question and not self._busy:
            self._current_question_id = self._post_build_question.id
        elif self._record and self._record.plan and not self._busy:
            self._sync_question_state(self._record.plan)
        else:
            self._current_question_id = ""
            self._selected_quick_answer = ""
            self._question_fields = {}
        if self._busy:
            self._agent_status.setText("● Агент работает — можно отправить уточнение")
            self._agent_status.setStyleSheet("color: #08745F; background: transparent;")
        elif can_next:
            self._agent_status.setText("● Тесты PASS — откройте паспорт и укажите, когда запускать")
            self._agent_status.setStyleSheet("color: #08745F; background: transparent;")
        elif self._post_build_question:
            self._agent_status.setText("● Нужны уточнения после сборки — ответьте в чате")
            self._agent_status.setStyleSheet("color: #C47E00; background: transparent;")
        elif (
            self._record
            and str((self._record.local_run or {}).get("tests_status") or "").casefold()
            in {"fail", "unknown"}
            and self._record.phase in {"ready", "tested"}
        ):
            self._agent_status.setText("● Тесты не пройдены — уточните в чате и перезапустите")
            self._agent_status.setStyleSheet("color: #C47E00; background: transparent;")
        elif unanswered:
            self._agent_status.setText("● Нужны уточнения — выберите вариант в чате")
            self._agent_status.setStyleSheet("color: #C47E00; background: transparent;")
        elif plan and not unanswered:
            self._agent_status.setText("● План готов — можно запускать")
            self._agent_status.setStyleSheet("color: #08745F; background: transparent;")
        else:
            self._agent_status.setText("● Готов к работе")
            self._agent_status.setStyleSheet("color: #08745F; background: transparent;")

    def _sync_feed_scroll_state(self, *_args) -> None:
        if self._feed_rebuilding:
            return
        bar = self._feed_scroll.verticalScrollBar()
        self._feed_stick_to_bottom = bar.value() >= max(0, bar.maximum() - 48)

    def _on_feed_range_changed(self, _minimum: int, _maximum: int) -> None:
        if self._feed_stick_to_bottom:
            self._scroll_feed_to_bottom()

    def _scroll_feed_to_bottom(self) -> None:
        def _go() -> None:
            if not self._feed_stick_to_bottom:
                return
            bar = self._feed_scroll.verticalScrollBar()
            bar.setValue(bar.maximum())

        QTimer.singleShot(0, _go)
        QTimer.singleShot(80, _go)
        QTimer.singleShot(200, _go)

    def _rebuild_feed(self) -> None:
        self._feed_rebuilding = True
        try:
            self._rebuild_feed_body()
        finally:
            self._feed_rebuilding = False
            self._scroll_feed_to_bottom()

    def _rebuild_feed_body(self) -> None:
        while self._feed_layout.count():
            item = self._feed_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        # Drop stale answer widgets from previous rebuild.
        self._question_fields = {}
        self._answer_group = None

        plan_question = (
            self._record is not None
            and self._record.plan is not None
            and bool(self._record.plan.unanswered())
            and not self._busy
        )
        post_question = bool(self._post_build_question) and not self._busy
        show_question = plan_question or post_question
        current_q_text = ""
        if plan_question and self._record and self._record.plan:
            current_q_text = (self._record.plan.unanswered()[0].question or "").strip()
        elif post_question and self._post_build_question is not None:
            current_q_text = (self._post_build_question.question or "").strip()

        # Hide only the *current* open question duplicate (card shows it).
        # Keep all previously asked questions visible in the chat history.
        skip_clarify_idx: int | None = None
        if show_question and current_q_text:
            for i in range(len(self._events) - 1, -1, -1):
                ev = self._events[i]
                if ev.title == "Уточнение" and (ev.body or "").strip() == current_q_text:
                    skip_clarify_idx = i
                    break

        for idx, event in enumerate(self._events):
            if skip_clarify_idx is not None and idx == skip_clarify_idx:
                continue
            if event.action_key.startswith("q:"):
                widget = FeedItem(
                    FeedEvent(
                        event.title,
                        event.body,
                        event.time,
                        action="",
                        action_key="",
                        role=event.role,
                    )
                )
            else:
                widget = FeedItem(event)
            widget.action_clicked.connect(self._on_feed_action)
            self._feed_layout.addWidget(widget)
        thinking = _visible_thinking(self._thinking_text)
        if thinking:
            think = QLabel(thinking)
            think.setWordWrap(True)
            think.setMinimumWidth(0)
            think.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            think.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            think.setFont(app_font(12))
            think.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            think.setStyleSheet(
                f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent; "
                "padding: 2px 8px 10px 8px;"
            )
            self._feed_layout.addWidget(think)
        if plan_question and self._record and self._record.plan:
            card = self._make_clarification_message(self._record.plan.unanswered()[0])
            self._feed_layout.addWidget(card)
        elif post_question and self._post_build_question is not None:
            card = self._make_clarification_message(self._post_build_question)
            self._feed_layout.addWidget(card)
        self._feed_layout.addStretch(1)

    def _render_chips(self) -> None:
        while self._chips_layout.count():
            item = self._chips_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        names: list[str] = []
        if self._record:
            names.extend(att.name for att in (self._record.attachments or []) if att.name)
        names.extend(Path(p).name for p in self._pending_paths)
        for name in names[:8]:
            chip = QFrame()
            chip.setObjectName("filechip")
            chip.setStyleSheet(_CHIP)
            lay = QHBoxLayout(chip)
            lay.setContentsMargins(10, 4, 8, 4)
            lay.setSpacing(6)
            lbl = QLabel(name)
            lbl.setFont(app_font(11))
            lbl.setStyleSheet("background: transparent; color: #06483D;")
            lay.addWidget(lbl)
            self._chips_layout.addWidget(chip)
        self._chips_layout.addStretch(1)
        self._chips_wrap.setVisible(bool(names))

    def _push_event(
        self,
        title: str,
        body: str,
        *,
        action: str = "",
        action_key: str = "",
        role: str = "",
    ) -> None:
        resolved_role = role
        if not resolved_role:
            resolved_role = (
                "user"
                if title.strip().casefold() in {"вы", "you"}
                else "agent"
            )
        self._events.append(
            FeedEvent(
                title=title,
                body=body,
                time=self._now(),
                action=action,
                action_key=action_key,
                role=resolved_role,
            )
        )
        self._rebuild_feed()

    def _ensure_question_in_feed(self, question_text: str) -> None:
        """Keep the asked question visible in history (do not lose it after answer)."""
        text = (question_text or "").strip()
        if not text:
            return
        for ev in reversed(self._events):
            if ev.title == "Уточнение" and (ev.body or "").strip() == text:
                return
        self._events.append(
            FeedEvent(
                title="Уточнение",
                body=text,
                time=self._now(),
                role="agent",
            )
        )

    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%H:%M")

    # --- interactions ----------------------------------------------------------

    def _on_feed_action(self, key: str) -> None:
        if key == "show_plan" and self._record and self._record.plan:
            plan = self._record.plan
            lines = [f"{s.id}: {s.title}" for s in (plan.steps or [])]
            self._push_event("Шаги плана", "\n".join(lines) or plan.goal or "—")
        elif key == "run_plan":
            self._on_execute()
        elif key == "fetch":
            self._on_fetch_results()
        elif key == "save":
            self._on_schedule_requested()
        elif key == "next":
            self._on_schedule_requested()
        elif key.startswith("q:"):
            self._input.setFocus()

    def _on_pick_files(self) -> None:
        patterns = " ".join(f"*{s}" for s in sorted(SUPPORTED_SUFFIXES))
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Приложить файлы", "", f"Документы ({patterns});;Все файлы (*)"
        )
        for path in paths:
            if path and Path(path).is_file() and path not in self._pending_paths:
                suffix = Path(path).suffix.lower()
                if suffix and suffix not in SUPPORTED_SUFFIXES:
                    continue
                self._pending_paths.append(path)
        self._render_chips()

    def _on_send(self) -> None:
        text = self._input.text().strip()
        if self._current_question_id:
            if text:
                field = self._question_fields.get(self._current_question_id)
                if isinstance(field, QLineEdit):
                    field.setText(text)
                    self._selected_quick_answer = ""
                self._input.clear()
            self._submit_question_answer()
            return
        if not text and not self._pending_paths:
            return
        self._input.clear()

        if self._record is None:
            if text:
                self._notes = (self._notes + "\n" + text).strip() if self._notes else text
            self._push_event("Вы", text or "Материалы приложены")
            self._on_plan()
            return

        # Free-form message while plan ready → replan or execute hint
        self._push_event("Вы", text)
        if self._record.plan and not self._record.plan.unanswered():
            self._push_event(
                "Агент",
                "План уже готов. Нажмите «Запустить», чтобы собрать workflow, "
                "или уточните требования — пересоберу план.",
                action="Запустить сборку",
                action_key="run_plan",
            )
        else:
            self._on_plan()

    def _append_user_files_to_event(self) -> None:
        if self._pending_paths:
            names = ", ".join(Path(p).name for p in self._pending_paths)
            self._push_event("Вложения", names)

    def _set_busy(self, busy: bool, base: str = "Агент работает") -> None:
        self._busy = busy
        self._send_btn.setEnabled(True)  # allow clarify while working, per mockup
        self._clip_btn.setEnabled(True)
        if busy:
            self._busy_base = base
            self._busy_n = 0
            self._busy_timer.start()
            self._tick_activity()
        else:
            self._busy_timer.stop()
            self._render_all()

    def _tick_activity(self) -> None:
        self._busy_n = (self._busy_n % 3) + 1
        self._agent_status.setText(f"● {self._busy_base}{'.' * self._busy_n}")

    def _run_async(self, label: str, fn) -> None:
        self._thinking_text = ""
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

    def _on_stream_event(self, event_type: str, text: str) -> None:
        if event_type == "thinking" and text:
            self._thinking_text += text
            if not self._thinking_timer.isActive():
                self._thinking_timer.start()
        elif event_type in {"decision", "system"} and text.strip():
            # short status lines stay as gray thinking context, not agent cards
            self._thinking_text = (self._thinking_text + "\n" + text.strip()).strip()
            if not self._thinking_timer.isActive():
                self._thinking_timer.start()

    def _on_async_ok(self, result: object, label: str) -> None:
        self._set_busy(False)
        if isinstance(result, WorkflowRecord):
            self._record = self._persist_passport_runtime(result)
            self._pending_paths = []
            self._workflow_title = result.title
            self._notes = result.notes or self._notes
            self._render_chips()
            if label.startswith("Планирование"):
                unanswered = result.plan.unanswered() if result.plan else []
                goal = (result.plan.goal if result.plan else "") or result.title
                self._thinking_text = ""
                self._push_event(
                    "План",
                    goal,
                    action="Показать шаги плана",
                    action_key="show_plan",
                )
                if unanswered:
                    q = unanswered[0]
                    self._push_event("Уточнение", q.question)
                else:
                    self._push_event(
                        "Сборка workflow",
                        "План готов без открытых вопросов. Можно запускать реализацию.",
                        action="Запустить сборку",
                        action_key="run_plan",
                    )
            elif label.startswith("Уточнение"):
                self._thinking_text = ""
                unanswered = result.plan.unanswered() if result.plan else []
                if unanswered:
                    q = unanswered[0]
                    self._push_event("Уточнение", q.question)
                else:
                    self._push_event(
                        "Сборка workflow",
                        "Уточнения учтены. План готов к запуску.",
                        action="Запустить сборку",
                        action_key="run_plan",
                    )
            elif label.startswith("Реализация"):
                self._thinking_text = ""
                self._tests_ok = False
                local = dict(getattr(result, "local_run", None) or {})
                tests = str(local.get("tests_status") or "").casefold()
                exec_status = str(local.get("exec_run_status") or "").upper()
                finished = exec_status == "FINISHED" or result.phase == "tested"
                report = (result.last_result or "").strip()
                if tests == "pass" and finished:
                    body = report or "TESTS: PASS."
                elif tests == "fail":
                    prefix = "Тестовый прогон не завершён. Сохранение недоступно.\n\n"
                    body = prefix + report if report else "TESTS: FAIL — сохранение недоступно."
                else:
                    prefix = "Тестовый прогон не завершён — перезапустите сборку.\n\n"
                    body = prefix + report if report else "Тестовый прогон не завершён — перезапустите сборку."
                self._push_event(
                    "Тестовый прогон",
                    body,
                    action="Скачать результат" if result.exec_agent_id else "",
                    action_key="fetch",
                )
                self._on_fetch_results()
            elif label.startswith("Публикация"):
                self._thinking_text = ""
                self._push_event(
                    "Сохранено",
                    "Агент опубликован в «Мои агенты».",
                )
            self.saved.emit(result.id)
            if result.phase == "done":
                self.saved_record.emit(result)
            self._render_all()
        elif isinstance(result, tuple) and len(result) == 2:
            dest_dir, files = result
            self._results_dir = str(dest_dir)
            self._results.clear()
            for path in files:
                item = QListWidgetItem(Path(path).name)
                item.setData(Qt.ItemDataRole.UserRole, path)
                self._results.addItem(item)
            if files:
                download_text = f"Скачано файлов: {len(files)}\n{dest_dir}"
            else:
                download_text = (
                    "Файлы результата не найдены (агент не положил их в artifacts/).\n"
                    f"{dest_dir}"
                )
            self._push_event("Результат", download_text)
            self._evaluate_tests(list(files))
            self._render_all()

    def _on_async_fail(self, message: str) -> None:
        self._set_busy(False)
        self._push_event("Ошибка", message)
        self._agent_status.setText("● Ошибка — попробуйте ещё раз")
        self._agent_status.setStyleSheet("color: #B00020; background: transparent;")

    def _on_plan(self) -> None:
        notes = (self._notes or "").strip()
        if self._record is None:
            if not notes and not self._pending_paths:
                QMessageBox.warning(
                    self,
                    "Документ",
                    "Нет материалов. Откройте workflow из паспорта агента.",
                )
                return
            self._push_event("Анализ документа", "Создаю workflow и запускаю планирование…")

            def create_and_plan() -> WorkflowRecord:
                created = self._api.create_workflow(notes=notes, file_paths=self._pending_paths)
                created = self._persist_passport_runtime(created)
                local = dict(created.local_run or {})
                local.update(self._desktop_capability_payload())
                try:
                    created = self._api.update_workflow_local_run(created.id, local)
                except ApiError:
                    pass
                planned = self._api.stream_plan_workflow(
                    created.id,
                    lambda event_type, text: self._stream_event.emit(event_type, text),
                )
                return self._persist_passport_runtime(planned)

            self._run_async("Планирование", create_and_plan)
            return
        self._push_event("План", "Пересобираю план…")
        self._run_async(
            "Планирование",
            lambda: self._api.stream_plan_workflow(
                self._record.id,  # type: ignore[union-attr]
                lambda event_type, text: self._stream_event.emit(event_type, text),
            ),
        )

    def _sync_question_state(self, plan: WorkflowPlan) -> None:
        unanswered = plan.unanswered()
        if not unanswered:
            self._current_question_id = ""
            self._selected_quick_answer = ""
            self._question_fields = {}
            return
        self._current_question_id = unanswered[0].id

    def _make_clarification_message(self, question: WorkflowOpenQuestion) -> QWidget:
        """Clarification with options — rendered as an agent message in the chat feed."""
        self._current_question_id = question.id
        self._question_fields = {}

        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        wrap.setMinimumWidth(0)
        wrap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        row = QHBoxLayout(wrap)
        row.setContentsMargins(4, 8, 4, 8)
        row.setSpacing(10)

        avatar = QLabel("🤖")
        avatar.setFixedSize(36, 36)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet(
            """
            background: #E8F5F1; border-radius: 18px;
            font-size: 16px;
            """
        )
        row.addWidget(avatar, 0, Qt.AlignmentFlag.AlignTop)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        meta = QHBoxLayout()
        meta.setContentsMargins(0, 0, 0, 0)
        head = QLabel("Уточнение")
        head.setFont(app_font(13, QFont.Weight.DemiBold))
        head.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        time = QLabel(self._now())
        time.setFont(app_font(11))
        time.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        meta.addWidget(head, 1)
        meta.addWidget(time, 0)
        col.addLayout(meta)

        card = QFrame()
        card.setObjectName("qcard")
        card.setStyleSheet(_QCARD)
        card.setMinimumWidth(0)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        title = _WrappingLabel("Агенту нужно уточнение")
        title.setFont(app_font(12, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #8A5300; background: transparent;")
        question_label = _WrappingLabel(question.question)
        question_label.setFont(app_font(13, QFont.Weight.DemiBold))
        question_label.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        lay.addWidget(title)
        lay.addWidget(question_label)
        if question.why:
            why = _WrappingLabel(question.why)
            why.setFont(app_font(11))
            why.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
            lay.addWidget(why)

        group = QButtonGroup(card)
        self._answer_group = group
        group.setExclusive(True)
        for answer in _quick_answers_for_question(question):
            # QRadioButton text does not wrap — indicator + wrapping label.
            opt_row = QHBoxLayout()
            opt_row.setContentsMargins(0, 0, 0, 0)
            opt_row.setSpacing(8)
            option = QRadioButton()
            option.setCursor(Qt.CursorShape.PointingHandCursor)
            option.setStyleSheet(_RADIO_OPTION)
            option.setFixedWidth(22)
            option.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            opt_text = _WrappingLabel(answer)
            opt_text.setFont(app_font(12))
            opt_text.setCursor(Qt.CursorShape.PointingHandCursor)
            opt_text.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
            opt_text.mousePressEvent = (  # type: ignore[method-assign]
                lambda _ev, btn=option: btn.setChecked(True)
            )
            option.toggled.connect(
                lambda checked=False, value=answer: self._select_quick_answer(value)
                if checked
                else None
            )
            group.addButton(option)
            opt_row.addWidget(option, 0, Qt.AlignmentFlag.AlignTop)
            opt_row.addWidget(opt_text, 1)
            lay.addLayout(opt_row)

        custom_row = QHBoxLayout()
        custom_row.setSpacing(8)
        custom_option = QRadioButton("Свой вариант")
        custom_option.setCursor(Qt.CursorShape.PointingHandCursor)
        custom_option.setFont(app_font(12))
        custom_option.setStyleSheet(_RADIO_OPTION)
        custom_input = QLineEdit()
        custom_input.setPlaceholderText("Напишите свой ответ")
        custom_input.setFont(app_font(12))
        custom_input.setMinimumWidth(0)
        custom_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        custom_input.setStyleSheet(_CUSTOM_ANSWER_FIELD)
        self._question_fields[question.id] = custom_input
        group.addButton(custom_option)
        custom_row.addWidget(custom_option, 0)
        custom_row.addWidget(custom_input, 1)
        lay.addLayout(custom_row)

        custom_option.toggled.connect(
            lambda checked=False, field=custom_input: field.setFocus() if checked else None
        )
        custom_input.textEdited.connect(
            lambda _value, option=custom_option: option.setChecked(True)
            if not option.isChecked()
            else None
        )
        custom_input.textEdited.connect(lambda _value: self._select_custom_answer())

        hint = _WrappingLabel("Выберите вариант или заполните свой ответ, затем «Далее».")
        hint.setFont(app_font(11))
        hint.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        lay.addWidget(hint)

        next_row = QHBoxLayout()
        next_row.addStretch(1)
        next_btn = QPushButton("Далее")
        next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        next_btn.setFixedHeight(34)
        next_btn.setMinimumWidth(110)
        next_btn.setFont(app_font(12, QFont.Weight.DemiBold))
        next_btn.setStyleSheet(_PRIMARY)
        next_btn.clicked.connect(self._submit_question_answer)
        next_row.addWidget(next_btn)
        lay.addLayout(next_row)

        col.addWidget(card)
        row.addLayout(col, 1)
        return wrap

    def _clear_questions(self) -> None:
        self._question_fields = {}
        self._answer_group = None
        self._current_question_id = ""
        self._selected_quick_answer = ""

    def _select_quick_answer(self, answer: str) -> None:
        self._selected_quick_answer = answer
        field = self._question_fields.get(self._current_question_id)
        if isinstance(field, QLineEdit):
            field.clear()

    def _select_custom_answer(self) -> None:
        self._selected_quick_answer = ""

    def _current_answer_text(self) -> str:
        if self._current_question_id:
            field = self._question_fields.get(self._current_question_id)
            if isinstance(field, QLineEdit):
                custom = field.text().strip()
                if custom:
                    return custom
            if self._selected_quick_answer.strip():
                return self._selected_quick_answer.strip()
        return self._input.text().strip()

    def _submit_question_answer(self) -> None:
        if not self._current_question_id or self._record is None:
            return
        text = self._current_answer_text()
        if not text and not self._pending_paths:
            QMessageBox.information(
                self,
                "Ответ",
                "Выберите вариант, заполните свой ответ или приложите файл.",
            )
            return
        qid = self._current_question_id
        asked = ""
        if qid.startswith("post-build-") and self._post_build_question is not None:
            asked = self._post_build_question.question
        elif self._record and self._record.plan:
            for q in self._record.plan.unanswered():
                if q.id == qid:
                    asked = q.question
                    break
            if not asked and self._record.plan.unanswered():
                asked = self._record.plan.unanswered()[0].question
        self._ensure_question_in_feed(asked)
        self._push_event("Вы", text or "Файл приложен", role="user")
        self._append_user_files_to_event()

        # After-build clarification → apply answer and re-run assembly.
        if qid.startswith("post-build-"):
            note = f"Уточнение после сборки: {text}"
            self._notes = (self._notes + "\n" + note).strip() if self._notes else note
            self._post_build_question = None
            self._clear_questions()
            wid = self._record.id
            local = dict(self._record.local_run or {})
            local.update(
                {
                    "post_build_answer": text,
                    "can_publish": False,
                    "tests_status": "unknown",
                }
            )
            self._ensure_desktop_capability(wid, local)

            def work() -> WorkflowRecord:
                self._api.update_workflow_local_run(wid, local)
                try:
                    return self._api.stream_execute_workflow(
                        wid,
                        lambda event_type, t: self._stream_event.emit(event_type, t),
                        reexecute=True,
                    )
                except Exception:  # noqa: BLE001
                    return self._api.execute_workflow(wid, reexecute=True)

            self._push_event("Сборка workflow", "Учитываю уточнение и запускаю повторную сборку…")
            self._run_async("Реализация", work)
            return

        answers = {qid: text}
        wid = self._record.id
        paths = list(self._pending_paths)
        qids = [qid] * len(paths) if paths else []
        self._clear_questions()

        def clarify() -> WorkflowRecord:
            return self._api.stream_clarify_workflow(
                wid,
                answers,
                lambda event_type, t: self._stream_event.emit(event_type, t),
                file_paths=paths,
                file_question_ids=qids,
            )

        self._run_async("Уточнение плана", clarify)

    def _on_run_clicked(self) -> None:
        reexecute = bool(self._record and self._record.exec_agent_id)
        self._on_execute(reexecute=reexecute)

    def _on_execute(self, reexecute: bool = False) -> None:
        if self._record is None or self._record.plan is None:
            QMessageBox.information(self, "План", "Сначала постройте план.")
            return
        if self._record.plan.unanswered():
            QMessageBox.information(self, "Уточнения", "Сначала ответьте на вопросы агента.")
            return
        self._ensure_desktop_capability(self._record.id, dict(self._record.local_run or {}))
        self._tests_ok = False
        self._post_build_question = None
        self._next_btn.setVisible(False)
        self._push_event("Сборка workflow", "Запускаю реализацию…")
        wid = self._record.id
        self._run_async(
            "Реализация",
            lambda: self._api.execute_workflow(wid, reexecute=reexecute),
        )

    def _on_fetch_results(self) -> None:
        if self._record is None or not self._record.exec_agent_id:
            return
        wid = self._record.id

        def work():
            result = self._api.download_workflow_artifacts(wid)
            return result.dest_dir, result.files

        self._run_async("Скачивание", work)

    def _evaluate_tests(self, files: list[str]) -> None:
        """Require TESTS: PASS in RESULT.md / last_result before save is allowed."""
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
        explicit_fail = "TESTS: FAIL" in upper or "TESTS:FAIL" in upper
        explicit_pass = "TESTS: PASS" in upper or "TESTS:PASS" in upper
        self._tests_ok = False
        self._post_build_question = None
        local_state = dict(self._record.local_run or {}) if self._record else {}
        exec_status = str(local_state.get("exec_run_status") or "").upper()
        run_finished = exec_status == "FINISHED" or (
            self._record is not None and self._record.phase == "tested"
        )
        ctx_bits: list[str] = []
        if self._record:
            if self._record.title:
                ctx_bits.append(self._record.title)
            if self._record.plan and self._record.plan.goal:
                ctx_bits.append(self._record.plan.goal)
            for q in getattr(self._record.plan, "answered_questions", None) or []:
                ans = getattr(q, "answer", "") or ""
                if ans:
                    ctx_bits.append(f"{getattr(q, 'question', '')} {ans}")
        context = " | ".join(ctx_bits)[:500]
        if explicit_fail:
            self._post_build_question = _extract_post_build_question(blob, context=context)
            self._ensure_question_in_feed(self._post_build_question.question)
            self._push_event(
                "Тесты",
                "TESTS: FAIL — сохранение недоступно. Ответьте на вопрос агента в чате.",
            )
            self._render_all()
            return
        if not explicit_pass:
            self._post_build_question = _extract_post_build_question(blob, context=context)
            self._ensure_question_in_feed(self._post_build_question.question)
            self._push_event(
                "Тесты",
                "TESTS: PASS не найден — сохранение недоступно. Ответьте на вопрос агента в чате.",
            )
            self._render_all()
            return
        if not run_finished:
            self._push_event(
                "Тесты",
                "Тестовый прогон не завершён — сохранение недоступно. Перезапустите сборку.",
            )
            self._render_all()
            return

        self._tests_ok = True
        self._push_event(
            "Тесты",
            "TESTS: PASS. Нажмите «Далее», чтобы заполнить паспорт и расписание.",
            action="Далее",
            action_key="next",
        )
        if self._record is None:
            return
        wid = self._record.id
        local = dict(self._record.local_run or {})
        local.update(
            {
                "status": "tested",
                "can_publish": True,
                "tests_status": "pass",
                "runtime": local.get("runtime") or "mcp",
            }
        )

        def sync() -> WorkflowRecord:
            return self._api.update_workflow_local_run(wid, local)

        try:
            self._record = sync()
        except ApiError as exc:
            self._push_event("Предупреждение", f"Не удалось зафиксировать TESTS: PASS на сервере: {exc}")

    def _on_schedule_requested(self) -> None:
        if self._record is None:
            return
        if not self._tests_ok:
            QMessageBox.information(
                self,
                "Тесты",
                "Паспорт доступен только после TESTS: PASS.",
            )
            return
        self.schedule_requested.emit(self._record)

    def _open_result_item(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _on_new(self) -> None:
        self._record = None
        self._pending_paths.clear()
        self._workflow_title = ""
        self._notes = ""
        self._passport_runtime = {}
        self._results_dir = ""
        self._tests_ok = False
        self._thinking_text = ""
        self._post_build_question = None
        self._clear_questions()
        self._events = []
        self._results.clear()
        self._render_chips()
        self._render_all()
        self._push_event(
            "Старт",
            "Опишите задачу или откройте паспорт агента — начну планирование.",
        )


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
                f"Уровень автономности: {int(getattr(passport, 'autonomy_level', 1) or 1)}",
            ]
        )
    lines = [
        f"# Паспорт ИИ-агента: {title}",
        "",
        "Составь план реализации ИИ-агента по согласованному паспорту.",
        "Уровень автономности: 1. Запись и прочие операции — только после подтверждения человека.",
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
