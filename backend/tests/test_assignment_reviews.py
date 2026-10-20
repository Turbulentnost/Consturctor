from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.assignment_review import AssignmentReview, AssignmentReviewTask, AssignmentReviewVerdict
from app.services.assignment_reviews import get_review, list_reviewed_keys, save_reviews


def _db():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(
        bind=engine,
        tables=[AssignmentReview.__table__, AssignmentReviewTask.__table__, AssignmentReviewVerdict.__table__],
    )
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def _item(number: str, *, conclusion="Можно закрыть", verdict="Можно закрывать", comment="Акт подписан") -> dict:
    return {
        "number": number,
        "target_id": "33235ba3-ad1d-11f1-987d-6cb31113810e",
        "conclusion": conclusion,
        "done": 1,
        "total": 1,
        "reason": "Задача принята автором.",
        "tasks": [
            {
                "n": 1,
                "performer": "Гапонова К.С.",
                "task": "Проверить данные с 1С",
                "conclusion": verdict,
                "comment": comment,
                "evidence": "принято в ДО",
                "task_state": "принято проверяющим",
                "advice": "Уже принято",
            }
        ],
    }


def _live(_ref: str, number: str) -> dict:
    return {
        "number": number,
        "ref_key": "33235ba3-ad1d-11f1-987d-6cb31113810e",
        "status": "Принято",
        "open": False,
        "date": "2026-09-10T16:40:38",
        "topic": "Дашборд",
        "basis": "Протокол",
        "customer": "Амураль И.Б.",
        "organization": "ИТЦ",
        "reporter": "Ильченко Е.А.",
        "secretary": "",
        "due": "2026-10-15",
        "lines": [{"line": 1, "text": "Проверить данные", "executor": "Гапонова К.С."}],
        "files": [{"ref_key": "f1", "name": "Акт", "extension": "pdf", "created": "2026-09-11"}],
        "docflow_tasks": [
            {
                "chain": "441656",
                "performer": "Гапонова Ксения Святославовна",
                "text": "Проверить данные и соответствие цифр с 1С",
                "label": "принято проверяющим",
                "begin": "2026-09-10T16:43:01",
                "due": "2026-09-11",
                "returns": 0,
                "executor_report": "вложено",
                "open_execute_task_id": "",
                "open_check_task_id": "",
                "history": [
                    {
                        "task_id": "t-exec",
                        "kind": "execute",
                        "report": "вложено",
                        "performer": "Гапонова Ксения Святославовна",
                        "begin": "2026-09-10T16:43:01",
                    }
                ],
                "files": [{"id": "f1", "name": "Акт", "extension": "pdf"}],
            }
        ],
    }


def test_save_snapshot_and_verdict():
    db = _db()
    result = save_reviews(db, [_item("АСТ00-00096")], user_id="u1", live_loader=_live)

    assert result["saved"] == ["АСТ00-00096"]
    view = get_review(db, number="АСТ00-00096")
    assert view["open"] is False
    assert view["topic"] == "Дашборд"
    assert view["files"][0]["name"] == "Акт"
    task = view["tasks"][0]
    assert task["conclusion"] == "Можно закрывать"
    assert task["comment"] == "Акт подписан"
    assert "соответствие" in task["title"]
    assert task["result"] == "вложено"


def test_closed_review_is_not_overwritten():
    db = _db()
    save_reviews(db, [_item("АСТ00-00096")], live_loader=_live)
    again = save_reviews(
        db,
        [_item("АСТ00-00096", verdict="Вернуть на доработку", comment="мало")],
        live_loader=_live,
    )

    assert again["skipped"] == ["АСТ00-00096"]
    view = get_review(db, ref_key="33235ba3-ad1d-11f1-987d-6cb31113810e")
    assert view["tasks"][0]["conclusion"] == "Можно закрывать"


def test_reviewed_keys_list():
    db = _db()
    save_reviews(db, [_item("АСТ00-00096")], live_loader=_live)
    keys = list_reviewed_keys(db)

    assert "АСТ00-00096" in keys["numbers"]
    assert "АСТ00-00096" in keys["closed_numbers"]
