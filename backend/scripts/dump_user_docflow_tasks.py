#!/usr/bin/env python3
"""
Открытые задачи 1С:Документооборот (HTTP SOAP inbox /doc/ws/dm.1cws).

Inbox: app.tools.onec.dok_soap.fetch_user_inbox_tasks (DOK_HTTP_*).
Предпочтительный CLI: scripts/get_do_user_tasks.py

Пример:
  cd backend
  py -3 scripts/get_do_user_tasks.py "Жалыбин Максим Дмитриевич"
  py -3 scripts/dump_user_docflow_tasks.py "Жалыбин Максим Дмитриевич" --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
WORKSPACE = BACKEND.parent.parent
sys.path.insert(0, str(BACKEND))

for env_path in (WORKSPACE / ".env", BACKEND / ".env"):
    if not env_path.is_file():
        continue
    for line in env_path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, _, value = raw.partition("=")
        key = key.strip()
        if not key:
            continue
        # backend/.env должен перекрывать пустые переменные окружения для CLI.
        if key not in os.environ or not str(os.environ.get(key, "")).strip():
            os.environ[key] = value.strip()


def format_when(value: str | None) -> str:
    text = str(value or "").strip()
    if not text or text.startswith("0001-01-01"):
        return "—"
    date = text[:10]
    if len(date) == 10 and date[4] == "-" and date[7] == "-":
        return f"{date[8:10]}.{date[5:7]}.{date[0:4]}"
    return text


def format_inbox_table(payload: dict[str, Any]) -> str:
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    header = [
        f"Пользователь: {payload.get('user_fio') or '—'}",
        f"Открытых задач: {payload.get('count', len(rows))}",
        f"С {payload.get('since') or '—'} (невыполненные)",
        "",
    ]
    if not rows:
        return "\n".join([*header, "Открытых задач нет."])

    lines = [
        *header,
        f"{'№':<3} {'Шаг':<14} {'Срок':<12} {'Автор':<28} Задача",
        "-" * 100,
    ]
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        title = str(row.get("description") or row.get("target") or row.get("name") or "").strip()
        name = str(row.get("name") or "").strip()
        extra = f"  ({name})" if name and title != name else ""
        lines.append(
            f"{index:<3} {str(row.get('step') or '—'):<14} "
            f"{format_when(str(row.get('due') or '')):<12} "
            f"{str(row.get('author') or '—'):<28} {title}{extra}"
        )
    return "\n".join(lines)


def dump_user_tasks(
    user: str,
    *,
    since_days: int = 90,
    executions: bool = False,
    already_ref: bool = False,
    service: bool = False,
    password: str = "",
) -> dict[str, Any]:
    if service:
        from app.services.docflow_document_tasks import odata_entity
        from app.services.docflow_tasks import docflow_base_url, list_docflow_tasks

        auth_args = {"fio": user.strip(), "password": password} if password else None
        tasks = list_docflow_tasks(
            fio=user.strip(),
            only_open=True,
            limit=200,
            auth_args=auth_args,
        )
        return {
            "endpoint": f"{docflow_base_url()}/{odata_entity()}?$filter=Исполнитель_Key…",
            "user_fio": user.strip(),
            "count": len(tasks),
            "rows": tasks,
        }

    if executions:
        from app.tools.onec.dok_http import (
            clear_request_auth,
            dok_endpoint_url,
            fetch_user_document_executions,
            set_request_auth,
        )

        fio = user.strip()
        user_ref = fio if not already_ref else fio
        resolved_fio = fio
        if password:
            set_request_auth(fio, password)
        try:
            rows = fetch_user_document_executions(user_ref, user_fio=resolved_fio)
        finally:
            clear_request_auth()
        return {
            "endpoint": dok_endpoint_url(template="TasksII", suffix="User"),
            "user_ref": user_ref,
            "user_fio": resolved_fio,
            "count": len(rows),
            "rows": rows,
        }

    from app.tools.onec.dok_soap import fetch_user_inbox_tasks

    fio = user.strip()
    return fetch_user_inbox_tasks(
        fio,
        since_days=since_days,
        username=fio if password else None,
        password=password or None,
    )


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Открытые задачи пользователя из 1С:Документооборота",
    )
    parser.add_argument(
        "users",
        nargs="*",
        help="ФИО (по умолчанию MY_NAME из .env)",
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=90,
        help="Окно дат для inbox, по умолчанию 90",
    )
    parser.add_argument("-o", "--output", help="Сохранить JSON")
    parser.add_argument("--json", action="store_true", help="Печатать JSON, а не таблицу")
    parser.add_argument(
        "--executions",
        action="store_true",
        help="Таблица исполнений документов (TasksII/User), не inbox",
    )
    parser.add_argument(
        "--service",
        action="store_true",
        help="Через backend list_docflow_tasks (HTTP SOAP inbox)",
    )
    parser.add_argument(
        "--ref",
        action="store_true",
        help="Для --executions: аргument уже ERP Ref_Key",
    )
    args = parser.parse_args(argv)

    users = [u.strip() for u in args.users if u.strip()]
    if not users:
        default = (os.environ.get("MY_NAME") or "").strip()
        if not default:
            print("Укажите ФИО или MY_NAME в .env", file=sys.stderr)
            return 2
        users = [default]

    payloads: list[dict[str, Any]] = []
    try:
        for user in users:
            pwd = (os.environ.get("MY_PASSWORD") or os.environ.get("ERP_PASSWORD") or "").strip()
            payloads.append(
                dump_user_tasks(
                    user,
                    since_days=args.since_days,
                    executions=args.executions,
                    already_ref=args.ref,
                    service=args.service,
                    password=pwd,
                )
            )
    except ImportError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        print("Проверьте app.tools.onec.dok_soap и DOK_HTTP_* в backend/.env", file=sys.stderr)
        return 1
    except (RuntimeError, ValueError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1

    result: dict[str, Any] | list[dict[str, Any]] = (
        payloads[0] if len(payloads) == 1 else payloads
    )
    if args.output:
        with open(args.output, "w", encoding="utf-8") as file:
            json.dump(result, file, ensure_ascii=False, indent=2, default=str)
            file.write("\n")
        print(f"Сохранено: {args.output}", file=sys.stderr)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0

    if args.service:
        for payload in payloads:
            print(f"Endpoint: {payload.get('endpoint')}")
            print(f"Пользователь: {payload.get('user_fio')}  задач: {payload.get('count')}")
            for index, row in enumerate(payload.get("rows") or [], start=1):
                if not isinstance(row, dict):
                    continue
                print(
                    f"{index}. [{row.get('number')}] {row.get('title')} | "
                    f"срок={row.get('due_at') or '—'} | {row.get('source')}"
                )
        return 0

    blocks = [format_inbox_table(payload) for payload in payloads]
    print("\n\n".join(blocks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
