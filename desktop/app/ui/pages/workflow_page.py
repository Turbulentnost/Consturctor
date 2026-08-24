from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from threading import Thread

from PySide6.QtCore import QPointF, Qt, QSize, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QImage,
    QPainter,
    QPen,
    QPixmap,
    QRadialGradient,
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
from app.tools.hitl import attach_pending_for, register_inline_host, set_host_workflow_id
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, scroll_bar_qss
from app.ui.widgets.cursor_feed import CursorFeedItem, resolve_feed_kind

SUPPORTED_SUFFIXES = {
    ".txt", ".md", ".markdown", ".csv", ".json", ".xml", ".html", ".htm",
    ".yaml", ".yml", ".log", ".pdf", ".docx", ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".xlsx", ".xls",
}

_STAGES = [
    ("document", "Материалы", "Файлы загружены", "Добавляем материалы"),
    ("designed", "Черновик", "Черновик готов", "Проектируем инструкцию по регламенту"),
    ("executing", "Пробный прогон", "Задача выполнена", "Агент делает задачу как Cursor"),
    ("tested", "Инструкция", "Инструкция готова", "Пишем правило для следующих запусков"),
    ("done", "Готово", "Агент сохранён", "Можно запускать агента"),
]
_PHASE_RANK = {
    "document": 0,
    "designing": 1,
    "designed": 1,
    "plan": 2,
    "clarify": 1,
    "ready": 2,
    "executing": 2,
    "tested": 3,
    "done": 4,
}

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
    """Только варианты агента. Запасные «Да/Нет» не подставляем."""
    return [str(item).strip() for item in (question.options or []) if str(item).strip()][:4]


def _demo_already_ran_state(validation: dict | None) -> bool:
    """Прогон уже был: это не «черновик готов, сейчас сам стартую»."""
    state = validation if isinstance(validation, dict) else {}
    if state.get("demo_started") is True:
        return True
    return str(state.get("status") or "") == "demo_failed"


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


_JSON_FENCE_RE = re.compile(r"```json\s*(.*?)```", re.IGNORECASE | re.DOTALL)


def _extract_json_object(text: str) -> dict | None:
    cleaned = text or ""
    fence = _JSON_FENCE_RE.search(cleaned)
    blob = fence.group(1).strip() if fence else ""
    if not blob:
        start = cleaned.find("{")
        if start >= 0:
            blob = cleaned[start:]
    if not blob:
        return None
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _event_json(text: str) -> dict:
    raw = (text or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _compact_payload(value: object, *, limit: int = 1200) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, indent=2)
        except TypeError:
            text = str(value)
    text = (text or "").strip()
    return text[:limit].rstrip() if len(text) > limit else text


def _format_plan_dict(data: dict) -> str:
    lines: list[str] = []
    title = str(data.get("title") or "").strip()
    goal = str(data.get("goal") or "").strip()
    if title:
        lines.append(title)
    if goal:
        lines.append(f"Цель: {goal}")
    steps = data.get("steps") or []
    if isinstance(steps, list) and steps:
        if lines:
            lines.append("")
        lines.append("Шаги:")
        for index, step in enumerate(steps, 1):
            if not isinstance(step, dict):
                continue
            sid = str(step.get("id") or f"s{index}").strip()
            stitle = str(step.get("title") or "").strip()
            action = str(step.get("action") or "").strip()
            done = str(step.get("done_when") or "").strip()
            lines.append(f"{sid} — {stitle}" if stitle else sid)
            if action:
                lines.append(f"  {action}")
            if done:
                lines.append(f"  Готово когда: {done}")
    return "\n".join(lines).strip()


def _local_design_prompt_for_record(record: WorkflowRecord) -> str:
    title = (record.title or "ИИ-агент").strip()
    materials = "\n\n".join(
        item
        for item in (
            record.notes.strip(),
            record.document_text[:8000].strip(),
            "\n".join(
                str(getattr(item, "text_preview", "") or "").strip()
                for item in (record.attachments or [])
                if str(getattr(item, "text_preview", "") or "").strip()
            ),
        )
        if item
    )
    return (
        "Ты проектировщик ИИ-агента Constructor.\n"
        "Сформируй план, как агент будет достигать цели, и верни финальный JSON-черновик.\n"
        "Бизнес-задачу сейчас не выполняй: только проектирование инструкции.\n"
        "Верни JSON-объект с полями goal, inputs, required_clarifications, result, "
        "recipient, confirmation_points, steps.\n"
        "Если в материалах нет расписания, периода, получателя или критерия успеха, "
        "задай вопросы через SDK askQuestion и заполни required_clarifications "
        "вопросами с 2-4 вариантами. Не выдумывай эти параметры.\n"
        "Каждый step должен иметь id, title, action, done_when, on_empty, on_error.\n"
        f"Название агента: {title}\n\n"
        "Материалы:\n"
        f"{materials or title}"
    )


def _draft_from_sdk_answer(answer: str) -> dict:
    data = _extract_json_object(answer) or {}
    steps: list[dict] = []
    for index, raw in enumerate(data.get("steps") or [], start=1):
        if not isinstance(raw, dict):
            continue
        action = str(raw.get("action") or raw.get("operation") or raw.get("title") or "").strip()
        steps.append(
            {
                "id": str(raw.get("id") or f"s{index}").strip(),
                "title": str(raw.get("title") or action or f"Шаг {index}").strip(),
                "action": action,
                "done_when": str(raw.get("done_when") or raw.get("doneWhen") or "").strip(),
                "on_empty": str(raw.get("on_empty") or raw.get("onEmpty") or "").strip(),
                "on_error": str(raw.get("on_error") or raw.get("onError") or "").strip(),
            }
        )
    return {
        "status": "draft",
        "goal": str(data.get("goal") or "").strip(),
        "inputs": [str(x).strip() for x in (data.get("inputs") or []) if str(x).strip()],
        "required_clarifications": data.get("required_clarifications") or [],
        "result": str(data.get("result") or "").strip(),
        "recipient": str(data.get("recipient") or "").strip(),
        "confirmation_points": [
            str(x).strip() for x in (data.get("confirmation_points") or []) if str(x).strip()
        ],
        "steps": steps,
    }


def _format_plan_steps(plan: WorkflowPlan | None) -> str:
    if plan is None:
        return "План ещё не загружен."
    lines: list[str] = []
    if (plan.title or "").strip():
        lines.append(plan.title.strip())
    if (plan.goal or "").strip():
        lines.append(f"Цель: {plan.goal.strip()}")
    steps = list(plan.steps or [])
    if steps:
        if lines:
            lines.append("")
        lines.append("Шаги:")
        for step in steps:
            sid = (step.id or "").strip()
            stitle = (step.title or "").strip()
            head = f"{sid} — {stitle}".strip(" —") if sid or stitle else "шаг"
            lines.append(head)
            if (step.action or "").strip():
                lines.append(f"  {step.action.strip()}")
            if (step.done_when or "").strip():
                lines.append(f"  Готово когда: {step.done_when.strip()}")
    else:
        if lines:
            lines.append("")
        lines.append("Шагов в плане нет.")
        raw = (plan.raw_text or "").strip()
        if raw:
            lines.append("")
            lines.append(raw[:2000])
    return "\n".join(lines).strip() or "—"


_REPLACEMENT = "\ufffd"
_DEFAULT_WPS = 22.0
_MIN_WPS = 16.0
_MAX_WPS = 40.0
_PACER_MS = 33
_WPS_MAX_ELAPSED = 1.0


def _word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", text or ""))


def _same_feed_question(left: str, right: str) -> bool:
    na = " ".join((left or "").casefold().replace("ё", "е").split())
    nb = " ".join((right or "").casefold().replace("ё", "е").split())
    if not na or not nb:
        return False
    if na == nb:
        return True
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    return len(shorter) >= 24 and shorter in longer


def _take_words(text: str, count: int) -> str:
    if count <= 0 or not text:
        return ""
    matches = list(re.finditer(r"\S+\s*", text))
    if not matches:
        return text
    end = matches[min(count, len(matches)) - 1].end()
    return text[:end]


_TOOL_FENCE_RE = re.compile(
    r"```(?:constructor_tool|tool)\s*\n.*?```",
    re.DOTALL | re.IGNORECASE,
)
_TOOL_FENCE_OPEN_RE = re.compile(
    r"```(?:constructor_tool|tool)\b.*\Z",
    re.DOTALL | re.IGNORECASE,
)
_TOOL_JSON_RE = re.compile(
    r"\{\s*\"name\"\s*:\s*\"[^\"]+\"[\s\S]*?\"arguments\"\s*:\s*\{[\s\S]*?\}\s*\}",
)


def _looks_like_tool_json(text: str) -> bool:
    blob = (text or "").strip()
    if not blob.startswith("{"):
        return False
    return '"name"' in blob and '"arguments"' in blob


