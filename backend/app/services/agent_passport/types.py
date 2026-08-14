from __future__ import annotations

from pydantic import BaseModel, Field


class ExtractedFunction(BaseModel):
    """Упрощённая функция агента для паспорта (без доменных enum Constructor)."""

    name: str
    description: str = ""
    action_level: str = "read"
    requires_human_approval: bool = False
    automation_kind: str = "auto"

    @property
    def is_physical(self) -> bool:
        return self.automation_kind == "physical"

    def with_derived_approval(self) -> ExtractedFunction:
        text = f"{self.name} {self.description}".casefold()
        kind = self.automation_kind
        if kind != "physical" and any(
            tip in text for tip in ("склад", "отгрузк", "погрузк", "физическ")
        ):
            kind = "physical"
        needs = self.requires_human_approval or kind == "physical" or self.action_level in {
            "write",
            "dangerous",
        }
        return self.model_copy(
            update={"automation_kind": kind, "requires_human_approval": needs}
        )


class PassportFunctionIn(BaseModel):
    name: str = Field(..., min_length=1)
    description: str = ""
    action_level: str = "read"
    requires_human_approval: bool = False
    automation_kind: str = "auto"
