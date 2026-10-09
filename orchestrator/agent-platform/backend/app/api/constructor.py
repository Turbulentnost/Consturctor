from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from app.constructor.avatars import USER_ID_PATTERN, AvatarUnavailable, fetch_avatar
from app.constructor.catalog import constructor_catalog
from app.constructor.db import fetch_agent_detail
from app.constructor.owners import agent_detail

router = APIRouter(prefix="/constructor")


@router.get("/owners")
def get_owners() -> dict[str, object]:
    return constructor_catalog.snapshot().model_dump()


@router.post("/refresh")
def refresh_owners() -> dict[str, object]:
    constructor_catalog.request_refresh()
    snapshot = constructor_catalog.snapshot()
    snapshot.refreshing = True
    return snapshot.model_dump()


@router.get("/agents/{agent_id}")
def get_agent(agent_id: str) -> dict[str, object]:
    if not USER_ID_PATTERN.fullmatch(agent_id):
        raise HTTPException(status_code=400, detail="Некорректный id агента")
    try:
        row = fetch_agent_detail(agent_id)
    except Exception as exc:
        message = str(exc).splitlines()[0] or "база недоступна"
        raise HTTPException(status_code=502, detail=f"База Constructor недоступна: {message}") from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Агент не найден")
    detail = agent_detail(row)
    if detail is None:
        raise HTTPException(status_code=404, detail="Агент не опубликован")
    return detail.model_dump()


@router.get("/users/{user_id}/avatar")
async def get_avatar(user_id: str) -> Response:
    if not USER_ID_PATTERN.fullmatch(user_id):
        raise HTTPException(status_code=400, detail="Некорректный id пользователя")
    try:
        avatar = await run_in_threadpool(fetch_avatar, user_id)
    except AvatarUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if avatar is None:
        raise HTTPException(status_code=404, detail="Аватар не найден")
    content, media_type = avatar
    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=600"},
    )
