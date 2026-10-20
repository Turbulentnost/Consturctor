from app.services import assignment_docflow_tasks as tasks


def _item(*executors):
    return {
        "ref_key": "b75214dc-a846-11f1-9877-6cb31113810c",
        "lines": [{"line": i + 1, "text": f"Мероприятие {i + 1}", "executor": name} for i, name in enumerate(executors)],
    }


def _row(task_id, name, performer, begin, executed=False, step="", *, chain=0, no=1, mark="", comment="", text=""):
    return {
        "id": task_id,
        "name": name,
        "performer": performer,
        "author": "Ильченко Екатерина Александровна",
        "begin": begin,
        "due": "2026-10-20T23:59:59",
        "executed": executed,
        "execution_mark": mark,
        "step": step,
        "number": f"ДО-000000000000000000000000000000000000{chain:06d}{no:05d}" if chain else "",
        "description": text,
        "comment": comment,
    }


def test_tasks_are_grouped_by_process_without_measures():
    item = _item("Тен Л.Л.", "Тен Л.Л.")
    rows = [
        _row("e1", "Исполнить задачу №1", "Тен Л.Л.", "2026-09-01T10:00:00", True, "Исполнить", chain=5001,
             mark="ExecutedNeutral", comment="Заявление подано, вх. 15", text="Подать заявление в ИФНС"),
        _row("c1", "Проверить: ПОРУЧЕНИЕ. Задача №1", "Ильченко Екатерина Александровна", "2026-09-02T10:00:00",
             step="Проверить исполнение", chain=5001, no=2),
        _row("e2", 'Исполнить "Поручения (ТД) АСТ00-00093"', "Тен Л.Л.", "2026-09-01T10:01:00", step="Исполнить",
             chain=5002),
    ]

    tasks.link_tasks(item, rows)

    first, second = item["docflow_tasks"]
    assert [step["task_id"] for step in first["history"]] == ["e1", "c1"]
    assert first["label"] == "исполнитель отчитался, ждёт проверки"
    assert first["open_check_task_id"] == "c1"
    assert first["executor_report"] == "Заявление подано, вх. 15"
    assert first["text"] == "Подать заявление в ИФНС"
    assert second["open_execute_task_id"] == "e2"
    assert all("docflow_tasks" not in line for line in item["lines"])
    assert item["docflow_summary"] == {
        "total": 2,
        "accepted": 0,
        "open_tasks": 2,
        "all_accepted": False,
        "executors_without_tasks": [],
    }


def test_negative_check_is_return_and_positive_is_acceptance():
    item = _item("Тен Л.Л.")
    rows = [
        _row("e1", "Исполнить", "Тен Л.Л.", "2026-09-01T09:00:00", True, "Исполнить", chain=7),
        _row("c1", "Проверить исполнение", "Ильченко Е.А.", "2026-09-02T09:00:00", True, "Проверить исполнение",
             chain=7, no=2, mark="ExecutedNegative"),
        _row("e2", "Исполнить", "Тен Л.Л.", "2026-09-03T09:00:00", True, "Исполнить", chain=7, no=3),
        _row("c2", "Проверить исполнение", "Ильченко Е.А.", "2026-09-04T09:00:00", True, "Проверить исполнение",
             chain=7, no=4, mark="ExecutedPositive"),
    ]

    tasks.link_tasks(item, rows)

    task = item["docflow_tasks"][0]
    assert task["label"] == "принято проверяющим"
    assert task["returns"] == 1
    assert task["accepted_at"] == "2026-09-04"
    assert task["accepted_by"] == "Ильченко Е.А."
    assert item["docflow_summary"]["all_accepted"] is True


def test_last_negative_check_is_not_acceptance():
    rows = [
        _row("e1", "Исполнить", "Тен Л.Л.", "2026-09-01T09:00:00", True, "Исполнить", chain=7),
        _row("c1", "Проверить исполнение", "Ильченко Е.А.", "2026-09-02T09:00:00", True, "Проверить исполнение",
             chain=7, no=2, mark="ExecutedNegative"),
    ]

    found, _ = tasks.build_tasks(rows)

    assert found[0]["label"] == "возвращено на доработку"


