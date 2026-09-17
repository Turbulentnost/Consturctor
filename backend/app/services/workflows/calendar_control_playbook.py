"""Playbook for «Подготовка ПСД к рабочему дню и контроль календаря»."""

from __future__ import annotations

from typing import Any

PSD_CHAIRMAN_FIO = "Амураль Игорь Борисович"
PSD_MEETINGS_FOLDER = "Совещания"

_TITLE_HINTS = (
    "подготовка псд",
    "контроль календаря",
    "календаря псд",
    "рабочему дню и контроль",
)


def is_calendar_control_agent(*parts: str) -> bool:
    blob = " ".join(str(part or "") for part in parts).casefold()
    from app.services.workflows.artifact_close_playbook import is_artifact_close_agent
    from app.services.workflows.rk_meeting_playbook import is_rk_meeting_agent
    from app.services.workflows.sd_meeting_playbook import is_sd_meeting_agent

    if is_artifact_close_agent(blob) or is_rk_meeting_agent(blob) or is_sd_meeting_agent(blob):
        return False
    return any(hint in blob for hint in _TITLE_HINTS)


def calendar_control_runtime_tools() -> list[str]:
    return [
        "users.current",
        "outlook.read_calendar",
        "outlook.search_mail",
        "calendar.show_meetings",
        "outlook.create_event",
        "users.list",
        "notify.send",
    ]


def calendar_control_schedule_draft() -> dict[str, Any]:
    return {
        "name": "Подготовка ПСД к рабочему дню и контроль календаря",
        "goal": calendar_control_playbook_draft()["goal"],
        "triggers": [
            {
                "kind": "interval",
                "message": (
                    "Утро: устный список совещаний ПСД на сегодня для планёрки. "
                    "Письменный план не готовить."
                ),
                "interval_value": 1.0,
                "interval_unit": "days",
                "once": False,
                "weekdays": [0, 1, 2, 3, 4],
                "window_start": "08:30",
                "window_end": "09:00",
            },
            {
                "kind": "interval",
                "message": (
                    "16:00: проверка календаря ПСД на завтра, окна 09:00–18:00 "
                    "кроме обеда. Предложить сдвиг и вызвать create_event — "
                    "запись только после разрешения."
                ),
                "interval_value": 1.0,
                "interval_unit": "days",
                "once": False,
                "weekdays": [0, 1, 2, 3, 4],
                "window_start": "16:00",
                "window_end": "16:30",
            },
        ],
    }


def calendar_control_playbook_draft() -> dict[str, Any]:
    return {
        "status": "verified",
        "title": "Подготовка ПСД к рабочему дню и контроль календаря",
        "goal": (
            "Держать календарь Председателя совета директоров "
            f"({PSD_CHAIRMAN_FIO}) в Outlook без окон в рабочее время "
            "(кроме обеда 12:00–13:00) и готовить его к дню устным списком встреч. "
            "При пересечении или окне — предложить сдвиг и вызвать "
            "outlook.create_event: запись только после разрешения человека. "
            "Письменный план дня не готовить."
        ),
        "result": (
            "Утром — устный список и при пересечении/окне предложение куда перенести. "
            "Вечером — карточка предложений. Сдвиг в Outlook только после HITL."
        ),
        "when_to_run": (
            "Будни 08:30 — устный список на сегодня. "
            "Будни 16:00 — окна на завтра. "
            "По кнопке — то же по текущему времени Москвы."
        ),
        "run_inputs": [],
        "steps": [
            {
                "id": "s1",
                "title": "Кто запустил и чей календарь ПСД",
                "tool": "users.current",
                "system": "constructor",
                "entity": "user",
                "operation": "read",
                "required_params": [],
                "done_when": (
                    f"Известно, совпадает ли текущий пользователь с {PSD_CHAIRMAN_FIO}."
                ),
            },
            {
                "id": "s2",
                "title": "Календарь ПСД на целевой день",
                "tool": "outlook.read_calendar",
                "system": "outlook",
                "entity": "calendar_event",
                "operation": "list",
                "required_params": ["date"],
                "done_when": (
                    f"Прочитан ящик «{PSD_MEETINGS_FOLDER}», встречи "
                    f"{PSD_CHAIRMAN_FIO} (утро=сегодня, вечер=завтра)."
                ),
            },
            {
                "id": "s3",
                "title": "Один поиск писем об отсутствии",
                "tool": "outlook.search_mail",
                "system": "outlook",
                "entity": "mail",
                "operation": "search",
                "required_params": ["query"],
                "done_when": "Один поиск query=отпуск. count=0 — отсутствий нет.",
            },
            {
                "id": "s4",
                "title": "Карточка совещаний",
                "tool": "calendar.show_meetings",
                "system": "constructor",
                "entity": "meetings_card",
                "operation": "show",
                "required_params": [],
                "done_when": "Показана карточка с полной темой и attendees[].",
            },
            {
                "id": "s5",
                "title": "Утро и вечер: список, предложение, create_event после HITL",
                "tool": "outlook.create_event",
                "system": "outlook",
                "entity": "calendar_event",
                "operation": "create",
                "required_params": [],
                "done_when": (
                    "В WORK_RESULT есть список и, если есть пересечение или окно, "
                    "предложение сдвига. create_event вызван только после карточки HITL "
                    "или отклонён человеком."
                ),
            },
        ],
        "runtime": {
            "kind": "calendar_control",
            "tools": calendar_control_runtime_tools(),
        },
    }


