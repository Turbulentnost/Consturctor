from fastapi import APIRouter

from app.agents.directory import all_agents

router = APIRouter()


@router.get("/agents")
def get_agents() -> dict[str, object]:
    return {"items": [item.model_dump() for item in all_agents()]}
