from pydantic import BaseModel, Field


class PlatformServiceHealth(BaseModel):
    name: str
    reachable: bool
    status: str = "unknown"


class HealthResponse(BaseModel):
    status: str
    erp_reachable: bool
    erp_server: str
    llm_provider: str
    auth_stub: bool = False
    registration_enabled: bool = True
    dev_mode: bool = False
    platform_services: list[PlatformServiceHealth] = Field(default_factory=list)
