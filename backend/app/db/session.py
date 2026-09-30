from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db.base import Base

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=40,
    pool_recycle=1800,
    pool_timeout=10,
    future=True,
    # Without a DB the OS TCP timeout (~2 min) would stall every DB-backed request.
    connect_args={"connect_timeout": 5} if settings.app_db_optional else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    # Import models so metadata is populated.
    from app.models import agent_run as _agent_run  # noqa: F401
    from app.models import calendar_overlay as _calendar_overlay  # noqa: F401
    from app.models import finance as _finance  # noqa: F401
    from app.models import notification as _notification  # noqa: F401
    from app.models import org as _org  # noqa: F401
    from app.models import orchestrator as _orchestrator  # noqa: F401
    from app.models import platform_task as _platform_task  # noqa: F401
    from app.models import regulation as _regulation  # noqa: F401
    from app.models import trigger as _trigger  # noqa: F401
    from app.models import user as _user  # noqa: F401
    from app.models import kpi_daily_metric as _kpi_daily_metric  # noqa: F401
    from app.models import position_kpi as _position_kpi  # noqa: F401
    from app.models import workflow as _workflow  # noqa: F401
    from app.modules.chat import models as _chat  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_columns()
    _ensure_indexes()
    _seed_position_kpi()


def _seed_position_kpi() -> None:
    from kpi.seed_pl_npo_010 import upsert_catalog

    db = SessionLocal()
    try:
        upsert_catalog(db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# create_all() only adds indexes together with a new table, so existing
# deployments need them created explicitly.
_HOT_PATH_INDEXES = (
    ("ix_agent_runs_user_wf_started", "agent_runs", "(user_id, workflow_id, started_at DESC)"),
    ("ix_agent_runs_user_status", "agent_runs", "(user_id, status)"),
    ("ix_workflows_user_phase_updated", "workflows", "(user_id, phase, updated_at DESC)"),
    ("ix_agent_triggers_owner_wf", "agent_triggers", "(owner_user_id, workflow_id)"),
)


def _ensure_indexes() -> None:
    for name, table, columns in _HOT_PATH_INDEXES:
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} {columns}")
                )
        except Exception:  # noqa: BLE001
            # A missing table or a concurrent creation must not block startup.
            continue


