from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from app.api_client import WorkflowFileItem, WorkflowFiles

ROOT = Path(__file__).resolve().parents[2]
PYBRIDGE = ROOT / "desktop-electron" / "pybridge"
if str(PYBRIDGE) not in sys.path:
    sys.path.insert(0, str(PYBRIDGE))

from agent_sidecar import (  # noqa: E402
    _persist_run_outputs,
    _stamp_run_event,
    needs_confirmation,
    OUTLOOK_MEETING_RULE,
    OUTLOOK_SERIES_MARKER,
    RUN_INPUTS_NO,
    RUN_INPUTS_QUESTION,
    RUN_INPUTS_RUN_HINT,
    RUN_INPUTS_YES,
    WHEN_TO_RUN_QUESTION,
    _annotate_readiness_question,
    _build_readiness_prompt,
    _format_readiness_answers_md,
    _label_readiness_question,
    _readiness_qa_from_draft,
    _readiness_qa_items,
    _copy_attachments,
    _file_request_from_payload,
    _is_meeting_text,
    _merge_outlook_rule_into_playbook,
    _merge_run_input_gate,
    _merge_run_inputs,
    _merge_when_to_run,
    _persist_knowledge_files,
    _persist_run_attachment,
    _run_inputs_from_answer,
    _run_inputs_from_local,
    _run_inputs_user_answered,
    _when_to_run_known,
    _when_to_run_user_answered,
    _with_sidecar_prompt,
)


class _Api:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.uploaded: list[tuple[str, list[str]]] = []
        self.uploaded_origins: list[str] = []
        self.run_attachments: list[tuple[str, str, list[str]]] = []
        self.run_outputs: list[tuple[str, str, list[str]]] = []

    def upload_workflow_files(
        self, workflow_id: str, paths: list[str], *, origin: str = ""
    ) -> None:
        self.uploaded.append((workflow_id, [str(item) for item in paths]))
        self.uploaded_origins.append(origin)

    def register_run_attachments(
        self, workflow_id: str, run_id: str, paths: list[str]
    ) -> None:
        self.run_attachments.append(
            (workflow_id, run_id, [str(item) for item in paths])
        )

    def register_workflow_run_files(
        self, workflow_id: str, run_id: str, paths: list[str]
    ) -> None:
        self.run_outputs.append((workflow_id, run_id, [str(item) for item in paths]))

    def list_workflow_files(self, workflow_id: str) -> WorkflowFiles:
        assert workflow_id == "wf-meet"
        assert self.uploaded
        name = Path(self.uploaded[0][1][0]).name
        return WorkflowFiles(
            user_files=[
                WorkflowFileItem(
                    id="file-xlsx",
                    filename=name,
                    size=4,
                    sha256="abc",
                    summary="Grafik",
                )
            ]
        )

    def download_workflow_file_to(self, workflow_id: str, file_id: str, destination: Path) -> str:
        assert workflow_id == "wf-meet"
        assert file_id == "file-xlsx"
        destination.write_bytes(b"XLSX")
        return str(destination)

    def workflow_file_text(self, workflow_id: str, file_id: str) -> dict[str, str]:
        return {"text": "sheet", "summary": "Grafik"}


def test_file_request_parses_needs_file() -> None:
    needs, accept = _file_request_from_payload(
        {"arguments": {"question": "Prilozhite grafik", "needsFile": True, "accept": ["xlsx"]}}
    )
    assert needs is True
    assert accept == ["xlsx"]


def test_file_request_accepts_pdf_and_images() -> None:
    needs, accept = _file_request_from_payload(
        {"arguments": {"needsFile": True, "accept": ["pdf", "png", "docx"]}}
    )
    assert needs is True
    assert accept == ["pdf", "png", "docx"]


def test_file_request_empty_accept_means_any() -> None:
    needs, accept = _file_request_from_payload({"arguments": {"needsFile": True}})
    assert needs is True
    assert accept == []


