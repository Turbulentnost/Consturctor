from __future__ import annotations

from pathlib import Path

from app.api_client import (
    WorkflowFileItem,
    WorkflowFiles,
    WorkflowOpenQuestion,
    WorkflowPlan,
    WorkflowPlanStep,
    WorkflowRecord,
)
from app.sdk_agent.bridge import DEFAULT_SDK_MODEL, CursorSdkBridge, CursorSdkUnavailable
from app.sdk_agent.files import seed_agent_brief, seed_agents_md, seed_workflow_files
from app.sdk_agent.prompt import (
    AGENTS_MD,
    build_demo_sdk_prompt,
    build_design_sdk_prompt,
    build_followup_sdk_prompt,
    build_sdk_prompt,
    inferred_design_answers,
)
from app.sdk_agent.tool_adapter import is_ask_question, sdk_design_tool_specs, sdk_tool_specs
from app.tools.ac.turboproject_tools import _sample_for_agent
from app.ui.pages.workflow_page import (
    demo_run_passed,
    _answered_text_for,
    _draft_from_sdk_answer,
    _event_json,
    _extract_json_object,
    _is_constructor_mcp_wrap,
    _keep_newer_phase,
    _live_tool_name,
    _normalize_live_tool_status,
    _payload_tool_skipped,
    _sdk_design_repair_prompt,
    _sdk_design_transcript,
    _skip_tool_detail,
    apply_sdk_answers_to_draft,
    design_ready_for_demo,
    design_stream_should_finish,
    record_ready_for_sdk_demo,
    merge_design_answers,
    qa_from_design_answers,
    qa_from_sdk_events,
    split_design_questions,
    tools_to_skip,
)
from app.ui.widgets.cursor_feed import resolve_feed_kind


def test_sdk_prompt_contains_plan_and_tool_instruction() -> None:
    record = WorkflowRecord(
        id="wf-1",
        title="Контроль сроков",
        phase="done",
        plan=WorkflowPlan(
            goal="Проверять сроки проектов",
            constraints=["Не менять данные без подтверждения"],
            steps=[
                WorkflowPlanStep(
                    id="s1",
                    title="Собрать данные",
                    action="Прочитать проекты TurboProject",
                    done_when="Есть список проектов",
                )
            ],
        ),
    )
    prompt = build_sdk_prompt(record, "проверь сейчас")
    assert "AGENTS.md" in prompt
    assert "materials/agent.md" in prompt
    assert "проверь сейчас" in prompt
    assert "Проверять сроки проектов" not in prompt
    assert "Прочитать проекты TurboProject" not in prompt
    assert "call the tool" not in prompt


def test_demo_sdk_prompt_requires_playbook_and_tests() -> None:
    record = WorkflowRecord(
        id="wf-1",
        title="Контроль сроков",
        phase="designed",
        plan=WorkflowPlan(goal="Проверять сроки проектов"),
    )
    prompt = build_demo_sdk_prompt(record)
    assert "пробный прогон" in prompt
    assert "TESTS: PASS" in prompt
    assert "playbook" in prompt
    assert "AGENTS.md" in prompt
    assert "get_user_portfolio" not in prompt
    assert "limit 3-5" not in prompt
    followup = build_demo_sdk_prompt(record, resume=True)
    assert followup.startswith("Сделай пробный прогон")
    assert "на русском" in followup
    assert "AGENTS.md" not in followup
    assert "get_user_portfolio" in AGENTS_MD
    assert "result_file" in AGENTS_MD
    assert "на русском" in AGENTS_MD


def test_design_sdk_prompt_is_short_and_points_to_materials() -> None:
    record = WorkflowRecord(id="wf-1", title="Контроль сроков", phase="new")
    prompt = build_design_sdk_prompt(record, "Верни ТОЛЬКО один JSON-объект")
    assert "AGENTS.md" in prompt
    assert "materials/agent.md" in prompt
    assert "askQuestion" in prompt
    assert "JSON-черновик" in prompt
    assert "на русском" in prompt
    assert "QUESTION:" not in prompt
    assert "web_search" not in prompt
    assert "workspace.powershell_run" not in prompt
    assert "Верни ТОЛЬКО один JSON-объект" not in prompt
    assert "customTools" not in prompt
    assert "required_clarifications" in AGENTS_MD
    assert "Триггер не заменяет остальные вопросы" in AGENTS_MD
    assert "Задавай столько вопросов, сколько реальных пробелов" in AGENTS_MD
    assert "не ищи его в MCP" in AGENTS_MD
    assert "Не пиши, что MCP не найден" in AGENTS_MD
    assert "расписания, периода, получателя или критерия успеха" not in prompt


