from app.services.workflows.plan_models import OpenQuestion, WorkflowPlan


def test_record_answers_drops_same_question_with_new_id() -> None:
    plan = WorkflowPlan(
        open_questions=[
            OpenQuestion(
                id="q1",
                question="Где хранятся и откуда читать данные проекта?",
            )
        ]
    )
    plan.record_answers({"q1": "Проекты из 1С, сроки из папки с mpp"})
    plan.open_questions = [
        OpenQuestion(
            id="q1_again",
            question="Где хранятся и откуда читать данные проекта (этапы, SLA)?",
        )
    ]
    plan.drop_resolved_open_questions()
    assert plan.unanswered() == []


def test_answer_first_keeps_remaining_queue() -> None:
    plan = WorkflowPlan(
        open_questions=[
            OpenQuestion(id="q1", question="Откуда читать проекты?"),
            OpenQuestion(id="q2", question="Как часто запускать агента?"),
            OpenQuestion(id="q3", question="Куда класть отчёт?"),
        ]
    )
    plan.record_answers({"q1": "TurboProject"})
    assert [q.id for q in plan.unanswered()] == ["q2", "q3"]
    plan.record_answers({"q2": "каждый день"})
    assert [q.id for q in plan.unanswered()] == ["q3"]


def test_record_answers_keeps_new_topic() -> None:
    plan = WorkflowPlan(
        open_questions=[
            OpenQuestion(id="q1", question="Откуда читать проекты?"),
        ]
    )
    plan.record_answers({"q1": "1С через COM"})
    plan.open_questions = [
        OpenQuestion(id="q2", question="Как часто запускать агента?"),
    ]
    plan.drop_resolved_open_questions()
    assert [q.id for q in plan.unanswered()] == ["q2"]
