"""Heuristic workflow plan when Cursor API is unavailable (dev_mode)."""

from __future__ import annotations

import re

from app.services.workflows.plan_models import OpenQuestion, PlanStep, WorkflowPlan

_BULLET_RE = re.compile(
    r"^(?:[-•●▪*]|\d+[.)]\s+)\s*(.+)$",
    re.MULTILINE,
)
_ONEC_HINTS = ("1с", "1c", "odata", "erp", "com", "action tracker", "поручен")
_OUTLOOK_HINTS = ("outlook", "календар", "совещан", "встреч", "imap", "exchange")
_WEB_HINTS = ("сайт", "эtp", "эtp", "браузер", "http", "портал")


def build_heuristic_plan(
    *,
    document_name: str,
    document_text: str,
    notes: str = "",
) -> WorkflowPlan:
    title = _clean_title(document_name) or "Агент по регламенту"
    body = _materials_body(document_text, notes)
    goal = _extract_goal(body, title)
    steps = _extract_steps(body, title)
    if not steps:
        steps = _default_steps(title, body)

    constraints = _extract_constraints(body)
    test_criteria = _default_tests(steps)
    runtime_kind = _infer_runtime_kind(body)
    open_questions = _default_questions(body, runtime_kind)

    plan = WorkflowPlan(
        title=title,
        goal=goal,
        constraints=constraints,
        out_of_scope=["Изменение регламента и оргструктуры без отдельного согласования"],
        steps=steps,
        test_criteria=test_criteria,
        open_questions=open_questions,
        raw_text="heuristic:dev_mode",
    )
    if runtime_kind:
        plan.runtime.kind = runtime_kind
    return plan


def _clean_title(name: str) -> str:
    stem = re.sub(r"\.(docx|pdf|txt|md)$", "", (name or "").strip(), flags=re.I)
    return stem[:120]


def _materials_body(document_text: str, notes: str) -> str:
    parts: list[str] = []
    if (notes or "").strip():
        parts.append(notes.strip())
    text = (document_text or "").strip()
    if text:
        # Skip compose_document file headers for matching.
        text = re.sub(r"^===== FILE:.*?=====\s*", "", text, flags=re.MULTILINE)
        parts.append(text)
    return "\n\n".join(parts).strip()


def _extract_goal(body: str, title: str) -> str:
    for line in body.splitlines():
        line = line.strip()
        if len(line) < 40 or line.startswith("====="):
            continue
        if re.search(r"[.!?]$", line) or len(line) > 80:
            return line[:500]
    return (
        f"Автоматизировать операции по регламенту «{title}»: "
        "регистрация, контроль и сопровождение поручений с проверкой по материалам."
    )


def _extract_steps(body: str, title: str) -> list[PlanStep]:
    candidates: list[str] = []
    for match in _BULLET_RE.finditer(body):
        line = match.group(1).strip()
        if 12 <= len(line) <= 240 and _looks_like_action(line):
            candidates.append(line)
    if not candidates:
        for line in body.splitlines():
            line = line.strip()
            if 20 <= len(line) <= 200 and _looks_like_action(line):
                candidates.append(line)
    seen: set[str] = set()
    steps: list[PlanStep] = []
    for idx, action in enumerate(candidates[:8], start=1):
        key = action.casefold()
        if key in seen:
            continue
        seen.add(key)
        steps.append(
            PlanStep(
                id=f"s{idx}",
                title=action[:80],
                action=action,
                done_when="Шаг воспроизводится на тестовых данных без ручных обходов",
                depends_on=[f"s{idx - 1}"] if idx > 1 else [],
            )
        )
    if steps:
        steps.insert(
            0,
            PlanStep(
                id="s0",
                title="Разбор регламента",
                action=f"Сопоставить шаги с материалами «{title}» и выделить обязательные артефакты",
                done_when="Список входов/выходов и ролей зафиксирован",
                depends_on=[],
            ),
        )
        for step in steps[1:]:
            if "s0" not in step.depends_on:
                step.depends_on = ["s0", *step.depends_on]
    return steps


