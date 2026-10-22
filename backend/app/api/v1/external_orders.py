from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.jwt import AuthContext
from app.db.session import get_db
from app.services.external_orders import (
    ExternalOrderError,
    accept_finding,
    accept_plan,
    add_baseline,
    add_decision,
    add_document,
    add_risk,
    approve_order_file,
    close_conditions,
    close_diff,
    confirm_check,
    create_order,
    delete_order_file,
    get_order,
    import_onec_order,
    import_tkp_order,
    link_onec,
    list_orders,
    make_plan,
    meta_for,
    patch_order,
    publish_order_plan,
    recent_onec_orders,
    refresh_onec,
    search_onec,
    transition,
    upload_order_file,
)

router = APIRouter(prefix="/external-orders", tags=["external-orders"])


class OrderCreateIn(BaseModel):
    customer: str = ""
    product: str = ""
    inn: str = ""
    contact: str = ""
    order_type: str = ""
    priority: str = ""


class OrderPatchIn(BaseModel):
    sections: dict = Field(default_factory=dict)
    owners: dict = Field(default_factory=dict)
    route: str | None = None


class TransitionIn(BaseModel):
    target: str


class EvidenceIn(BaseModel):
    evidence: str = ""


class DiffCloseIn(BaseModel):
    note: str = ""


class RiskIn(BaseModel):
    title: str = ""
    impact: str = ""
    measure: str = ""
    source: str = ""


class DecisionIn(BaseModel):
    protocol: str = ""
    decision: str = ""
    allowed_stage: str = "tkp"
    conditions: str = ""
    base_version: str = ""
    baseline_id: str = ""


class DocumentIn(BaseModel):
    kind: str = "other"
    title: str = ""
    version: str = ""
    note: str = ""


class FileIn(BaseModel):
    kind: str = "other"
    filename: str = ""
    content_base64: str = ""


class BaselineIn(BaseModel):
    composition: str = ""
    cost: str = ""
    mcr: str = ""
    margin: str = ""
    bdds: str = ""
    deadlines: str = ""
    reason: str = ""


class ConditionCloseIn(BaseModel):
    document_id: str = ""


class OnecLinkIn(BaseModel):
    ref_key: str = ""


def _role(auth: AuthContext, as_role: str) -> str:
    from app.services.external_orders import resolve_role

    return resolve_role(
        fio=auth.fio or "",
        position=auth.position or "",
        department=auth.department or "",
        as_role=as_role,
    )


def _call(action):
    try:
        return action()
    except ExternalOrderError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc


@router.get("/meta")
def get_meta(
    as_role: str = Query(default=""),
    auth: AuthContext = Depends(get_current_user),
) -> dict:
    return meta_for(
        fio=auth.fio or "",
        position=auth.position or "",
        department=auth.department or "",
        as_role=as_role,
    )


