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
    OUTLOOK_MEETING_RULE,
    OUTLOOK_SERIES_MARKER,
    WHEN_TO_RUN_HINT,
    WHEN_TO_RUN_QUESTION,
    _file_request_from_payload,
    _is_meeting_text,
    _merge_outlook_rule_into_playbook,
    _merge_when_to_run,
    _persist_knowledge_files,
    _when_to_run_known,
    _with_sidecar_prompt,
)


class _Api:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.uploaded: list[tuple[str, list[str]]] = []

    def upload_workflow_files(self, workflow_id: str, paths: list[str]) -> None:
        self.uploaded.append((workflow_id, [str(item) for item in paths]))

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


def test_design_prompt_requires_agent_trigger_question() -> None:
    text = _with_sidecar_prompt("Sproektiruy", mode="design")
    assert WHEN_TO_RUN_HINT in text
    assert "when_to_run" in text
    run_text = _with_sidecar_prompt("Sdelai demo")
    assert WHEN_TO_RUN_HINT not in run_text


def test_when_to_run_not_inferred_from_meeting_cadence() -> None:
    record = SimpleNamespace(
        title="Planer soveschaniy",
        notes="Nuzhno zaplanirovat ezhenedelnye soveschaniya v Outlook",
        document_text="",
        local_run={},
    )
    assert _when_to_run_known(record) is False


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
