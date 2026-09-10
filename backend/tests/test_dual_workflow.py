"""Tests for dual-agent regulation workflow."""

from __future__ import annotations

from app.services.regulation_creation.dual_workflow import (
    apply_research_payload,
    completeness_report_markdown,
    enable_dual_workflow,
    merge_field_value,
    process_completeness_score,
    processes_ready_for_agent,
)


def test_enable_dual_workflow_flag() -> None:
    state = enable_dual_workflow({})
    assert state["dualWorkflow"] is True
    assert state["pipeline"]["dualWorkflow"] is True


def test_human_wins_fundamental_conflict() -> None:
    value, source = merge_field_value(
        field="frequency",
        human_value="ежедневно",
        research_value="раз в неделю",
        research_confidence="high",
    )
    assert value == "ежедневно"
    assert source == "human"


def test_research_fills_when_no_human() -> None:
    value, source = merge_field_value(
        field="trigger",
        human_value="",
        research_value="письмо в Outlook",
        research_confidence="high",
    )
    assert value == "письмо в Outlook"
    assert source == "research"


def test_apply_research_payload_merges_facts() -> None:
    state = {
        "processes": [
            {
                "id": "p1",
                "title": "Test",
                "roleStatus": "belongs",
                "knownFacts": {},
            }
        ],
        "pipeline": {"selectedProcessIds": ["p1"]},
    }
    updated = apply_research_payload(
        state,
        {
            "researchFacts": [
                {
                    "processId": "p1",
                    "field": "frequency",
                    "value": "каждый рабочий день",
                    "confidence": "high",
                    "sourceQuote": "ежедневно",
                }
            ]
        },
    )
    process = updated["processes"][0]
    assert process["knownFacts"]["frequency"] == "каждый рабочий день"


def test_processes_ready_for_agent() -> None:
    state = {
        "processes": [
            {
                "id": "p1",
                "title": "Ready process",
                "roleStatus": "belongs",
                "knownFacts": {
                    "workLocation": "1C",
                    "frequency": "daily",
                    "trigger": "mail",
                    "steps": ["Открыть 1C", "Заполнить форму", "Отправить"],
                },
            }
        ],
        "pipeline": {"selectedProcessIds": ["p1"], "dualWorkflow": True},
        "dualWorkflow": True,
    }
    ready = processes_ready_for_agent(state)
    assert len(ready) == 1
    assert ready[0]["processId"] == "p1"


def test_completeness_report_markdown() -> None:
    md = completeness_report_markdown(
        [
            {
                "processId": "p1",
                "title": "Proc",
                "completenessScore": 50,
                "missingInDocument": ["trigger"],
                "foundInDocument": [{"field": "frequency", "value": "daily", "quote": "q"}],
                "notes": "ok",
            }
        ]
    )
    assert "Proc" in md
    assert "50%" in md
    assert "trigger" in md


def test_select_processes_exits_material_review() -> None:
    from app.services.regulation_creation.pipeline import select_processes

    state = enable_dual_workflow(
        {
            "processes": [
                {
                    "id": "p1",
                    "title": "Проверка документации",
                    "roleStatus": "unclear",
                    "knownFacts": {},
                }
            ],
            "pipeline": {
                "stage": "select",
                "materialReviewPending": True,
                "materialReviewDone": False,
            },
        }
    )
    out = select_processes(state, ["p1"])
    assert out["pipeline"]["stage"] == "interview"
    assert out["pipeline"]["interviewPhase"] == "collect"
    assert out["pipeline"]["materialReviewDone"] is True
    assert (out.get("questionQueue") or [])


def test_processes_need_collect_questions() -> None:
    from app.services.regulation_creation.pipeline import processes_need_collect_questions

    state = {
        "processes": [
            {
                "id": "p1",
                "title": "Test",
                "roleStatus": "belongs",
                "knownFacts": {},
            }
        ],
        "pipeline": {"selectedProcessIds": ["p1"]},
    }
    assert processes_need_collect_questions(state) is True
    state["processes"][0]["knownFacts"] = {
        "workLocation": "1C",
        "frequency": "daily",
        "trigger": "mail",
        "steps": ["Шаг 1", "Шаг 2"],
    }
    assert processes_need_collect_questions(state) is False


def test_build_regulation_gap_report() -> None:
    from app.services.regulation_creation.dual_workflow import build_regulation_gap_report

    state = {
        "dualWorkflow": True,
        "processes": [
            {
                "id": "p1",
                "title": "Проверка документации",
                "roleStatus": "belongs",
                "knownFacts": {"workLocation": "1C"},
            }
        ],
        "pipeline": {"selectedProcessIds": ["p1"], "dualWorkflow": True, "blocks": []},
        "researchQueue": [
            {
                "processId": "p1",
                "field": "trigger",
                "hypothesis": "по заявке в Outlook",
                "needsHumanConfirm": True,
            }
        ],
    }
    report = build_regulation_gap_report(state)
    assert report["processes"][0]["collectGaps"]
    assert report["processes"][0]["researchHypotheses"]
    assert report["sectionRisks"]


def test_enqueue_research_hypotheses() -> None:
    from app.services.regulation_creation.question_queue import enqueue_research_hypotheses, queue_depth

    state = {
        "researchQueue": [
            {
                "processId": "p1",
                "field": "trigger",
                "hypothesis": "заявка в Outlook",
                "needsHumanConfirm": True,
            }
        ],
        "pipeline": {"stage": "interview", "interviewPhase": "collect", "selectedProcessIds": ["p1"]},
    }
    out = enqueue_research_hypotheses(state)
    assert queue_depth(out) >= 1
