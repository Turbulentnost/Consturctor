"""Fetch last-week 1C assignments via platform-tool-onec-com module and HTTP tool."""
from __future__ import annotations

import json
import os
import random
import sys
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "platform-tool-onec-com"))

env: dict[str, str] = {}
for line in (ROOT / "infra" / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, _, v = line.partition("=")
    env[k.strip()] = v.strip().strip('"').strip("'")
for k, v in env.items():
    os.environ[k] = v

from platform_tool_onec_com.onec_com import (  # noqa: E402
    connect_session,
    get_task_details,
    query_tasks_period,
)


def last_week_iso() -> tuple[str, str]:
    today = date.today()
    week_start = today - timedelta(days=today.weekday() + 7)
    week_end = week_start + timedelta(days=7)
    return week_start.isoformat(), week_end.isoformat()


def http_tool(tool: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"http://127.0.0.1:7831/api/v1/tools/{tool}/invoke",
        data=json.dumps({"run_id": "fetch-porucheniya", "payload": payload}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        body = json.loads(resp.read())
    return body.get("data") or {}


def main() -> int:
    date_from, date_to = last_week_iso()
    print(f"=== Поручения за прошлую неделю: {date_from} — {date_to} ===")

    session = connect_session()
    app = session["object"]
    user = session["current_user"]
    print("Пользователь:", user)

    mine = query_tasks_period(app, date_from=date_from, date_to=date_to, mine_only=True, limit=100)
    all_rows = query_tasks_period(app, date_from=date_from, date_to=date_to, mine_only=False, limit=100)
    rows = mine if mine else all_rows
    scope = "мои" if mine else "все доступные"
    print(f"Найдено ({scope}): {len(rows)}")

    if not rows:
        print("Нет задач за период.")
        return 1

    for i, row in enumerate(rows[:15], 1):
        att_n = len(row.get("attachments") or [])
        subj = row.get("subject") or {}
        subj_hint = f" | предмет: {subj.get('type', '')} {subj.get('номер', subj.get('number', ''))}" if subj else ""
        print(
            f"  {i:2}. {row['number']} | {row['date'][:16]} | {row['description'][:65]}"
            f"{subj_hint} | вложений: {att_n}"
        )

    # Prefer tasks with attachments, else random
    with_files = [r for r in rows if r.get("attachments")]
    sample = with_files[:3] if with_files else (rows if len(rows) <= 3 else random.sample(rows, 3))
    if len(with_files) < 3 and len(sample) < 3:
        rest = [r for r in rows if r not in sample]
        sample.extend(random.sample(rest, min(3 - len(sample), len(rest))))

    print(f"\n=== Детали по {len(sample)} поручениям ===")
    report: list[dict] = []
    for idx, row in enumerate(sample[:3], 1):
        details = get_task_details(app, number=row["number"])
        merged = {**row, **details}
        report.append(merged)
        print(f"\n--- #{idx}: {row['number']} ---")
        print("  Задача:", row.get("description", ""))
        print("  Дата:", row.get("date", ""), "| Срок:", row.get("due_date", ""))
        print("  Автор:", row.get("author", ""), "| Исполнитель:", row.get("executor", ""))
        print("  Статус:", "выполнена" if str(row.get("done")).lower() in {"true", "истина", "1"} else "открыта")
        if row.get("result"):
            print("  Результат:", row["result"])
        subj = details.get("subject") or row.get("subject") or {}
        if subj:
            print(
                "  Предмет:",
                subj.get("type", ""),
                subj.get("номер", subj.get("number", "")),
                subj.get("наименование", subj.get("description", ""))[:120],
            )
        atts = details.get("attachments") or row.get("attachments") or []
        print(f"  Вложения ({len(atts)}):")
        for att in atts:
            name = att.get("name", "")
            ext = att.get("extension", "")
            size = att.get("size", "")
            print(f"    • {name}.{ext} — {size} байт")
            if att.get("description"):
                print(f"      описание: {att['description'][:200]}")
            if att.get("created"):
                print(f"      создан: {att['created'][:19]}")
            if att.get("storage_type"):
                print(f"      хранение: {att['storage_type']}")

    # HTTP tool smoke
    print("\n=== HTTP tool onec.com.query_assignments ===")
    try:
        http_data = http_tool(
            "onec.com.query_assignments",
            {"date_from": date_from, "date_to": date_to, "mine_only": False, "limit": 5},
        )
        print(http_data.get("summary"), "count=", http_data.get("count"))
    except Exception as exc:
        print("HTTP tool failed:", exc)

    out = ROOT / "logs" / "porucheniya_last_week.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nОтчёт: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
