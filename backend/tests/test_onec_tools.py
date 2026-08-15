"""1C OData tool smoke tests."""

from __future__ import annotations

from app.services.onec_tools import OnecToolError, invoke_onec, odata_configured


def test_onec_odata_get_stub_or_real() -> None:
    result = invoke_onec(
        "onec.odata_get",
        {"entity": "Document_ТД_ВходящаяКорреспонденция", "top": 2},
    )
    assert "source" in result or "value" in result or "data" in result
    if not odata_configured():
        assert result.get("source") == "stub"
        assert result.get("count", 0) >= 1


def test_onec_unknown_tool() -> None:
    try:
        invoke_onec("onec.unknown", {})
        raise AssertionError("expected OnecToolError")
    except OnecToolError:
        pass
