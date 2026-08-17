from __future__ import annotations

import hashlib
import hmac
import secrets
from uuid import uuid4

from app.db.session import SessionLocal
from app.models.user import AppUser

_PBKDF2_ITERATIONS = 120_000


class LocalAuthError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def is_local_user_id(user_id: str) -> bool:
    return (user_id or "").startswith("local-")


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        _PBKDF2_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password_hash(stored: str, password: str) -> bool:
    try:
        scheme, iterations, salt, digest = stored.split("$", 3)
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    expected = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        int(iterations),
    ).hex()
    return hmac.compare_digest(expected, digest)


def find_local_user_by_fio(fio: str) -> AppUser | None:
    fio = fio.strip()
    if not fio:
        return None
    with SessionLocal() as db:
        user = (
            db.query(AppUser)
            .filter(AppUser.fio == fio, AppUser.password_hash.isnot(None))
            .first()
        )
        if user is None:
            return None
        db.expunge(user)
        return user


def list_local_user_fios(search: str | None = None) -> list[str]:
    term = (search or "").strip()
    with SessionLocal() as db:
        query = db.query(AppUser.fio).filter(AppUser.password_hash.isnot(None))
        if term:
            query = query.filter(AppUser.fio.ilike(f"%{term}%"))
        rows = query.order_by(AppUser.fio).limit(200).all()
        return [str(row[0]).strip() for row in rows if str(row[0]).strip()]


def register_local_user(*, fio: str, password: str, department: str = "") -> AppUser:
    fio = fio.strip()
    department = department.strip()
    if len(fio) < 2:
        raise LocalAuthError("Укажите ФИО (минимум 2 символа)")
    if len(password) < 4:
        raise LocalAuthError("Пароль должен быть не короче 4 символов")

    with SessionLocal() as db:
        existing = db.query(AppUser).filter(AppUser.fio == fio).first()
        if existing is not None and existing.password_hash:
            raise LocalAuthError("Пользователь с таким ФИО уже зарегистрирован", status_code=409)
        if existing is not None:
            user = existing
            user.password_hash = hash_password(password)
            if department and not (user.department or "").strip():
                user.department = department
        else:
            user = AppUser(
                id=f"local-{uuid4().hex[:12]}",
                fio=fio,
                department=department or "Локальный пользователь",
                position="",
                password_hash=hash_password(password),
            )
            db.add(user)
        db.commit()
        db.refresh(user)
        db.expunge(user)
        return user
