-- Agent process execution history (KPI input for completed tasks and avg duration)

CREATE TABLE IF NOT EXISTS kpi.agent_execution_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id VARCHAR(128) NOT NULL,
    process_seq INTEGER NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    is_started BOOLEAN NOT NULL DEFAULT FALSE,
    is_completed BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT uq_agent_execution_history_agent_seq UNIQUE (agent_id, process_seq)
);

CREATE INDEX IF NOT EXISTS idx_agent_execution_history_agent_id
    ON kpi.agent_execution_history (agent_id);

CREATE INDEX IF NOT EXISTS idx_agent_execution_history_started_at
    ON kpi.agent_execution_history (started_at);

CREATE INDEX IF NOT EXISTS idx_agent_execution_history_completed_at
    ON kpi.agent_execution_history (completed_at)
    WHERE is_completed = TRUE;
