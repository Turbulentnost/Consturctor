#!/usr/bin/env python3
"""
Закрыть задачу 1С:Документооборот и проверить результат в базе ДО.

Пароль спрашивается в терминале и не попадает ни в аргументы, ни в отчёт.
Отчёт пишется в backend/storage/docflow_inbox/close_report.txt.

Пример:
  cd backend
  py -3 scripts/close_docflow_task.py 1d3729cc-b5b3-11f1-9889-6cb31113810c "Мангасарян Давид Карленович"
"""

from __future__ import annotations

import sys
from getpass import getpass
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.services.docflow_task_action import handle_docflow_task_action  # noqa: E402
from app.services.docflow_tasks import DocflowError  # noqa: E402
from app.tools.onec.dok_soap import (  # noqa: E402
    load_config,
    open_tasks_for_target,
    retrieve_task_card,
)

REPORT = BACKEND / "storage" / "docflow_inbox" / "close_report.txt"


def describe(card: dict[str, object]) -> str:
    return (
        f"  УИД: {card.get('id')}\n"
        f"  Задача: {card.get('name')}\n"
        f"  Шаг: {card.get('step')}\n"
        f"  Исполнитель: {card.get('performer')}\n"
        f"  Исполнена: {card.get('executed')}, пометка: {card.get('execution_mark') or '—'}\n"
        f"  Предмет: {card.get('target')} [{card.get('target_id')} / {card.get('target_type')}]"
    )


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if len(argv) < 2:
        print(__doc__)
        return 2
    task_id = argv[0].strip()
    fio = argv[1].strip()
    password = getpass(f"Пароль 1С для {fio}: ").strip()
    if not password:
        print("Пароль пустой", file=sys.stderr)
        return 2

    lines: list[str] = []

    def log(text: str) -> None:
        print(text)
        lines.append(text)

    config = load_config(username=fio, password=password, require_user=True)
    timeout = min(60.0, float(config.timeout))

    log(f"Задача из таблицы Оркестратора: {task_id}")
    card = retrieve_task_card(config, task_id, timeout=timeout)
    log("Состояние до закрытия:")
    log(describe(card))

    target_id = str(card.get("target_id") or "")
    target_type = str(card.get("target_type") or "")
    before = open_tasks_for_target(config, target_id, target_type, timeout=max(timeout, 120.0))
    log(f"Открытых задач по предмету до закрытия: {len(before)}")
    for row in before:
        log(f"  - {row['id']} | {row['step']} | {row['performer']} | {row['description'][:60]}")

    try:
        result = handle_docflow_task_action(
            {"action": "close", "task_id": task_id, "fio": fio, "erp_password": password}
        )
    except DocflowError as exc:
        log(f"ЗАКРЫТИЕ НЕ ПРОШЛО: {exc}")
        REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return 1
    log(f"Ответ закрытия: {result.get('summary')} (закрыто: {result.get('closed_task_ids')})")

    after = open_tasks_for_target(config, target_id, target_type, timeout=max(timeout, 120.0))
    log(f"Открытых задач по предмету после закрытия: {len(after)}")
    for row in after:
        log(f"  - {row['id']} | {row['step']} | {row['performer']} | {row['description'][:60]}")

    mine = [
        row
        for row in after
        if str(row.get("performer") or "") == str(card.get("performer") or "")
        and str(row.get("description") or "") == str(card.get("description") or "")
    ]
    log("ИТОГ: задача закрыта в ДО" if not mine else f"ИТОГ: задача всё ещё открыта ({len(mine)})")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nОтчёт: {REPORT}")
    return 0 if not mine else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
