from __future__ import annotations

from pathlib import Path

from app.services.act_protocol_merge import (
    extract_protocol_text,
    merge_protocol_documents,
    parse_protocol_to_documents,
    task_implies_protocol_merge,
)

PROTOCOL = Path(__file__).resolve().parents[2] / "logs" / "protocol_rk_47_2026-08-19.txt"
FREEFORM = Path(__file__).resolve().parents[2] / "logs" / "protocol_freeform_3_tasks.txt"


def test_task_implies_protocol_merge() -> None:
    assert task_implies_protocol_merge("Дополни ACT-реестр из протокола")
    assert task_implies_protocol_merge(
        "добавь ещё Задача: тест, Исполнитель: Иванов, срок до 20.08.26, статус в работе"
    )
    assert not task_implies_protocol_merge("Выгрузи полный реестр")


def test_parse_protocol_three_acts() -> None:
    text = PROTOCOL.read_text(encoding="utf-8")
    docs = parse_protocol_to_documents(text)
    numbers = {d["number_display"] for d in docs}
    assert numbers == {"ACT00-00089", "ACT00-00090", "ACT00-00091"}
    act89 = next(d for d in docs if d["number_display"] == "ACT00-00089")
    assert len(act89["task_lines"]) == 2
    assert act89["task_lines"][0]["executor"] == "Свистун Сергей Николаевич"
    assert act89["task_lines"][0]["deadline"] == "30.09.2026"


def test_merge_adds_new_documents() -> None:
    text = PROTOCOL.read_text(encoding="utf-8")
    protocol_docs = parse_protocol_to_documents(text)
    odata = [
        {
            "number_display": "ACT00-00088",
            "task_lines": [{"task": "existing", "deadline_raw": "2026-01-01T00:00:00"}],
        }
    ]
    merged, stats = merge_protocol_documents(list(odata), protocol_docs)
    assert stats["added_documents"] == 3
    assert stats["added_task_lines"] == 5
    assert len(merged) == 4


def test_extract_protocol_from_task_block() -> None:
    task = "Дополни реестр\n\n--- ПРОТОКОЛ ---\nACT00-00099 — «Тест»\n  1. Задача\n     Исполнитель: Иванов\n     Срок: 01.01.2027"
    assert "ACT00-00099" in extract_protocol_text(task)


def test_parse_freeform_protocol_three_tasks() -> None:
    text = FREEFORM.read_text(encoding="utf-8")
    docs = parse_protocol_to_documents(text)
    assert len(docs) == 1
    doc = docs[0]
    assert doc["number_display"] == "ACT00-PROTO-20260819"
    assert len(doc["task_lines"]) == 3
    assert doc["task_lines"][0]["executor"] == "Тищенко Марина Николаевна"
    assert doc["task_lines"][0]["deadline"] == "05.09.2026"
    assert doc["task_lines"][1]["executor"] == "Свистун Сергей Николаевич"
    assert doc["task_lines"][2]["executor"] == "Жалыбин Максим Дмитриевич"


def test_merge_freeform_adds_synthetic_act() -> None:
    text = FREEFORM.read_text(encoding="utf-8")
    protocol_docs = parse_protocol_to_documents(text)
    odata = [
        {
            "number_display": "ACT00-00088",
            "task_lines": [{"task": "existing", "deadline_raw": "2026-01-01T00:00:00"}],
        }
    ]
    merged, stats = merge_protocol_documents(list(odata), protocol_docs)
    assert stats["added_documents"] == 1
    assert stats["added_task_lines"] == 3
    assert len(merged) == 2
    proto = next(d for d in merged if d["number_display"] == "ACT00-PROTO-20260819")
    assert len(proto["task_lines"]) == 3


def test_parse_inline_task_addition() -> None:
    task = (
        "добавь ещё Задача: выполнить работы по созданию агента, "
        "Исполнитель: Жалыбин Максим Дмитриевич, срок до 20.08.26, статус в работе"
    )
    docs = parse_protocol_to_documents(task)
    assert len(docs) == 1
    assert docs[0]["number_display"].startswith("ACT00-PROTO-")
    line = docs[0]["task_lines"][0]
    assert "агента" in line["task"].casefold()
    assert line["executor"] == "Жалыбин Максим Дмитриевич"
    assert line["deadline"] == "20.08.2026"


def test_extract_freeform_from_task() -> None:
    text = FREEFORM.read_text(encoding="utf-8")
    task = f"Дополни ACT-реестр по протоколу ниже\n\n{text}"
    extracted = extract_protocol_text(task)
    assert "Тищенко Марина Николаевна" in extracted
    assert "ACT00-" not in extracted
