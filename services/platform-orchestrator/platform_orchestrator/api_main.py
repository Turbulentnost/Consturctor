from __future__ import annotations

from uuid import UUID

from fastapi import FastAPI, HTTPException

from platform_contracts.runs import RunStartRequest, RunStatus
from platform_orchestrator.service import create_run, get_run, get_run_events, settings

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


def main() -> None:
    import uvicorn

    uvicorn.run(app, host=settings.api_host, port=settings.api_port)


if __name__ == "__main__":
    main()