def test_copy_attachments_writes_text_sidecar(tmp_path: Path) -> None:
    source = tmp_path / "kit.txt"
    source.write_text("povestka", encoding="utf-8")
    cwd = tmp_path / "run"
    cwd.mkdir()
    paths = _copy_attachments(str(cwd), [str(source)])
    assert "materials/attachments/001_kit.txt" in paths
    sidecar = cwd / "materials" / "attachments" / "001_kit.txt.txt"
    assert sidecar.is_file()
    assert sidecar.read_text(encoding="utf-8") == "povestka"


def test_persist_xlsx_uploads_and_seeds_manifest(tmp_path: Path) -> None:
    source = tmp_path / "schedule.xlsx"
    source.write_bytes(b"XLSX")
    cwd = tmp_path / "run"
    cwd.mkdir()
    api = _Api(tmp_path)

    copied = _persist_knowledge_files(api, "wf-meet", str(cwd), [str(source)], keep=False)

    assert copied
    assert copied[0].startswith("materials/attachments/")
    assert api.uploaded == []

    copied_keep = _persist_knowledge_files(api, "wf-meet", str(cwd), [str(source)], keep=True)
    assert copied_keep
    assert api.uploaded == [("wf-meet", [str(source)])]
    manifest = cwd / "materials" / "manifest.json"
    assert manifest.is_file()
    assert "schedule.xlsx" in manifest.read_text(encoding="utf-8")
    assert (cwd / "materials" / "001_schedule.xlsx").read_bytes() == b"XLSX"


def test_readiness_answers_md_lists_saved_qa() -> None:
    text = _format_readiness_answers_md(
        [
            {
                "question": "По агенту «Календарь ПСД»: когда запускать?",
                "answer": "Каждый день к 08:00",
                "blockTitle": "ИИ-агент: Рабочий день и календарь ПСД",
            }
        ]
    )
    assert "Календарь ПСД" in text
    assert "Каждый день к 08:00" in text
    assert "уже даны" in text


def test_readiness_qa_from_draft_reads_sdk_readiness() -> None:
    draft = SimpleNamespace(
        sdk_readiness={
            "qa": [
                {
                    "question": "Когда запускать?",
                    "answer": "По календарю",
                    "blockTitle": "Календарь",
                }
            ]
        }
    )
    items = _readiness_qa_from_draft(draft)
    assert items[0]["answer"] == "По календарю"
    assert _readiness_qa_items({}) == []


def test_readiness_prompt_mentions_previous_answers() -> None:
    fresh = _build_readiness_prompt(has_answers=False)
    resumed = _build_readiness_prompt(has_answers=True)
    assert "askQuestion" in fresh
    assert "answers.md уже есть ответы" in resumed


def test_sidecar_prompt_includes_outlook_series_rule() -> None:
    text = _with_sidecar_prompt("Sdelai demo")
    assert "keepKnowledgeFile" in text
    assert "outlook.create_event" in text
    assert "Sdelai demo" in text


def test_meeting_text_detects_outlook_task() -> None:
    assert _is_meeting_text("Nuzhno zaplanirovat soveschaniya v Outlook")
    assert not _is_meeting_text("Sochini otchet po KPI")


def test_merge_outlook_rule_appends_once() -> None:
    first = _merge_outlook_rule_into_playbook(
        {"playbook": {"instructions": "Chitai sluzhebki 1C"}}
    )
    assert first is not None
    instructions = str(first["playbook"]["instructions"])
    assert "Chitai sluzhebki 1C" in instructions
    assert OUTLOOK_SERIES_MARKER in instructions
    assert OUTLOOK_MEETING_RULE in instructions

    second = _merge_outlook_rule_into_playbook(first)
    assert second is None


def test_design_prompt_does_not_inject_hardcoded_questions() -> None:
    text = _with_sidecar_prompt("Sproektiruy", mode="design")
    assert "Always ask via askQuestion: when to run THIS agent" not in text
    assert "you MUST" not in text
    run_text = _with_sidecar_prompt("Sdelai demo")
    assert RUN_INPUTS_RUN_HINT in run_text


