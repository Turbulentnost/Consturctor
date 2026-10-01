from __future__ import annotations

import time
from pathlib import Path

from app.api_client import WorkflowFileItem, WorkflowFiles
from app.sdk_agent.files import seed_last_agent_outputs
from app.tools.result_files import collect_output_files_from_dir


def _dated_reports_api(downloaded: list[str]):
    class _Api:
        def list_workflow_files(self, workflow_id: str) -> WorkflowFiles:
            return WorkflowFiles(
                agent_files=[
                    WorkflowFileItem(
                        id="sept10",
                        run_id="run-10",
                        filename="Svodka_SD_2026-09-10.docx",
                        created_at="2026-09-10T09:00:00Z",
                    ),
                    WorkflowFileItem(
                        id="sept30",
                        run_id="run-30",
                        filename="Svodka_SD_2026-09-30.docx",
                        created_at="2026-09-30T06:19:12Z",
                    ),
                ]
            )

        def download_workflow_file_to(self, workflow_id: str, file_id: str, destination: Path) -> str:
            downloaded.append(file_id)
            destination.write_bytes(f"docx-{file_id}".encode())
            return str(destination)

    return _Api()


def test_seed_last_agent_outputs_restores_only_the_previous_run(tmp_path: Path) -> None:
    downloaded: list[str] = []
    restored = seed_last_agent_outputs(_dated_reports_api(downloaded), "wf-1", str(tmp_path))  # type: ignore[arg-type]
    assert restored == ["Svodka_SD_2026-09-30.docx"]
    assert downloaded == ["sept30"]
    assert not (tmp_path / "Svodka_SD_2026-09-10.docx").exists()


def test_output_sweep_skips_restored_and_keeps_new_documents(tmp_path: Path) -> None:
    seed_last_agent_outputs(_dated_reports_api([]), "wf-1", str(tmp_path))  # type: ignore[arg-type]
    restored = tmp_path / "Svodka_SD_2026-09-30.docx"
    assert restored.stat().st_mtime < time.time() - 3600
    assert collect_output_files_from_dir(tmp_path) == []

    fresh = tmp_path / "Svodka_SD_2026-10-27.docx"
    fresh.write_bytes(b"new report")
    assert collect_output_files_from_dir(tmp_path) == [fresh.resolve()]

    restored.write_bytes(b"agent rewrote the report")
    assert set(collect_output_files_from_dir(tmp_path)) == {fresh.resolve(), restored.resolve()}


def test_output_sweep_skips_documents_left_before_the_run(tmp_path: Path) -> None:
    leftover = tmp_path / "Svodka_SD_2026-09-10.docx"
    leftover.write_bytes(b"old")
    time.sleep(0.05)
    seed_last_agent_outputs(_dated_reports_api([]), "wf-1", str(tmp_path))  # type: ignore[arg-type]
    assert leftover.resolve() not in collect_output_files_from_dir(tmp_path)
