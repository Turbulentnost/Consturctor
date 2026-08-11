from __future__ import annotations

from app.services.regulation.types import ExtractedBlock


def recognition_quality(blocks: list[ExtractedBlock]) -> float:
    if not blocks:
        return 0.0
    values = [max(0.0, min(1.0, block.confidence)) for block in blocks]
    non_empty_ratio = sum(1 for block in blocks if block.text.strip() or block.table) / len(blocks)
    return round((sum(values) / len(values)) * non_empty_ratio, 3)