def calendar_control_playbook_instructions() -> str:
    return (
        "Агент «Подготовка ПСД к рабочему дню и контроль календаря».\n"
        f"ПСД — {PSD_CHAIRMAN_FIO}. Его совещания лежат в общедоступном ящике "
        f"«{PSD_MEETINGS_FOLDER}», не в личном календаре помощника и не в "
        "календаре Жалыбина. Письменный план дня не готовить.\n"
        "\n"
        "Режим по Москве:\n"
        "- до 16:00, особенно утро / планёрка → УТРО. После карточки сразу WORK_RESULT.\n"
        "- с 16:00 → ВЕЧЕР.\n"
        "\n"
        "УТРО (ровно эти шаги, потом стоп):\n"
        "1. users.current — кто запустил. ФИО не спрашивать.\n"
        "2. outlook.read_calendar — только сегодня: date=сегодня, "
        f"folder={PSD_MEETINGS_FOLDER}, people=[\"{PSD_CHAIRMAN_FIO}\"]. "
        "Инструмент читает общий ящик и оставляет встречи, где ПСД в участниках. "
        "Свой календарь и GetSharedDefaultFolder по ФИО не использовать.\n"
        "3. outlook.search_mail — ровно один раз: query=отпуск, folder=Inbox, "
        "date=сегодня. count=0 = отсутствий нет. Не вызывать снова с "
        "больничный/отсутствие/списком ФИО.\n"
        "4. calendar.show_meetings — сегодняшние встречи ПСД, mark=keep, "
        "полная тема, attendees[].\n"
        "5. Если два слота пересекаются или есть окно — сначала блок «Предложение» "
        "(какую встречу, с какого времени, на какое свободное окно и почему: "
        "разовую сдвигать, регулярную оставлять; длительность та же; "
        "окно в 09:00–18:00 кроме обеда 12:00–13:00), затем "
        f"outlook.create_event (organizer={PSD_CHAIRMAN_FIO}). "
        "Разрешение спрашивает карточка HITL — askQuestion для этого не нужен. "
        "Без подтверждения в календарь не писать. Если пересечений и окон нет — "
        "create_event не вызывать.\n"
        "6. ## WORK_RESULT: полный устный список (время, тема, кто нужен) "
        "и «Предложение». ACTIONS. TESTS: PASS.\n"
        "Нельзя утром: askQuestion, web_search, imap.*, "
        "второй search_mail, вопрос «что должен делать агент», "
        "create_event без HITL.\n"
        "\n"
        "ВЕЧЕР:\n"
        "1. users.current\n"
        f"2. outlook.read_calendar на завтра: folder={PSD_MEETINGS_FOLDER}, "
        f"people=[\"{PSD_CHAIRMAN_FIO}\"]\n"
        "3. outlook.search_mail один раз query=отпуск\n"
        "4. при необходимости — тот же ящик «Совещания» с people[] других участников\n"
        "5. Окно = промежуток между встречами в 09:00–18:00. Обед 12:00–13:00 "
        "и хвост после последней встречи до 18:00 окном не считать.\n"
        "6. Окна и пересечения — предложить сдвиг уже стоящих встреч раньше. "
        "Длительности не менять, новые совещания не выдумывать.\n"
        "7. calendar.show_meetings: keep / add-green (предложение) / cancel-red\n"
        f"8. outlook.create_event (organizer={PSD_CHAIRMAN_FIO}) на предложенный "
        "сдвиг или на встречу, которую назвал человек. Жди HITL. "
        "Без разрешения не считать запись сделанной.\n"
        "9. ## WORK_RESULT: список + «Предложение» + итог HITL. TESTS: PASS. "
        "Дальше инструменты не вызывать.\n"
        "\n"
        "Если calendars[].status не meetings/own/shared/visible — напиши "
        "«нет доступа к ящику Совещания» и остановись. Не подставляй личный "
        "календарь. status=meetings и count=0 — у ПСД нет встреч в этот день.\n"
        "\n"
        "Суббота, воскресенье и праздники РФ 2026 (1–8 янв, 23 фев, 8 мар, "
        "1 и 9 мая, 12 июн, 4 ноя) — сказать «нерабочий день» и остановиться. "
        "web_search не нужен.\n"
        "\n"
        "Сдвиг: вызови outlook.create_event и дождись разрешения HITL. "
        "Не пиши в календарь молча и не спрашивай то же через askQuestion.\n"
        "\n"
        "Нельзя: imap.list_unread / imap.search; писать в календарь без HITL; "
        "рассылать приглашения вручную; выдумывать встречи; готовить xlsx/Word "
        "план дня; спрашивать расписание агента на рабочем прогоне."
    )