def _default_steps(title: str, body: str) -> list[PlanStep]:
    mentions_assignments = "поручен" in body.casefold()
    base = [
        PlanStep(
            id="s1",
            title="Разбор регламента",
            action=f"Извлечь обязанности и контрольные точки из «{title}»",
            done_when="Описаны входы, выходы и роли",
        ),
        PlanStep(
            id="s2",
            title="Сценарий сопровождения",
            action="Описать цепочку: регистрация → контроль сроков → эскалация → отчёт",
            done_when="Сценарий покрывает ключевые этапы регламента",
            depends_on=["s1"],
        ),
    ]
    if mentions_assignments:
        base.append(
            PlanStep(
                id="s3",
                title="Интеграция с учётной системой",
                action="Подключить чтение/обновление поручений через выбранный способ доступа",
                done_when="Тестовый прогон получает и обновляет поручение",
                depends_on=["s2"],
            )
        )
    base.append(
        PlanStep(
            id=f"s{len(base)+1}",
            title="Тестовый прогон",
            action="Проверить сценарий на fixtures или live-данных по критериям",
            done_when="TESTS: PASS по чек-листу",
            depends_on=[base[-1].id],
        )
    )
    return base


def _extract_constraints(body: str) -> list[str]:
    out = [
        "Не запрашивать у пользователя секреты — учётные данные только в backend/.env",
        "Следовать формулировкам регламента, не выдумывать процессы",
    ]
    lower = body.casefold()
    if any(h in lower for h in _ONEC_HINTS):
        out.append("Доступ к 1С — только через COM на машине пользователя или OData на сервере Constructor")
    return out


def _default_tests(steps: list[PlanStep]) -> list[str]:
    titles = [s.title for s in steps if s.title]
    if not titles:
        return ["Агент выполняет сценарий без ошибок на тестовых данных"]
    return [
        f"Проверка шага: {titles[-1]}",
        "Нет необработанных исключений и потери данных",
        "Результат соответствует регламенту (статусы, сроки, артефакты)",
    ]


def _infer_runtime_kind(body: str) -> str:
    lower = body.casefold()
    if any(h in lower for h in _ONEC_HINTS):
        return "onec"
    if any(h in lower for h in _OUTLOOK_HINTS):
        return "outlook_calendar"
    if any(h in lower for h in _WEB_HINTS):
        return "browser_task"
    return ""


def _default_questions(body: str, runtime_kind: str) -> list[OpenQuestion]:
    lower = body.casefold()
    questions: list[OpenQuestion] = []
    if runtime_kind == "onec" or any(h in lower for h in _ONEC_HINTS):
        questions.append(
            OpenQuestion(
                id="q_access",
                question="Как подключаться к 1С для этого агента?",
                why="От способа доступа зависят шаги реализации и тестовый прогон",
                options=[
                    "COM на этом компьютере (desktop-host)",
                    "OData на сервере Constructor",
                    "Только fixtures / офлайн без live",
                ],
            )
        )
    if runtime_kind == "outlook_calendar" or any(h in lower for h in _OUTLOOK_HINTS):
        questions.append(
            OpenQuestion(
                id="q_mail",
                question="Как работать с почтой/календарём?",
                why="Нужно выбрать канал интеграции до сборки workflow",
                options=[
                    "Outlook COM на этом компьютере",
                    "IMAP/Graph через сервер",
                    "Только fixtures",
                ],
            )
        )
    if not questions:
        questions.append(
            OpenQuestion(
                id="q_scope",
                question="Что считать успешным результатом первого релиза?",
                why="Нужен критерий готовности для тестового прогона",
                options=[
                    "Только чтение и отчёт по регламенту",
                    "Чтение + регистрация изменений",
                    "Полный цикл с эскалацией",
                ],
            )
        )
    return questions


def _looks_like_action(line: str) -> bool:
    lower = line.casefold()
    if lower.startswith(("приложение", "раздел", "глава", "статья", "таблица")):
        return False
    return bool(
        re.search(
            r"\b(ведёт|ведет|формирует|контролирует|регистрирует|обеспечивает|"
            r"сопровождает|фиксирует|мониторит|эскалирует|проводит|подготавливает|"
            r"согласовывает|обновляет|создаёт|создает|направляет|отслеживает)\b",
            lower,
        )
    )