@router.get("")
def get_orders(
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _ = auth
    items = list_orders(db)
    return {"count": len(items), "orders": items}


@router.post("")
def post_order(
    body: OrderCreateIn,
    as_role: str = Query(default=""),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return _call(
        lambda: create_order(
            db,
            role=_role(auth, as_role),
            fio=auth.fio or "",
            fields=body.model_dump(),
        )
    )


@router.get("/agent")
def get_agent(
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _ = auth
    from app.services.external_order_agent import TITLE, ensure_agent

    row = ensure_agent(db)
    if row is None:
        return {"workflow_id": "", "title": TITLE}
    return {"workflow_id": row.id, "title": row.title}


@router.get("/matrix")
def get_matrix(
    order_id: str = Query(default=""),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _ = auth
    from app.services.external_order_matrix import evaluate_matrix

    def load() -> dict:
        order = get_order(db, order_id) if order_id.strip() else None
        return evaluate_matrix(order)

    return _call(load)


@router.get("/onec/recent")
def get_onec_recent(
    auth: AuthContext = Depends(get_current_user),
) -> dict:
    _ = auth
    return _call(lambda: recent_onec_orders())


@router.post("/onec/import-tkp")
def post_onec_import_tkp(
    body: OnecLinkIn,
    as_role: str = Query(default=""),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return _call(
        lambda: import_tkp_order(
            db,
            role=_role(auth, as_role),
            fio=auth.fio or "",
            ref_key=body.ref_key,
        )
    )


@router.post("/onec/import")
def post_onec_import(
    body: OnecLinkIn,
    as_role: str = Query(default=""),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return _call(
        lambda: import_onec_order(
            db,
            role=_role(auth, as_role),
            fio=auth.fio or "",
            ref_key=body.ref_key,
        )
    )


@router.get("/onec")
def get_onec(
    q: str = Query(default=""),
    counterparty: str = Query(default=""),
    auth: AuthContext = Depends(get_current_user),
) -> dict:
    _ = auth
    return _call(lambda: search_onec(q, counterparty))


@router.post("/{order_id}/strategy")
def post_strategy(
    order_id: str,
    as_role: str = Query(default=""),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    from app.services.external_order_strategy import link_strategy

    return _call(
        lambda: link_strategy(db, order_id, role=_role(auth, as_role), fio=auth.fio or "")
    )


@router.get("/{order_id}/review")
def get_review(
    order_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _ = auth
    from app.services.external_order_matrix import review_checklist

    return _call(lambda: review_checklist(get_order(db, order_id)))


@router.get("/{order_id}")
def get_one(
    order_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _ = auth
    return _call(lambda: get_order(db, order_id))


@router.patch("/{order_id}")
def patch_one(
    order_id: str,
    body: OrderPatchIn,
    as_role: str = Query(default=""),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    fields = body.model_dump(exclude_none=True)
    return _call(
        lambda: patch_order(db, order_id, role=_role(auth, as_role), fio=auth.fio or "", fields=fields)
    )


@router.post("/{order_id}/transition")
def post_transition(
    order_id: str,
    body: TransitionIn,
    as_role: str = Query(default=""),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return _call(
        lambda: transition(
            db, order_id, role=_role(auth, as_role), fio=auth.fio or "", target=body.target
        )
    )


@router.post("/{order_id}/checks/{check_id}/confirm")
def post_confirm(
    order_id: str,
    check_id: str,
    body: EvidenceIn,
    as_role: str = Query(default=""),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return _call(
        lambda: confirm_check(
            db,
            order_id,
            check_id,
            role=_role(auth, as_role),
            fio=auth.fio or "",
            evidence=body.evidence,
        )
    )


@router.post("/{order_id}/diffs/{diff_id}/close")
def post_close_diff(
    order_id: str,
    diff_id: str,
    body: DiffCloseIn,
    as_role: str = Query(default=""),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return _call(
        lambda: close_diff(
            db, order_id, diff_id, role=_role(auth, as_role), fio=auth.fio or "", note=body.note
        )
    )


@router.post("/{order_id}/risks")
def post_risk(
    order_id: str,
    body: RiskIn,
    as_role: str = Query(default=""),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return _call(
        lambda: add_risk(
            db, order_id, role=_role(auth, as_role), fio=auth.fio or "", fields=body.model_dump()
        )
    )


@router.post("/{order_id}/decisions")
def post_decision(
    order_id: str,
    body: DecisionIn,
    as_role: str = Query(default=""),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return _call(
        lambda: add_decision(
            db, order_id, role=_role(auth, as_role), fio=auth.fio or "", fields=body.model_dump()
        )
    )


@router.post("/{order_id}/decisions/{decision_id}/close-conditions")
def post_close_conditions(
    order_id: str,
    decision_id: str,
    body: ConditionCloseIn,
    as_role: str = Query(default=""),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return _call(
        lambda: close_conditions(
            db,
            order_id,
            decision_id,
            role=_role(auth, as_role),
            fio=auth.fio or "",
            document_id=body.document_id,
        )
    )


@router.post("/{order_id}/documents")
def post_document(
    order_id: str,
    body: DocumentIn,
    as_role: str = Query(default=""),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return _call(
        lambda: add_document(
            db, order_id, role=_role(auth, as_role), fio=auth.fio or "", fields=body.model_dump()
        )
    )


@router.post("/{order_id}/files")
def post_file(
    order_id: str,
    body: FileIn,
    as_role: str = Query(default=""),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return _call(
        lambda: upload_order_file(
            db, order_id, role=_role(auth, as_role), fio=auth.fio or "", fields=body.model_dump()
        )
    )


@router.post("/{order_id}/files/{document_id}/approve")
def post_approve_file(
    order_id: str,
    document_id: str,
    as_role: str = Query(default=""),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return _call(
        lambda: approve_order_file(
            db, order_id, document_id, role=_role(auth, as_role), fio=auth.fio or ""
        )
    )


@router.delete("/{order_id}/files/{document_id}")
def delete_file(
    order_id: str,
    document_id: str,
    as_role: str = Query(default=""),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return _call(
        lambda: delete_order_file(
            db, order_id, document_id, role=_role(auth, as_role), fio=auth.fio or ""
        )
    )


@router.post("/{order_id}/baselines")
def post_baseline(
    order_id: str,
    body: BaselineIn,
    as_role: str = Query(default=""),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return _call(
        lambda: add_baseline(
            db, order_id, role=_role(auth, as_role), fio=auth.fio or "", fields=body.model_dump()
        )
    )


@router.post("/{order_id}/plan")
def post_plan(
    order_id: str,
    as_role: str = Query(default=""),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return _call(lambda: make_plan(db, order_id, role=_role(auth, as_role), fio=auth.fio or ""))


@router.post("/{order_id}/plan/approve")
def post_plan_approve(
    order_id: str,
    as_role: str = Query(default=""),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return _call(lambda: accept_plan(db, order_id, role=_role(auth, as_role), fio=auth.fio or ""))


@router.post("/{order_id}/plan/publish")
def post_plan_publish(
    order_id: str,
    as_role: str = Query(default=""),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return _call(
        lambda: publish_order_plan(db, order_id, role=_role(auth, as_role), fio=auth.fio or "")
    )


@router.post("/{order_id}/onec")
def post_onec(
    order_id: str,
    body: OnecLinkIn,
    as_role: str = Query(default=""),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return _call(
        lambda: link_onec(
            db,
            order_id,
            role=_role(auth, as_role),
            fio=auth.fio or "",
            ref_key=body.ref_key,
        )
    )


@router.post("/{order_id}/onec/refresh")
def post_onec_refresh(
    order_id: str,
    as_role: str = Query(default=""),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return _call(
        lambda: refresh_onec(
            db,
            order_id,
            role=_role(auth, as_role),
            fio=auth.fio or "",
        )
    )


@router.post("/{order_id}/findings/{finding_id}/accept")
def post_accept(
    order_id: str,
    finding_id: str,
    as_role: str = Query(default=""),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return _call(
        lambda: accept_finding(
            db, order_id, finding_id, role=_role(auth, as_role), fio=auth.fio or ""
        )
    )
