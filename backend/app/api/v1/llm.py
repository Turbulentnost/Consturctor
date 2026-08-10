from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.core.jwt import AuthContext
from app.schemas.llm import ChatRequest, ChatResponse
from app.services import llm_service

router = APIRouter(prefix="/llm", tags=["llm"])


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    _auth: AuthContext = Depends(get_current_user),
) -> ChatResponse:
    return llm_service.chat(body)
