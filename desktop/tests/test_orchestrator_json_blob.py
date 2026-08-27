from app.orchestrator.json_blob import extract_json_object


def test_extract_json_object_from_fence() -> None:
    text = """готово
```json
{"summary": "KPI", "tiles": [{"id": "a"}]}
```
"""
    data = extract_json_object(text)
    assert data is not None
    assert data["summary"] == "KPI"
    assert data["tiles"][0]["id"] == "a"


def test_extract_json_object_from_braces() -> None:
    data = extract_json_object('текст {"tiles":[{"id":"x"}]} хвост')
    assert data is not None
    assert data["tiles"][0]["id"] == "x"
