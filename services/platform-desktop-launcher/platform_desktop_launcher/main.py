from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from platform_desktop_launcher.spawn import ensure_desktop_service, load_specs, port_open, repo_root, resolve_port


class LauncherSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    api_host: str = "0.0.0.0"
    api_port: int = 7829
    service_name: str = "platform-desktop-launcher"


class EnsureRequest(BaseModel):
    port: int | None = None
    tool_name: str | None = None
    wait_seconds: float = Field(default=30.0, ge=1.0, le=120.0)


settings = LauncherSettings()
app = FastAPI(title=settings.service_name, version="0.1.0")


@app.get("/health")
def health() -> dict[str, Any]:
    specs = load_specs(repo_root())
    ports = {
        str(spec.port): "up" if port_open(spec.port) else "down"
        for spec in specs.values()
    }
    return {
        "status": "ok",
        "service": settings.service_name,
        "launcher_port": settings.api_port,
        "desktop_ports": ports,
    }


@app.post("/api/v1/ensure")
def ensure(body: EnsureRequest) -> dict[str, Any]:
    specs = load_specs(repo_root())
    try:
        port = resolve_port(port=body.port, tool_name=body.tool_name, specs=specs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = ensure_desktop_service(port=port, wait_seconds=body.wait_seconds)
    if not result["ok"]:
        raise HTTPException(status_code=503, detail=str(result["message"]))
    return result


def main() -> None:
    import uvicorn

    uvicorn.run(app, host=settings.api_host, port=settings.api_port)


if __name__ == "__main__":
    main()
