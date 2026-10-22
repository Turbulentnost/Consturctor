from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TodayNews(Base):
    """Новость-карточка на вкладке «Сегодня». Видна до show_until."""

    __tablename__ = "today_news"
    __table_args__ = (Index("ix_today_news_until", "show_until"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # process_change | info
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="info")
    # Кто опубликовал: user_id человека или ключ серверного агента.
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    author_label: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    # Ссылки карточки: файл базы знаний, поставленные задачи.
    file_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    file_name: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    task_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # Фото карточки на диске бэкенда. Пусто — текстовая карточка.
    image_path: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    image_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    show_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TodayNewsRecipient(Base):
    """Кому показать новость. user_id «*» — всем сотрудникам."""

    __tablename__ = "today_news_recipients"
    __table_args__ = (Index("ix_today_news_recipients_user", "user_id"),)

    news_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("today_news.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
