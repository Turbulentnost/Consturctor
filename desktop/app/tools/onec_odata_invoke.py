"""Proxy 1C OData list reads to the Constructor backend (onec.odata_get)."""

from __future__ import annotations

from typing import Any


def fetch_odata_list(
    *,
    entity: str,
    odata_filter: str = "",
    top: int = 30,
    number: str = "",
    ref_key: str = "",
) -> dict[str, Any]:
    from app.tools import runtime_api

    args: dict[str, Any] = {"entity": entity, "top": max(1, min(200, int(top or 30)))}
    if odata_filter:
        args["filter"] = odata_filter
    if number:
        args["number"] = number
    if ref_key:
        args["ref_key"] = ref_key

    data = runtime_api.request(
        "POST",
        "/api/v1/tools/onec.odata_get/invoke",
        json={"arguments": args},
        timeout=180.0,
    )
    if isinstance(data, dict) and "result" in data:
        raw = data.get("result")
        return raw if isinstance(raw, dict) else {"value": raw}
    return data if isinstance(data, dict) else {"value": data}


def odata_rows(raw: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in (raw.get("value") or []) if isinstance(row, dict)]
