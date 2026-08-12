"""Модель найденной закупки."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Tender:
    """Одна закупка из результатов поиска Росэлторг."""

    title: str
    amount: str
    deadline: str
    url: str = ""
    procedure_id: str = ""
    matched_queries: list[str] = field(default_factory=list)

    def dedup_key(self) -> str:
        """Ключ для дедупликации: id закупки, иначе URL, иначе название."""
        return (self.procedure_id or self.url or self.title).strip().lower()
