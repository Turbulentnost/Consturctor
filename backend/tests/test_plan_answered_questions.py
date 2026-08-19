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


def test_delegate_answer_does_not_spawn_followup() -> None:
    plan = WorkflowPlan(
        open_questions=[
            OpenQuestion(id="q1", question="Как в 1С называется тип решения?"),
        ]
    )
    plan.record_answers({"q1": "Точные не знаю, выясни сам как они называются"})
    created = plan.ensure_followups_for_unclear_answers(
        recent_answers={"q1": "Точные не знаю, выясни сам как они называются"},
        prior_questions=plan.answered_questions,
    )
    assert created == []
    assert plan.unanswered() == []


def test_sanitize_drops_impl_question_after_delegate() -> None:
    plan = WorkflowPlan(
        answered_questions=[
            OpenQuestion(
                id="q1",
                question="Какие значения типа решения не блокируют переход?",
                answer="Точные не знаю, выясни сам",
            )
        ],
        open_questions=[
            OpenQuestion(
                id="q2",
                question="Какое значение N дней для правила resheniya из ответа q14?",
                options=["3", "7", "14"],
            ),
            OpenQuestion(
                id="q3",
                question="Как сообщить результат руководителю?",
                options=["Прислать уведомление", "Сформировать отчёт"],
            ),
        ],
    )
    plan.sanitize_open_questions()
    assert [q.id for q in plan.unanswered()] == ["q3"]


def test_sanitize_drops_tool_named_question() -> None:
    plan = WorkflowPlan(
        open_questions=[
            OpenQuestion(
                id="q1",
                question="Какой инструмент вызвать для уведомления?",
                options=["notify_tools", "turboproject", "onec.odata_get"],
            ),
            OpenQuestion(
                id="q2",
                question="Как сообщить о срыве срока?",
                options=["Прислать уведомление", "Сформировать отчёт"],
            ),
        ]
    )
    plan.sanitize_open_questions()
    assert [q.id for q in plan.unanswered()] == ["q2"]