def _strip_tool_call_text(text: str) -> str:
    """Убрать из ответа агента вход вызова: fence constructor_tool и JSON name+arguments."""
    cleaned = _TOOL_FENCE_RE.sub("", text or "")
    cleaned = _TOOL_JSON_RE.sub("", cleaned)
    cleaned = _TOOL_FENCE_OPEN_RE.sub("", cleaned)
    last = cleaned.rfind("{")
    if last >= 0:
        tail = cleaned[last:]
        if _looks_like_tool_json(tail) and tail.count("{") > tail.count("}"):
            cleaned = cleaned[:last]
    return cleaned.strip()


def _stream_delta(streamed: str, chunk: str) -> str:
    """Хвост куска с учётом перекрытия: backend может присылать скользящее окно."""
    if not chunk:
        return ""
    if not streamed:
        return chunk
    if chunk.startswith(streamed):
        return chunk[len(streamed) :]
    if streamed.endswith(chunk) or chunk in streamed:
        return ""
    overlap = min(len(streamed), len(chunk))
    while overlap > 0:
        if streamed.endswith(chunk[:overlap]):
            return chunk[overlap:]
        overlap -= 1
    return chunk


def _visible_thinking(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return ""
    data = _extract_json_object(cleaned)
    if data and (data.get("steps") is not None or data.get("goal") or data.get("title")):
        parsed = _format_plan_dict(data)
        prefix = _JSON_FENCE_RE.sub("", cleaned)
        start = prefix.find("{")
        if start >= 0:
            prefix = prefix[:start]
        prefix = prefix.strip()
        if prefix and parsed:
            return f"{prefix}\n\n{parsed}"
        return parsed or prefix or cleaned
    return cleaned


class _WrappingLabel(QLabel):
    """QLabel that wraps inside constrained layouts (scroll feed / cards)."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def _available_width(self) -> int:
        w = self.width()
        if w >= 80:
            return w
        parent = self.parentWidget()
        while parent is not None:
            if parent.width() >= 80:
                return parent.width()
            parent = parent.parentWidget()
        return 420

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return max(super().heightForWidth(max(80, width)), 0)

    def sizeHint(self) -> QSize:  # noqa: N802
        w = self._available_width()
        return QSize(w, self.heightForWidth(w))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, 0)


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
            inner.adjustSize()


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
        "INVOKER",
        "TEST_PROJECT_REF",
        "TEST_STAGE_REF",
    }
)

_INFRA_FAIL_HINTS = (
    "onec",
    "1с",
    "1c",
    "odata",
    "invoker",
    "backend/.env",
    "constructor_api",
    "backend_url",
    "turboproject",
    "live-проверк",
    "live 1с",
    "live 1c",
    "нет канала",
    "с облака",
    "cloud vm",
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


def _is_infra_access_fail(blob: str) -> bool:
    low = (blob or "").casefold()
    return any(hint in low for hint in _INFRA_FAIL_HINTS)


def _fixtures_passed(blob: str) -> bool:
    low = (blob or "").casefold()
    if re.search(r"fixtures[^\n|]{0,160}pass", low):
        return True
    return "pytest pass" in low and "fixture" in low


def _result_md_from_files(files: list[str]) -> str:
    for path in files:
        if Path(path).name.lower() in {"result.md", "results.md"}:
            try:
                return Path(path).read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                continue
    return ""


def _has_subject_result(text: str) -> bool:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    meaningful = [
        ln
        for ln in lines
        if not ln.upper().replace(" ", "").startswith("TESTS:")
        and ln.casefold() not in {"pass", "fail"}
    ]
    return bool(meaningful)


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
    kind: str = ""
    event_key: str = ""


_TEMP_DIR = Path(__file__).resolve().parents[1] / "temp"
_CHECK_ICON_PATH = _TEMP_DIR / "зеленаягалочка.png"
_RAIL_W = 22
_DONE_DOT = 14
_IDLE_DOT = 10
_ACTIVE_CORE = 7
_ROW_PAD_Y = 8
_DOT_TOP = _ROW_PAD_Y + 9
_CHECK_SIZE = 8


def _white_check_icon(size: int = _CHECK_SIZE) -> QPixmap:
    """Green check on black → white check on transparent, then scaled."""
    if not _CHECK_ICON_PATH.exists():
        return QPixmap()
    src = QImage(str(_CHECK_ICON_PATH))
    if src.isNull():
        return QPixmap()
    img = src.convertToFormat(QImage.Format.Format_ARGB32)
    for y in range(img.height()):
        for x in range(img.width()):
            color = QColor.fromRgba(img.pixel(x, y))
            if color.red() < 48 and color.green() < 48 and color.blue() < 48:
                color.setAlpha(0)
                img.setPixelColor(x, y, color)
    punched = QPixmap.fromImage(img)
    out = QPixmap(punched.size())
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.drawPixmap(0, 0, punched)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(out.rect(), QColor("#FFFFFF"))
    painter.end()
    return out.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


class _StageRail(QWidget):
    """Vertical connector + title-aligned dots; active step has a small glowing core."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._kind = "mid"
        self._state = "idle"
        self.setFixedWidth(_RAIL_W)
        self.setMinimumHeight(20)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self._check = _white_check_icon()

    def set_kind(self, kind: str) -> None:
        self._kind = kind
        self.update()

    def set_state(self, state: str) -> None:
        self._state = state
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cx = self.width() / 2.0
        cy = float(_DOT_TOP)
        center = QPointF(cx, cy)

        if self._state == "active":
            glow = QRadialGradient(center, 11.0)
            glow.setColorAt(0.00, QColor(8, 116, 95, 230))
            glow.setColorAt(0.28, QColor(8, 116, 95, 150))
            glow.setColorAt(0.55, QColor(110, 210, 180, 80))
            glow.setColorAt(1.00, QColor(8, 116, 95, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(center, 11.0, 11.0)
            painter.setBrush(QColor("#08745F"))
            core = _ACTIVE_CORE / 2.0
            painter.drawEllipse(center, core, core)
            return

        if self._state == "done":
            radius = _DONE_DOT / 2.0
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#08745F"))
            painter.drawEllipse(center, radius, radius)
            if not self._check.isNull():
                pw = self._check.width()
                ph = self._check.height()
                painter.drawPixmap(int(cx - pw / 2), int(cy - ph / 2), self._check)
            return

        radius = _IDLE_DOT / 2.0
        painter.setPen(QPen(QColor("#C5D2CD"), 1.4))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(center, radius, radius)


class _StageRow(QFrame):
    def __init__(
        self,
        title: str,
        done_hint: str,
        active_hint: str,
        *,
        kind: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._title_text = title
        self._done_hint = done_hint
        self._active_hint = active_hint
        self._kind = kind
        self.setObjectName("stagerow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 10, 0)
        lay.setSpacing(8)
        self.rail = _StageRail()
        self.rail.set_kind(kind)
        texts = QVBoxLayout()
        texts.setContentsMargins(0, _ROW_PAD_Y, 0, _ROW_PAD_Y)
        texts.setSpacing(2)
        self.title = QLabel(title)
        self.title.setWordWrap(True)
        self.title.setFont(app_font(13, QFont.Weight.DemiBold))
        self.hint = QLabel(done_hint)
        self.hint.setWordWrap(True)
        self.hint.setFont(app_font(11))
        self.badge = QLabel("Выполняется…")
        self.badge.setFont(app_font(11, QFont.Weight.Medium))
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.setFixedHeight(22)
        self.badge.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.badge.setStyleSheet(
            """
            QLabel {
                background: #FFFFFF;
                color: #08745F;
                border: 1px solid #B7D6CE;
                border-radius: 11px;
                padding: 0 10px;
            }
            """
        )
        self.badge.setVisible(False)
        texts.addWidget(self.title)
        texts.addWidget(self.hint)
        texts.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(self.rail, 0)
        lay.addLayout(texts, 1)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        x = int(self.rail.x() + self.rail.width() / 2)
        cy = int(self.rail.y() + _DOT_TOP)
        painter.setPen(QPen(QColor("#D7E0DC"), 1))
        if self._kind != "first":
            painter.drawLine(x, 0, x, cy)
        if self._kind != "last":
            painter.drawLine(x, cy, x, self.height())

    def set_state(self, state: str, *, busy: bool = False) -> None:
        self.rail.set_state(state)
        if state == "done":
            self.setStyleSheet("QFrame#stagerow { background: transparent; border: none; }")
            self.title.setStyleSheet("color: #101817; background: transparent;")
            self.hint.setText(self._done_hint)
            self.hint.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
            self.badge.setVisible(False)
            return
        if state == "active":
            self.setStyleSheet(
                """
                QFrame#stagerow {
                    background: #F3F8F6;
                    border: 1px solid #08745F;
                    border-radius: 14px;
                }
                """
            )
            self.title.setStyleSheet("color: #101817; background: transparent;")
            self.hint.setText(self._active_hint)
            self.hint.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
            self.badge.setVisible(True)
            self.badge.setText("Выполняется…" if busy else "Текущий этап")
            return
        self.setStyleSheet("QFrame#stagerow { background: transparent; border: none; }")
        self.title.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        self.hint.setText(self._active_hint)
        self.hint.setStyleSheet("color: #9AA7A2; background: transparent;")
        self.badge.setVisible(False)


class StageStepper(QWidget):
    """Правая панель этапов: линия, маленькие кружки, карточка текущего шага."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._active = 0
        self._busy = False
        self._rows: list[_StageRow] = []
        self.setFixedWidth(272)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 16, 18)
        root.setSpacing(0)

        heading = QLabel("Создание агента")
        heading.setFont(app_font(15, QFont.Weight.DemiBold))
        heading.setStyleSheet("color: #06483D; background: transparent;")
        self._meta = QLabel("Этап 1 из 6 · 0%")
        self._meta.setFont(app_font(12))
        self._meta.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
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
        root.addWidget(heading)
        root.addSpacing(4)
        root.addWidget(self._meta)
        root.addSpacing(10)
        root.addWidget(self._bar)
        root.addSpacing(16)

        self._list = QVBoxLayout()
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(0)
        last = len(_STAGES) - 1
        for index, (_key, title, done_hint, active_hint) in enumerate(_STAGES):
            kind = "first" if index == 0 else "last" if index == last else "mid"
            row = _StageRow(title, done_hint, active_hint, kind=kind)
            self._rows.append(row)
            self._list.addWidget(row)
        root.addLayout(self._list)
        root.addStretch(1)

        self.setStyleSheet(
            """
            StageStepper {
                background: #FFFFFF;
                border: 1px solid rgba(16,24,23,0.08);
                border-radius: 18px;
            }
            """
        )
        self.set_phase("document")

    def set_phase(self, phase: str, *, busy: bool = False) -> None:
        rank = _PHASE_RANK.get(phase, 0)
        if phase == "done":
            rank = len(_STAGES) - 1
        self._active = rank
        self._busy = busy
        for i, row in enumerate(self._rows):
            if i < rank or (phase == "done" and i <= rank):
                state = "done"
            elif i == rank:
                state = "active"
            else:
                state = "idle"
            row.set_state(state, busy=busy and state == "active")
        total = len(_STAGES)
        current = total if phase == "done" else min(total, rank + 1)
        pct = 100 if phase == "done" else int(round((rank / max(1, total - 1)) * 100))
        self._meta.setText(f"Этап {current} из {total} · {pct}%")
        self._bar.setValue(pct)


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
        self._event_seq = 0
        self._expanded_keys: set[str] = set()
        self._collapsed_keys: set[str] = set()
        self._pending_answers: dict[str, str] = {}
        self._tests_ok = False
        self._thinking_text = ""
        self._thinking_received = ""
        self._thinking_shown = ""
        self._thinking_wps = _DEFAULT_WPS
        self._thinking_word_budget = 0.0
        self._thinking_chunk = ""
        self._thinking_chunk_at = 0.0
        self._thinking_live: CursorFeedItem | None = None
        self._assistant_live: CursorFeedItem | None = None
        self._stream_finished = False
        self._pending_async: tuple[object, str] | None = None
        self._pending_async_fail = ""
        self._post_build_question: WorkflowOpenQuestion | None = None
        self._execute_started = False
        self._planning_stream = False
        self._last_stream_phrase = ""
        self._last_stream_error = ""
        self._last_exec_report = ""
        self._live_tools: list[dict] = []
        self._live_tool_widgets: dict[str, CursorFeedItem] = {}
        self._hitl_cards: list[QWidget] = []
        self._activity_banner: QLabel | None = None
        self._busy_frames = ("◐", "◓", "◑", "◒")
        self._question_fields: dict[str, QLineEdit] = {}
        self._current_question_id = ""
        self._selected_quick_answer = ""
        self._answer_group: QButtonGroup | None = None
        self._async_ok.connect(self._on_async_ok)
        self._async_fail.connect(self._on_async_fail)
        self._stream_event.connect(self._on_stream_event)
        self._thinking_timer = QTimer(self)
        self._thinking_timer.setInterval(_PACER_MS)
        self._thinking_timer.timeout.connect(self._tick_thinking_pacer)
        self._feed_stick_to_bottom = True
        self._feed_rebuilding = False
        self._build()
        self._render_all()
        register_inline_host(self, "")

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
        self._feed_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

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
        self._composer_wrap = QWidget()
        self._composer_wrap.setStyleSheet("background: transparent;")
        self._composer_wrap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        composer_row = QHBoxLayout()
        composer_row.setContentsMargins(0, 0, 0, 0)
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
        self._composer_wrap.setLayout(composer_row)
        feed_lay.addWidget(self._composer_wrap)

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
        set_host_workflow_id(self, record.id)
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
        self._event_seq = 0
        self._expanded_keys = set()
        self._collapsed_keys = set()
        self._events = []
        self._execute_started = bool(record.exec_agent_id or record.last_result)
        self._last_stream_phrase = ""
        self._last_stream_error = ""
        self._last_exec_report = (record.last_result or "").strip()
        if record.plan:
            self._events.append(
                FeedEvent(
                    "План",
                    _format_plan_steps(record.plan),
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
                FeedEvent("Результат тестового прогона", record.last_result, self._now())
            )
        for ev in self._events:
            if not ev.event_key:
                ev.event_key = self._next_event_key()
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

    # --- render ----------------------------------------------------------------

    def _playbook(self) -> dict:
        local = (self._record.local_run if self._record else None) or {}
        playbook = local.get("playbook")
        return playbook if isinstance(playbook, dict) else {}

    def _validation_state(self, record: WorkflowRecord | None = None) -> dict:
        local = ((record or self._record).local_run if (record or self._record) else None) or {}
        validation = local.get("validation")
        return validation if isinstance(validation, dict) else {}

    def _draft_blocked_before_demo(self, record: WorkflowRecord | None = None) -> bool:
        validation = self._validation_state(record)
        if validation.get("status") == "blocked_before_demo":
            return True
        return validation.get("demo_started") is False and validation.get("can_run_demo") is False

    def _demo_already_ran(self, record: WorkflowRecord | None = None) -> bool:
        return _demo_already_ran_state(self._validation_state(record))

    def _can_run_demo(self, record: WorkflowRecord | None = None) -> bool:
        current = record or self._record
        if current is None or self._draft_blocked_before_demo(current):
            return False
        if self._demo_already_ran(current):
            return False
        validation = self._validation_state(current)
        if validation.get("can_run_demo") is False:
            return False
        return current.phase == "designed"

    def _draft_blocker_text(self, record: WorkflowRecord) -> str:
        validation = self._validation_state(record)
        message = str(validation.get("message") or "").strip()
        reasons = [str(item).strip() for item in (validation.get("reasons") or []) if str(item).strip()]
        if reasons:
            message = (message + "\n\n" if message else "") + "\n".join(f"• {item}" for item in reasons[:6])
        return message or "Пробный прогон не запускался: нужно исправить черновик."

    def _update_run_button(self, *, plan, unanswered: bool) -> None:
        del plan, unanswered
        show = bool(self._record) and not self._post_build_question
        self._run_btn.setVisible(show)
        if not show:
            return
        if self._busy:
            self._run_btn.setEnabled(False)
            self._run_btn.setText("Идёт прогон…" if self._execute_started else "Проектирую…")
            return
        self._run_btn.setEnabled(True)
        if self._record and self._record.phase == "designed":
            if self._draft_blocked_before_demo():
                self._run_btn.setText("Исправить черновик")
            elif self._demo_already_ran():
                self._run_btn.setText("Запустить снова")
            else:
                self._run_btn.setVisible(False)
        else:
            self._run_btn.setText("Запустить снова")

    def _should_hide_run_plan_action(self) -> bool:
        if self._busy or self._execute_started:
            return True
        if self._record and self._record.exec_agent_id:
            return True
        return any(
            ev.title in {"Результат тестового прогона", "Тестовый прогон"}
            or (
                ev.title == "Сборка workflow"
                and "реализац" in (ev.body or "").casefold()
            )
            for ev in self._events
        )

    def _render_all(self) -> None:
        phase = self._record.phase if self._record else "document"
        if self._busy and self._execute_started and phase == "designed":
            phase = "executing"
        self._stepper.set_phase(phase, busy=self._busy)
        self._rebuild_feed()
        plan = self._record.plan if self._record else None
        unanswered = bool(plan and plan.unanswered())
        self._update_run_button(plan=plan, unanswered=unanswered)
        can_next = bool(
            self._record
            and not self._busy
            and self._record.phase != "done"
            and (self._tests_ok or self._playbook().get("demo_ok"))
        )
        draft_ready = bool(
            self._record
            and self._record.phase == "designed"
            and not self._busy
            and not self._post_build_question
            and not unanswered
            and not can_next
            and not self._demo_already_ran()
        )
        self._composer_wrap.setVisible(not draft_ready and not can_next)
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
            self._agent_status.setStyleSheet("color: #08745F; background: transparent;")
            self._tick_activity()
        elif self._last_stream_error and not can_next:
            self._agent_status.setText("● Предыдущий запуск завершился ошибкой — можно запустить снова")
            self._agent_status.setStyleSheet("color: #B00020; background: transparent;")
        elif can_next:
            self._agent_status.setText("● Первый результат готов — нажмите «Далее», чтобы подтвердить название и расписание")
            self._agent_status.setStyleSheet("color: #08745F; background: transparent;")
        elif self._post_build_question:
            self._agent_status.setText("● Нужны уточнения после сборки — ответьте в чате")
            self._agent_status.setStyleSheet("color: #C47E00; background: transparent;")
        elif self._record and self._record.phase == "designed" and self._draft_blocked_before_demo():
            self._agent_status.setText("● Черновик требует исправления — нажмите «Исправить черновик»")
            self._agent_status.setStyleSheet("color: #B00020; background: transparent;")
        elif self._record and self._record.phase == "designed" and self._demo_already_ran():
            self._agent_status.setText("● Пробный прогон не дал устойчивый результат — можно запустить снова")
            self._agent_status.setStyleSheet("color: #C47E00; background: transparent;")
        elif self._record and self._record.phase == "designed":
            self._agent_status.setText("● Черновик готов — запускаю пробный прогон")
            self._agent_status.setStyleSheet("color: #08745F; background: transparent;")
        elif self._record and self._record.phase in {"ready", "tested", "executing"}:
            self._agent_status.setText("● Можно запустить пробный прогон снова")
            self._agent_status.setStyleSheet("color: #08745F; background: transparent;")
        elif unanswered:
            self._agent_status.setText("● Нужен ответ по смыслу задачи — без этого неясен объём работы")
            self._agent_status.setStyleSheet("color: #C47E00; background: transparent;")
        elif plan and not unanswered:
            self._agent_status.setText("● Можно запускать пробный прогон")
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
        if not self._feed_stick_to_bottom:
            return
        bar = self._feed_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

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
            if w is not None and w in self._hitl_cards:
                continue
            if w is not None:
                w.deleteLater()
        # Drop stale answer widgets from previous rebuild.
        self._question_fields = {}
        self._answer_group = None

        plan_question = bool(
            self._record
            and self._record.plan
            and self._record.plan.unanswered()
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

        hide_run_plan = self._should_hide_run_plan_action()
        self._feed_layout.addStretch(1)
        self._assistant_live = None
        self._live_tool_widgets = {}
        for idx, event in enumerate(self._events):
            if skip_clarify_idx is not None and idx == skip_clarify_idx:
                continue
            hide_action = event.action_key.startswith("q:") or (
                event.action_key == "run_plan" and hide_run_plan
            )
            widget = self._feed_item(event, fallback_key=f"e{idx}", hide_action=hide_action)
            self._feed_layout.addWidget(widget)
            if event.title == "Агент" and event.kind == "agent":
                self._assistant_live = widget
        thinking = (self._thinking_shown or "").strip()
        self._thinking_live = None
        if thinking:
            self._expanded_keys.add("live-thinking")
            live = CursorFeedItem(
                kind="thinking",
                text=thinking,
                title="Thinking",
                detail=thinking,
                event_key="live-thinking",
                expanded=True,
            )
            live.expand_toggled.connect(self._on_expand_toggled)
            self._thinking_live = live
            self._feed_layout.addWidget(live)
        for tool in self._live_tools:
            name = str(tool.get("name") or "инструмент")
            status = str(tool.get("status") or "running")
            detail = str(tool.get("detail") or "")
            if status == "running":
                title = f"Инструмент: {name}"
                body = detail or "Выполняется…"
            elif status == "ok":
                title = f"Инструмент: {name}"
                body = detail or "Готово"
            else:
                title = f"Инструмент: {name}"
                body = detail or "Ошибка"
            key = str(tool.get("key") or f"live-tool-{name}")
            widget = CursorFeedItem(
                kind="tool",
                text=body,
                title=title,
                detail=body,
                event_key=key,
                expanded=key not in self._collapsed_keys,
            )
            widget.expand_toggled.connect(self._on_expand_toggled)
            self._live_tool_widgets[key] = widget
            self._feed_layout.addWidget(widget)
        self._activity_banner = None
        if self._busy:
            frame = self._busy_frames[self._busy_n % len(self._busy_frames)]
            phrase = (self._last_stream_phrase or self._busy_base or "Агент работает").strip()
            if len(phrase) > 100:
                phrase = phrase[:97] + "…"
            banner = _WrappingLabel(f"{frame} Система работает — {phrase}")
            banner.setFont(app_font(12, QFont.Weight.Medium))
            banner.setStyleSheet("color: #08745F; background: #EAF7F3; border-radius: 10px; padding: 8px 10px;")
            self._activity_banner = banner
            self._feed_layout.addWidget(banner)
        if plan_question and self._record and self._record.plan:
            card = self._make_clarification_message(self._record.plan.unanswered()[0])
            self._feed_layout.addWidget(card)
        elif post_question and self._post_build_question is not None:
            card = self._make_clarification_message(self._post_build_question)
            self._feed_layout.addWidget(card)
        for card in self._hitl_cards:
            self._feed_layout.addWidget(card)
        from app.ui.widgets.result_file_card import flush_pending_result_files

        flush_pending_result_files()

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
        from app.tools.result_files import remembered_result_names

        result_names = remembered_result_names(str(getattr(self._record, "id", "") or ""))
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
        for name in result_names[:8]:
            chip = QFrame()
            chip.setObjectName("filechip")
            chip.setStyleSheet(_CHIP)
            lay = QHBoxLayout(chip)
            lay.setContentsMargins(10, 4, 8, 4)
            lay.setSpacing(6)
            lbl = QLabel(name)
            lbl.setFont(app_font(11))
            lbl.setStyleSheet("background: transparent; color: #08745F;")
            lay.addWidget(lbl)
            self._chips_layout.addWidget(chip)
        self._chips_layout.addStretch(1)
        self._chips_wrap.setVisible(bool(names or result_names))

    def _next_event_key(self) -> str:
        self._event_seq += 1
        return f"e{self._event_seq}"

    def _on_expand_toggled(self, key: str, expanded: bool) -> None:
        if not key:
            return
        if expanded:
            self._expanded_keys.add(key)
            self._collapsed_keys.discard(key)
        else:
            self._expanded_keys.discard(key)
            self._collapsed_keys.add(key)

    def _feed_item(
        self,
        event: FeedEvent,
        *,
        fallback_key: str = "",
        hide_action: bool = False,
    ) -> CursorFeedItem:
        kind = resolve_feed_kind(role=event.role, title=event.title, kind=event.kind)
        key = event.event_key or fallback_key
        title = event.title
        if kind == "thinking":
            title = "Thinking"
        elif kind not in {"plan", "tool"}:
            title = ""
        if kind == "tool":
            expanded = key not in self._collapsed_keys
            if "не выполнено" in (event.title or "").casefold() or self._tool_body_is_error(
                event.body
            ):
                expanded = True
        else:
            expanded = key in self._expanded_keys
        widget = CursorFeedItem(
            kind=kind,
            text=event.body,
            title=title,
            detail=event.body,
            action="" if hide_action else event.action,
            action_key="" if hide_action else event.action_key,
            event_key=key,
            expanded=expanded,
        )
        widget.action_clicked.connect(self._on_feed_action)
        widget.expand_toggled.connect(self._on_expand_toggled)
        return widget

    def _reset_thinking_pacer(self) -> None:
        self._thinking_timer.stop()
        self._thinking_text = ""
        self._thinking_received = ""
        self._thinking_shown = ""
        self._thinking_wps = _DEFAULT_WPS
        self._thinking_word_budget = 0.0
        self._thinking_chunk = ""
        self._thinking_chunk_at = 0.0
        self._thinking_live = None
        self._stream_finished = False
        self._pending_async = None
        self._pending_async_fail = ""

    def _flush_thinking(self) -> None:
        text = _visible_thinking(self._thinking_shown or self._thinking_received)
        self._thinking_text = ""
        self._thinking_received = ""
        self._thinking_shown = ""
        self._thinking_live = None
        self._thinking_timer.stop()
        if not text:
            return
        key = self._next_event_key()
        if "live-thinking" in self._expanded_keys:
            self._expanded_keys.discard("live-thinking")
            self._expanded_keys.add(key)
        self._events.append(
            FeedEvent(
                title="Thinking",
                body=text,
                time=self._now(),
                kind="thinking",
                event_key=key,
            )
        )
        self._rebuild_feed()

    def _push_event(
        self,
        title: str,
        body: str,
        *,
        action: str = "",
        action_key: str = "",
        role: str = "",
        kind: str = "",
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
                kind=kind,
                event_key=self._next_event_key(),
            )
        )
        self._rebuild_feed()

    def _question_already_in_feed(self, question_text: str) -> bool:
        text = (question_text or "").strip()
        if not text:
            return True
        for ev in self._events:
            if ev.title == "Уточнение" and _same_feed_question(ev.body, text):
                return True
        return False

    def _push_question_if_new(self, question_text: str) -> None:
        text = (question_text or "").strip()
        if not text or self._question_already_in_feed(text):
            return
        self._push_event("Уточнение", text)

    def _ensure_question_in_feed(self, question_text: str) -> None:
        """Keep the asked question visible in history (do not lose it after answer)."""
        self._push_question_if_new(question_text)

    def _mark_question_answered(self, qid: str, answer: str) -> None:
        if self._record is None or self._record.plan is None or not qid:
            return
        questions = []
        changed = False
        for item in self._record.plan.open_questions or []:
            if item.id == qid and not (item.answer or "").strip():
                questions.append(replace(item, answer=answer))
                changed = True
            else:
                questions.append(item)
        if not changed:
            return
        plan = replace(self._record.plan, open_questions=questions)
        self._record = replace(self._record, plan=plan)

    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%H:%M")

    # --- interactions ----------------------------------------------------------

    def _on_feed_action(self, key: str) -> None:
        if key == "show_plan" and self._record and self._record.plan:
            body = _format_plan_steps(self._record.plan)
            target: FeedEvent | None = None
            for ev in self._events:
                if ev.action_key == "show_plan":
                    target = ev
                    break
                if ev.title in {"План", "Шаги плана"}:
                    target = ev
            if target is None:
                self._push_event("План", body, action="Показать шаги плана", action_key="show_plan")
                target = self._events[-1]
            else:
                target.body = body
            if target.event_key:
                self._expanded_keys.add(target.event_key)
            self._rebuild_feed()
        elif key == "run_plan":
            if self._record is not None and self._draft_blocked_before_demo():
                self._on_plan()
            else:
                self._on_execute()
        elif key == "run_demo":
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
        if self._record.plan and self._record.plan.unanswered():
            self._current_question_id = self._record.plan.unanswered()[0].id
            self._selected_quick_answer = text
            self._submit_question_answer()
            return
        self._push_event("Вы", text)
        if self._demo_already_ran():
            self._store_retry_hint(text)
            self._on_execute()
            return
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
            self._live_tools = []
            self._live_tool_widgets = {}
            if not (self._last_stream_phrase or "").strip():
                self._last_stream_phrase = base
            self._busy_timer.start()
            self._tick_activity()
            plan = self._record.plan if self._record else None
            unanswered = bool(plan and plan.unanswered())
            self._update_run_button(plan=plan, unanswered=unanswered)
            phase = self._record.phase if self._record else "document"
            if self._execute_started and phase == "designed":
                phase = "executing"
            self._stepper.set_phase(phase, busy=True)
            self._rebuild_feed()
        else:
            self._busy_timer.stop()
            self._render_all()

    def _tick_activity(self) -> None:
        self._busy_n = (self._busy_n % 4) + 1
        frame = self._busy_frames[(self._busy_n - 1) % len(self._busy_frames)]
        running = next((t for t in self._live_tools if t.get("status") == "running"), None)
        if running:
            name = str(running.get("name") or "инструмент")
            self._agent_status.setText(f"{frame} Вызываю {name}…")
            self._agent_status.setStyleSheet("color: #08745F; background: transparent;")
            self._refresh_activity_banner(f"Вызываю {name}…")
            return
        phrase = (self._last_stream_phrase or self._busy_base or "Агент работает").strip()
        if len(phrase) > 80:
            phrase = phrase[:77] + "…"
        if (self._busy_base or "").startswith("Реализация"):
            self._agent_status.setText(f"{frame} Реализация… {phrase}" if phrase else f"{frame} Реализация…")
        else:
            self._agent_status.setText(f"{frame} {self._busy_base}{'.' * min(self._busy_n, 3)}")
        self._agent_status.setStyleSheet("color: #08745F; background: transparent;")
        self._refresh_activity_banner(phrase)

    def _refresh_activity_banner(self, phrase: str) -> None:
        if self._activity_banner is None or not self._busy:
            return
        frame = self._busy_frames[(self._busy_n - 1) % len(self._busy_frames)]
        text = (phrase or self._busy_base or "Агент работает").strip()
        if len(text) > 100:
            text = text[:97] + "…"
        self._activity_banner.setText(f"{frame} Система работает — {text}")

    def _tool_body_is_error(self, body: str) -> bool:
        low = (body or "").casefold()
        return any(
            marker in low
            for marker in ("ошибка", "не выполнено", "отклонён", "не записан")
        )

    def _upsert_live_tool(self, name: str, *, status: str, detail: str = "") -> None:
        tool_name = (name or "").strip() or "инструмент"
        if self._planning_stream and not self._is_catalog_tool_name(tool_name):
            line = f"{tool_name}: {detail}".strip() if detail else tool_name
            self._append_thinking(line + "\n")
            return
        incoming = (detail or "").strip()
        running = next(
            (
                item
                for item in self._live_tools
                if item.get("name") == tool_name and item.get("status") == "running"
            ),
            None,
        )
        target = running
        if target is None and status != "running":
            target = next(
                (item for item in reversed(self._live_tools) if item.get("name") == tool_name),
                None,
            )
        if target is not None:
            target["status"] = status
            target["detail"] = self._merge_tool_detail(str(target.get("detail") or ""), incoming, status)
            self._refresh_live_tool_widget(target)
            return
        if status == "running":
            for item in self._live_tools:
                if item.get("status") == "running":
                    item["status"] = "ok"
                    item["detail"] = item.get("detail") or "Готово"
                    self._refresh_live_tool_widget(item)
            key = self._next_event_key()
            tool = {
                "name": tool_name,
                "status": "running",
                "detail": incoming or "Выполняется…",
                "key": key,
            }
            self._live_tools.append(tool)
            self._last_stream_phrase = f"вызываю {tool_name}"
            self._append_live_tool_widget(tool)
            return
        key = self._next_event_key()
        tool = {
            "name": tool_name,
            "status": status,
            "detail": incoming or ("Готово" if status == "ok" else "Ошибка"),
            "key": key,
        }
        self._live_tools.append(tool)
        self._append_live_tool_widget(tool)

    def _tool_card_body(self, tool: dict) -> tuple[str, str]:
        name = str(tool.get("name") or "инструмент")
        status = str(tool.get("status") or "running")
        detail = str(tool.get("detail") or "")
        title = f"Инструмент: {name}"
        if status == "running":
            return title, detail or "Выполняется…"
        if status == "ok":
            return title, detail or "Готово"
        return f"Инструмент: {name} — не выполнено", detail or "Ошибка"

    def _refresh_live_tool_widget(self, tool: dict) -> None:
        key = str(tool.get("key") or "")
        widget = self._live_tool_widgets.get(key)
        if widget is None:
            self._append_live_tool_widget(tool)
            return
        title, body = self._tool_card_body(tool)
        widget.set_tool_detail(body)
        widget.set_header_title(title)
        if str(tool.get("status") or "") == "error":
            widget.set_expanded(True)
            self._collapsed_keys.discard(key)
            self._expanded_keys.add(key)

    def _append_live_tool_widget(self, tool: dict) -> None:
        key = str(tool.get("key") or self._next_event_key())
        tool["key"] = key
        title, body = self._tool_card_body(tool)
        error = str(tool.get("status") or "") == "error"
        if error:
            self._collapsed_keys.discard(key)
            self._expanded_keys.add(key)
        widget = CursorFeedItem(
            kind="tool",
            text=body,
            title=title,
            detail=body,
            event_key=key,
            expanded=error or key not in self._collapsed_keys,
        )
        widget.expand_toggled.connect(self._on_expand_toggled)
        self._live_tool_widgets[key] = widget
        banner = self._activity_banner
        if banner is not None:
            index = self._feed_layout.indexOf(banner)
            if index >= 0:
                self._feed_layout.insertWidget(index, widget)
                self._scroll_feed_to_bottom()
                return
        self._feed_layout.addWidget(widget)
        self._scroll_feed_to_bottom()

    def _merge_tool_detail(self, previous: str, incoming: str, status: str) -> str:
        placeholders = {
            "",
            "Готово",
            "Выполняется…",
            "Выполняется на сервере Constructor…",
            "Выполняется на этом компьютере…",
        }
        if incoming and incoming not in placeholders:
            return incoming
        if previous and previous not in placeholders:
            return previous
        if incoming:
            return incoming
        if status == "error":
            return previous or "Ошибка"
        if status == "ok":
            return previous or "Готово"
        return previous or "Выполняется…"

    def _commit_live_tools_to_feed(self) -> None:
        for tool in self._live_tools:
            name = str(tool.get("name") or "инструмент")
            status = str(tool.get("status") or "")
            detail = str(tool.get("detail") or "").strip()
            if status == "ok":
                body = detail or "Готово"
                title = f"Инструмент: {name}"
            elif status == "error":
                body = detail or "Ошибка"
                title = f"Инструмент: {name} — не выполнено"
            elif status in {"skipped", "blocked_in_design"}:
                body = detail or "На этапе проектирования инструмент не вызывается"
                title = f"Инструмент: {name} — пропущен"
            else:
                body = detail or "Вызов завершён"
                title = f"Инструмент: {name}"
            key = str(tool.get("key") or self._next_event_key())
            self._events.append(
                FeedEvent(
                    title=title,
                    body=body,
                    time=self._now(),
                    kind="tool",
                    event_key=key,
                )
            )
        self._live_tools = []
        self._live_tool_widgets = {}

    def _is_catalog_tool_name(self, name: str) -> bool:
        token = (name or "").strip()
        if not token:
            return False
        low = token.casefold()
        return "." in token or low.startswith(("web_", "site_", "outlook", "mail"))

    def _parse_tool_activity(self, text: str) -> bool:
        """Return True if text was handled as tool activity (not Thinking)."""
        raw = (text or "").strip()
        if not raw:
            return False
        low = raw.casefold()
        call = re.search(
            r"(?:Cursor вызывает|Выполняю на этом компьютере|Выполняю на компьютере)\s*[:«\"]?\s*«?([^\n»]+)»?",
            raw,
            re.IGNORECASE,
        )
        if call and ("вызывает" in low or "выполняю" in low):
            name = call.group(1).strip(" «»\"'.,;")
            detail = "Выполняется на сервере Constructor…"
            if "компьютере" in low:
                detail = "Выполняется на этом компьютере…"
            self._upsert_live_tool(name, status="running", detail=detail)
            return True
        if "жду вызов constructor tool" in low:
            names = raw.split(":", 1)[-1].strip() if ":" in raw else raw
            self._last_stream_phrase = f"жду вызов {names}"
            self._push_event("Система", f"Жду вызов Constructor tool: {names}", kind="system")
            return True
        progress = re.search(r"«([^»]+)»\s*:\s*(читаю|загружаю|ожидаю)\b(.+)$", raw, re.IGNORECASE)
        if progress:
            name = progress.group(1).strip()
            detail = (progress.group(2) + progress.group(3)).strip()
            self._upsert_live_tool(name, status="running", detail=detail)
            self._last_stream_phrase = f"{name}: {detail}"
            return True
        done = re.search(r"«([^»]+)»\s*:\s*готово\.?", raw, re.IGNORECASE)
        if done:
            self._upsert_live_tool(done.group(1).strip(), status="ok", detail="Готово")
            self._last_stream_phrase = f"{done.group(1).strip()} готово"
            return True
        failed = re.search(r"«([^»]+)»\s*:\s*(.+)$", raw)
        if failed and "готово" not in failed.group(2).casefold():
            detail = failed.group(2).strip()
            # Прогресс/подсказка, не ошибка.
            if any(hint in detail.casefold() for hint in ("читаю", "загружаю", "может занять", "ожидаю")):
                self._upsert_live_tool(failed.group(1).strip(), status="running", detail=detail)
                self._last_stream_phrase = f"{failed.group(1).strip()}: {detail}"
                return True
            self._upsert_live_tool(
                failed.group(1).strip(),
                status="error",
                detail=detail,
            )
            self._last_stream_phrase = f"ошибка {failed.group(1).strip()}"
            return True
        return False

    def _run_async(self, label: str, fn) -> None:
        self._reset_thinking_pacer()
        self._live_tools = []
        self._live_tool_widgets = {}
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
        incoming = (text or "").replace(_REPLACEMENT, "")
        if event_type in {"heartbeat", "ping"}:
            self._tick_activity()
            return
        if event_type == "question":
            self._flush_thinking()
            payload = _event_json(incoming)
            question = str(
                payload.get("question")
                or payload.get("prompt")
                or payload.get("title")
                or incoming
            ).strip()
            options = [str(item).strip() for item in (payload.get("options") or []) if str(item).strip()]
            if question:
                body = question
                if options:
                    body += "\n\n" + "\n".join(f"• {item}" for item in options[:6])
                self._push_event("Уточнение", body, kind="question")
                self._tick_activity()
            return
        if event_type == "tool_call":
            self._flush_thinking()
            payload = _event_json(incoming)
            name = str(payload.get("tool") or payload.get("name") or "инструмент").strip()
            status = str(payload.get("status") or "running").strip() or "running"
            detail = ""
            if status in {"blocked_in_design", "skipped"}:
                detail = "На этапе проектирования инструмент не вызывается."
            else:
                args = payload.get("arguments")
                detail = _compact_payload(args, limit=600) if args else "Выполняется..."
            self._upsert_live_tool(name, status=status, detail=detail)
            self._tick_activity()
            return
        if event_type == "tool_result":
            self._flush_thinking()
            payload = _event_json(incoming)
            if payload:
                name = str(payload.get("tool") or payload.get("name") or "инструмент")
                status = str(payload.get("status") or "").strip()
                if not status:
                    status = "ok" if payload.get("ok", True) else "error"
                result = payload.get("result")
                error = str(payload.get("error") or "").strip()
                if status in {"skipped", "blocked_in_design"} or payload.get("skipped"):
                    detail = (
                        str((result or {}).get("text") or "").strip()
                        if isinstance(result, dict)
                        else ""
                    )
                    self._upsert_live_tool(
                        name.strip() or "инструмент",
                        status="skipped",
                        detail=detail or "На этапе проектирования инструмент не вызывается.",
                    )
                else:
                    detail = error or _compact_payload(result)
                    self._upsert_live_tool(
                        name.strip() or "инструмент",
                        status="error" if status == "error" else "ok",
                        detail=(detail or "Готово").strip(),
                    )
                self._tick_activity()
                return
            raw = incoming.strip()
            name, sep, body = raw.partition("\n")
            if not sep:
                name, body = "инструмент", raw
            self._upsert_live_tool(
                name.strip() or "инструмент",
                status="error" if self._tool_body_is_error(body) else "ok",
                detail=(body or "Готово").strip(),
            )
            self._tick_activity()
            return
        if event_type == "progress" and incoming.strip():
            self._last_stream_phrase = incoming.strip()
            self._tick_activity()
            return
        if incoming.strip():
            last_line = incoming.strip().splitlines()[-1].strip()
            if last_line:
                self._last_stream_phrase = last_line
        if event_type == "error" and incoming.strip():
            self._flush_thinking()
            self._last_stream_error = incoming.strip()
            self._push_event("Ошибка", incoming.strip(), kind="error")
            self._agent_status.setText("● Ошибка — смотрите карточку в ленте")
            self._agent_status.setStyleSheet("color: #B00020; background: transparent;")
            return
        if incoming.strip() and (
            "запускаю пробный прогон" in incoming.casefold()
            or "запускаю задачу по описанию" in incoming.casefold()
        ):
            self._planning_stream = False
            self._execute_started = True
        if event_type in {"decision", "system", "status", "message"} and incoming.strip():
            self._flush_thinking()
            if self._parse_tool_activity(incoming):
                self._tick_activity()
                return
            self._push_event("Система", incoming.strip(), kind="system")
            return
        if event_type == "assistant" and incoming:
            self._flush_thinking()
            shown = incoming.replace("\ufffd", "")
            if shown.strip():
                last = self._events[-1] if self._events else None
                if last is not None and last.title == "Агент" and last.kind == "agent":
                    delta = _stream_delta(last.body or "", shown)
                    if not delta:
                        return
                    visible = _strip_tool_call_text((last.body or "") + delta)
                    if not visible.strip() or visible == (last.body or ""):
                        return
                    last.body = visible
                    if self._assistant_live is not None:
                        self._assistant_live.set_body_text(last.body)
                        self._scroll_feed_to_bottom()
                    else:
                        self._rebuild_feed()
                else:
                    cleaned = _strip_tool_call_text(shown)
                    if cleaned.strip():
                        self._push_event("Агент", cleaned, kind="agent")
            return
        if event_type == "thinking" and incoming:
            self._append_thinking(incoming)
            return
        if event_type == "final" and incoming:
            self._flush_thinking()
            payload = _event_json(incoming)
            answer = str(payload.get("answer") or incoming).strip()
            if answer:
                data = _extract_json_object(answer)
                text = _format_plan_dict(data) if data else _strip_tool_call_text(answer)
                if text.strip():
                    self._push_event("Результат", text[:4000], kind="agent")

    def _append_thinking(self, incoming: str) -> None:
        if not incoming:
            return
        delta = _stream_delta(self._thinking_received, incoming)
        if not delta:
            return
        self._thinking_received += delta
        self._thinking_text = self._thinking_received
        self._note_thinking_chunk(delta)
        self._ensure_thinking_pacer()

    def _note_thinking_chunk(self, delta: str) -> None:
        now = time.monotonic()
        previous = self._thinking_chunk
        started = self._thinking_chunk_at
        if previous and started:
            words = _word_count(previous)
            elapsed = now - started
            # Пауза модели — не скорость печати. Иначе think ползёт по 3 слова/с.
            if words >= 1 and 0.08 <= elapsed <= _WPS_MAX_ELAPSED:
                self._thinking_wps = min(_MAX_WPS, max(_MIN_WPS, words / elapsed))
        self._thinking_chunk = delta
        self._thinking_chunk_at = now

    def _ensure_thinking_pacer(self) -> None:
        if not self._thinking_timer.isActive():
            self._thinking_timer.start()

    def _catch_up_thinking(self) -> None:
        if len(self._thinking_shown) >= len(self._thinking_received):
            return
        self._thinking_shown = self._thinking_received
        self._paint_live_thinking()

    def _tick_thinking_pacer(self) -> None:
        remaining = self._thinking_received[len(self._thinking_shown) :]
        if remaining and (self._stream_finished or self._pending_async_fail):
            self._catch_up_thinking()
            remaining = ""
        if remaining:
            wps = self._thinking_wps
            backlog = _word_count(remaining)
            if backlog > 36:
                wps = _MAX_WPS
            self._thinking_word_budget += wps * (_PACER_MS / 1000.0)
            take = int(self._thinking_word_budget)
            if take < 1:
                return
            self._thinking_word_budget -= take
            piece = _take_words(remaining, take) or remaining
            self._thinking_shown += piece
            self._paint_live_thinking()
        if len(self._thinking_shown) >= len(self._thinking_received):
            if self._stream_finished or self._pending_async_fail:
                self._thinking_timer.stop()
                self._finish_pending_async()
            elif not remaining:
                self._thinking_timer.stop()

    def _paint_live_thinking(self) -> None:
        shown = self._thinking_shown
        if self._thinking_live is not None:
            self._thinking_live.set_body_text(shown)
            self._scroll_feed_to_bottom()
            return
        if not shown.strip():
            return
        self._expanded_keys.add("live-thinking")
        live = CursorFeedItem(
            kind="thinking",
            text=shown,
            title="Thinking",
            detail=shown,
            event_key="live-thinking",
            expanded=True,
        )
        live.expand_toggled.connect(self._on_expand_toggled)
        self._thinking_live = live
        self._feed_layout.addWidget(live)
        self._scroll_feed_to_bottom()

    def _finish_pending_async(self) -> None:
        fail = self._pending_async_fail
        pending = self._pending_async
        self._pending_async = None
        self._pending_async_fail = ""
        self._stream_finished = False
        self._flush_thinking()
        if fail:
            self._last_stream_error = fail
            self._commit_live_tools_to_feed()
            self._set_busy(False)
            self._push_event("Ошибка", fail, kind="error")
            self._agent_status.setText("● Ошибка — предыдущий запуск не завершён")
            self._agent_status.setStyleSheet("color: #B00020; background: transparent;")
            return
        if pending is None:
            self._commit_live_tools_to_feed()
            self._set_busy(False)
            return
        result, label = pending
        self._commit_live_tools_to_feed()
        self._apply_async_result(result, label)

    def _on_async_ok(self, result: object, label: str) -> None:
        self._pending_async = (result, label)
        self._stream_finished = True
        self._catch_up_thinking()
        self._finish_pending_async()

    def _apply_async_result(self, result: object, label: str) -> None:
        self._set_busy(False)
        if isinstance(result, WorkflowRecord):
            self._record = self._persist_passport_runtime(result)
            set_host_workflow_id(self, self._record.id)
            self._pending_paths = []
            self._workflow_title = result.title
            self._notes = result.notes or self._notes
            self._render_chips()
            if label.startswith("Планирование") or label.startswith("Пробный"):
                unanswered = result.plan.unanswered() if result.plan else []
                if unanswered:
                    self._push_event("Агент", unanswered[0].question)
                    self._push_question_if_new(unanswered[0].question)
                elif self._draft_blocked_before_demo(result):
                    self._show_demo_result(result)
                elif result.phase == "designed" and self._can_run_demo(result):
                    self._show_design_result(result)
                else:
                    self._show_demo_result(result)
            elif label.startswith("Уточнение"):
                unanswered = result.plan.unanswered() if result.plan else []
                if unanswered:
                    self._push_event("Агент", "Принял ответ, следующий вопрос.")
                    self._push_question_if_new(unanswered[0].question)
                else:
                    self._show_demo_result(result)
            elif label.startswith("Реализация"):
                self._show_demo_result(result)
            elif label.startswith("Публикация"):
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
            self._show_test_run_result(files=list(files), dest_dir=str(dest_dir))

    def _on_async_fail(self, message: str) -> None:
        self._last_stream_error = message
        self._pending_async_fail = message
        self._stream_finished = True
        self._catch_up_thinking()
        self._finish_pending_async()

    def _show_demo_result(self, result: WorkflowRecord) -> None:
        self._last_exec_report = (result.last_result or "").strip()
        if self._draft_blocked_before_demo(result):
            self._execute_started = False
            self._tests_ok = False
            self._push_event(
                "Черновик требует исправления",
                self._draft_blocker_text(result),
                action="Исправить черновик",
                action_key="run_plan",
            )
            self._agent_status.setText("● Пробный прогон не запускался — нужно исправить черновик")
            self._agent_status.setStyleSheet("color: #B00020; background: transparent;")
            return
        playbook = (result.local_run or {}).get("playbook") or {}
        if not isinstance(playbook, dict):
            playbook = {}
        work = (result.local_run or {}).get("work_result") or {}
        if not isinstance(work, dict):
            work = {}
        from app.tools.result_files import publish_answer_files

        wid = str(result.id or "")
        self._render_chips()
        report = str(work.get("text") or result.last_result or "").strip()
        extras: list[str] = []
        for item in work.get("files") or []:
            extras.append(f"Файл: {item}")
        for item in work.get("actions") or []:
            extras.append(f"Действие: {item}")
        for item in work.get("notifications") or []:
            extras.append(f"Уведомление: {item}")
        if extras:
            report = (report + "\n\n" + "\n".join(extras)).strip()
        publish_answer_files(workflow_id=wid, work=work, text=report)
        if report:
            self._push_event("Результат", report[:4000])
        self._tests_ok = bool(playbook.get("demo_ok") or result.phase in {"tested", "ready"})
        if self._tests_ok:
            self._push_event(
                "Сохранение",
                "Первый результат готов. Нажмите «Далее», чтобы подтвердить название агента и расписание.",
                action="Далее",
                action_key="next",
            )
        else:
            self._execute_started = False
            self._push_event(
                "Агент",
                "Пробный прогон не дал устойчивый результат. Можно запустить снова.",
                action="Запустить снова",
                action_key="run_demo",
            )

    def _show_design_result(self, result: WorkflowRecord) -> None:
        if self._draft_blocked_before_demo(result):
            self._execute_started = False
            self._show_demo_result(result)
            return
        if result.phase == "designed" and self._can_run_demo(result):
            self._on_execute()
            return
        self._show_demo_result(result)

    def _on_plan(self) -> None:
        self._execute_started = False
        self._planning_stream = True
        notes = (self._notes or "").strip()
        if self._record is None:
            if not notes and not self._pending_paths:
                QMessageBox.warning(
                    self,
                    "Документ",
                    "Нет материалов. Откройте агента из паспорта.",
                )
                return
            def create_and_demo() -> WorkflowRecord:
                created = self._api.create_workflow(notes=notes, file_paths=self._pending_paths)
                created = self._persist_passport_runtime(created)
                demoed = self._design_with_sdk(created.id)
                return self._persist_passport_runtime(demoed)

            self._run_async("Планирование черновика", create_and_demo)
            return
        self._run_async(
            "Планирование черновика",
            lambda: self._design_with_sdk(self._record.id),  # type: ignore[union-attr]
        )

    def attach_hitl_card(self, card: QWidget) -> None:
        if card not in self._hitl_cards:
            self._hitl_cards.append(card)
        self._feed_layout.addWidget(card)
        self._scroll_feed_to_bottom()
        from app.ui.widgets.result_file_card import flush_pending_result_files

        flush_pending_result_files()
        self._render_chips()

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
        col = QVBoxLayout(wrap)
        col.setContentsMargins(0, 8, 0, 8)
        col.setSpacing(4)

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
        self._mark_question_answered(qid, text)
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

            def work() -> WorkflowRecord:
                self._api.update_workflow_local_run(wid, local)
                return self._execute_with_stream(wid, True)

            self._push_event("Сборка workflow", "Учитываю уточнение и запускаю повторную сборку…")
            self._execute_started = True
            self._last_stream_phrase = ""
            self._last_stream_error = ""
            self._run_btn.setEnabled(False)
            self._run_btn.setText("Идёт сборка…")
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

    def _execute_with_stream(self, workflow_id: str, reexecute: bool) -> WorkflowRecord:
        try:
            return self._api.stream_execute_workflow(
                workflow_id,
                lambda event_type, t: self._stream_event.emit(event_type, t),
                reexecute=reexecute,
            )
        except ApiError as exc:
            low = (exc.message or "").casefold()
            retryable = exc.status_code in {404, 405} or "подключ" in low or "сети" in low
            if not retryable:
                raise
            return self._api.execute_workflow(workflow_id, reexecute=reexecute)
        except Exception:  # noqa: BLE001
            return self._api.execute_workflow(workflow_id, reexecute=reexecute)

    def _design_with_sdk(self, workflow_id: str) -> WorkflowRecord:
        events: list[dict] = []
        try:
            from app.sdk_agent import CursorSdkBridge, CursorSdkUnavailable
            from app.sdk_agent.prompt import build_design_sdk_prompt

            bridge = CursorSdkBridge()
            bridge.check_ready()
            record = self._api.get_workflow(workflow_id)
            try:
                design_prompt = self._api.local_design_prompt(workflow_id)
            except ApiError as exc:
                if exc.status_code not in {404, 405}:
                    raise
                design_prompt = _local_design_prompt_for_record(record)

            def on_sdk_event(payload: dict) -> None:
                if not isinstance(payload, dict):
                    return
                event_type = str(payload.get("type") or "")
                if event_type not in {"ready", "done"}:
                    events.append(payload)
                text = str(payload.get("text") or payload.get("message") or "")
                if event_type == "assistant":
                    self._stream_event.emit("assistant", text)
                elif event_type in {"question", "tool_call", "tool_result", "final"}:
                    self._stream_event.emit(event_type, json.dumps(payload, ensure_ascii=False))
                elif event_type == "tool_call":
                    self._stream_event.emit(
                        "decision",
                        f"Проектировщик проверяет: {payload.get('tool') or ''}",
                    )
                elif event_type == "tool_result":
                    self._stream_event.emit(
                        "tool_result",
                        f"{payload.get('tool') or ''}\nГотово",
                    )
                elif event_type in {"status", "decision", "progress", "error", "thinking"}:
                    self._stream_event.emit(event_type, text)

            result = bridge.run(
                prompt=build_design_sdk_prompt(record, design_prompt),
                workflow_id=workflow_id,
                mode="design",
                on_event=on_sdk_event,
            )
            answer = str(result.get("answer") or "").strip()
            try:
                return self._api.finish_local_design_workflow(
                    workflow_id,
                    answer=answer,
                    events=events,
                )
            except ApiError as exc:
                if exc.status_code not in {404, 405}:
                    raise
                draft = _draft_from_sdk_answer(answer)
                local = dict(record.local_run or {})
                local["runtime"] = "cursor-sdk"
                local["design_runtime"] = "cursor-sdk"
                local["playbook_draft"] = draft
                local["validation"] = {
                    "ok": bool(draft.get("steps")),
                    "status": "draft_ready" if draft.get("steps") else "blocked_before_demo",
                    "demo_started": False,
                    "can_run_demo": bool(draft.get("steps")),
                    "issues": [],
                    "reasons": [] if draft.get("steps") else ["Cursor SDK не вернул JSON-черновик."],
                }
                local["can_run_demo"] = bool(draft.get("steps"))
                local["demo_ok"] = False
                local["can_publish"] = False
                saved = self._api.update_workflow_local_run(workflow_id, local)
                return replace(saved, phase="designed", local_run=local)
        except CursorSdkUnavailable:
            return self._api.stream_plan_workflow(
                workflow_id,
                lambda event_type, text: self._stream_event.emit(event_type, text),
            )

    def _demo_with_sdk(self, workflow_id: str) -> WorkflowRecord:
        events: list[dict] = []
        try:
            from app.sdk_agent import CursorSdkBridge, CursorSdkUnavailable
            from app.sdk_agent.prompt import build_demo_sdk_prompt

            bridge = CursorSdkBridge()
            bridge.check_ready()
            record = self._api.get_workflow(workflow_id)

            def on_sdk_event(payload: dict) -> None:
                if not isinstance(payload, dict):
                    return
                event_type = str(payload.get("type") or "")
                if event_type not in {"ready", "done"}:
                    events.append(payload)
                text = str(payload.get("text") or payload.get("message") or "")
                if event_type == "assistant":
                    self._stream_event.emit("assistant", text)
                elif event_type in {"question", "tool_call", "tool_result", "final"}:
                    self._stream_event.emit(event_type, json.dumps(payload, ensure_ascii=False))
                elif event_type == "tool_call":
                    self._stream_event.emit(
                        "decision",
                        f"Выполняю на этом компьютере: {payload.get('tool') or ''}",
                    )
                elif event_type == "tool_result":
                    self._stream_event.emit(
                        "tool_result",
                        f"{payload.get('tool') or ''}\nГотово",
                    )
                elif event_type in {"status", "decision", "progress", "error", "thinking"}:
                    self._stream_event.emit(event_type, text)

            result = bridge.run(
                prompt=build_demo_sdk_prompt(record),
                workflow_id=workflow_id,
                on_event=on_sdk_event,
            )
            answer = str(result.get("answer") or "").strip()
            try:
                return self._api.finish_local_demo_workflow(
                    workflow_id,
                    answer=answer,
                    events=events,
                )
            except ApiError as exc:
                if exc.status_code not in {404, 405}:
                    raise
                return self._api.stream_demo_workflow(
                    workflow_id,
                    lambda event_type, text: self._stream_event.emit(event_type, text),
                )
        except CursorSdkUnavailable:
            return self._api.stream_demo_workflow(
                workflow_id,
                lambda event_type, text: self._stream_event.emit(event_type, text),
            )

    def _store_retry_hint(self, text: str) -> None:
        hint = (text or "").strip()
        if not hint or self._record is None:
            return
        local = dict(self._record.local_run or {})
        local["retry_hint"] = hint
        self._record.local_run = local
        try:
            self._record = self._api.update_workflow_local_run(self._record.id, local)
        except ApiError:
            pass

    def _on_run_clicked(self) -> None:
        if self._record is not None and self._draft_blocked_before_demo():
            self._push_event("Черновик", "Отправляю черновик на повторное проектирование…")
            self._run_btn.setEnabled(False)
            self._run_btn.setText("Исправляю…")
            self._on_plan()
            return
        self._on_execute()

    def _on_execute(self, reexecute: bool = False) -> None:
        del reexecute
        if self._record is None:
            self._on_plan()
            return
        self._tests_ok = False
        self._post_build_question = None
        self._execute_started = True
        self._planning_stream = False
        self._last_stream_phrase = ""
        self._last_stream_error = ""
        self._next_btn.setVisible(False)
        self._run_btn.setEnabled(False)
        self._run_btn.setText("Идёт прогон…")
        self._push_event("Пробный прогон", "Запускаю задачу по описанию бизнес-процесса…")
        workflow_id = self._record.id
        self._run_async(
            "Пробный прогон",
            lambda: self._demo_with_sdk(workflow_id),
        )

    def _show_test_run_result(self, *, files: list[str], dest_dir: str) -> None:
        from app.tools.result_files import publish_result_files

        publish_result_files(
            {"files": files},
            workflow_id=str(getattr(self._record, "id", "") or ""),
        )
        result_md = _result_md_from_files(files)
        report = (self._last_exec_report or "").strip()
        if self._record and (self._record.last_result or "").strip():
            report = (self._record.last_result or "").strip() or report
        parts: list[str] = []
        if report:
            parts.append(report)
        if result_md and result_md not in report:
            parts.append(result_md)
        combined = "\n\n".join(parts).strip()
        if not _has_subject_result(combined):
            body = "Инструмент не вернул данные."
            if self._last_stream_error:
                body += "\n\n" + self._last_stream_error
            elif dest_dir and not files:
                body += "\nФайлы результата не найдены в artifacts/."
            self._tests_ok = False
            self._push_event("Результат тестового прогона", body)
            self._render_all()
            return
        self._push_event("Результат тестового прогона", combined)
        self._evaluate_tests(list(files))
        self._render_all()

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
        odata_ok = bool(local_state.get("odata_configured"))
        infra_fail = _is_infra_access_fail(blob)
        if explicit_fail and infra_fail and (_fixtures_passed(blob) or odata_ok):
            explicit_fail = False
            explicit_pass = True
        if explicit_fail:
            if infra_fail:
                self._push_event(
                    "Тесты",
                    "Live 1С с облака недоступен — это ожидаемо. "
                    "Проверка идёт через OData на сервере Constructor, без вопросов в чате. "
                    "Перезапустите сборку.",
                )
                self._render_all()
                return
            self._post_build_question = _extract_post_build_question(blob, context=context)
            self._ensure_question_in_feed(self._post_build_question.question)
            self._push_event(
                "Тесты",
                "TESTS: FAIL — сохранение недоступно. Ответьте на вопрос агента в чате.",
            )
            self._render_all()
            return
        if not explicit_pass:
            if infra_fail and odata_ok:
                explicit_pass = True
            elif infra_fail:
                self._push_event(
                    "Тесты",
                    "Live 1С с облака недоступен — это ожидаемо. "
                    "Проверка идёт через OData на сервере Constructor, без вопросов в чате. "
                    "Перезапустите сборку.",
                )
                self._render_all()
                return
            else:
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
        if not (self._tests_ok or self._playbook().get("demo_ok")):
            QMessageBox.information(
                self,
                "Прогон",
                "Сначала дождитесь успешного пробного прогона.",
            )
            return
        self.schedule_requested.emit(self._record)

    def _open_result_item(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        wid = str(getattr(self._record, "id", "") or "")
        if wid:
            set_host_workflow_id(self, wid)
            attach_pending_for(wid)

    def _on_new(self) -> None:
        self._record = None
        set_host_workflow_id(self, "")
        self._pending_paths.clear()
        self._workflow_title = ""
        self._notes = ""
        self._passport_runtime = {}
        self._results_dir = ""
        self._tests_ok = False
        self._reset_thinking_pacer()
        self._post_build_question = None
        self._execute_started = False
        self._planning_stream = False
        self._last_stream_phrase = ""
        self._last_stream_error = ""
        self._last_exec_report = ""
        self._live_tools = []
        self._live_tool_widgets = {}
        self._activity_banner = None
        self._hitl_cards = []
        from app.tools.result_files import clear_remembered_result_files

        clear_remembered_result_files()
        self._clear_questions()
        self._events = []
        self._event_seq = 0
        self._expanded_keys = set()
        self._collapsed_keys = set()
        self._results.clear()
        self._render_chips()
        self._render_all()


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