def test_design_sdk_prompt_asks_logic_gaps_before_json() -> None:
    record = WorkflowRecord(id="wf-1", title="Контроль сроков", phase="new")
    prompt = build_design_sdk_prompt(record, "Верни JSON")
    assert "Когда пробелы закрыты" in prompt
    assert "askQuestion" in prompt
    assert "сразу верни финальный JSON" not in prompt
    assert "после закрытых пробелов" in AGENTS_MD
    assert "без JSON" in AGENTS_MD
    assert "второй круг размышлений" in AGENTS_MD


def test_design_sdk_prompt_infers_event_trigger() -> None:
    record = WorkflowRecord(
        id="wf-1",
        title="Контроль сроков",
        phase="new",
        notes="Событийный триггер: событие вместо расписания, запуск при нарушении SLA.",
    )
    prompt = build_design_sdk_prompt(record, "Верни JSON")
    assert "when_to_run: событийный триггер" not in prompt
    assert inferred_design_answers(record) == [
        ("Когда запускать агента?", "событийный триггер из материалов")
    ]


def test_design_sdk_prompt_infers_labeled_business_params() -> None:
    record = WorkflowRecord(
        id="wf-1",
        title="Контроль сроков",
        phase="new",
        notes=(
            "Получатель: руководитель проекта\n"
            "Критерий успеха: отчёт содержит риски или пишет, что рисков нет."
        ),
    )

    answers = inferred_design_answers(record)
    assert ("Кому отправлять результат?", "руководитель проекта") in answers
    assert (
        "По каким критериям считать результат успешным?",
        "отчёт содержит риски или пишет, что рисков нет.",
    ) in answers
    prompt = build_design_sdk_prompt(record, "Верни JSON")
    assert "recipient: руководитель проекта" not in prompt
    assert "success_criteria: отчёт содержит риски" not in prompt


def test_design_sdk_prompt_does_not_infer_schedule_from_process_wording() -> None:
    record = WorkflowRecord(
        id="wf-1",
        title="Контроль сроков",
        phase="new",
        notes="Ежедневный контроль сроков проектов. Руководитель вручную сверяет вехи.",
    )
    assert inferred_design_answers(record) == []
    prompt = build_design_sdk_prompt(record, "Верни JSON")
    assert "не спрашивай расписание" not in prompt


def test_design_stream_finishes_only_on_json_or_done() -> None:
    talking = [
        {
            "type": "assistant",
            "text": "В паспорте достаточно данных. Вопросов не задаю, сразу отдаю итоговый план.",
        }
    ]
    assert design_stream_should_finish(talking) is False
    assert design_stream_should_finish([{"type": "done", "status": "ok"}]) is True
    assert design_stream_should_finish(
        [
            {
                "type": "assistant",
                "text": '{"goal":"Проверять сроки","steps":[{"id":"s1","title":"Проверить"}]}',
            }
        ]
    ) is True
    assert design_stream_should_finish(
        [
            {
                "type": "thinking",
                "text": '{"goal":"Проверять сроки","steps":[{"id":"s1","title":"Проверить"}]}',
            }
        ]
    ) is True


def test_sdk_design_transcript_extracts_json_from_events() -> None:
    events = [
        {"type": "assistant", "text": "Сначала сверяю паспорт."},
        {
            "type": "final",
            "text": (
                "```json\n"
                '{"goal":"Проверять сроки","inputs":["паспорт"],'
                '"required_clarifications":[],"steps":[{"id":"s1","title":"Проверить",'
                '"action":"read","done_when":"данные получены","on_empty":"сообщить",'
                '"on_error":"сообщить"}]}\n'
                "```"
            ),
        },
    ]

    transcript = _sdk_design_transcript("", events)
    draft = _draft_from_sdk_answer(transcript)
    assert draft["goal"] == "Проверять сроки"
    assert draft["steps"][0]["id"] == "s1"
    repair = _sdk_design_repair_prompt("base", "уточнения не нужны")
    assert "Не начинай проектирование заново" in repair
    assert "ТОЛЬКО один валидный JSON" in repair


