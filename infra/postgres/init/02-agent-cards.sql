-- Agent cards: business tasks and KPI (separate from platform tool inventory)

CREATE TABLE IF NOT EXISTS platform_core.agent_cards (
    agent_id VARCHAR(128) PRIMARY KEY,
    title VARCHAR(256) NOT NULL,
    version VARCHAR(32) NOT NULL DEFAULT '1.0',
    description TEXT NOT NULL DEFAULT '',
    department VARCHAR(256) NOT NULL DEFAULT '',
    tasks_json TEXT NOT NULL DEFAULT '[]',
    kpi_metrics_json TEXT NOT NULL DEFAULT '[]',
    interaction_mode VARCHAR(32) NOT NULL DEFAULT 'pull',
    callback_url VARCHAR(512),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS platform_core.agent_sessions (
    id UUID PRIMARY KEY,
    agent_id VARCHAR(128) NOT NULL REFERENCES platform_core.agent_cards(agent_id),
    external_session_id VARCHAR(256) NOT NULL DEFAULT '',
    user_id VARCHAR(64) NOT NULL DEFAULT '',
    department VARCHAR(256) NOT NULL DEFAULT '',
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    context_json TEXT NOT NULL DEFAULT '{}',
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_agent_sessions_agent_id ON platform_core.agent_sessions (agent_id);

-- Agent work reports: what the agent did and how well (KPI input)
CREATE TABLE IF NOT EXISTS kpi.agent_task_reports (
    id UUID PRIMARY KEY,
    agent_id VARCHAR(128) NOT NULL,
    session_id UUID,
    run_id UUID,
    task_id VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL,
    quality_score DOUBLE PRECISION,
    summary TEXT NOT NULL DEFAULT '',
    outcome_json TEXT NOT NULL DEFAULT '{}',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_task_reports_agent_id ON kpi.agent_task_reports (agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_task_reports_task_id ON kpi.agent_task_reports (task_id);
CREATE INDEX IF NOT EXISTS idx_agent_task_reports_created_at ON kpi.agent_task_reports (created_at);

-- Example: inbound correspondence agent
-- Tasks = business work. Tools = separate platform inventory (tool_registry + ACL by department).
INSERT INTO platform_core.agent_cards (
    agent_id, title, version, description, department,
    tasks_json, kpi_metrics_json, interaction_mode
) VALUES (
    'inbound-mail-v1',
    'Входящая корреспонденция',
    '1.0',
    'Агент на отдельном сервере обрабатывает входящую почту. Платформа оценивает результат работы; tools — вспомогательный слой.',
    'Отдел МТО',
    '[
      {
        "task_id": "classify_incoming",
        "title": "Классификация входящего документа",
        "description": "Определить тип, срочность, ответственное подразделение",
        "evaluation_criteria": {"requires_category": true, "requires_department": true},
        "kpi_tags": ["accuracy", "completeness"]
      },
      {
        "task_id": "register_document",
        "title": "Регистрация документа",
        "description": "Создать карточку входящего документа с корректными реквизитами",
        "evaluation_criteria": {"requires_document_number": true, "requires_attachments_linked": true},
        "kpi_tags": ["accuracy", "operator_keep"]
      },
      {
        "task_id": "route_for_review",
        "title": "Маршрутизация на согласование",
        "description": "Направить документ нужным исполнителям",
        "evaluation_criteria": {"requires_assignees": true},
        "kpi_tags": ["timeliness"]
      }
    ]',
    '[
      {"metric_id": "task_success_rate", "title": "Доля успешно закрытых задач", "kind": "rate", "source": "agent_task_reports", "threshold_min": 0.9, "weight": 1.0},
      {"metric_id": "avg_quality_score", "title": "Средняя оценка качества", "kind": "score", "source": "agent_task_reports", "threshold_min": 0.8, "weight": 1.5},
      {"metric_id": "operator_keep_rate", "title": "Оператор принял без правок", "kind": "rate", "source": "review_events", "threshold_min": 0.85, "weight": 2.0, "task_ids": ["register_document"]}
    ]',
    'pull'
) ON CONFLICT (agent_id) DO NOTHING;
