"""Новости-карточки вкладки «Сегодня»: кому показать и до какого момента."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.org import OrgMember
from app.models.today_news import TodayNews, TodayNewsRecipient
from app.models.user import AppUser
from app.services.org_structure import fio_key, is_liquidated, member_by_fio

EVERYONE = "*"
KINDS = ("info", "process_change")
MAX_DAYS = 180
MAX_BODY = 4000
MAX_IMAGE_BYTES = 8 * 1024 * 1024
IMAGE_TYPES = {
    b"\x89PNG": ("image/png", ".png"),
    b"\xff\xd8\xff": ("image/jpeg", ".jpg"),
    b"GIF8": ("image/gif", ".gif"),
    b"RIFF": ("image/webp", ".webp"),
}


def _storage_dir() -> Path:
    from app.config import settings

    return Path(settings.platform_task_storage_dir).parent / "today_news"


class NewsError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def parse_until(raw: str) -> datetime:
    text = (raw or "").strip()
    if not text:
        raise NewsError("Укажите, до какой даты и времени показывать новость")
    try:
        return _utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError as exc:
        raise NewsError(f"show_until в формате ISO 8601, получено: {text}") from exc


def resolve_audience(db: Session, fios: list[str], departments: list[str]) -> tuple[list[str], list[str]]:
    """user_id получателей и строки, которые не удалось найти."""
    found: list[str] = []
    missing: list[str] = []
    for fio in fios:
        member = member_by_fio(db, fio) if fio.strip() else None
        user_id = _user_id(db, member) if member is not None else ""
        if user_id:
            found.append(user_id)
        elif fio.strip():
            missing.append(fio.strip())
    for name in departments:
        key = fio_key(name)
        if not key:
            continue
        members = [
            member
            for member in db.scalars(select(OrgMember).where(OrgMember.department.ilike(f"%{name.strip()}%"))).all()
            if fio_key(member.department) == key and not is_liquidated(member.fio)
        ]
        ids = [user_id for user_id in (_user_id(db, member) for member in members) if user_id]
        if ids:
            found.extend(ids)
        else:
            missing.append(name.strip())
    return list(dict.fromkeys(found)), missing


def _user_id(db: Session, member: OrgMember) -> str:
    if member.user_id:
        return member.user_id
    user = db.scalar(select(AppUser).where(AppUser.fio == member.fio).limit(1))
    return user.id if user is not None else ""


def publish(
    db: Session,
    *,
    title: str,
    body: str,
    show_until: datetime,
    user_ids: list[str],
    everyone: bool = False,
    kind: str = "info",
    source: str = "",
    author_label: str = "",
    file_id: str = "",
    file_name: str = "",
    task_ids: list[str] | None = None,
    image: bytes | None = None,
) -> dict[str, Any]:
    picture = _image_kind(image) if image else None
    heading = " ".join((title or "").split())
    if len(heading) < 3:
        raise NewsError("Заголовок новости — хотя бы три символа")
    text = (body or "").strip()
    if len(text) > MAX_BODY:
        raise NewsError(f"Текст новости не длиннее {MAX_BODY} символов")
    now = datetime.now(timezone.utc)
    until = _utc(show_until)
    if until <= now:
        raise NewsError("Показывать до — момент в будущем")
    if until > now + timedelta(days=MAX_DAYS):
        raise NewsError(f"Новость показывается не дольше {MAX_DAYS} дней")
    if kind not in KINDS:
        raise NewsError("kind: info | process_change")
    recipients = [EVERYONE] if everyone else list(dict.fromkeys(item for item in user_ids if item))
    if not recipients:
        raise NewsError("Кому показать новость: укажите сотрудников, отдел или всех")
    news = TodayNews(
        id=uuid.uuid4().hex,
        title=heading[:256],
        body=text,
        kind=kind,
        source=source[:64],
        author_label=author_label[:512],
        file_id=file_id[:64],
        file_name=file_name[:512],
        task_ids=list(task_ids or [])[:50],
        show_until=until,
    )
    if image and picture:
        folder = _storage_dir()
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{news.id}{picture[1]}"
        target.write_bytes(image)
        news.image_path, news.image_type = str(target), picture[0]
    db.add(news)
    db.flush()
    for user_id in recipients:
        db.add(TodayNewsRecipient(news_id=news.id, user_id=user_id))
    db.commit()
    return news_out(news) | {"recipients": len(recipients) if not everyone else "all"}


def news_out(news: TodayNews) -> dict[str, Any]:
    return {
        "id": news.id,
        "title": news.title,
        "body": news.body,
        "kind": news.kind,
        "author": news.author_label,
        "file_id": news.file_id,
        "file_name": news.file_name,
        "task_ids": list(news.task_ids or []),
        "image_url": f"/api/v1/today/news/{news.id}/image" if news.image_path else "",
        "show_until": _utc(news.show_until).isoformat(),
        "created_at": _utc(news.created_at).isoformat() if news.created_at else "",
    }


def list_for(db: Session, user_id: str) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    rows = db.scalars(
        select(TodayNews)
        .join(TodayNewsRecipient, TodayNewsRecipient.news_id == TodayNews.id)
        .where(
            TodayNews.show_until > now,
            or_(TodayNewsRecipient.user_id == user_id, TodayNewsRecipient.user_id == EVERYONE),
        )
        .order_by(TodayNews.created_at.desc())
        .limit(100)
    ).unique().all()
    if not rows:
        return []
    dismissed = set(
        db.scalars(
            select(TodayNewsRecipient.news_id).where(
                TodayNewsRecipient.user_id == user_id,
                TodayNewsRecipient.news_id.in_([row.id for row in rows]),
                TodayNewsRecipient.dismissed_at.is_not(None),
            )
        ).all()
    )
    return [news_out(row) for row in rows if row.id not in dismissed]


def _image_kind(data: bytes) -> tuple[str, str]:
    if len(data) > MAX_IMAGE_BYTES:
        raise NewsError("Фото новости не больше 8 МБ")
    for magic, kind in IMAGE_TYPES.items():
        if data.startswith(magic) and (magic != b"RIFF" or data[8:12] == b"WEBP"):
            return kind
    raise NewsError("Фото новости — PNG, JPEG, GIF или WebP")


def load_image(source: str) -> bytes:
    """Фото по ссылке http(s) или по пути к файлу на общей папке."""
    text = (source or "").strip()
    if not text:
        return b""
    if text.lower().startswith(("http://", "https://")):
        import httpx

        try:
            response = httpx.get(text, timeout=20, follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise NewsError(f"Фото не скачалось: {exc}") from exc
        data = response.content
    else:
        if not text.startswith("\\\\"):
            raise NewsError("Фото — ссылка http(s) или путь на сетевой папке \\\\сервер\\...")
        try:
            data = Path(text).read_bytes()
        except OSError as exc:
            raise NewsError(f"Фото не прочитано: {exc}") from exc
    _image_kind(data)
    return data


def image_for(db: Session, user_id: str, news_id: str) -> tuple[str, str]:
    news = db.get(TodayNews, news_id)
    if news is None or not news.image_path:
        raise NewsError("Фото нет", 404)
    allowed = db.scalar(
        select(TodayNewsRecipient.news_id).where(
            TodayNewsRecipient.news_id == news_id,
            or_(TodayNewsRecipient.user_id == user_id, TodayNewsRecipient.user_id == EVERYONE),
        )
    )
    if allowed is None or not Path(news.image_path).is_file():
        raise NewsError("Фото нет", 404)
    return news.image_path, news.image_type


def dismiss(db: Session, user_id: str, news_id: str) -> None:
    news = db.get(TodayNews, news_id)
    if news is None:
        raise NewsError("Новость не найдена", 404)
    mine = db.get(TodayNewsRecipient, (news_id, user_id))
    if mine is None:
        if db.get(TodayNewsRecipient, (news_id, EVERYONE)) is None:
            raise NewsError("Новость не найдена", 404)
        mine = TodayNewsRecipient(news_id=news_id, user_id=user_id)
        db.add(mine)
    mine.dismissed_at = datetime.now(timezone.utc)
    db.commit()
