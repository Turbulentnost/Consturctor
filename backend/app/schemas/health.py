from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    erp_reachable: bool
    erp_server: str
    llm_provider: str
