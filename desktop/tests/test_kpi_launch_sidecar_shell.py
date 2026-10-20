"""Сайдкар orchestrator: PowerShell агента запуска KPI идёт без подтверждения, кроме удаления."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SIDECAR = ROOT / "orchestrator" / "desktop-electron" / "pybridge" / "agent_sidecar.py"
SHELL = "workspace.powershell_run"


def _load():
    name = "orchestrator_agent_sidecar"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SIDECAR)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _record(workflow_id: str, title: str) -> SimpleNamespace:
    return SimpleNamespace(id=workflow_id, title=title, notes="", local_run={})


def test_kpi_launch_gets_its_pack_with_shell() -> None:
    sidecar = _load()
    specs = sidecar._tool_specs_for_workflow(_record("wf-kpi", "Запуск модулей KPI"))
    names = {item["name"] for item in specs or []}
    assert {SHELL, "onec.position_holders", "kpi.publish_position_result", "kpi.read_methodology"} <= names
    assert sidecar._kpi_shell_auto_approved("wf-kpi", SHELL, {"command": 'python x.py --fio "А"'})
    assert sidecar._kpi_shell_auto_approved("wf-kpi", SHELL, {"command": "Get-ChildItem C:\\"})


def test_kpi_launch_shell_waits_longer_than_the_tool() -> None:
    sidecar = _load()
    specs = sidecar._tool_specs_for_workflow(_record("wf-kpi", "Запуск модулей KPI"))
    shell = next(item for item in specs if item["name"] == SHELL)
    assert shell["timeoutSeconds"] > sidecar._KPI_SHELL_TIMEOUT_SECONDS == 300


def test_bridge_budget_follows_powershell_timeout() -> None:
    from app.sdk_agent.tool_adapter import tool_timeout_seconds

    assert tool_timeout_seconds(SHELL, {"command": "dir", "timeout_seconds": 300}) > 300
    assert tool_timeout_seconds(SHELL, {"command": "dir", "timeout_seconds": 9999}) <= 300 + 60


def test_destructive_commands_still_ask_a_person() -> None:
    sidecar = _load()
    sidecar._tool_specs_for_workflow(_record("wf-kpi", "Запуск модулей KPI"))
    assert not sidecar._kpi_shell_auto_approved("wf-kpi", SHELL, {"command": "Remove-Item C:\\kpi -Recurse"})
    assert not sidecar._kpi_shell_auto_approved("wf-kpi", SHELL, {"command": "Set-Content a.py 'x'"})


def test_other_agents_shell_still_asks() -> None:
    sidecar = _load()
    sidecar._tool_specs_for_workflow(_record("wf-rk", "Подготовка к ревизионной комиссии"))
    assert "wf-rk" not in sidecar._KPI_LAUNCH_WORKFLOWS
    assert not sidecar._kpi_shell_auto_approved("wf-rk", SHELL, {"command": "dir"})


def test_date_and_methodology_reads_do_not_wait_for_a_person() -> None:
    sidecar = _load()
    assert not sidecar.needs_confirmation("get_current_date")
    assert not sidecar.needs_confirmation("kpi.read_methodology")
    assert sidecar.needs_confirmation(SHELL)
