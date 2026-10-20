from fastapi import APIRouter

from app.agents.directory import all_agents
from app.constructor.catalog import constructor_catalog
from app.sdk.runner import sdk_status
from app.skills.registry import list_skills
from app.tools.registry import list_tools

router = APIRouter()


@router.get("/health")
def health() -> dict[str, object]:
    status = sdk_status()
    return {
        "status": "ok",
        "sdk": "connected" if status["connected"] else "not_connected",
        "constructor": constructor_catalog.snapshot().state,
        "agents": len(all_agents()),
        "tools": len(list_tools()),
        "skills": len(list_skills()),
    }
