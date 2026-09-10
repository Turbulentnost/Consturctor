from datetime import datetime, timezone, timedelta
import json
import time
from app.db.session import SessionLocal
from app.models.workflow import Workflow

USER = "82FBCC3C4322D93A44439708C0DDC7B5"
since = datetime.now(timezone.utc) - timedelta(hours=2)
seen = {}
print("WATCH_START", flush=True)
for _ in range(90):
    db = SessionLocal()
    try:
        rows = (
            db.query(Workflow)
            .filter(Workflow.user_id == USER, Workflow.updated_at >= since)
            .order_by(Workflow.updated_at.desc())
            .limit(8)
            .all()
        )
        for row in rows:
            local = row.local_run if isinstance(row.local_run, dict) else {}
            recipe = local.get("write_recipe") if isinstance(local.get("write_recipe"), dict) else {}
            stamp = f"{row.updated_at.isoformat()}|{row.phase}|{local.get('demo_ok')}|{bool(recipe)}|{recipe.get('ok')}|{(recipe.get('summary') or '')[:80]}"
            if seen.get(row.id) != stamp:
                seen[row.id] = stamp
                print(
                    "WF",
                    row.id,
                    "phase="+str(row.phase),
                    "title="+(row.title or "")[:80],
                    "demo="+str(local.get("demo_ok")),
                    "recipe_ok="+str(recipe.get("ok")),
                    "recipe="+(str(recipe.get("summary") or "")[:120]),
                    "updated="+str(row.updated_at),
                    flush=True,
                )
    finally:
        db.close()
    time.sleep(4)
print("WATCH_END", flush=True)
