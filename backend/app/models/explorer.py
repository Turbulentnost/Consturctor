from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ExplorerEntry(Base):
    """Папка или файл проводника «База знаний» на общей сетевой папке."""

    __tablename__ = "explorer_entries"
    __table_args__ = (
        Index("ix_explorer_entries_owner_parent", "owner_user_id", "parent_id"),
        Index("ix_explorer_entries_owner_folder", "owner_folder"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # folder | file
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("explorer_entries.id", ondelete="CASCADE"), nullable=True
    )
    owner_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_fio: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    # Папка владельца в корне хранилища, например «мангасарян».
    owner_folder: Mapped[str] = mapped_column(String(255), nullable=False)
    # Путь относительно корня хранилища.
    rel_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    content_type: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    updated_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")


class ExplorerFileKey(Base):
    """Ключ шифрования файла и его владелец."""

    __tablename__ = "explorer_file_keys"

    file_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("explorer_entries.id", ondelete="CASCADE"), primary_key=True
    )
    owner_user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Ключ записи. Им же шифруется файл.
    key: Mapped[str] = mapped_column(Text, nullable=False)
    # Ключ чтения. Создаётся вместе с ключом записи.
    read_key: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # private | users | department | all
    access_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="private")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ExplorerHistoryRepo(Base):
    """Скрытый git-репозиторий истории в папке владельца. Ключ знает только система."""

    __tablename__ = "explorer_history_repos"

    owner_folder: Mapped[str] = mapped_column(String(255), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Ключ Fernet, которым зашифровано каждое содержимое в репозитории.
    key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ExplorerKeyGrant(Base):
    """Кому, кроме владельца, выдан ключ файла: сотруднику, отделу или всем."""

    __tablename__ = "explorer_key_grants"
    __table_args__ = (Index("ix_explorer_key_grants_grantee", "grantee_kind", "grantee_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    file_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("explorer_file_keys.file_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # user | department | all
    grantee_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    # user_id для user, название отдела для department, пусто для all.
    grantee_id: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    grantee_label: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    # read | write. Старые выдачи без колонки считаются записью.
    permission: Mapped[str] = mapped_column(String(16), nullable=False, default="write")
    # Если человек попал в доступ через выбор отдела — название этого отдела.
    source_department: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
