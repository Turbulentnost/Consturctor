from __future__ import annotations

from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models.agent_run import AgentRun
from app.models.user import AppUser
from app.models.workflow import Workflow
from app.schemas.admin import AdminFilterOut, AdminUserRowOut, AdminUsersOut
from app.services.admin import stub_payloads
from app.services.admin_access import admin_user_ids
from app.services.triggers.service import workflow_is_deleted

_MOSCOW = ZoneInfo("Europe/Moscow")
_PAGE_SIZE = 5


def _format_activity(dt) -> str:
    if dt is None:
        return "—"
    local = dt.astimezone(_MOSCOW) if dt.tzinfo else dt.replace(tzinfo=_MOSCOW)
    return local.strftime("%d.%m.%Y %H:%M")


def _activity_label(status: str) -> str:
    key = (status or "").casefold()
    if key in {"online", "away"}:
        return "Активен"
    if key == "offline":
        return "Не в сети"
    return "Активен"


def build_admin_users() -> AdminUsersOut:
    stub = stub_payloads.stub_users()
    with SessionLocal() as db:
        total = int(db.scalar(select(func.count()).select_from(AppUser)) or 0)
        if total == 0:
            return AdminUsersOut(
                source="admin_api",
                breadcrumb=str(stub["breadcrumb"]),
                title=str(stub["title"]),
                subtitle=str(stub["subtitle"]),
                add_label=str(stub["addLabel"]),
                filters=[
                    AdminFilterOut(id="department", options=["Все подразделения"]),
                    AdminFilterOut(id="role", options=["Все роли", "Администратор", "Пользователь"]),
                    AdminFilterOut(id="status", options=["Все статусы", "Активен", "Не в сети"]),
                ],
                rows=[],
                pagination={"pageSize": _PAGE_SIZE, "total": 0},
            )
        users = (
            db.execute(select(AppUser).order_by(AppUser.fio.asc()).limit(500))
            .scalars()
            .all()
        )
        workflows = db.execute(
            select(Workflow.user_id, Workflow.local_run, Workflow.phase)
        ).all()
        used_pairs = db.execute(select(AgentRun.user_id, AgentRun.workflow_id).distinct()).all()
        administrator_ids = admin_user_ids(db)

    access: dict[str, int] = {}
    for user_id, local_run, phase in workflows:
        class _Row:
            pass

        row = _Row()
        row.local_run = local_run
        row.phase = phase
        if workflow_is_deleted(row):
            continue
        access[str(user_id)] = access.get(str(user_id), 0) + 1
    used: dict[str, set[str]] = {}
    for user_id, workflow_id in used_pairs:
        used.setdefault(str(user_id), set()).add(str(workflow_id))

    departments = sorted({(u.department or "").strip() for u in users if (u.department or "").strip()})
    dept_options = ["Все подразделения", *departments[:20]]
    rows = [
        AdminUserRowOut(
            fio=user.fio or "—",
            position=user.position or "—",
            department=user.department or "—",
            role="Администратор" if user.id in administrator_ids else "Пользователь",
            status=_activity_label(user.activity_status),
            agents_access=access.get(user.id, 0),
            agents_used=len(used.get(user.id, set())),
            last_activity=_format_activity(user.updated_at),
        )
        for user in users
    ]

    return AdminUsersOut(
        source="admin_api",
        breadcrumb=str(stub["breadcrumb"]),
        title=str(stub["title"]),
        subtitle=str(stub["subtitle"]),
        add_label=str(stub["addLabel"]),
        filters=[
            AdminFilterOut(id="department", options=dept_options),
            AdminFilterOut(
                id="role",
                options=["Все роли", "Администратор", "Пользователь"],
            ),
            AdminFilterOut(
                id="status",
                options=["Все статусы", "Активен", "Не в сети"],
            ),
        ],
        rows=rows,
        pagination={"pageSize": _PAGE_SIZE, "total": total},
    )