def test_run_sdk_prompt_does_not_dump_tool_catalog() -> None:
    record = WorkflowRecord(id="wf-1", title="Контроль сроков", phase="done")
    prompt = build_sdk_prompt(record, "проверь сейчас")
    assert "AGENTS.md" in prompt
    assert "на русском" in prompt
    assert "customTools" not in prompt
    assert "web_search" not in prompt
    assert "- turboproject." not in prompt
    assert build_followup_sdk_prompt("ответ: ежедневно") == "ответ: ежедневно"


def test_sdk_event_json_parses_structured_payload() -> None:
    payload = _event_json('{"type":"question","question":"Когда запускать?","options":["ежедневно"]}')
    assert payload["type"] == "question"
    assert payload["question"] == "Когда запускать?"
    assert payload["options"] == ["ежедневно"]


def test_sdk_answers_close_matching_clarifications() -> None:
    draft = apply_sdk_answers_to_draft(
        {
            "required_clarifications": [
                {
                    "question": "Когда запускать агент?",
                    "options": ["ежедневно", "вручную"],
                },
                {
                    "question": "Кто получает отчёт?",
                    "options": ["руководитель", "куратор"],
                },
            ],
            "recipient": "",
        },
        [
            ("Когда запускать агент?", "ежедневно утром"),
            ("Кто получает отчёт?", "руководитель проекта"),
        ],
    )
    assert draft["required_clarifications"] == []
    assert "ежедневно утром" in draft["answers"]
    assert draft["when_to_run"] == "ежедневно утром"
    assert draft["recipient"] == "руководитель проекта"

    rewritten = apply_sdk_answers_to_draft(
        {
            "required_clarifications": [
                {
                    "question": "Как часто стартовать этого агента?",
                    "options": ["каждый час", "вручную"],
                }
            ]
        },
        [("Когда запускать агент?", "только вручную из чата")],
    )
    assert rewritten["required_clarifications"] == []


def test_split_design_questions_breaks_numbered_bundle() -> None:
    parts = split_design_questions(
        "\n".join(
            [
                "Нужны ответы:",
                "1. Когда запускать агент?",
                "- ежедневно утром",
                "- только вручную",
                "2. Какой период и контур проектов проверять за один прогон?",
                "- все активные",
                "- вехи на 7 дней",
                "3. Кто получает отчёт?",
                "- руководитель",
            ]
        )
    )
    assert [item[0] for item in parts] == [
        "Когда запускать агент?",
        "Какой период и контур проектов проверять за один прогон?",
        "Кто получает отчёт?",
    ]
    assert parts[0][1] == ["ежедневно утром", "только вручную"]


def test_rephrased_question_reuses_previous_answer() -> None:
    qa = [("Когда запускать агент?", "только вручную из чата")]
    assert _answered_text_for(qa, "Как часто стартовать этого агента?") == "только вручную из чата"
    assert _answered_text_for(qa, "Какая периодичность работы агента?") == "только вручную из чата"

    success = [("По каким критериям считать результат успешным?", "отчёт содержит риски")]
    assert _answered_text_for(success, "Какие правила успеха применить?") == "отчёт содержит риски"


def test_qa_from_sdk_events_pairs_question_and_answer() -> None:
    pairs = qa_from_sdk_events(
        [
            {
                "type": "question",
                "requestId": "r1",
                "question": "Когда запускать агент?",
            },
            {
                "type": "tool_result",
                "requestId": "r1",
                "tool": "askQuestion",
                "result": {"answer": "вручную"},
            },
        ]
    )
    assert pairs == [("Когда запускать агент?", "вручную")]


def test_design_answers_merge_and_parse() -> None:
    rows = merge_design_answers(
        [{"question": "Когда запускать агент?", "answer": "вручную"}],
        [("Как часто стартовать этого агента?", "ежедневно утром")],
    )
    assert rows == [{"question": "Как часто стартовать этого агента?", "answer": "ежедневно утром"}]
    assert qa_from_design_answers(rows) == [("Как часто стартовать этого агента?", "ежедневно утром")]


