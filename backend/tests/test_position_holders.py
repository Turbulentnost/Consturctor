"""onec.position_holders: ФИО тех, кто сейчас на должности."""

from __future__ import annotations

from app.services.local_mcp import list_tools
from app.services.onec_tools import ONEC_TOOLS, REAL_HANDLERS
from app.services.workflows.kpi_launch_playbook import is_kpi_launch_agent, kpi_launch_runtime_tools
from app.tools.onec.position_holders import invoke_position_holders


class _Staff:
    def search(self, entity: str, text: str) -> list[dict]:
        if entity.endswith("Должности"):
            return [{"Ref_Key": "11111111-1111-1111-1111-111111111111", "Description": text, "DeletionMark": False}]
        return [{"Ref_Key": "22222222-2222-2222-2222-222222222222", "Description": text, "DeletionMark": False}]

    def slice_last(self, period: str, position_key: str, department_key: str):
        del period, position_key, department_key
        return [
            {
                "Сотрудник_Key": "33333333-3333-3333-3333-333333333333",
                "Должность_Key": "11111111-1111-1111-1111-111111111111",
                "Подразделение_Key": "22222222-2222-2222-2222-222222222222",
                "Period": "2026-01-15T00:00:00",
                "ВидСобытия": "Прием",
                "КоличествоСтавок": 1,
            }
        ], False

    def employees(self, keys: list[str]) -> dict:
        return {
            keys[0]: {
                "Ref_Key": keys[0],
                "Description": "Карташова Анастасия Эдуардовна",
                "Code": "00-01",
                "DeletionMark": False,
            }
        }

    def employee_slice(self, period: str, employee_keys: list[str]) -> dict:
        del period
        key = employee_keys[0]
        return {
            key: {
                "Сотрудник_Key": key,
                "Должность_Key": "11111111-1111-1111-1111-111111111111",
                "Подразделение_Key": "22222222-2222-2222-2222-222222222222",
                "Period": "2026-01-15T00:00:00",
                "ВидСобытия": "Прием",
                "КоличествоСтавок": 1,
            }
        }

    def employee_states(self, employee_keys: list[str], as_of: str) -> dict:
        del employee_keys, as_of
        return {}

    def get(self, entity: str, ref_key: str):
        del entity, ref_key
        return {"Description": "Управление делами", "Ref_Key": ref_key, "Parent_Key": "00000000-0000-0000-0000-000000000000"}


def test_position_holders_returns_fio() -> None:
    result = invoke_position_holders(
        {"position": "Помощник", "department": "Управление делами", "as_of": "2026-10-16"},
        source=_Staff(),
    )
    assert result["status"] == "found"
    assert result["people"][0]["fio"] == "Карташова Анастасия Эдуардовна"


def test_position_holders_is_registered() -> None:
    assert "onec.position_holders" in ONEC_TOOLS
    assert "onec.position_holders" in REAL_HANDLERS
    names = {item["name"] for item in list_tools()}
    assert "onec.position_holders" in names


def test_kpi_launch_agent_gets_holders_tool() -> None:
    blob = "Запуск модулей KPI platform:80d85957-2002-480d-b058-caa7a8198711"
    assert is_kpi_launch_agent(blob)
    assert "onec.position_holders" in kpi_launch_runtime_tools()
