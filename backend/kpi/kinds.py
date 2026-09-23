from __future__ import annotations

FORMULA_KINDS = frozenset(
    {
        "ratio_higher",
        "ratio_lower",
        "gate_then_ratio",
        "min_of",
        "complement_ratio",
        "violation_bands",
        "individual",
        "needs_clarify",
    }
)

SOURCE_ROLES = frozenset({"plan", "fact"})

SOURCE_KINDS = frozenset(
    {
        "regulation",
        "position_norm",
        "outlook",
        "onec",
        "files",
        "agent_runs",
        "manual",
        "unknown",
    }
)

BONUS_KINDS = frozenset({"salary_times_crp_times_sum", "none"})
