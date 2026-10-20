from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.jwt import AuthContext
from app.db.session import get_db
from app.services.user_ui_prefs import UserUiPrefsError, read_prefs, save_prefs

router = APIRouter(prefix="/me/ui", tags=["ui-prefs"])


def _raise(exc: UserUiPrefsError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("")
def get_ui_prefs(
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return read_prefs(db, user_id=auth.user_id)


@router.patch("")
def patch_ui_prefs(
    body: dict[str, Any],
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return save_prefs(db, user_id=auth.user_id, raw=body)
    except UserUiPrefsError as exc:
        _raise(exc)
        raise
