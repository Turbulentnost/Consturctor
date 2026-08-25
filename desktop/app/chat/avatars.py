from __future__ import annotations

from PySide6.QtGui import QPixmap

from app.api_client import ApiClient, ApiError

_cache: dict[str, QPixmap] = {}


def avatar_path(peer_id: str) -> str:
    return f"/api/v1/auth/users/{peer_id}/avatar" if peer_id else ""


def peek_avatar(peer_id: str) -> QPixmap | None:
    return _cache.get(peer_id)


def load_peer_avatar(api: ApiClient, peer_id: str) -> QPixmap:
    if not peer_id:
        return QPixmap()
    cached = _cache.get(peer_id)
    if cached is not None:
        return cached
    try:
        data = api.fetch_bytes(avatar_path(peer_id))
    except ApiError:
        empty = QPixmap()
        _cache[peer_id] = empty
        return empty
    pixmap = QPixmap()
    if not pixmap.loadFromData(data):
        empty = QPixmap()
        _cache[peer_id] = empty
        return empty
    _cache[peer_id] = pixmap
    return pixmap
