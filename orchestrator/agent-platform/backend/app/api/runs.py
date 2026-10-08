from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agents.directory import find_agent
from app.runs import create_run, list_runs
from app.tools.registry import get_tool

router = APIRouter()


class RunCreate(BaseModel):
    agent_id: str
    prompt: str
    tool_names: list[str] = Field(default_factory=list)


@router.get("/runs")
def get_runs() -> dict[str, object]:
    return {"items": [item.model_dump() for item in list_runs()]}


@router.post("/runs")
def post_run(body: RunCreate) -> dict[str, object]:
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Пустой промпт")
    agent = find_agent(body.agent_id.strip())
    if agent is None:
        raise HTTPException(
            status_code=404,
            detail=f"Агент не зарегистрирован: {body.agent_id}",
        )
    unknown = [name for name in body.tool_names if get_tool(name) is None]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Инструменты не зарегистрированы: {', '.join(unknown)}",
        )
    return create_run(agent, prompt, body.tool_names).model_dump()
