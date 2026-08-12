from __future__ import annotations

from app.schemas.regulation import ChangeTransaction, RegulationChangeDraft


def transaction_for_change(change: RegulationChangeDraft, *, index: int) -> ChangeTransaction:
    return ChangeTransaction(
        transactionId=f"TX-{index:03d}",
        changes=[change],
        reason=(
            "Изменение сформировано из ответа пользователя. "
            "Связанные блоки перечислены в affectedBlocks и должны согласовываться вместе."
        ),
    )
