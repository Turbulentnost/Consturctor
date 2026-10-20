from fastapi import APIRouter

from app.api import agents, constructor, health, platform, runs, sdk, settings, skills, tools

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(agents.router, prefix="/api/v1")
api_router.include_router(constructor.router, prefix="/api/v1")
api_router.include_router(tools.router, prefix="/api/v1")
api_router.include_router(skills.router, prefix="/api/v1")
api_router.include_router(sdk.router, prefix="/api/v1")
api_router.include_router(runs.router, prefix="/api/v1")
api_router.include_router(platform.router, prefix="/api/v1")
api_router.include_router(settings.router, prefix="/api/v1")
