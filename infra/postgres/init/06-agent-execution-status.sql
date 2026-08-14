-- Execution outcome for completed KPI history rows (done | error; pending while in progress)

ALTER TABLE kpi.agent_execution_history
    ADD COLUMN IF NOT EXISTS status VARCHAR(32) NOT NULL DEFAULT 'pending';

UPDATE kpi.agent_execution_history
SET status = 'done'
WHERE is_completed = TRUE
  AND status = 'pending';

CREATE INDEX IF NOT EXISTS idx_agent_execution_history_status_completed
    ON kpi.agent_execution_history (status)
    WHERE is_completed = TRUE;
