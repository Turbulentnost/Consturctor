from __future__ import annotations

from uuid import UUID

from fastapi import FastAPI, HTTPException

from platform_orchestrator.agent_mocks import list_mock_scenarios
from platform_orchestrator.tool_sandbox import list_sandbox_tests
from platform_orchestrator.service import (
    create_run,
    get_run,
    get_run_events,
    invoke_tool_for_api,
    settings,
    simulate_all_sandbox_tests,
    simulate_mock_scenario,
    simulate_sandbox_test,
    start_mock_run,
)
from platform_contracts.runs import RunStartRequest, RunStatus
from platform_contracts.tools import ToolInvokeRequest, ToolResult

app = FastAPI(title="platform-orchestrator", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "platform-orchestrator", "use_stubs": settings.use_stubs}


@app.post("/api/v1/runs", response_model=RunStatus)
def start_run(body: RunStartRequest) -> RunStatus:
    return create_run(body)


@app.get("/api/v1/runs/{run_id}", response_model=RunStatus)
def run_status(run_id: UUID) -> RunStatus:
    status = get_run(run_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return status


@app.get("/api/v1/runs/{run_id}/events")
def run_events(run_id: UUID) -> dict:
    return {"items": get_run_events(run_id)}


@app.post("/api/v1/tools/{tool_name}/invoke", response_model=ToolResult)
def invoke_tool(tool_name: str, body: ToolInvokeRequest) -> ToolResult:
    return invoke_tool_for_api(body, tool_name)


@app.get("/api/v1/agent/mocks")
def agent_mocks() -> dict:
    return {"items": list_mock_scenarios(), "use_stubs": settings.use_stubs}


@app.post("/api/v1/agent/mocks/{scenario_id}/run", response_model=RunStatus)
def run_agent_mock(scenario_id: str, body: RunStartRequest) -> RunStatus:
    try:
        return start_mock_run(scenario_id, body)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/v1/agent/mocks/{scenario_id}/simulate")
def simulate_agent_mock(scenario_id: str, body: RunStartRequest) -> dict:
    try:
        return simulate_mock_scenario(
            scenario_id,
            department=body.department,
            user_id=body.user_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/v1/tools/sandbox")
def tool_sandbox_list() -> dict:
    return {"items": list_sandbox_tests(), "use_stubs": settings.use_stubs}


@app.post("/api/v1/tools/sandbox/run-all")
def tool_sandbox_run_all(body: RunStartRequest) -> dict:
    return simulate_all_sandbox_tests(
        department=body.department,
        user_id=body.user_id,
    )


@app.post("/api/v1/tools/sandbox/{test_id}/run")
def tool_sandbox_run(test_id: str, body: RunStartRequest) -> dict:
    try:
        return simulate_sandbox_test(
            test_id,
            department=body.department,
            user_id=body.user_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def main() -> None:
    import uvicorn

    uvicorn.run(app, host=settings.api_host, port=settings.api_port)


if __name__ == "__main__":
    main()
