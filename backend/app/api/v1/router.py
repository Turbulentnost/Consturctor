from fastapi import APIRouter

from app.api.v1 import (
    agent_mocks,
    agents,
    auth,
    cron_jobs,
    health,
    kpi,
    llm,
    notifications,
    regulation_creation,
    regulations,
    runs,
    tool_sandbox,
    tools,
    triggers,
    workflows,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router, prefix="/api/v1")
api_router.include_router(llm.router, prefix="/api/v1")
api_router.include_router(regulations.router, prefix="/api/v1")
api_router.include_router(agents.router, prefix="/api/v1")
api_router.include_router(tools.router, prefix="/api/v1")
api_router.include_router(tool_sandbox.router, prefix="/api/v1")
api_router.include_router(agent_mocks.router, prefix="/api/v1")
api_router.include_router(runs.router, prefix="/api/v1")
api_router.include_router(cron_jobs.router, prefix="/api/v1")
api_router.include_router(kpi.router, prefix="/api/v1")
api_router.include_router(regulation_creation.router, prefix="/api/v1")
api_router.include_router(workflows.router, prefix="/api/v1")
api_router.include_router(notifications.router, prefix="/api/v1")
api_router.include_router(triggers.router, prefix="/api/v1")
