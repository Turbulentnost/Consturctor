"""Seed demo agent cards and KPI history for folder-tab UI comparison."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, text

TASKS = [
    {
        "task_id": "parse_regulation",
        "title": "Извлечение процесса из регламента",
        "description": "Разобрать регламент на шаги, роли и контрольные точки",
        "evaluation_criteria": {"requires_steps": True, "requires_roles": True},
        "kpi_tags": ["accuracy", "completeness"],
    },
    {
        "task_id": "match_roles",
        "title": "Сопоставление ролей с ERP",
        "description": "Связать роли из регламента с должностями 1С",
        "evaluation_criteria": {"requires_erp_mapping": True},
        "kpi_tags": ["accuracy"],
    },
    {
        "task_id": "finalize_agent",
        "title": "Финализация карточки агента",
        "description": "Собрать черновик агента и KPI для публикации",
        "evaluation_criteria": {"requires_kpi_metrics": True, "requires_tasks": True},
        "kpi_tags": ["timeliness", "operator_keep"],
    },
]

KPI_METRICS = [
    {
        "metric_id": "task_success_rate",
        "title": "Доля успешно закрытых задач",
        "kind": "rate",
        "source": "agent_execution_history",
        "threshold_min": 0.85,
        "weight": 1.2,
    },
    {
        "metric_id": "avg_execution_duration_sec",
        "title": "Среднее время выполнения",
        "kind": "duration",
        "source": "agent_execution_history",
        "threshold_max": 7200.0,
        "weight": 1.0,
    },
]


@dataclass(frozen=True)
class DemoAgentSpec:
    agent_id: str
    title: str
    description: str
    history_count: int
    completion_rate: float
    avg_duration_min: int


DEMO_AGENTS: tuple[DemoAgentSpec, ...] = (
    DemoAgentSpec(
        agent_id="test-agent-zhalybin-maxim-v1",
        title="Агент 1: Жалыбин Максим",
        description="Тестовый агент конструктора — извлечение процесса и KPI.",
        history_count=50,
        completion_rate=0.90,
        avg_duration_min=95,
    ),
    DemoAgentSpec(
        agent_id="test-agent-demo-inbound-v1",
        title="Агент 2: Входящая почта",
        description="Демо-агент обработки входящей корреспонденции.",
        history_count=35,
        completion_rate=0.86,
        avg_duration_min=42,
    ),
    DemoAgentSpec(
        agent_id="test-agent-demo-mto-v1",
        title="Агент 3: Регламент МТО",
        description="Демо-агент разбора регламентов отдела МТО.",
        history_count=28,
        completion_rate=0.93,
        avg_duration_min=68,
    ),
    DemoAgentSpec(
        agent_id="test-agent-demo-analytics-v1",
        title="Агент 4: Аналитика KPI",
        description="Демо-агент сбора и визуализации KPI-метрик.",
        history_count=22,
        completion_rate=0.77,
        avg_duration_min=55,
    ),
)


def resolve_database_url(explicit: str | None) -> str:
    if explicit:
        return explicit
    env_path = Path(__file__).resolve().parents[1] / "backend" / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://constructor:constructor@127.0.0.1:5432/constructor",
    )


def _seed_execution_history(
    conn,
    *,
    agent_id: str,
    now: datetime,
    count: int,
    completion_rate: float,
    avg_duration_min: int,
) -> tuple[int, int]:
    conn.execute(
        text("DELETE FROM kpi.agent_execution_history WHERE agent_id = :agent_id"),
        {"agent_id": agent_id},
    )
    completed_target = max(0, min(count, int(round(count * completion_rate))))
    incomplete_slots = {count} if count > 0 else set()
    if completed_target < count:
        incomplete_slots.add(max(1, count // 2))

    completed_count = 0
    for process_seq in range(1, count + 1):
        hours_ago = int((count - process_seq) * (24 * 14 / max(count, 1)))
        is_completed = process_seq not in incomplete_slots and completed_count < completed_target
        duration_min = max(
            15,
            avg_duration_min + ((process_seq * 11) % 40) - 20,
        ) if is_completed else 0
        started_at = now - timedelta(hours=hours_ago)
        completed_at = (
            started_at + timedelta(minutes=duration_min)
            if is_completed and duration_min > 0
            else None
        )
        if is_completed:
            completed_count += 1
        conn.execute(
            text(
                """
                INSERT INTO kpi.agent_execution_history (
                    id, agent_id, process_seq, started_at, completed_at,
                    is_started, is_completed
                ) VALUES (
                    :id, :agent_id, :process_seq, :started_at, :completed_at,
                    :is_started, :is_completed
                )
                """
            ),
            {
                "id": uuid.uuid4(),
                "agent_id": agent_id,
                "process_seq": process_seq,
                "started_at": started_at,
                "completed_at": completed_at,
                "is_started": True,
                "is_completed": is_completed,
            },
        )
    return count, completed_count


def _upsert_agent_card(conn, spec: DemoAgentSpec) -> None:
    conn.execute(
        text(
            """
            INSERT INTO platform_core.agent_cards (
                agent_id, title, version, description, department,
                tasks_json, kpi_metrics_json, interaction_mode, enabled
            ) VALUES (
                :agent_id, :title, '1.0', :description, '',
                :tasks_json, :kpi_metrics_json, 'pull', TRUE
            )
            ON CONFLICT (agent_id) DO UPDATE SET
                title = EXCLUDED.title,
                description = EXCLUDED.description,
                tasks_json = EXCLUDED.tasks_json,
                kpi_metrics_json = EXCLUDED.kpi_metrics_json,
                enabled = TRUE,
                updated_at = NOW()
            """
        ),
        {
            "agent_id": spec.agent_id,
            "title": spec.title,
            "description": spec.description,
            "tasks_json": json.dumps(TASKS, ensure_ascii=False),
            "kpi_metrics_json": json.dumps(KPI_METRICS, ensure_ascii=False),
        },
    )


def seed(database_url: str) -> None:
    engine = create_engine(database_url)
    now = datetime.now(timezone.utc)

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE platform_core.agent_cards
                SET enabled = FALSE, updated_at = NOW()
                WHERE agent_id = 'inbound-mail-v1'
                """
            )
        )

        for spec in DEMO_AGENTS:
            _upsert_agent_card(conn, spec)
            conn.execute(
                text("DELETE FROM kpi.agent_task_reports WHERE agent_id = :agent_id"),
                {"agent_id": spec.agent_id},
            )
            total, completed = _seed_execution_history(
                conn,
                agent_id=spec.agent_id,
                now=now,
                count=spec.history_count,
                completion_rate=spec.completion_rate,
                avg_duration_min=spec.avg_duration_min,
            )
            rate = completed / total if total else 0.0
            print(f"Seeded {spec.agent_id}")
            print(f"  title: {spec.title}")
            print(f"  history: {total} rows ({completed} completed, {rate:.0%})")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed 4 demo KPI agents for UI comparison")
    parser.add_argument(
        "--database-url",
        default=None,
        help="Postgres URL (default: DATABASE_URL from backend/.env)",
    )
    args = parser.parse_args()
    database_url = resolve_database_url(args.database_url)
    try:
        seed(database_url)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"\nDone: {len(DEMO_AGENTS)} demo agents ready for KPI folder UI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