def test_runner_does_not_emit_duplicate_askquestion_event() -> None:
    runner = Path(__file__).resolve().parents[1] / "sdk-agent" / "src" / "runner.ts"
    text = runner.read_text(encoding="utf-8")
    tool_call_block = text.split('} else if (event.type === "tool_call") {', 1)[1].split(
        '} else if (event.type === "system") {',
        1,
    )[0]
    assert 'type: "question"' not in tool_call_block
    assert "SDK_TOOLS" not in text
    assert "tools: [" not in text
    assert "Agent.resume" in text
    assert "force: true" in text
    assert "settleRun" in text
    assert "playbookDraftReady" in text
    assert "testsPassReady" in text
    assert "thought +=" in text
    assert "finishIfReady" in text
    assert "TESTS: PASS" in text
    assert "result: event.result" in text
    assert 'provider === "custom-user-tools"' in text
    assert "skipped" in text
    assert "isError: true" in text


def test_question_feed_kind_is_separate_block() -> None:
    assert resolve_feed_kind(title="Уточнение") == "question"
    assert resolve_feed_kind(kind="question") == "question"


def test_sdk_design_tool_specs_include_constructor_tools() -> None:
    tools = sdk_design_tool_specs()
    names = {str(item.get("name") or "") for item in tools}
    assert "askQuestion" in names
    assert "workspace.powershell_run" in names


def test_sdk_tool_specs_include_desktop_schema() -> None:
    tools = sdk_tool_specs()
    names = {str(item.get("name") or "") for item in tools}
    assert "askQuestion" in names
    assert "web_search" in names
    ask = next(item for item in tools if item.get("name") == "askQuestion")
    assert "question" in (ask.get("inputSchema") or {}).get("properties", {})
    assert "расписание, период" not in str(ask.get("description") or "")
    assert "пробел" in str(ask.get("description") or "")
    web = next(item for item in tools if item.get("name") == "web_search")
    assert isinstance(web.get("inputSchema"), dict)


def test_record_ready_for_sdk_demo_clears_server_clarify_gate() -> None:
    record = WorkflowRecord(
        id="wf-1",
        title="Агент",
        phase="clarify",
        plan=WorkflowPlan(
            open_questions=[
                WorkflowOpenQuestion(
                    id="draft-q1",
                    question="Когда запускать этого агента?",
                    options=["вручную", "ежедневно"],
                )
            ]
        ),
        local_run={
            "validation": {
                "status": "blocked_before_demo",
                "can_run_demo": False,
            }
        },
    )
    ready = record_ready_for_sdk_demo(record)
    assert ready.phase == "designed"
    assert ready.plan is not None
    unanswered = ready.plan.unanswered()
    assert unanswered
    assert "Когда запускать" in unanswered[0].question
    assert ready.local_run["can_run_demo"] is False
    assert design_ready_for_demo(ready) is True

    known = WorkflowRecord(
        id="wf-1",
        title="Агент",
        phase="clarify",
        notes="Когда запускать: ежедневно утром",
        local_run={"playbook_draft": {"when_to_run": "ежедневно утром"}},
    )
    ready_known = record_ready_for_sdk_demo(known)
    assert ready_known.local_run["can_run_demo"] is True
    assert (ready_known.plan.unanswered() if ready_known.plan else []) == []


def test_sdk_design_ready_for_demo_even_if_validation_blocked() -> None:
    record = WorkflowRecord(
        id="wf-1",
        title="Агент",
        phase="designed",
        local_run={
            "design_runtime": "cursor-sdk",
            "validation": {
                "status": "blocked_before_demo",
                "can_run_demo": False,
                "demo_started": False,
            },
        },
    )
    assert design_ready_for_demo(record) is True


def test_sdk_demo_does_not_autorun_after_tests_pass() -> None:
    record = WorkflowRecord(
        id="wf-1",
        title="A",
        phase="designed",
        last_result="The control circuit worked.\nTESTS: PASS",
        local_run={
            "design_runtime": "cursor-sdk",
            "validation": {"demo_started": True, "can_run_demo": True},
        },
    )
    assert design_ready_for_demo(record) is True
    assert demo_run_passed(record) is True


