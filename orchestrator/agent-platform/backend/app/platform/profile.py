"""Паспорт и иконка агента: после успешного прогона их заполняет облачный агент Cursor.

Результат записывается в агента и вместе с ним уходит в общую базу (turbotest.agents).
"""

from __future__ import annotations

import logging
import threading

from app.config import settings
from app.platform import cloud, shared
from app.platform.passport import PASSPORT_LABELS, AgentPassport, clean_icon, parse_json_object
from app.platform.sessions import PlatformAgent, store

logger = logging.getLogger(__name__)

PLAN_CHARS = 8_000
ANSWER_CHARS = 2_000
REQUEST_CHARS = 3_000

_lock = threading.Lock()
_running: set[str] = set()

# Иконки TurboTester (components/Icons.tsx): контур 24×24, обводка 1.8, скруглённые концы.
_STYLE_EXAMPLES = """\
Список дел:   <path d="m3.5 6.5 1.8 1.8L8.5 5"/><path d="m3.5 16.5 1.8 1.8L8.5 15"/><path d="M12 6.5h8.5"/><path d="M12 12h8.5"/><path d="M12 17.5h8.5"/>
Терминал:     <rect x="3.5" y="4.5" width="17" height="15" rx="3"/><path d="m7.5 10 2.5 2-2.5 2"/><path d="M12.5 14.5h4"/>
Настройки:    <path d="M4 6.5h9"/><path d="M17 6.5h3"/><circle cx="15" cy="6.5" r="2"/><path d="M4 12h3"/><path d="M11 12h9"/><circle cx="9" cy="12" r="2"/>
Изображение:  <rect x="3.5" y="4.5" width="17" height="15" rx="3"/><circle cx="9" cy="10" r="1.6"/><path d="m20.5 16-4.5-4.5-8.5 8"/>"""

_PROMPT = """Ты проектировщик ИИ-агентов. Ниже — агент платформы TurboTester: задача пользователя,
план (инструкция агента) и его последний успешный прогон. Ничего не запускай, не создавай файлов
и не вызывай инструменты — только ответь.

1. Заполни паспорт агента в формате Constructor. Пример хорошего паспорта:
ИИ-агент: Контроль дебиторской задолженности
Цель: не допускать отгрузки клиентов с недопустимой задолженностью.
Триггер: поступила новая заявка на отгрузку.
Получает: клиент, окончательный заказ, договор.
Проверяет: CRM → 1С → условия договора.
Принимает решения: если ответственности нет → разрешить; если лимит выше → заблокировать и передать руководителю.
Может самостоятельно: читать данные, готовить черновики.
Требует подтверждения человека: запись в учётные системы, отправка писем.
Не может: проводить финансовые операции.
Результат: решение + объяснение + ссылки на исходные данные.

Поле name — название агента в списке: кто он по роли, 2–4 слова, с заглавной буквы, без кавычек,
имён файлов и точки в конце. Как в примере: «Контроль дебиторской задолженности»,
«Генератор идей для тестов», «Сборщик отчёта по логам». Не пересказывай задачу и не называй
результат («Документ …», «Файл …», «Подготовь …») — называй самого агента.

Остальные поля — кратко, по-деловому, по-русски, 1–2 фразы. Опирайся на факты из плана и прогона:
какие инструменты агент реально вызывал и что получилось. Поля «Может самостоятельно»,
«Требует подтверждения человека», «Не может» выведи из того, что агент делал в прогоне и что
по смыслу задачи должен подтверждать человек. Пустых полей не оставляй: если подтверждение
не нужно ни для чего, так и напиши и объясни почему (например, «Не требуется: агент только
пишет файл в своей рабочей папке»).

2. Нарисуй иконку агента — SVG в стиле иконок программы. Правила стиля:
- корень <svg viewBox="0 0 24 24">, только элементы path, circle, rect, line, polyline, polygon, ellipse;
- контур без заливки: никаких fill, stroke, style, class, цветов, текста, градиентов и transform;
- 2–6 фигур, поля от края 3–3.5, координаты с шагом 0.5, читается в размере 16 px;
- метафора — один узнаваемый предмет, который отличает этого агента от других по смыслу
  задачи: лампочка для идей, лупа для поиска, шестерня для настройки, график для метрик и т. п.;
- не рисуй список с галочками, лист с строками, папку, робота или лицо — ими выглядят все агенты.
Примеры ниже показывают только стиль линий, не копируй их (внутренности <svg>):
{examples}

Ответ — СТРОГО один JSON-объект без пояснений:
{{"passport": {{{fields}}}, "icon_svg": "<svg viewBox=\\"0 0 24 24\\">…</svg>"}}

Текущее рабочее название (начало задачи): {title}

Задача пользователя:
\"\"\"
{request}
\"\"\"

План (инструкция агента):
\"\"\"
{plan}
\"\"\"

Последний прогон: {status}; вызовы инструментов: {tools}
Итог прогона:
\"\"\"
{answer}
\"\"\"
"""


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else f"{text[:limit]}…"


def build_prompt(agent: PlatformAgent) -> str:
    run = agent.last_run
    tools = shared.tools_summary(run)
    listing = ", ".join(f"{item['name']} ×{item['calls']}" for item in tools) or "не было"
    return _PROMPT.format(
        examples=_STYLE_EXAMPLES,
        fields=", ".join(f'"{key}": "…"' for key in PASSPORT_LABELS),
        title=agent.title,
        request=_clip(agent.request, REQUEST_CHARS) or "(нет)",
        plan=_clip(agent.instruction, PLAN_CHARS),
        status=run.status if run else "не запускался",
        tools=listing,
        answer=_clip(run.answer if run else "", ANSWER_CHARS) or "(нет)",
    )


def parse_reply(text: str) -> tuple[AgentPassport, str]:
    data = parse_json_object(text)
    if data is None:
        raise ValueError("облачный агент вернул не JSON")
    passport = AgentPassport.from_payload(data.get("passport"))
    if not passport.goal or not passport.name:
        raise ValueError("в паспорте нет названия или цели")
    return passport, clean_icon(data.get("icon_svg"))


def needs_profile(agent: PlatformAgent) -> bool:
    return bool(agent.instruction.strip()) and agent.passport is None and agent.profile_status != "pending"


def schedule(agent_id: str, config_title: str) -> bool:
    """Запустить облачного агента в фоне. False — уже идёт или выключено."""
    if not settings.platform_profile_enabled or not settings.cursor_api_key.strip():
        return False
    with _lock:
        if agent_id in _running:
            return False
        _running.add(agent_id)
    if store.set_agent_profile(agent_id, status="pending") is None:
        with _lock:
            _running.discard(agent_id)
        return False
    threading.Thread(target=_job, args=(agent_id, config_title), daemon=True, name=f"profile-{agent_id[:8]}").start()
    return True


def _job(agent_id: str, config_title: str) -> None:
    try:
        agent = store.get_agent(agent_id)
        if agent is None:
            return
        reply = cloud.ask(build_prompt(agent), name=f"Паспорт · {agent.title}")
        passport, icon = parse_reply(reply.text)
        saved = store.set_agent_profile(agent_id, status="ready", passport=passport, icon_svg=icon)
        if saved is not None:
            shared.publish(saved, config_title)
        logger.info("profile for agent %s ready (cloud agent %s)", agent_id, reply.agent_id)
    except Exception as exc:  # noqa: BLE001 — паспорт не должен ронять платформу
        message = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
        logger.warning("profile for agent %s failed: %s", agent_id, message)
        store.set_agent_profile(agent_id, status="error", error=message)
    finally:
        with _lock:
            _running.discard(agent_id)
