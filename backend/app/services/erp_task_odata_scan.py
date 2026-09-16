"""МоиЗадачи semantics on Task_ЗадачаИсполнителя when OData ignores role filters.

On erp_pm the service user often gets the same page for ``Исполнитель`` / ``Автор``
filters as for ``Executed eq false`` only. We paginate open tasks and match
``Исполнитель`` (мне) and ``Автор`` (от меня) by GUID string on the row.
"""

from __future__ import annotations

from typing import Any, Callable

from app.services.erp_assignments import TASK_ENTITY
from app.services.erp_tasks import is_constructor_test_probe, merge_task_lists

ROLE_EXECUTOR = "executor"
ROLE_AUTHOR = "author"
ROLE_MENTION = "mention"

_OPEN_FILTER = "DeletionMark eq false and Executed eq false"
_DEFAULT_PAGE_SIZE = 200
_DEFAULT_MAX_ROWS = 10_000


def normalize_user_ref(value: Any) -> str:
    return str(value or "").strip().lower()


def row_user_ref(row: dict[str, Any], field: str) -> str:
    return normalize_user_ref(row.get(field))


def row_matches_user_ref(row: dict[str, Any], field: str, user_ref: str) -> bool:
    expected = normalize_user_ref(user_ref)
    if not expected:
        return False
    return row_user_ref(row, field) == expected


def classify_my_task_row(
    row: dict[str, Any],
    *,
    user_ref: str,
    fio: str,
    mention_checker: Callable[[dict[str, Any], str], bool] | None = None,
    roles: frozenset[str] | None = None,
) -> str | None:
    allowed = roles or frozenset({ROLE_EXECUTOR, ROLE_AUTHOR, ROLE_MENTION})
    if ROLE_EXECUTOR in allowed and row_matches_user_ref(row, "Исполнитель", user_ref):
        return ROLE_EXECUTOR
    if ROLE_AUTHOR in allowed and row_matches_user_ref(row, "Автор", user_ref):
        return ROLE_AUTHOR
    if ROLE_MENTION in allowed and mention_checker and mention_checker(row, fio):
        return ROLE_MENTION
    return None


def _source_for_role(role: str) -> str:
    if role == ROLE_AUTHOR:
        return "erp_pm+odata (от меня)"
    return "erp_pm+odata"


def scan_task_zadacha_ispolnitelya(
    *,
    user_ref: str,
    fio: str,
    limit: int,
    fetch_page: Callable[..., dict[str, Any]],
    mention_checker: Callable[[dict[str, Any], str], bool] | None = None,
    map_row: Callable[[dict[str, Any], str], dict[str, Any]] | None = None,
    roles: frozenset[str] | None = None,
    page_size: int = _DEFAULT_PAGE_SIZE,
    max_rows: int = _DEFAULT_MAX_ROWS,
) -> tuple[list[dict[str, Any]], str]:
    """Return open tasks for user (executor + author + optional title mention)."""
    limit = max(1, min(int(limit or 50), 200))
    page_size = max(50, min(int(page_size or _DEFAULT_PAGE_SIZE), 500))
    max_rows = max(page_size, min(int(max_rows or _DEFAULT_MAX_ROWS), 20_000))

    collected: list[dict[str, Any]] = []
    seen: set[str] = set()
    skip = 0
    scanned = 0
    truncated = False

    while len(collected) < limit and scanned < max_rows:
        top = min(page_size, max_rows - scanned)
        data = fetch_page(
            TASK_ENTITY,
            params={
                "$top": top,
                "$skip": skip,
                "$orderby": "Date desc",
                "$filter": _OPEN_FILTER,
            },
        )
        batch = [row for row in (data.get("value") or []) if isinstance(row, dict)]
        if not batch:
            break
        scanned += len(batch)
        skip += len(batch)

        for row in batch:
            role = classify_my_task_row(
                row,
                user_ref=user_ref,
                fio=fio,
                mention_checker=mention_checker,
                roles=roles,
            )
            if role is None:
                continue
            marker = str(row.get("Ref_Key") or row.get("Number") or "").strip()
            if marker and marker in seen:
                continue
            if marker:
                seen.add(marker)
            if map_row is not None:
                mapped = map_row(row, role)
            else:
                mapped = dict(row)
                mapped["source"] = _source_for_role(role)
            if is_constructor_test_probe(mapped):
                continue
            collected.append(mapped)
            if len(collected) >= limit:
                break

        if len(batch) < top:
            break
        if scanned >= max_rows and len(collected) < limit:
            truncated = True
            break

    warning = ""
    if truncated:
        warning = (
            f"OData: просмотрено {scanned} открытых задач (лимит сканирования); "
            "возможны пропуски — включите SQL fallback или VPN до erp_pm."
        )
    return collected[:limit], warning
