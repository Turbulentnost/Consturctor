from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str = Field(..., description="system | user | assistant")
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(..., min_length=1)
    model: str | None = None


class ChatResponse(BaseModel):
    provider: str
    model: str
    content: str
