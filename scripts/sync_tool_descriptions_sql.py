"""Generate infra/postgres/init/03-tool-descriptions.sql from tool_catalog."""

from __future__ import annotations

from pathlib import Path

from platform_contracts.tool_catalog import TOOL_CATALOG


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    out = root / "infra" / "postgres" / "init" / "03-tool-descriptions.sql"
    lines = [
        "-- Sync tool_registry descriptions from platform_contracts/tool_catalog.py",
        "",
    ]
    for name in sorted(TOOL_CATALOG):
        desc = TOOL_CATALOG[name].description.replace("'", "''")
        lines.append(
            f"UPDATE platform_core.tool_registry SET description = '{desc}' WHERE name = '{name}';"
        )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {out} ({len(TOOL_CATALOG)} tools)")


if __name__ == "__main__":
    main()
