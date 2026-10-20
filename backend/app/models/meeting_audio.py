"""Расшифровки совещаний и отпечатки голосов сотрудников."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MeetingTranscript(Base):
    """Полный текст расшифровки. Голоса здесь ещё могут быть «Голос N»."""

    __tablename__ = "meeting_transcripts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    duration_sec: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    transcript_path: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    full_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    segments: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    embeddings: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    speaker_map: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class VoiceProfile(Base):
    """Отпечаток голоса человека. Следующая запись узнаёт его без угадывания по тексту."""

    __tablename__ = "voice_profiles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    fio: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    fio_key: Mapped[str] = mapped_column(String(512), nullable=False, default="", index=True)
    embedding: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
