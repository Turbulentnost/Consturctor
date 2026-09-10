from sqlalchemy import create_engine, text

from app.config import settings

eng = create_engine(settings.database_url)
with eng.connect() as conn:
    print("=== open runs ===")
    for row in conn.execute(
        text(
            """
            SELECT id, workflow_id, status, started_at, finished_at, left(message, 60)
            FROM agent_runs
            WHERE finished_at IS NULL OR status IN ('started', 'running')
            ORDER BY started_at DESC
            LIMIT 10
            """
        )
    ):
        print(row)

    print("\n=== daily control + studio local_run ===")
    for row in conn.execute(
        text(
            """
            SELECT id, title, updated_at,
                   local_run->>'status' AS lr_status,
                   local_run->>'tests_status' AS tests,
                   local_run->>'ui_mode' AS ui_mode,
                   left(local_run->>'work_result', 160) AS work_result
            FROM workflows
            WHERE title ILIKE '%поручен%' OR title ILIKE '%заседаний Совета%'
            ORDER BY updated_at DESC
            LIMIT 6
            """
        )
    ).mappings():
        print(dict(row))

    print("\n=== last events of daily control run ===")
    events = conn.execute(
        text("SELECT events_json FROM agent_runs WHERE id = 'd3fd52b7-dcfa-4c97-bfc3-a83d3114bba5'")
    ).scalar() or []
    print("count", len(events))
    for ev in events[-12:]:
        if isinstance(ev, dict):
            print(ev.get("type"), ev.get("tool"), str(ev.get("text") or ev.get("error") or ev.get("status") or "")[:120])
