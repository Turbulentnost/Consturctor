from datetime import date

from app.services.docflow_protocols import is_board_report_task, pick_month_protocol

TASK = (
    "За 2 рабочих дня до проведения Совета директоров по ГК предоставлять "
    "управленческую отчетность за прошедший месяц"
)


def test_board_report_task_matches_director_report() -> None:
    assert is_board_report_task(TASK)
    assert is_board_report_task(TASK.replace("отчетность", "отчётность"))
    assert is_board_report_task("За 2 дня до проведения Совета директоров по ГК предоставить отчёт")
    assert is_board_report_task("1. За 2 рабочих дня до заседания сдать отчётность")
    assert not is_board_report_task("Доклад по повестке совета директоров")
    assert not is_board_report_task(
        "Подготовить презентацию. За 2 рабочих дня до совета сдать отчетность"
    )
    assert not is_board_report_task("")


def test_pick_month_protocol_prefers_current_month() -> None:
    older = {"Date": "2026-09-30T00:00:00", "Number": "226"}
    current = {"Date": "2026-10-02T00:00:00", "Number": "250"}
    picked = pick_month_protocol([older, current], date(2026, 10, 5))
    assert picked is current


def test_pick_month_protocol_falls_back_to_latest() -> None:
    latest = {"Date": "2026-09-30T00:00:00", "Number": "226"}
    older = {"Date": "2026-08-27T00:00:00", "Number": "201"}
    picked = pick_month_protocol([older, latest], date(2026, 10, 5))
    assert picked is latest


def test_docflow_execution_closes_control_task() -> None:
    from app.services.docflow_protocols import TASK_DONE, TASK_OPEN, apply_docflow_execution

    tasks = [
        {"n": 3, "text": TASK, "responsible": "Полякова Наталия", "executed": False, "done": False, "overdue": True, "status": TASK_OPEN},
        {"item": "4", "text": "Подготовить справку по дебиторской задолженности", "executed": False, "status": TASK_OPEN},
    ]
    rows = [
        {"name": "Исполнить задачу №3", "step": "Исполнить", "description": TASK, "executed": True, "begin": "2026-10-01"},
        {"name": "Утвердить задачу №3", "step": "Утвердить", "description": TASK, "executed": True, "begin": "2026-10-02"},
        {
            "name": "Исполнить задачу №4",
            "step": "Исполнить",
            "description": "Подготовить справку по дебиторской задолженности",
            "executed": True,
            "begin": "2026-10-01",
        },
    ]
    apply_docflow_execution(tasks, rows)
    assert tasks[0]["executed"] is True
    assert tasks[0]["done"] is True
    assert tasks[0]["confirmed"] is True
    assert tasks[0].get("completed") is not True
    assert tasks[0]["overdue"] is False
    assert tasks[0]["status"] == TASK_DONE
    assert tasks[1]["executed"] is False


def test_sent_step_does_not_close_siblings_with_the_same_text() -> None:
    from app.services.docflow_protocols import apply_docflow_execution

    tasks = [
        {"n": index, "text": TASK, "responsible": f"Сотрудник {index}", "executed": False, "done": False}
        for index in range(1, 12)
    ]
    rows = [
        {
            "name": f"Исполнить задачу №{index}",
            "step": "Исполнить",
            "description": TASK,
            "executed": True,
            "begin": "2026-10-01",
        }
        for index in range(1, 12)
    ]
    rows.append(
        {"name": "Утвердить задачу №6", "step": "Утвердить", "description": TASK, "executed": True, "begin": "2026-10-02"}
    )
    apply_docflow_execution(tasks, rows)
    done = [task["n"] for task in tasks if task["done"]]
    assert done == [6]
    assert tasks[5]["confirmed"] is True
    assert all(task.get("completed") is not True for task in tasks)


def test_rescheduled_open_docflow_task_stays_open() -> None:
    from app.services.docflow_protocols import apply_docflow_execution

    tasks = [{"n": 3, "text": TASK, "executed": False, "done": False}]
    rows = [
        {"name": "Исполнить задачу №3", "description": TASK, "executed": True, "begin": "2026-09-01"},
        {"name": "Исполнить задачу №3", "description": TASK, "executed": False, "begin": "2026-10-01"},
    ]
    apply_docflow_execution(tasks, rows)
    assert tasks[0]["executed"] is False


def test_shared_board_prefix_does_not_close_another_task() -> None:
    from app.services.docflow_protocols import apply_docflow_execution

    other = "За 2 рабочих дня до проведения Совета директоров по ГК подготовить справку по дебиторке"
    tasks = [{"n": 0, "text": other, "executed": False, "done": False}]
    apply_docflow_execution(
        tasks,
        [{"name": TASK, "description": TASK, "executed": True, "begin": "2026-10-01"}],
    )
    assert tasks[0]["executed"] is False


def test_completed_control_task_is_not_counted_twice() -> None:
    from app.services.docflow_protocols import _merge_listed_tasks

    register = [
        {"n": index, "text": f"{TASK} {index}", "responsible": "Иванов Иван", "executed": index == 3, "done": index == 3}
        for index in range(1, 12)
    ]
    docflow = [
        {
            "n": 3,
            "text": f"{TASK} 3",
            "responsible": "Иванов Иван Иванович",
            "executed": True,
            "done": True,
        }
    ]
    extra = _merge_listed_tasks(register, docflow)
    counted = extra + register
    assert extra == []
    assert len(counted) == 11
    assert sum(1 for item in counted if item["executed"]) == 1