def test_readiness_prompt_skips_design_run_hints() -> None:
    text = _with_sidecar_prompt("Utochni reglament", mode="readiness")
    assert text == "Utochni reglament"
    assert RUN_INPUTS_RUN_HINT not in text


def test_label_readiness_question_prefixes_unnamed_agent() -> None:
    labeled, title = _label_readiness_question(
        "Когда запускать этого агента?",
        ["Контроль календаря ПСД", "Сбор замечаний"],
    )
    assert title == "Контроль календаря ПСД"
    assert "Контроль календаря ПСД" in labeled
    assert labeled.startswith("По агенту")


def test_label_readiness_question_keeps_named_block() -> None:
    source = "По агенту «Сбор замечаний»: какой статус считать закрытым?"
    labeled, title = _label_readiness_question(
        source,
        ["Контроль календаря ПСД", "Сбор замечаний"],
    )
    assert title == "Сбор замечаний"
    assert labeled == source


def test_annotate_readiness_question_sets_block_context() -> None:
    payload = _annotate_readiness_question(
        {"question": "Когда запускать этого агента?", "options": ["раз в день"]},
        ["Контроль календаря ПСД"],
    )
    assert payload["blockTitle"] == "Контроль календаря ПСД"
    assert "1 из 1" in payload["context"]
    assert "Контроль календаря ПСД" in payload["question"]


def test_when_to_run_not_inferred_from_meeting_cadence() -> None:
    record = SimpleNamespace(
        title="Planer soveschaniy",
        notes="Nuzhno zaplanirovat ezhenedelnye soveschaniya v Outlook",
        document_text="",
        local_run={},
    )
    assert _when_to_run_known(record) is False


def test_when_to_run_known_from_process_cadence() -> None:
    record = SimpleNamespace(
        title="Agent",
        notes="Условия: каждое рабочее утро к 07:50; днём раз в час с 08:00 до 17:00",
        document_text="",
        local_run={},
    )
    assert _when_to_run_known(record) is True
    assert _when_to_run_user_answered(record) is True


def test_when_to_run_known_from_playbook() -> None:
    record = SimpleNamespace(
        title="Agent",
        notes="",
        document_text="",
        local_run={"playbook_draft": {"when_to_run": "raz v den"}},
    )
    assert _when_to_run_known(record) is True


def test_merge_when_to_run_writes_draft() -> None:
    merged = _merge_when_to_run({}, "raz v den")
    assert merged is not None
    assert merged["playbook_draft"]["when_to_run"] == "raz v den"
    assert merged["design_answers"][0]["question"] == WHEN_TO_RUN_QUESTION
    assert _merge_when_to_run(merged, "raz v den") is None


def test_user_answered_ignores_llm_invented_draft() -> None:
    # An LLM-written playbook_draft.when_to_run must NOT suppress the question:
    # the user was never actually asked.
    record = SimpleNamespace(
        title="Agent",
        notes="",
        document_text="",
        local_run={"playbook_draft": {"when_to_run": "raz v den"}},
    )
    assert _when_to_run_known(record) is True
    assert _when_to_run_user_answered(record) is False


def test_user_answered_true_from_design_answers() -> None:
    record = SimpleNamespace(
        title="Agent",
        notes="",
        document_text="",
        local_run={"design_answers": [{"question": WHEN_TO_RUN_QUESTION, "answer": "raz v den"}]},
    )
    assert _when_to_run_user_answered(record) is True


def test_user_answered_true_from_materials_label() -> None:
    record = SimpleNamespace(
        title="Agent",
        notes="Триггер агента: ежедневно утром",
        document_text="",
        local_run={},
    )
    assert _when_to_run_user_answered(record) is True


