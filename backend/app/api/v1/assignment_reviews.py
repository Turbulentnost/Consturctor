from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.jwt import AuthContext
from app.db.session import get_db
from app.services.assignment_reviews import get_review, list_reviewed_keys, list_reviews, save_reviews

router = APIRouter(prefix="/assignment-reviews", tags=["assignment-reviews"])


class AssignmentReviewIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    number: str = ""
    target_id: str = ""
    conclusion: str = ""
    done: int = 0
    total: int = 0
    reason: str = ""
    tasks: list[dict] = Field(default_factory=list)


class AssignmentReviewsSaveIn(BaseModel):
    assignments: list[AssignmentReviewIn] = Field(default_factory=list)
    workflow_id: str = ""
    run_id: str = ""


@router.post("")
def post_assignment_reviews(
    body: AssignmentReviewsSaveIn,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    items = [item.model_dump() for item in body.assignments if item.number or item.target_id]
    if not items:
        raise HTTPException(status_code=400, detail="Нет поручений для сохранения")
    result = save_reviews(
        db,
        items,
        user_id=auth.user_id,
        workflow_id=body.workflow_id,
        run_id=body.run_id,
    )
    return {"ok": True, **result}


@router.get("")
def get_assignment_reviews(
    date_from: str = Query(default=""),
    date_to: str = Query(default=""),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _ = auth
    items = list_reviews(db, date_from=date_from, date_to=date_to)
    return {"count": len(items), "reviews": items}


@router.get("/keys")
def get_assignment_review_keys(
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _ = auth
    return list_reviewed_keys(db)


@router.get("/{ref_key}")
def get_assignment_review(
    ref_key: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _ = auth
    item = get_review(db, ref_key=ref_key) or get_review(db, number=ref_key)
    if item is None:
        raise HTTPException(status_code=404, detail="Проверки этого поручения ещё нет")
    return item