def _ensure_columns() -> None:
    """Add new columns to existing tables without a full migration tool.

    Shared DB (constructor @ 192.168.1.157:5435) may already have a `users` table
    from AIConstructor with a different shape (e.g. avatar_key instead of avatar_path).
    """
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'users'
                """
            )
        ).fetchall()
        existing = {str(r[0]) for r in rows}
        alters: list[str] = []
        if "department_changed_at" not in existing:
            alters.append("ADD COLUMN department_changed_at TIMESTAMPTZ NULL")
        if "position" not in existing:
            alters.append("ADD COLUMN position VARCHAR(512) NOT NULL DEFAULT ''")
        if "avatar_path" not in existing:
            alters.append("ADD COLUMN avatar_path VARCHAR(1024) NULL")
        if "updated_at" not in existing:
            alters.append(
                "ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
            )
        if "department" not in existing:
            alters.append("ADD COLUMN department VARCHAR(512) NOT NULL DEFAULT ''")
        if "activity_status" not in existing:
            alters.append("ADD COLUMN activity_status VARCHAR(16) NOT NULL DEFAULT 'online'")
        if "is_support" not in existing:
            alters.append("ADD COLUMN is_support BOOLEAN NOT NULL DEFAULT FALSE")
        if "onec_catalog_ref_key" not in existing:
            alters.append("ADD COLUMN onec_catalog_ref_key VARCHAR(36) NOT NULL DEFAULT ''")
        if existing and "fio" not in existing:
            alters.append("ADD COLUMN fio VARCHAR(512) NOT NULL DEFAULT ''")
        if existing:
            for clause in alters:
                conn.execute(text(f"ALTER TABLE users {clause}"))
        trigger_rows = conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'agent_triggers'
                """
            )
        ).fetchall()
        trigger_cols = {str(r[0]) for r in trigger_rows}
        org_member_rows = conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'org_members'
                """
            )
        ).fetchall()
        org_member_cols = {str(r[0]) for r in org_member_rows}
        if org_member_cols and "position_id" not in org_member_cols:
            conn.execute(
                text(
                    "ALTER TABLE org_members ADD COLUMN position_id VARCHAR(64) NULL "
                    "REFERENCES org_positions(id)"
                )
            )
        if org_member_cols and "person_id" not in org_member_cols:
            conn.execute(text("ALTER TABLE org_members ADD COLUMN person_id VARCHAR(64) NULL"))
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_org_members_person_id "
                    "ON org_members (person_id)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_org_members_position_id "
                    "ON org_members (position_id)"
                )
            )
        if trigger_cols and "interval_seconds" not in trigger_cols:
            conn.execute(
                text(
                    "ALTER TABLE agent_triggers "
                    "ADD COLUMN interval_seconds INTEGER NOT NULL DEFAULT 0"
                )
            )
        if trigger_cols and "active_days" not in trigger_cols:
            conn.execute(
                text(
                    "ALTER TABLE agent_triggers "
                    "ADD COLUMN active_days VARCHAR(32) NOT NULL DEFAULT ''"
                )
            )
        if trigger_cols and "window_start_min" not in trigger_cols:
            conn.execute(
                text("ALTER TABLE agent_triggers ADD COLUMN window_start_min INTEGER NULL")
            )
        if trigger_cols and "window_end_min" not in trigger_cols:
            conn.execute(
                text("ALTER TABLE agent_triggers ADD COLUMN window_end_min INTEGER NULL")
            )
        if trigger_cols and "skipped_slots" not in trigger_cols:
            conn.execute(
                text(
                    "ALTER TABLE agent_triggers "
                    "ADD COLUMN skipped_slots JSON NOT NULL DEFAULT '[]'"
                )
            )
        notif_rows = conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'notifications'
                """
            )
        ).fetchall()
        notif_cols = {str(r[0]) for r in notif_rows}
        if notif_cols and "read_at" not in notif_cols:
            conn.execute(text("ALTER TABLE notifications ADD COLUMN read_at TIMESTAMPTZ NULL"))
        if notif_cols and "run_id" not in notif_cols:
            conn.execute(
                text("ALTER TABLE notifications ADD COLUMN run_id VARCHAR(64) NOT NULL DEFAULT ''")
            )
        run_rows = conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'agent_runs'
                """
            )
        ).fetchall()
        run_cols = {str(r[0]) for r in run_rows}
        if run_cols and "events_json" not in run_cols:
            conn.execute(
                text("ALTER TABLE agent_runs ADD COLUMN events_json JSON NOT NULL DEFAULT '[]'")
            )
        if run_cols and "trigger_id" not in run_cols:
            conn.execute(
                text("ALTER TABLE agent_runs ADD COLUMN trigger_id VARCHAR(64) NOT NULL DEFAULT ''")
            )
        if run_cols and "trigger_kind" not in run_cols:
            conn.execute(
                text("ALTER TABLE agent_runs ADD COLUMN trigger_kind VARCHAR(32) NOT NULL DEFAULT ''")
            )
        if run_cols and "trigger_reason" not in run_cols:
            conn.execute(
                text("ALTER TABLE agent_runs ADD COLUMN trigger_reason TEXT NOT NULL DEFAULT ''")
            )
        creation_rows = conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'regulation_creation_drafts'
                """
            )
        ).fetchall()
        ptask_rows = conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'platform_tasks'
                """
            )
        ).fetchall()
        ptask_cols = {str(r[0]) for r in ptask_rows}
        if ptask_cols and "review_due_at" not in ptask_cols:
            conn.execute(text("ALTER TABLE platform_tasks ADD COLUMN review_due_at TIMESTAMPTZ NULL"))
        if ptask_cols and "accepted_at" not in ptask_cols:
            conn.execute(text("ALTER TABLE platform_tasks ADD COLUMN accepted_at TIMESTAMPTZ NULL"))
        if ptask_cols and "rework_count" not in ptask_cols:
            conn.execute(
                text("ALTER TABLE platform_tasks ADD COLUMN rework_count INTEGER NOT NULL DEFAULT 0")
            )
        kpi_profile_rows = conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'position_kpi_profiles'
                """
            )
        ).fetchall()
        kpi_profile_cols = {str(r[0]) for r in kpi_profile_rows}
        if kpi_profile_cols and "effective_to" not in kpi_profile_cols:
            conn.execute(
                text("ALTER TABLE position_kpi_profiles ADD COLUMN effective_to DATE NULL")
            )
        if kpi_profile_cols and "source_import_id" not in kpi_profile_cols:
            conn.execute(
                text(
                    "ALTER TABLE position_kpi_profiles "
                    "ADD COLUMN source_import_id VARCHAR(64) NOT NULL DEFAULT ''"
                )
            )
        if kpi_profile_cols:
            conn.execute(
                text(
                    "ALTER TABLE position_kpi_profiles "
                    "DROP CONSTRAINT IF EXISTS position_kpi_profiles_position_name_key"
                )
            )
            conn.execute(text("DROP INDEX IF EXISTS uq_position_kpi_profiles_name_effective"))
            # Old schema had unique=True on position_name; versions per department/date need duplicates.
            is_unique_name_index = conn.execute(
                text(
                    "SELECT 1 FROM pg_indexes WHERE tablename = 'position_kpi_profiles' "
                    "AND indexname = 'ix_position_kpi_profiles_position_name' "
                    "AND indexdef LIKE 'CREATE UNIQUE INDEX%'"
                )
            ).first()
            if is_unique_name_index:
                conn.execute(text("DROP INDEX ix_position_kpi_profiles_position_name"))
                conn.execute(
                    text(
                        "CREATE INDEX ix_position_kpi_profiles_position_name "
                        "ON position_kpi_profiles (position_name)"
                    )
                )
            conn.execute(
                text(
                    "ALTER TABLE position_kpi_profiles "
                    "DROP CONSTRAINT IF EXISTS uq_position_kpi_profiles_name_effective"
                )
            )
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_position_kpi_profiles_name_dept_effective "
                    "ON position_kpi_profiles (position_name, department, effective_from)"
                )
            )
        salary_rows = conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'finance_salary_entries'
                """
            )
        ).fetchall()
        salary_cols = {str(r[0]) for r in salary_rows}
        if salary_cols and "department" not in salary_cols:
            conn.execute(
                text(
                    "ALTER TABLE finance_salary_entries "
                    "ADD COLUMN department VARCHAR(512) NOT NULL DEFAULT ''"
                )
            )
        if salary_cols and "position_id" not in salary_cols:
            conn.execute(
                text(
                    "ALTER TABLE finance_salary_entries "
                    "ADD COLUMN position_id VARCHAR(64) NULL REFERENCES org_positions(id)"
                )
            )
            conn.execute(
                text(
                    "UPDATE finance_salary_entries salary "
                    "SET position_id = person.position_id "
                    "FROM org_people person "
                    "WHERE salary.person_id = person.id AND salary.position_id IS NULL"
                )
            )
        if salary_cols:
            conn.execute(
                text(
                    "ALTER TABLE finance_salary_entries "
                    "DROP CONSTRAINT IF EXISTS uq_finance_salary_person_date_revision"
                )
            )
            if "person_id" in salary_cols:
                conn.execute(
                    text(
                        "ALTER TABLE finance_salary_entries "
                        "ALTER COLUMN person_id DROP NOT NULL"
                    )
                )
            if "fio_snapshot" in salary_cols:
                conn.execute(
                    text(
                        "ALTER TABLE finance_salary_entries "
                        "ALTER COLUMN fio_snapshot DROP NOT NULL"
                    )
                )
            conn.execute(
                text(
                    "ALTER TABLE finance_salary_entries "
                    "DROP CONSTRAINT IF EXISTS uq_finance_salary_position_date_revision"
                )
            )
            conn.execute(text("DROP INDEX IF EXISTS uq_finance_salary_position_date_revision"))
            conn.execute(
                text(
                    """
                    WITH ranked AS (
                        SELECT
                            id,
                            ROW_NUMBER() OVER (
                                PARTITION BY position_id, department, effective_from
                                ORDER BY created_at, id
                            ) AS new_revision,
                            ROW_NUMBER() OVER (
                                PARTITION BY position_id, department, effective_from
                                ORDER BY created_at DESC, id DESC
                            ) AS newest
                        FROM finance_salary_entries
                        WHERE position_id IS NOT NULL
                    )
                    UPDATE finance_salary_entries salary
                    SET revision = ranked.new_revision,
                        is_current = (ranked.newest = 1)
                    FROM ranked
                    WHERE salary.id = ranked.id
                    """
                )
            )
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "uq_finance_salary_position_dept_date_revision "
                    "ON finance_salary_entries (position_id, department, effective_from, revision)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_finance_salary_entries_position_id "
                    "ON finance_salary_entries (position_id)"
                )
            )
        creation_cols = {str(r[0]) for r in creation_rows}
        if creation_cols and "interview_json" not in creation_cols:
            conn.execute(
                text(
                    "ALTER TABLE regulation_creation_drafts "
                    "ADD COLUMN interview_json JSON NOT NULL DEFAULT '{}'"
                )
            )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
