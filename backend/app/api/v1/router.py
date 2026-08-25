from fastapi import APIRouter

from app.api.v1 import (
    agents,
    auth,
    health,
    llm,
    notifications,
    regulation_creation,
    regulations,
    tools,
    triggers,
    workflows,
)
from app.modules.chat.api import router as chat_router

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router, prefix="/api/v1")
api_router.include_router(llm.router, prefix="/api/v1")
api_router.include_router(regulations.router, prefix="/api/v1")
api_router.include_router(agents.router, prefix="/api/v1")
api_router.include_router(regulation_creation.router, prefix="/api/v1")
api_router.include_router(workflows.router, prefix="/api/v1")
api_router.include_router(tools.router, prefix="/api/v1")
api_router.include_router(notifications.router, prefix="/api/v1")
api_router.include_router(triggers.router, prefix="/api/v1")
api_router.include_router(chat_router, prefix="/api/v1")
