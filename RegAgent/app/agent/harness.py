from __future__ import annotations

from pathlib import Path
from shutil import copy2
from uuid import uuid4

from app.agent.setup import run_setup
from app.agent.pipeline import CardPipelineService
from app.config import REGULATIONS_DIR, WORKSPACES_DIR, cursor_api_key, ensure_data_dirs
from app.models import Card, UiSpec
from app.regulation.extract import extract_text
from app.storage.repository import CardRepository


class CardService:
    """Legacy wrapper — новый pipeline через CardPipelineService."""

    def __init__(self, repo: CardRepository | None = None) -> None:
        self.repo = repo or CardRepository()
        self.pipeline = CardPipelineService(self.repo)

    def create_from_regulation(
        self,
        source_path: str,
        *,
        clarifications: dict[str, str] | None = None,
        existing: Card | None = None,
        on_event=None,
    ) -> tuple[Card, UiSpec]:
        if cursor_api_key():
            card = self.pipeline.intake_regulation(source_path, existing=existing)
            card = self.pipeline.run_functions(card, on_event=on_event)
            if len(card.functions.groups) > 1 and not card.functions.selected_group_id:
                return card, card.ui_spec
            card = self.pipeline.run_passport(card, on_event=on_event)
            if clarifications and card.passport.questions:
                card = self.pipeline.answer_passport_questions(card, clarifications)
            card = self.pipeline.run_playbook_draft(card, on_event=on_event)
            return card, card.ui_spec

        ensure_data_dirs()
        card_id = existing.id if existing else f"card-{uuid4().hex[:12]}"
        reg_dir = REGULATIONS_DIR / card_id
        reg_dir.mkdir(parents=True, exist_ok=True)
        dest = reg_dir / Path(source_path).name
        if Path(source_path).resolve() != dest.resolve():
            copy2(source_path, dest)
        text = extract_text(dest if dest.exists() else source_path)
        spec = run_setup(
            regulation_text=text,
            file_name=dest.name,
            clarifications=clarifications,
            on_event=on_event,
        )
        workspace = WORKSPACES_DIR / card_id
        workspace.mkdir(parents=True, exist_ok=True)
        card = Card(
            id=card_id,
            title=spec.title,
            summary=spec.summary,
            regulation_path=str(dest),
            regulation_text=text,
            ui_spec=spec,
            rules_prompt=spec.rules_prompt,
            workspace_dir=str(workspace),
            phase="demo",
            cursor_agent_id=(existing.cursor_agent_id if existing else ""),
        )
        if existing:
            card.created_at = existing.created_at
        self.repo.save(card)
        return card, spec

    def save_card(self, card: Card) -> Card:
        return self.repo.save(card)

    def list_cards(self) -> list[Card]:
        return self.repo.list_cards()

    def get(self, card_id: str) -> Card | None:
        return self.repo.get(card_id)

    def delete(self, card_id: str) -> None:
        self.repo.delete(card_id)

    def update_agent_id(self, card_id: str, agent_id: str) -> None:
        self.repo.update_agent_id(card_id, agent_id)