def test_persist_run_attachment_is_temporary(tmp_path: Path) -> None:
    # A per-run attachment must go to the temporary run_attachment bucket, not
    # to the permanent knowledge base.
    source = tmp_path / "meetings-2026.xlsx"
    source.write_bytes(b"XLSX")
    cwd = tmp_path / "run"
    cwd.mkdir()
    api = _Api(tmp_path)

    copied = _persist_run_attachment(api, "wf-meet", str(cwd), [str(source)], run_id="run-1")

    assert copied
    assert copied[0].startswith("materials/attachments/")
    assert api.uploaded == []
    assert api.run_attachments == [("wf-meet", "run-1", [str(source)])]


def test_keep_knowledge_upload_uses_keep_origin(tmp_path: Path) -> None:
    from agent_sidecar import _upload_knowledge_files

    source = tmp_path / "catalog.xlsx"
    source.write_bytes(b"XLSX")
    cwd = tmp_path / "run"
    cwd.mkdir()
    api = _Api(tmp_path)

    ok = _upload_knowledge_files(
        api, "wf-meet", str(cwd), [str(source)], run_id="run-1", origin="keep_knowledge"
    )

    assert ok is True
    assert api.uploaded == [("wf-meet", [str(source)])]
    assert api.uploaded_origins == ["keep_knowledge"]


def test_design_prompt_does_not_force_run_inputs_gate() -> None:
    text = _with_sidecar_prompt("Sproektiruy", mode="design")
    assert "you MUST" not in text
    run_text = _with_sidecar_prompt("Sdelai demo")
    assert RUN_INPUTS_RUN_HINT in run_text
    assert "Do not substitute" in run_text


def test_run_inputs_from_local_normalizes_entries() -> None:
    local = {
        "playbook": {
            "run_inputs": [
                {"name": "Годовые совещания", "description": "Файл на год", "accept": ".xlsx"},
                "Список участников",
                {"title": "Годовые совещания"},
            ]
        }
    }
    inputs = _run_inputs_from_local(local)
    assert [item["name"] for item in inputs] == ["Годовые совещания", "Список участников"]
    assert inputs[0]["accept"] == ".xlsx"
    assert inputs[1]["description"] == ""


def test_run_inputs_from_local_empty() -> None:
    assert _run_inputs_from_local({}) == []
    assert _run_inputs_from_local({"playbook": {}}) == []


def test_run_inputs_user_answered_ignores_llm_invented_list() -> None:
    record = SimpleNamespace(
        local_run={"playbook_draft": {"run_inputs": [{"name": "grafik.xlsx"}]}}
    )
    assert _run_inputs_user_answered(record) is False


def test_run_inputs_user_answered_no() -> None:
    record = SimpleNamespace(
        local_run={"design_answers": [{"question": RUN_INPUTS_QUESTION, "answer": RUN_INPUTS_NO}]}
    )
    assert _run_inputs_user_answered(record) is True


def test_run_inputs_user_answered_yes_needs_spec() -> None:
    yes_only = SimpleNamespace(
        local_run={"design_answers": [{"question": RUN_INPUTS_QUESTION, "answer": RUN_INPUTS_YES}]}
    )
    assert _run_inputs_user_answered(yes_only) is False
    complete = SimpleNamespace(
        local_run={
            "design_answers": [{"question": RUN_INPUTS_QUESTION, "answer": RUN_INPUTS_YES}],
            "playbook_draft": {"run_inputs": [{"name": "grafik.xlsx"}]},
        }
    )
    assert _run_inputs_user_answered(complete) is True


def test_merge_run_input_gate_does_not_write_run_inputs() -> None:
    merged = _merge_run_input_gate({}, RUN_INPUTS_NO)
    assert merged is not None
    assert merged["design_answers"][0]["question"] == RUN_INPUTS_QUESTION
    assert "playbook_draft" not in merged
    assert _merge_run_input_gate(merged, RUN_INPUTS_NO) is None


def test_merge_run_inputs_writes_spec() -> None:
    merged = _merge_run_inputs(
        {},
        [{"name": "grafik.xlsx", "description": "obrazec", "accept": ".xlsx"}],
        gate_answer=RUN_INPUTS_YES,
    )
    assert merged is not None
    assert merged["playbook_draft"]["run_inputs"][0]["name"] == "grafik.xlsx"
    assert merged["design_answers"][0]["answer"] == RUN_INPUTS_YES


