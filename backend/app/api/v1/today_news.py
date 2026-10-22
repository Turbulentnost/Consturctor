from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.jwt import AuthContext
from app.db.session import get_db
from app.services import today_news

router = APIRouter(prefix="/today/news", tags=["today-news"])


class NewsPublish(BaseModel):
    title: str = Field(..., min_length=3, max_length=256)
    body: str = Field("", max_length=4000)
    show_until: str
    recipients: list[str] = Field(default_factory=list)
    departments: list[str] = Field(default_factory=list)
    everyone: bool = False
    image: str = ""


def _raise(exc: today_news.NewsError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("")
def read_news(auth: AuthContext = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"items": today_news.list_for(db, auth.user_id)}


@router.post("")
def publish_news(
    body: NewsPublish,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return publish_as_user(db, auth, body.model_dump())
    except today_news.NewsError as exc:
        _raise(exc)
        raise


@router.get("/{news_id}/image")
def read_image(
    news_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    try:
        path, media_type = today_news.image_for(db, auth.user_id, news_id)
    except today_news.NewsError as exc:
        _raise(exc)
        raise
    return FileResponse(path, media_type=media_type or "application/octet-stream")


@router.post("/{news_id}/dismiss")
def dismiss_news(
    news_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    try:
        today_news.dismiss(db, auth.user_id, news_id)
    except today_news.NewsError as exc:
        _raise(exc)
    return {"ok": True}


def publish_as_user(db: Session, auth: AuthContext, arguments: dict[str, Any]) -> dict[str, Any]:
    """Публикация от имени сотрудника. Всем сразу — только администратор."""
    from app.services.admin_access import is_admin_user

    everyone = arguments.get("everyone") is True
    if everyone and not is_admin_user(auth.user_id):
        raise today_news.NewsError("Новость для всех публикует только администратор", 403)
    fios = [str(item) for item in arguments.get("recipients") or [] if str(item).strip()]
    departments = [str(item) for item in arguments.get("departments") or [] if str(item).strip()]
    user_ids, missing = today_news.resolve_audience(db, fios, departments)
    if missing and not user_ids and not everyone:
        raise today_news.NewsError(f"Не найдены получатели: {', '.join(missing)}", 404)
    result = today_news.publish(
        db,
        title=str(arguments.get("title") or ""),
        body=str(arguments.get("body") or ""),
        show_until=today_news.parse_until(str(arguments.get("show_until") or "")),
        user_ids=user_ids,
        everyone=everyone,
        source=auth.user_id,
        author_label=auth.fio or "",
        image=today_news.load_image(str(arguments.get("image") or "")) or None,
    )
    return result | {"not_found": missing}
