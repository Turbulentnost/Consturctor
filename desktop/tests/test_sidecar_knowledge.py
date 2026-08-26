from __future__ import annotations

import sys
from pathlib import Path

from app.api_client import WorkflowFileItem, WorkflowFiles

ROOT = Path(__file__).resolve().parents[2]
PYBRIDGE = ROOT / "desktop-electron" / "pybridge"
if str(PYBRIDGE) not in sys.path:
    sys.path.insert(0, str(PYBRIDGE))

from agent_sidecar import _file_request_from_payload, _persist_knowledge_files  # noqa: E402


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

    copied = _persist_knowledge_files(api, "wf-meet", str(cwd), [str(source)])

    assert copied
    assert copied[0].startswith("materials/attachments/")
    assert api.uploaded == [("wf-meet", [str(source)])]
    manifest = cwd / "materials" / "manifest.json"
    assert manifest.is_file()
    assert "schedule.xlsx" in manifest.read_text(encoding="utf-8")
    assert (cwd / "materials" / "001_schedule.xlsx").read_bytes() == b"XLSX"
