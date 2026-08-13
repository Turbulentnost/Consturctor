from __future__ import annotations

import json
from pathlib import Path

from platform_contracts.tool_catalog import TOOL_CATALOG, all_tool_names, openai_function_schema


def test_catalog_covers_manifest_tools() -> None:
    manifest_path = Path(__file__).resolve().parents[1] / "backend" / "data" / "tool_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_names = set(manifest["default"])
    catalog_names = set(all_tool_names())
    missing = manifest_names - catalog_names
    assert not missing, f"Missing catalog entries: {sorted(missing)}"


def test_every_tool_has_description_and_parameters() -> None:
    for name, entry in TOOL_CATALOG.items():
        assert entry.description.strip(), name
        assert entry.parameters.get("type") == "object", name
        assert "properties" in entry.parameters, name
        schema = openai_function_schema(name)
        assert schema is not None
        assert schema["function"]["name"] == name
