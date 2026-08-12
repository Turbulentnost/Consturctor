-- Constructor platform: shared PostgreSQL schemas

CREATE SCHEMA IF NOT EXISTS platform_core;
CREATE SCHEMA IF NOT EXISTS kpi;
CREATE SCHEMA IF NOT EXISTS tools_audit;

-- Agent runs
CREATE TABLE IF NOT EXISTS platform_core.agent_runs (
    id UUID PRIMARY KEY,
    agent_id VARCHAR(128) NOT NULL,
    user_id VARCHAR(64) NOT NULL DEFAULT '',
    department VARCHAR(256) NOT NULL DEFAULT '',
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    config_json TEXT NOT NULL DEFAULT '{}',
    tools_json TEXT NOT NULL DEFAULT '[]',
    error_message TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_status ON platform_core.agent_runs (status);
CREATE INDEX IF NOT EXISTS idx_agent_runs_department ON platform_core.agent_runs (department);
CREATE INDEX IF NOT EXISTS idx_agent_runs_started_at ON platform_core.agent_runs (started_at);

-- Tool registry (manifest)
CREATE TABLE IF NOT EXISTS platform_core.tool_registry (
    name VARCHAR(128) PRIMARY KEY,
    service_url VARCHAR(512) NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    departments_json TEXT NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Append-only tool audit
CREATE TABLE IF NOT EXISTS tools_audit.tool_events (
    id UUID PRIMARY KEY,
    run_id UUID,
    tool_name VARCHAR(128) NOT NULL,
    department VARCHAR(256) NOT NULL DEFAULT '',
    user_id VARCHAR(64) NOT NULL DEFAULT '',
    input_hash VARCHAR(64) NOT NULL DEFAULT '',
    output_summary TEXT NOT NULL DEFAULT '',
    status VARCHAR(32) NOT NULL DEFAULT 'ok',
    error_message TEXT,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tool_events_run_id ON tools_audit.tool_events (run_id);
CREATE INDEX IF NOT EXISTS idx_tool_events_tool_name ON tools_audit.tool_events (tool_name);
CREATE INDEX IF NOT EXISTS idx_tool_events_created_at ON tools_audit.tool_events (created_at);

-- HITL review events (KPI)
CREATE TABLE IF NOT EXISTS kpi.review_events (
    id UUID PRIMARY KEY,
    run_id UUID,
    category VARCHAR(64) NOT NULL DEFAULT 'general',
    event_type VARCHAR(64) NOT NULL,
    actor VARCHAR(32) NOT NULL DEFAULT 'operator',
    source VARCHAR(128) NOT NULL DEFAULT 'api',
    department VARCHAR(256) NOT NULL DEFAULT '',
    old_value TEXT,
    new_value TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_review_events_created_at ON kpi.review_events (created_at);
CREATE INDEX IF NOT EXISTS idx_review_events_event_type ON kpi.review_events (event_type);
CREATE INDEX IF NOT EXISTS idx_review_events_department ON kpi.review_events (department);

-- Periodic KPI snapshots
CREATE TABLE IF NOT EXISTS kpi.kpi_snapshots (
    id UUID PRIMARY KEY,
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    department VARCHAR(256) NOT NULL DEFAULT '',
    metrics_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kpi_snapshots_period ON kpi.kpi_snapshots (period_start, period_end);

-- Seed default tools
INSERT INTO platform_core.tool_registry (name, service_url, description, departments_json)
VALUES
    ('imap.list_unread', '', 'List unread IMAP messages', '[]'),
    ('imap.fetch_message', '', 'Fetch and parse email message', '[]'),
    ('imap.fetch_attachments', '', 'Fetch email attachments', '[]'),
    ('imap.search', '', 'Search IMAP mailbox', '[]'),
    ('onec.odata_get', '', 'OData GET entity', '[]'),
    ('onec.odata_post', '', 'OData POST create document', '[]'),
    ('onec.odata_patch', '', 'OData PATCH update document', '[]'),
    ('onec.attach_file', '', 'Attach file to 1C document', '[]'),
    ('onec.sql_query', '', 'Read-only SQL SELECT', '[]'),
    ('shell.run', '', 'Run sandboxed shell command', '[]'),
    ('com.list_apps', '', 'List registered COM applications', '[]'),
    ('com.connect', '', 'Connect COM application session', '[]'),
    ('com.invoke', '', 'Invoke COM method on session', '[]'),
    ('com.release', '', 'Release COM session', '[]'),
    ('com.outlook.launch', '', 'Launch Outlook via COM', '[]'),
    ('com.outlook.close', '', 'Close Outlook COM session', '[]'),
    ('com.outlook.calendar_list', '', 'List Outlook calendar appointments', '[]'),
    ('com.outlook.calendar_get', '', 'Get Outlook appointment by EntryID', '[]'),
    ('fs.list', '', 'List files in allowed roots', '[]'),
    ('fs.read', '', 'Read file from allowed roots', '[]'),
    ('fs.write', '', 'Write file in allowed roots', '[]'),
    ('fs.stat', '', 'Stat file or directory', '[]'),
    ('fs.move', '', 'Move file within allowed roots', '[]'),
    ('fs.copy', '', 'Copy file within allowed roots', '[]'),
    ('browser.open_session', '', 'Open ephemeral browser session', '[]'),
    ('browser.close_session', '', 'Close ephemeral browser session', '[]'),
    ('browser.navigate', '', 'Navigate browser to URL', '[]'),
    ('browser.snapshot', '', 'Snapshot interactive page elements', '[]'),
    ('browser.click', '', 'Click element in browser', '[]'),
    ('browser.type', '', 'Type text into element', '[]'),
    ('browser.fill', '', 'Fill input element', '[]'),
    ('browser.wait', '', 'Wait for selector URL or timeout', '[]'),
    ('browser.tabs', '', 'List create or switch tabs', '[]'),
    ('browser.screenshot', '', 'Take browser screenshot', '[]'),
    ('browser.extract_text', '', 'Extract text from page', '[]')
ON CONFLICT (name) DO NOTHING;
