from app.services.workflows.data_sandbox import run_dataset_code, validate_code


def test_sandbox_extracts_nested_field() -> None:
    data = {
        "document": {
            "number": "123",
            "risks": [{"type": "учёт рисков и замечаний", "status": "open"}],
        }
    }
    outcome = run_dataset_code(
        code="result = data['document']['risks'][0]['type']",
        data=data,
    )

    assert outcome["ok"] is True
    assert outcome["result"] == "учёт рисков и замечаний"


def test_sandbox_rejects_os_import() -> None:
    assert validate_code("import os\nresult = 1")
    outcome = run_dataset_code(code="import os\nresult = os.getcwd()", data={})
    assert outcome["ok"] is False


def test_sandbox_requires_result() -> None:
    outcome = run_dataset_code(code="value = 1", data={})
    assert outcome["ok"] is False
    assert "result" in outcome["error"]


def test_sandbox_filters_list() -> None:
    data = {"items": [{"id": 1, "ok": False}, {"id": 2, "ok": True}]}
    outcome = run_dataset_code(
        code="result = [item['id'] for item in data['items'] if item['ok']]",
        data=data,
    )
    assert outcome["ok"] is True
    assert outcome["result"] == [2]
