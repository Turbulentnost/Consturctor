from fastapi import APIRouter

from app.api.v1 import agent_mocks, auth, health, kpi, llm, runs, tool_sandbox, tools

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router, prefix="/api/v1")
api_router.include_router(llm.router, prefix="/api/v1")
api_router.include_router(tools.router, prefix="/api/v1")
api_router.include_router(tool_sandbox.router, prefix="/api/v1")
api_router.include_router(agent_mocks.router, prefix="/api/v1")
api_router.include_router(runs.router, prefix="/api/v1")
api_router.include_router(kpi.router, prefix="/api/v1")
