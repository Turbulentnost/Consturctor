from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from shutil import copy2
from typing import Any
from uuid import uuid4

from app.agent.dictionary import validate_dictionary
from app.agent.oneshot import run_oneshot_prompt
from app.agent.json_parse import fallback_ui_spec
from app.agent.prompts_create import (
    build_demo_continue_prompt,
    build_demo_prompt,
    build_demo_system,
    build_functions_prompt,
    build_passport_prompt,
    build_passport_questions_prompt,
    build_playbook_draft_prompt,
    build_playbook_repair_prompt,
    build_ui_spec_from_pipeline,
    parse_demo_result,
    parse_functions_result,
    parse_passport_questions,
    parse_passport_result,
    parse_playbook_draft,
    playbook_from_draft,
    validate_playbook_draft,
)
from app.agent.runtime import CardAgentSession
from app.config import REGULATIONS_DIR, WORKSPACES_DIR, cursor_api_key, ensure_data_dirs
from app.models import Card, FunctionGroup, can_publish
from app.regulation.extract import extract_text
from app.storage.repository import CardRepository

logger = logging.getLogger(__name__)

EventCallback = Callable[[dict[str, Any]], None]


class PipelineError(RuntimeError):
    pass


class CardPipelineService:
    def __init__(self, repo: CardRepository | None = None) -> None:
        self.repo = repo or CardRepository()

    def intake_regulation(self, source_path: str, *, existing: Card | None = None) -> Card:
        ensure_data_dirs()
        card_id = existing.id if existing else f"card-{uuid4().hex[:12]}"
        reg_dir = REGULATIONS_DIR / card_id
        reg_dir.mkdir(parents=True, exist_ok=True)
        dest = reg_dir / Path(source_path).name
        if Path(source_path).resolve() != dest.resolve():
            copy2(source_path, dest)
        text = extract_text(dest if dest.exists() else source_path)
        workspace = WORKSPACES_DIR / card_id
        workspace.mkdir(parents=True, exist_ok=True)
        card = Card(
            id=card_id,
            title=Path(source_path).stem[:120],
            regulation_path=str(dest),
            regulation_text=text,
            workspace_dir=str(workspace),
            phase="review",
            cursor_agent_id=(existing.cursor_agent_id if existing else ""),
        )
        if existing:
            card.created_at = existing.created_at
        self.repo.save(card)
        return card

    def _cwd(self, card: Card) -> str:
        return card.workspace_dir or "."

    def run_functions(
        self,
        card: Card,
        *,
        on_event: EventCallback | None = None,
    ) -> Card:
        if on_event:
            on_event({"type": "phase_start", "phase": "functions", "text": "Анализируем функции регламента…"})
        if not cursor_api_key():
            card.functions = _fallback_functions(card)
            card.title = card.title or "Агент по регламенту"
            card.phase = "passport" if len(card.functions.groups) == 1 else "functions"
            if len(card.functions.groups) == 1:
                card.functions.selected_group_id = card.functions.groups[0].id
            if on_event:
                on_event({"type": "phase_end", "phase": "functions"})
            return self.repo.save(card)

        prompt = build_functions_prompt(
            regulation_text=card.regulation_text,
            file_name=Path(card.regulation_path).name,
        )
        text = run_oneshot_prompt(prompt, cwd=self._cwd(card), on_event=on_event)
        parsed = parse_functions_result(text)
        card.functions = parsed
        if parsed.title:
            card.title = parsed.title
        if parsed.summary:
            card.summary = parsed.summary
        if not parsed.groups:
            card.functions = _fallback_functions(card)
        if len(card.functions.groups) == 1:
            card.functions.selected_group_id = card.functions.groups[0].id
            card.phase = "passport"
        else:
            card.phase = "functions"
        if on_event:
            on_event({"type": "phase_end", "phase": "functions"})
        return self.repo.save(card)

    def select_function_group(self, card: Card, group_id: str) -> Card:
        card.functions.selected_group_id = group_id
        card.phase = "passport"
        return self.repo.save(card)

    def run_passport(
        self,
        card: Card,
        *,
        on_event: EventCallback | None = None,
    ) -> Card:
        if on_event:
            on_event({"type": "phase_start", "phase": "passport", "text": "Формируем паспорт агента…"})
        group = _selected_group(card)
        if not cursor_api_key():
            spec = fallback_ui_spec(card.regulation_text, Path(card.regulation_path).name)
            card.passport = _fallback_passport(card, group)
            card.passport.questions = spec.needs_clarification
            card.phase = "readiness" if card.passport.questions else "design"
            if on_event:
                on_event({"type": "phase_end", "phase": "passport"})
            return self.repo.save(card)

        prompt = build_passport_prompt(card=card, group=group)
        if on_event:
            on_event({"type": "substep", "text": "Формируем паспорт агента…"})
        text = run_oneshot_prompt(prompt, cwd=self._cwd(card), on_event=on_event)
        card.passport = parse_passport_result(text)
        if card.passport.title:
            card.title = card.passport.title
        if card.passport.summary:
            card.summary = card.passport.summary

        q_prompt = build_passport_questions_prompt(card=card)
        if on_event:
            on_event({"type": "substep", "text": "Готовим уточняющие вопросы…"})
        q_text = run_oneshot_prompt(q_prompt, cwd=self._cwd(card), on_event=on_event)
        card.passport.questions = parse_passport_questions(q_text)
        card.phase = "readiness" if card.passport.questions else "design"
        if on_event:
            on_event({"type": "phase_end", "phase": "passport"})
        return self.repo.save(card)

    def answer_passport_questions(self, card: Card, answers: dict[str, str]) -> Card:
        card.passport.answered.update(answers)
        card.passport.questions = [
            q for q in card.passport.questions if q.id not in answers
        ]
        card.phase = "design"
        return self.repo.save(card)

    def run_playbook_draft(
        self,
        card: Card,
        *,
        on_event: EventCallback | None = None,
    ) -> Card:
        if on_event:
            on_event({"type": "phase_start", "phase": "playbook", "text": "Собираем сценарий…"})
        if not cursor_api_key():
            card.playbook_draft = _fallback_playbook_draft(card)
            card.phase = "demo"
            if on_event:
                on_event({"type": "phase_end", "phase": "playbook"})
            return self.repo.save(card)

        prompt = build_playbook_draft_prompt(card=card)
        if on_event:
            on_event({"type": "substep", "text": "Собираем сценарий…"})
        text = run_oneshot_prompt(prompt, cwd=self._cwd(card), on_event=on_event)
        draft = parse_playbook_draft(text)
        draft = validate_playbook_draft(draft, card.passport)
        if draft.status == "failed" and draft.errors:
            if on_event:
                on_event({"type": "substep", "text": "Исправляем сценарий…"})
            repair = build_playbook_repair_prompt(card=card.model_copy(update={"playbook_draft": draft}), errors=draft.errors)
            repaired_text = run_oneshot_prompt(repair, cwd=self._cwd(card), on_event=on_event)
            draft = validate_playbook_draft(parse_playbook_draft(repaired_text), card.passport)
        card.playbook_draft = draft
        card.phase = "demo" if draft.status == "verified" else "design"
        if on_event:
            on_event({"type": "phase_end", "phase": "playbook"})
        return self.repo.save(card)

    def run_demo(
        self,
        card: Card,
        *,
        on_event: EventCallback | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> Card:
        steps_total = max(1, len(card.playbook_draft.steps))
        if on_event:
            on_event(
                {
                    "type": "phase_start",
                    "phase": "demo",
                    "text": f"Пробный прогон (шаг 1 из {steps_total})…",
                    "step": 1,
                    "steps_total": steps_total,
                }
            )
        if not cursor_api_key():
            card.demo = parse_demo_result("RESULT:\nДемо offline (нет API ключа)", steps_count=steps_total)
            card.demo.ok = False
            card.phase = "demo"
            if on_event:
                on_event({"type": "phase_end", "phase": "demo"})
            return self.repo.save(card)

        session = CardAgentSession(card)
        try:
            if on_event:
                on_event({"type": "substep", "text": "Подключаем агента…"})
            session.open()
            card.cursor_agent_id = session.agent_id
            system = build_demo_system(card)
            session.send(system, on_event=on_event, cancel_check=cancel_check)

            if on_event:
                on_event(
                    {
                        "type": "substep",
                        "text": f"Пробный прогон (шаг 1 из {steps_total})…",
                        "step": 1,
                        "steps_total": steps_total,
                    }
                )
            prompt = build_demo_prompt(card=card)
            answer = session.send(prompt, on_event=on_event, cancel_check=cancel_check)
            demo = parse_demo_result(answer, steps_count=steps_total)
            card.demo = demo
            card.phase = "demo"
            if demo.ok:
                card.demo.verified = True
        except Exception as exc:
            logger.warning("Demo failed: %s", exc)
            card.demo = parse_demo_result(f"RESULT:\nОшибка: {exc}")
            card.demo.ok = False
            card.phase = "failed"
        finally:
            session.close()
        if on_event:
            on_event({"type": "phase_end", "phase": "demo"})
        return self.repo.save(card)

    def continue_demo_step(
        self,
        card: Card,
        step_index: int,
        *,
        on_event: EventCallback | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> Card:
        session = CardAgentSession(card)
        try:
            session.open()
            prompt = build_demo_continue_prompt(card=card, step_index=step_index)
            answer = session.send(prompt, on_event=on_event, cancel_check=cancel_check)
            demo = parse_demo_result(answer, steps_count=len(card.playbook_draft.steps))
            card.demo = demo
        finally:
            session.close()
        return self.repo.save(card)

    def publish(self, card: Card) -> Card:
        if not can_publish(card):
            raise PipelineError(
                "Публикация недоступна: нужен verified playbook_draft и demo.ok=true"
            )
        card.playbook = playbook_from_draft(card.playbook_draft, card.passport)
        card.ui_spec = build_ui_spec_from_pipeline(card)
        card.rules_prompt = card.ui_spec.rules_prompt
        card.phase = "published"
        card.triggers = card.triggers.model_copy(update={"enabled": False})
        card.kpi = card.kpi.model_copy(update={"enabled": False})
        return self.repo.save(card)

    def advance_after_schedule(self, card: Card) -> Card:
        card.phase = "published"
        return self.repo.save(card)

    def set_phase(self, card: Card, phase: str) -> Card:
        card.phase = phase  # type: ignore[assignment]
        return self.repo.save(card)

    def get(self, card_id: str) -> Card | None:
        return self.repo.get(card_id)

    def list_cards(self) -> list[Card]:
        return self.repo.list_cards()

    def save(self, card: Card) -> Card:
        return self.repo.save(card)

    def delete(self, card_id: str) -> None:
        self.repo.delete(card_id)


def _selected_group(card: Card) -> FunctionGroup | None:
    gid = card.functions.selected_group_id
    for group in card.functions.groups:
        if group.id == gid:
            return group
    if len(card.functions.groups) == 1:
        return card.functions.groups[0]
    return None


def _fallback_functions(card: Card) -> Any:
    from app.models import FunctionsData

    validation = validate_dictionary(
        system="onec",
        entity="porucheniya",
        operations=["docflow_tasks"],
    )
    group = FunctionGroup(
        id="g1",
        title=card.title or "Основной процесс",
        summary=card.summary or "По регламенту",
        system="onec",
        entity="porucheniya",
        operations=["docflow_tasks"],
        tools=validation.tools or ["onec.docflow_tasks"],
    )
    return FunctionsData(groups=[group], title=card.title, summary=card.summary)


def _fallback_passport(card: Card, group: FunctionGroup | None) -> Any:
    from app.models import PassportData

    tools = group.tools if group else ["onec.docflow_tasks"]
    return PassportData(
        title=card.title,
        goal=f"Автоматизировать процесс по регламенту «{card.title}»",
        summary=card.summary,
        system=group.system if group else "onec",
        entity=group.entity if group else "porucheniya",
        operations=group.operations if group else ["docflow_tasks"],
        tools=tools,
    )


def _fallback_playbook_draft(card: Card) -> Any:
    from app.models import PlaybookDraft, PlaybookStep

    tool = (card.passport.tools or ["onec.docflow_tasks"])[0]
    step = PlaybookStep(
        id="s1",
        title="Основной сценарий",
        action=card.passport.goal or "Выполни задачу по регламенту",
        tool=tool,
        done_when="Пользователь получил результат",
    )
    draft = PlaybookDraft(status="verified", steps=[step], tools=[tool])
    return validate_playbook_draft(draft, card.passport)
