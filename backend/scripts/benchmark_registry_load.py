"""Compare assignment registry list with/without tabular part (requires OData in .env)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.erp_assignments import handle_assignments  # noqa: E402


def _run(label: str, **extra: object) -> float:
    args = {
        "action": "list",
        "limit": 100,
        "only_open": False,
        "profile": True,
        **extra,
    }
    t0 = time.perf_counter()
    result = handle_assignments(args)
    elapsed = time.perf_counter() - t0
    timing = result.get("timing_ms") or {}
    print(
        f"{label}: wall={elapsed:.2f}s count={result.get('count')} "
        f"timing_ms={timing}"
    )
    return elapsed


def main() -> int:
    # Wide period so the sample is representative.
    common = {"date_from": "2024-01-01", "date_to": "2026-12-31"}
    full = _run("include_lines=1", include_lines=True, **common)
    lite = _run("include_lines=0", include_lines=False, **common)
    if lite > 0 and full > 0:
        ratio = full / lite
        print(f"speedup lite vs full: {ratio:.2f}x")
        if ratio < 3:
            print("WARN: target 3x not reached on this run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