def calendar_control_local_playbook(
    *, title: str, demo_text: str = "", answered_scope: str = ""
) -> dict[str, Any]:
    scope = (answered_scope or "").strip()
    scope_line = f"Объём запуска:\n{scope}\n\n" if scope else ""
    summary = (demo_text or calendar_control_playbook_instructions()).strip()
    if len(summary) > 2500:
        summary = summary[:2500] + "…"
    return {
        "instructions": f"{scope_line}{calendar_control_playbook_instructions()}",
        "example_run": summary,
        "demo_ok": True,
        "tools": calendar_control_runtime_tools(),
        "name": title or "Подготовка ПСД к рабочему дню и контроль календаря",
        "expected_result": calendar_control_playbook_draft()["result"],
        "triggers": calendar_control_schedule_draft()["triggers"],
        "when_to_run": calendar_control_playbook_draft()["when_to_run"],
        "steps": calendar_control_playbook_draft()["steps"],
    }


def apply_calendar_control_config(
    local_run: dict[str, Any] | None, *, title: str, notes: str
) -> dict[str, Any]:
    local = dict(local_run or {})
    blob = f"{title} {notes}"
    if not is_calendar_control_agent(blob):
        return local
    draft = calendar_control_playbook_draft()
    playbook = calendar_control_local_playbook(title=title or draft["title"], demo_text=notes)
    local["playbook"] = playbook
    local["playbook_draft"] = draft
    local["schedule_draft"] = calendar_control_schedule_draft()
    local["runtime"] = str(local.get("runtime") or "mcp")
    local["tools"] = calendar_control_runtime_tools()
    local["ui_mode"] = "chat"
    return local


def apply_calendar_control_plan_runtime(
    plan_data: dict[str, Any] | None, *, title: str, notes: str
) -> dict[str, Any]:
    plan = dict(plan_data or {})
    if not is_calendar_control_agent(title, notes, plan.get("goal") or ""):
        return plan
    seed = calendar_control_playbook_draft()
    runtime = dict(plan.get("runtime") or {})
    runtime["kind"] = "calendar_control"
    runtime["tools"] = calendar_control_runtime_tools()
    plan["runtime"] = runtime
    plan["steps"] = seed["steps"]
    plan["goal"] = seed["goal"]
    plan["constraints"] = [
        "При пересечении или окне — предложить какую встречу куда перенести "
        "и вызвать outlook.create_event. Запись только после HITL.",
        "Утром не задавать askQuestion и не повторять search_mail.",
        "Не готовить письменный план дня.",
        "Не писать в Outlook без разрешения человека.",
    ]
    if not (plan.get("title") or "").strip():
        plan["title"] = title or seed["title"]
    return plan