def test_run_inputs_from_answer_parses_attachment_note() -> None:
    specs = _run_inputs_from_answer(
        "Прикрепленные файлы: grafik.xlsx\n\n"
        "Прикреплённые файлы (прочитай их из рабочей области): materials/attachments/001_grafik.xlsx"
    )
    assert [item["name"] for item in specs] == ["grafik.xlsx"]
    assert specs[0]["accept"] == ".xlsx"


def test_stamp_run_event_adds_workflow_and_run_kind() -> None:
    stamped = _stamp_run_event(
        {"type": "event", "runId": "run-1", "payload": {"type": "run", "run_id": "abc"}},
        workflow_id="wf-meet",
        kind="run",
    )
    assert stamped["workflowId"] == "wf-meet"
    assert stamped["kind"] == "run"
    assert stamped["payload"]["run_id"] == "abc"


def test_stamp_run_event_does_not_override_existing() -> None:
    stamped = _stamp_run_event(
        {"type": "result", "kind": "run", "workflowId": "kept"},
        workflow_id="other",
        kind="run",
    )
    assert stamped["workflowId"] == "kept"
    assert stamped["kind"] == "run"


def test_sandbox_python_tools_skip_sidecar_hitl() -> None:
    assert needs_confirmation("code.write_python") is False
    assert needs_confirmation("code.run_python") is False
    assert needs_confirmation("outlook.send_mail") is True


def test_run_demo_asks_for_file_before_sdk() -> None:
    from agent_sidecar import Sidecar

    names = Sidecar._run_demo.__code__.co_names
    assert "_ensure_run_input_sample_asked" not in names
    assert "_ensure_run_inputs_provided" in names


def test_empty_draft_is_not_file_gate_answered() -> None:
    record = SimpleNamespace(local_run={"playbook_draft": {}, "playbook": {}})
    assert _run_inputs_user_answered(record) is False
    assert _run_inputs_from_local(record.local_run) == []


def test_persist_run_outputs_uploads_created_document(tmp_path: Path, monkeypatch) -> None:
    report = tmp_path / "plan.md"
    report.write_text("ok", encoding="utf-8")
    monkeypatch.setattr("app.tools.result_files.workspace_for", lambda _wid: tmp_path)
    api = _Api(tmp_path)
    uploaded = _persist_run_outputs(
        api,
        "wf-meet",
        str(tmp_path),
        tool="report.export_document",
        result={"path": str(report), "file": str(report), "filename": report.name},
        run_id="run-1",
    )
    assert uploaded == [str(report.resolve())]
    assert api.run_outputs == [("wf-meet", "run-1", [str(report.resolve())])]


def test_persist_run_outputs_sweeps_cwd_at_end(tmp_path: Path, monkeypatch) -> None:
    report = tmp_path / "plan.md"
    report.write_text("ok", encoding="utf-8")
    monkeypatch.setattr("app.tools.result_files.workspace_for", lambda _wid: tmp_path / "missing")
    api = _Api(tmp_path)
    uploaded = _persist_run_outputs(
        api,
        "wf-meet",
        str(tmp_path),
        run_id="run-1",
    )
    assert uploaded == [str(report.resolve())]
    assert api.run_outputs == [("wf-meet", "run-1", [str(report.resolve())])]


def test_persist_run_outputs_skips_read_tools(tmp_path: Path, monkeypatch) -> None:
    leftover = tmp_path / "old.json"
    leftover.write_text("[]", encoding="utf-8")
    monkeypatch.setattr("app.tools.result_files.workspace_for", lambda _wid: tmp_path)
    api = _Api(tmp_path)
    uploaded = _persist_run_outputs(
        api,
        "wf-meet",
        str(tmp_path),
        tool="outlook.read_calendar",
        result={"events": [], "count": 0},
        run_id="run-1",
    )
    assert uploaded == []
    assert api.run_outputs == []
