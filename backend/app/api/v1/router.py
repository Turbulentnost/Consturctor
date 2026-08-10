from fastapi import APIRouter

from app.api.v1 import auth, health, kpi, llm, runs, tools

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router, prefix="/api/v1")
api_router.include_router(llm.router, prefix="/api/v1")
api_router.include_router(tools.router, prefix="/api/v1")
api_router.include_router(runs.router, prefix="/api/v1")
api_router.include_router(kpi.router, prefix="/api/v1")