def test_extract_json_object_uses_last_brace() -> None:
    data = _extract_json_object('текст {"goal":"Проверить","steps":[{"id":"s1"}]} хвост')
    assert data is not None
    assert data["goal"] == "Проверить"
    assert data["steps"][0]["id"] == "s1"


def test_keep_newer_phase_does_not_fall_back_to_document() -> None:
    designed = WorkflowRecord(id="wf-1", title="Агент", phase="designed")
    saved = WorkflowRecord(id="wf-1", title="Агент", phase="document")
    kept = _keep_newer_phase(designed, saved)
    assert kept.phase == "designed"


def test_is_ask_question_name() -> None:
    assert is_ask_question("askQuestion")
    assert is_ask_question("ask_question")
    assert not is_ask_question("web_search")


def test_bridge_reports_missing_api_key(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    runner = tmp_path / "runner.ts"
    runner.write_text("", encoding="utf-8")
    bridge = CursorSdkBridge(runner=runner)
    try:
        bridge.check_ready()
    except CursorSdkUnavailable as exc:
        assert "CURSOR_API_KEY" in str(exc)
    else:
        raise AssertionError("expected CursorSdkUnavailable")


def test_node_version_parser() -> None:
    assert CursorSdkBridge._node_version("22.13.0") == (22, 13)
    assert CursorSdkBridge._node_version("bad") == (0, 0)


def test_default_sdk_model_is_grok_46() -> None:
    assert DEFAULT_SDK_MODEL == "grok-4.6"


def test_turboproject_empty_call_is_sampled_for_agent() -> None:
    raw = {
        "summary": "TurboProject: 20 проект(ов) с 1С из 251",
        "total_projects": 251,
        "projects": [
            {
                "project_name": f"P{index}",
                "overdue_tasks": [{"id": n} for n in range(30)],
                "overdue_milestones": [{"id": n} for n in range(12)],
                "resources": [f"R{n}" for n in range(40)],
            }
            for index in range(20)
        ],
    }
    sampled = _sample_for_agent(raw, {})
    assert sampled["sample"] is True
    assert len(sampled["projects"]) == 5
    assert len(sampled["projects"][0]["overdue_tasks"]) == 8
    assert "не весь портфель" in sampled["summary"]


def test_bridge_externalizes_large_tool_result(tmp_path: Path) -> None:
    bridge = CursorSdkBridge(runner=tmp_path / "runner.ts")
    result = {
        "summary": "big payload",
        "total_projects": 251,
        "projects": [{"name": f"P{index}", "blob": "x" * 2000} for index in range(40)],
    }
    compact = bridge._externalize_large_result(
        tool="turboproject",
        request_id="req-1",
        result=result,
        cwd=str(tmp_path),
    )
    assert compact["externalized"] is True
    assert compact["summary"]["projects_count"] == 40
    assert compact["summary"]["total_projects"] == 251
    assert compact["next_step"]
    assert "sample" not in compact
    assert "preview" not in compact
    path = tmp_path / compact["result_file"]
    assert path.is_file()
    assert "big payload" in path.read_text(encoding="utf-8")


def test_bridge_keeps_small_list_result_inline(tmp_path: Path) -> None:
    bridge = CursorSdkBridge(runner=tmp_path / "runner.ts")
    result = {
        "projects": [{"id": "1", "name": "A"}, {"id": "2", "name": "B"}],
        "total": 2,
    }
    compact = bridge._externalize_large_result(
        tool="turboproject.get_user_portfolio",
        request_id="req-2",
        result=result,
        cwd=str(tmp_path),
    )
    assert compact == result
    assert "result_file" not in compact
    assert "next_step" not in compact


def test_bridge_externalizes_long_list_even_when_items_tiny(tmp_path: Path) -> None:
    bridge = CursorSdkBridge(runner=tmp_path / "runner.ts")
    result = {"entities": [{"name": f"E{index}"} for index in range(60)]}
    compact = bridge._externalize_large_result(
        tool="onec.odata_catalog",
        request_id="req-4",
        result=result,
        cwd=str(tmp_path),
    )
    assert compact["externalized"] is True
    assert compact["result_file"]
    assert compact["next_step"]
    assert compact["summary"]["entities_count"] == 60
    assert "sample" not in compact
    assert (tmp_path / compact["result_file"]).is_file()


def test_bridge_keeps_tiny_scalar_result_inline(tmp_path: Path) -> None:
    bridge = CursorSdkBridge(runner=tmp_path / "runner.ts")
    result = {"ok": True, "employee": "Ivanov I.I."}
    compact = bridge._externalize_large_result(
        tool="users.current",
        request_id="req-3",
        result=result,
        cwd=str(tmp_path),
    )
    assert compact == result
    assert "result_file" not in compact
    assert "next_step" not in compact


def test_cursor_completed_tool_status_is_ok() -> None:
    assert _normalize_live_tool_status("completed") == "ok"
    assert _normalize_live_tool_status("running") == "running"
    assert _normalize_live_tool_status("error") == "error"
    assert _normalize_live_tool_status("skipped") == "skipped"
    assert _normalize_live_tool_status("", ok=True) == "ok"
    assert _normalize_live_tool_status("", ok=False) == "error"


def test_payload_tool_skipped_from_result() -> None:
    assert _payload_tool_skipped({"result": {"skipped": True}}) is True
    assert _payload_tool_skipped({"skipped": True, "ok": True}) is True
    assert _payload_tool_skipped({"status": "skipped"}) is True
    assert _payload_tool_skipped({"ok": True, "result": {"summary": "ok"}}) is False
    assert "продолжает" in _skip_tool_detail()


def test_bridge_skip_tool_unblocks_invoke(monkeypatch, tmp_path: Path) -> None:
    import json
    import threading
    import time

    started = threading.Event()

    def fake_invoke(tool: str, args: dict) -> dict:
        started.set()
        time.sleep(4)
        return {"late": True}

    monkeypatch.setattr("app.sdk_agent.bridge.invoke_sdk_tool", fake_invoke)
    sent: list[dict] = []

    class _Stdin:
        def write(self, raw: str) -> None:
            sent.append(json.loads(raw))

        def flush(self) -> None:
            return None

    class _Proc:
        stdin = _Stdin()

    bridge = CursorSdkBridge(runner=tmp_path / "runner.ts")

    def work() -> None:
        bridge._handle_tool_request(
            _Proc(),  # type: ignore[arg-type]
            {
                "requestId": "req-skip",
                "tool": "outlook.read_calendar",
                "arguments": {"date_from": "2026-08-01"},
            },
            workflow_id="wf-1",
            cwd=str(tmp_path),
        )

    thread = threading.Thread(target=work)
    thread.start()
    assert started.wait(2)
    assert bridge.skip_tool("req-skip") is True
    thread.join(timeout=2)
    assert thread.is_alive() is False
    assert sent
    assert sent[0]["ok"] is True
    assert sent[0]["result"]["skipped"] is True
    assert sent[0]["requestId"] == "req-skip"


def test_tools_to_skip_uses_running_card_when_request_id_is_stale() -> None:
    live = [
        {"name": "turboproject.get", "status": "ok", "request_id": "old"},
        {"name": "turboproject.get", "status": "running", "request_id": "new"},
    ]
    targets = tools_to_skip(live, "old")
    assert len(targets) == 1
    assert targets[0]["request_id"] == "new"


def test_tools_to_skip_without_request_id() -> None:
    live = [{"name": "turboproject.get", "status": "running", "request_id": ""}]
    targets = tools_to_skip(live, "")
    assert targets == live


def test_bridge_skip_marks_all_active_when_id_unknown(tmp_path: Path) -> None:
    bridge = CursorSdkBridge(runner=tmp_path / "runner.ts")
    bridge._mark_active("req-live", "turboproject.get")
    assert bridge.skip_tool("stale") is True
    assert bridge._is_skipped("req-live") is True
    assert bridge._is_skipped("stale") is True


def test_bridge_skip_before_invoke_starts(tmp_path: Path) -> None:
    bridge = CursorSdkBridge(runner=tmp_path / "runner.ts")
    assert bridge.skip_tool("pending-1") is True
    assert bridge._is_skipped("pending-1") is True
    result = CursorSdkBridge.skipped_tool_result("outlook.read_calendar")
    assert result["skipped"] is True
    assert result["tool"] == "outlook.read_calendar"


def test_seed_workflow_files_materializes_manifest(tmp_path: Path) -> None:
    class _Api:
        def list_workflow_files(self, workflow_id: str) -> WorkflowFiles:
            assert workflow_id == "wf-1"
            return WorkflowFiles(
                user_files=[
                    WorkflowFileItem(
                        id="file-1",
                        filename="reglament.txt",
                        size=9,
                        sha256="abc",
                        summary="Регламент",
                    )
                ]
            )

        def download_workflow_file_to(self, workflow_id: str, file_id: str, destination: Path) -> str:
            assert workflow_id == "wf-1"
            assert file_id == "file-1"
            destination.write_bytes(b"original")
            return str(destination)

        def workflow_file_text(self, workflow_id: str, file_id: str) -> dict[str, str]:
            assert workflow_id == "wf-1"
            assert file_id == "file-1"
            return {"text": "Полный текст регламента", "summary": "Регламент"}

    hint = seed_workflow_files(_Api(), "wf-1", str(tmp_path))  # type: ignore[arg-type]
    manifest = tmp_path / "materials" / "manifest.json"
    assert manifest.is_file()
    assert (tmp_path / "materials" / "001_reglament.txt").read_bytes() == b"original"
    assert (tmp_path / "materials" / "001_reglament.txt.txt").read_text(encoding="utf-8")
    assert "materials/manifest.json" in hint
    assert "askQuestion" in hint
    assert "БАЗА ДОКУМЕНТОВ" not in hint


def test_seed_agent_brief_writes_plan_and_design_text(tmp_path: Path) -> None:
    record = WorkflowRecord(
        id="wf-1",
        title="Контроль сроков",
        phase="designed",
        notes="Получатель: руководитель",
        document_text="Регламент контроля сроков",
        plan=WorkflowPlan(
            goal="Проверять сроки проектов",
            steps=[
                WorkflowPlanStep(
                    id="s1",
                    title="Собрать данные",
                    action="Прочитать проекты TurboProject",
                    done_when="Есть список проектов",
                )
            ],
        ),
    )
    path = seed_agent_brief(str(tmp_path), record, extra="Верни ТОЛЬКО один JSON-объект")
    text = (tmp_path / path).read_text(encoding="utf-8")
    assert path == "materials/agent.md"
    assert "Язык: русский" in text
    assert "Проверять сроки проектов" in text
    assert "Прочитать проекты TurboProject" in text
    assert "Верни ТОЛЬКО один JSON-объект" in text
    assert "recipient: руководитель" in text
    agents = seed_agents_md(str(tmp_path))
    assert agents == "AGENTS.md"
    assert "customTools" in (tmp_path / agents).read_text(encoding="utf-8")


def test_mcp_tool_name_unwraps_constructor_tool() -> None:
    wrap = {
        "tool": "mcp",
        "arguments": {
            "providerIdentifier": "custom-user-tools",
            "toolName": "workspace.powershell_run",
            "args": {"command": "Get-ChildItem"},
        },
    }
    assert _live_tool_name(wrap) == "workspace.powershell_run"
    assert _is_constructor_mcp_wrap(wrap) is True
    assert _is_constructor_mcp_wrap({"tool": "read"}) is False
    assert _live_tool_name({"tool": "read"}) == "read"


def test_confirm_write_tool_read_is_allowed() -> None:
    allowed, rejected = CursorSdkBridge._confirm_write_tool("onec.odata_get", {})
    assert allowed is True
    assert rejected is None


def test_confirm_write_tool_is_autonomous_without_ui() -> None:
    # No QApplication instance in this test process -> headless: proceed.
    allowed, rejected = CursorSdkBridge._confirm_write_tool("onec.odata_post", {"entity": "X"})
    assert allowed is True
    assert rejected is None


def test_server_catalog_exposes_both_worlds() -> None:
    from app.tools.server_tools import SERVER_TOOL_NAMES

    names = {str(t.get("name")) for t in sdk_tool_specs()}
    # Server-executed tools are offered to the local SDK agent.
    assert {"onec.odata_get", "imap.list_unread", "users.current"} <= names
    # Local COM tools stay in the catalog too.
    assert "onec.search_documents" in names
    # Local COM 1C must not be routed to the server.
    assert "onec.search_documents" not in SERVER_TOOL_NAMES