def test_deadline_transfer_joins_its_task_by_date():
    rows = [
        _row("e1", "Исполнить задачу №1", "Ростовцева А.В.", "2026-05-29T15:11:57", step="Исполнить", chain=97426),
        _row("p1", 'Согласовать перенос срока по задаче: Исполнить задачу №1 ("Поручения (ТД) АСТ00-00039 '
             'от 29.05.2026 15:11:30 (Поручения)") от 29.05.2026 15:11:57', "Ильченко Е.А.", "2026-06-02T09:19:01",
             True, "Рассмотреть вопрос", chain=2865, no=13),
        _row("p2", "Ознакомиться: перенос срока по задаче \"Исполнить задачу №1 от 29.05.2026 15:11:57\"",
             "Ростовцева А.В.", "2026-06-02T09:35:12", True, "Ознакомиться с результатом рассмотрения",
             chain=2865, no=14),
        _row("r1", 'Ознакомиться "Поручения (ТД) АСТ00-00039"', "Тищенко М.Н.", "2026-06-03T10:00:00", False,
             "Ознакомиться", chain=7769, no=6),
    ]

    found, other = tasks.build_tasks(rows)

    assert [step["task_id"] for step in found[0]["history"]] == ["e1", "p1", "p2"]
    assert found[0]["returns"] == 0
    assert [step["task_id"] for step in other] == ["r1"]


def test_merges_duplicate_rows_from_both_queries():
    rows = [
        _row("e1", "Исполнить", "Тен Л.Л.", "2026-09-01T09:00:00", step="Исполнить", chain=7),
        {"id": "e1", "name": "Исполнить", "performer": "Тен Л.Л.", "begin": "2026-09-01T09:00:00",
         "step": "Исполнить", "description": "Подать заявление", "executed": False},
    ]

    found, _ = tasks.build_tasks(rows)

    assert len(found) == 1 and len(found[0]["history"]) == 1
    assert found[0]["text"] == "Подать заявление"


def test_executor_without_tasks_is_flagged():
    item = _item("Тен Людмила Лаврентьевна", "Солдатенко Оксана Николаевна", "")
    rows = [_row("e1", "Исполнить", "Тен Людмила Лаврентьевна", "2026-09-01T09:00:00", step="Исполнить", chain=7)]

    tasks.link_tasks(item, rows)

    assert item["docflow_summary"]["executors_without_tasks"] == ["Солдатенко Оксана Николаевна"]


def test_without_session_password_falls_back_to_dump(monkeypatch):
    item = _item("Тен Л.Л.")
    monkeypatch.setattr(tasks, "_service_login", lambda: ("", ""))
    monkeypatch.setattr(
        "app.services.docflow_protocols._dump_open_rows",
        lambda refs: {refs[0]: [_row("e1", "Исполнить задачу №1", "Тен Л.Л.", "2026-09-01", step="Исполнить")]},
    )

    note = tasks.attach_docflow_tasks([item], {})

    assert "только открытые задачи" in note
    assert item["docflow_tasks"][0]["open_execute_task_id"] == "e1"


def test_files_go_to_the_sending_of_the_uploader():
    item = _item("Тен Л.Л.")
    rows = [
        _row("e1", "Исполнить задачу №1", "Тен Людмила Лаврентьевна", "2026-09-01T10:00:00", True, "Исполнить",
             chain=5001) | {"end": "2026-09-05T12:00:00"},
        _row("e2", "Исполнить задачу №1", "Тен Людмила Лаврентьевна", "2026-09-10T10:00:00", True, "Исполнить",
             chain=5001, no=3) | {"end": "2026-09-15T11:00:11"},
    ]
    item["files"] = [
        {"ref_key": "f1", "name": "Лист записи", "created": "2026-09-15T10:57:22", "uploaded_by": "Тен Людмила Лаврентьевна"},
        {"ref_key": "f2", "name": "Скан", "created": "2026-09-03T09:00:00", "uploaded_by": "Тен Людмила Лаврентьевна"},
        {"ref_key": "f3", "name": "Поручение", "created": "2026-08-31T09:00:00", "uploaded_by": "Ильченко Екатерина Александровна"},
        {"ref_key": "f4", "name": "Без автора", "created": "2026-09-03T09:00:00", "uploaded_by": ""},
    ]

    tasks.link_tasks(item, rows)

    (task,) = item["docflow_tasks"]
    assert [(file["ref_key"], file["task_id"]) for file in task["files"]] == [("f1", "e2"), ("f2", "e1")]
    assert [file["ref_key"] for file in item["docflow_assignment_files"]] == ["f3", "f4"]


def test_file_prefers_the_task_in_progress_over_a_later_one():
    item = _item("Тен Л.Л.")
    rows = [
        _row("a", "Исполнить задачу №1", "Тен Людмила Лаврентьевна", "2026-09-07T15:59:20", True, "Исполнить",
             chain=5001) | {"end": "2026-09-07T16:05:00"},
        _row("b", "Исполнить задачу №2", "Тен Людмила Лаврентьевна", "2026-09-07T16:23:33", True, "Исполнить",
             chain=5002) | {"end": "2026-09-15T11:00:11"},
    ]
    item["files"] = [{"ref_key": "f", "created": "2026-09-07T16:00:36", "uploaded_by": "Тен Людмила Лаврентьевна"}]

    tasks.link_tasks(item, rows)

    first, second = item["docflow_tasks"]
    assert [file["task_id"] for file in first["files"]] == ["a"]
    assert second["files"] == []
