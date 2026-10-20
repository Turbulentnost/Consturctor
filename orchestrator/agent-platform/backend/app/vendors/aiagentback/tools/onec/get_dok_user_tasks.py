"""
Форматирование и обёртка для тестов / ``python -m``.

Автономный скрипт без импортов проекта:
  python scripts/get_do_user_tasks.py "Жалыбин Максим Дмитриевич"
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


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
) -> dict[str, Any]:
    if executions:
        from app.vendors.aiagentback.tools.onec.connection import create_session
        from app.vendors.aiagentback.tools.onec.dok_http import dok_endpoint_url, fetch_user_document_executions
        from app.vendors.aiagentback.tools.onec.lookup_user_ref import resolve_user_by_fio

        if already_ref:
            user_ref = user.strip()
            resolved_fio = user_ref
        else:
            session = create_session()
            user_ref, resolved_fio, _ = resolve_user_by_fio(session, user)
        rows = fetch_user_document_executions(user_ref, user_fio=resolved_fio)
        return {
            "endpoint": dok_endpoint_url(template="TasksII", suffix="User"),
            "user_ref": user_ref,
            "user_fio": resolved_fio,
            "count": len(rows),
            "rows": rows,
        }

    from app.vendors.aiagentback.tools.onec.dok_soap import fetch_user_inbox_tasks

    return fetch_user_inbox_tasks(user.strip(), since_days=since_days)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Открытые задачи пользователя из 1С:Документооборота",
    )
    parser.add_argument("users", nargs="+", help="ФИО одного или нескольких пользователей")
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
        "--ref",
        action="store_true",
        help="Для --executions: аргумент уже ERP Ref_Key",
    )
    args = parser.parse_args(argv)

    payloads: list[dict[str, Any]] = []
    try:
        for user in args.users:
            payloads.append(
                dump_user_tasks(
                    user,
                    since_days=args.since_days,
                    executions=args.executions,
                    already_ref=args.ref,
                )
            )
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

    blocks = [format_inbox_table(payload) for payload in payloads]
    print("\n\n".join(blocks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
