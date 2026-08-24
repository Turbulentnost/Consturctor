from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from app.config import settings

PREFIX = "enc:v1:"
FILE_MAGIC = b"CHENC1"
_NONCE_LEN = 16
_MAC_LEN = 32
_DEFAULT = "constructor-chat-dev-change-me"


def _passphrase() -> str:
    return (getattr(settings, "chat_encryption_key", None) or "").strip() or _DEFAULT


def _key() -> bytes:
    return hashlib.sha256(_passphrase().encode("utf-8")).digest()


def _stream(key: bytes, nonce: bytes, size: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < size:
        out.extend(hashlib.sha256(key + nonce + counter.to_bytes(8, "big")).digest())
        counter += 1
    return bytes(out[:size])


def _seal(data: bytes) -> bytes:
    key = _key()
    nonce = secrets.token_bytes(_NONCE_LEN)
    cipher = bytes(a ^ b for a, b in zip(data, _stream(key, nonce, len(data))))
    mac = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
    return nonce + cipher + mac


def _open(blob: bytes) -> bytes:
    if len(blob) < _NONCE_LEN + _MAC_LEN:
        raise ValueError("слишком короткий пакет")
    key = _key()
    nonce = blob[:_NONCE_LEN]
    mac = blob[-_MAC_LEN:]
    cipher = blob[_NONCE_LEN:-_MAC_LEN]
    expect = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expect):
        raise ValueError("повреждённый или чужой ключ")
    return bytes(a ^ b for a, b in zip(cipher, _stream(key, nonce, len(cipher))))


def encrypt_bytes(data: bytes) -> bytes:
    if not data:
        return b""
    return FILE_MAGIC + _seal(data)


def decrypt_bytes(blob: bytes) -> bytes:
    if not blob:
        return b""
    raw = blob[len(FILE_MAGIC) :] if blob.startswith(FILE_MAGIC) else blob
    return _open(raw)


def encrypt_text(plain: str) -> str:
    text = plain or ""
    if not text:
        return ""
    if text.startswith(PREFIX):
        return text
    return PREFIX + base64.urlsafe_b64encode(_seal(text.encode("utf-8"))).decode("ascii")


def decrypt_text(value: str) -> str:
    text = value or ""
    if not text.startswith(PREFIX):
        return text
    try:
        packed = base64.urlsafe_b64decode(text[len(PREFIX) :].encode("ascii"))
        raw = packed[len(FILE_MAGIC) :] if packed.startswith(FILE_MAGIC) else packed
        return _open(raw).decode("utf-8")
    except Exception:
        return "[не удалось расшифровать]"


def is_encrypted_file(data: bytes) -> bool:
    return data.startswith(FILE_MAGIC)
