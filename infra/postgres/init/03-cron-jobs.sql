-- User-defined cron jobs (scheduled tool chains)

CREATE TABLE IF NOT EXISTS platform_core.scheduled_jobs (
    id UUID PRIMARY KEY,
    name VARCHAR(256) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    template_id VARCHAR(64) NOT NULL DEFAULT 'custom',
    agent_id VARCHAR(128) NOT NULL,
    user_id VARCHAR(64) NOT NULL DEFAULT '',
    department VARCHAR(256) NOT NULL DEFAULT '',
    cron_expr VARCHAR(128) NOT NULL,
    timezone VARCHAR(64) NOT NULL DEFAULT 'Europe/Moscow',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    config_json TEXT NOT NULL DEFAULT '{}',
    last_run_at TIMESTAMPTZ,
    last_run_id UUID,
    next_run_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_enabled_next
    ON platform_core.scheduled_jobs (enabled, next_run_at);
CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_user_id
    ON platform_core.scheduled_jobs (user_id);
