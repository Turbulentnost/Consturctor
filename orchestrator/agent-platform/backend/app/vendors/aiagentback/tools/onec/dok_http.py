"""HTTP-клиент документооборота (ДО).

Шаблоны ``hs/dterp``:
- ``TasksID?TasksID=<guid>`` — ``РезультатВыполнения`` задачи исполнителя;
- ``POST TasksII/User`` — таблица исполнений/задач пользователя
  (структура ``{Пользователь: Ref_Key}``);
- ``POST Tasks`` — статус задач по списку ``ПроцессID``.

Пользователь ДО часто кириллический — Basic Auth собираем вручную в UTF-8.

Связь с регистром протоколов: ``ИдентификаторЗадачи`` — наш uuid4 и в ДО не
существует. В ``ПроцессID`` лежит GUID бизнес-процесса ДО; задача исполнителя
создаётся следом и имеет тот же суффикс GUID, а первый сегмент смещён на
``0xF8`` (проверено на протоколах 2026). Сначала пробуем этот GUID, затем
``task_id`` как есть.
"""

from __future__ import annotations

import base64
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests

from app.vendors.aiagentback.core.config import settings
from app.vendors.aiagentback.core.logging import get_logger
from app.vendors.aiagentback.tools.onec.v8_internal_format import (
    array_of_strings_to_internal,
    from_internal_string,
    structure_to_internal,
)

logger = get_logger(__name__)

_EMPTY_GUID = "00000000-0000-0000-0000-000000000000"
_STRING_VALUE_RE = re.compile(r'\{"S","((?:[^"\\]|\\.)*)"\}')
_MAX_WORKERS = 8
# ЗадачаИсполнителя.Ref_Key ≈ ПроцессID с +0xF8 в первом сегменте GUID.
_PROCESS_TO_TASK_OFFSET = 0xF8


def dok_http_configured() -> bool:
    return bool(
        str(settings.DOK_HTTP_SERVER or "").strip()
        and str(settings.DOK_HTTP_USER or "").strip()
    )


def dok_endpoint_url(*, template: str | None = None, suffix: str | None = None) -> str:
    server = str(settings.DOK_HTTP_SERVER or "").strip()
    port = int(settings.DOK_HTTP_PORT or 81)
    base = str(settings.DOK_HTTP_BASE_PATH or "").rstrip("/")
    service = str(settings.DOK_HTTP_SERVICE or "dterp").strip() or "dterp"
    tpl = (
        template
        if template is not None
        else str(settings.DOK_HTTP_TEMPLATE or "Tasks")
    ).strip("/")
    url = f"http://{server}:{port}{base}/hs/{service}/{tpl}"
    suffix_value = settings.DOK_HTTP_SUFFIX if suffix is None else suffix
    if str(suffix_value or "").strip():
        url += f"/{str(suffix_value).strip('/')}"
    return url


def dok_tasks_id_url() -> str:
    return dok_endpoint_url(template="TasksID", suffix="")


def _dok_auth_headers() -> dict[str, str]:
    user = str(settings.DOK_HTTP_USER or "")
    password = str(settings.DOK_HTTP_PASSWORD or "")
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _decode_dok_body(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _dok_timeout() -> float:
    return float(settings.DOK_HTTP_TIMEOUT or 30)


def post_internal(url: str, body: str) -> requests.Response:
    return requests.post(
        url,
        headers={
            **_dok_auth_headers(),
            "Content-Type": "text/plain;charset=UTF-8",
        },
        data=body.encode("utf-8"),
        timeout=_dok_timeout(),
    )


def parse_dok_response(response: requests.Response) -> Any:
    if response.status_code > 299:
        text = _decode_dok_body(response.content).strip()
        raise RuntimeError(f"HTTP {response.status_code}: {text[:800]}")
    text = _decode_dok_body(response.content).strip()
    if not text:
        return []
    parsed = from_internal_string(text)
    return parsed if parsed is not None else text


def fetch_process_tasks(
    process_ids: list[str],
    *,
    template: str = "Tasks",
    suffix: str = "",
) -> list[dict[str, Any]]:
    """POST Tasks — статус задач по списку ПроцессID."""

    if not process_ids:
        return []
    if not dok_http_configured():
        raise RuntimeError("DOK_HTTP_SERVER / DOK_HTTP_USER не заданы")

    url = dok_endpoint_url(template=template, suffix=suffix)
    response = post_internal(url, array_of_strings_to_internal(process_ids))
    parsed = parse_dok_response(response)
    return parsed if isinstance(parsed, list) else []


def fetch_user_document_executions(
    user_ref: str,
    *,
    user_fio: str | None = None,
    template: str = "TasksII",
    suffix: str = "User",
) -> list[dict[str, Any]]:
    """POST TasksII/User со структурой {Пользователь: Ref_Key}.

    Если структура не принята или таблица пустая, пробуем ФИО и массив УИД —
    так работали COM-отбор и старый скрипт get_tasks_user_http.
    """

    normalized = str(user_ref or "").strip()
    if not normalized or normalized == _EMPTY_GUID:
        return []
    if not dok_http_configured():
        raise RuntimeError("DOK_HTTP_SERVER / DOK_HTTP_USER не заданы")

    url = dok_endpoint_url(template=template, suffix=suffix)
    payloads: list[str] = [structure_to_internal({"Пользователь": normalized})]
    fio = str(user_fio or "").strip()
    if fio and fio != normalized:
        payloads.append(structure_to_internal({"Пользователь": fio}))
    payloads.append(array_of_strings_to_internal([normalized]))

    last_rows: list[dict[str, Any]] = []
    for body in payloads:
        try:
            parsed = parse_dok_response(post_internal(url, body))
        except (requests.RequestException, RuntimeError) as exc:
            logger.warning("DOK TasksII/User request failed: %s", exc)
            continue
        if not isinstance(parsed, list):
            continue
        last_rows = parsed
        if parsed:
            return parsed
    return last_rows


def parse_execution_result_from_internal(text: str) -> str | None:
    """Достаёт непустой ``РезультатВыполнения`` из ``ЗначениеВСтрокуВнутр``."""

    if not text or "РезультатВыполнения" not in text:
        return None
    for value in _STRING_VALUE_RE.findall(text):
        cleaned = value.replace('""', '"').strip()
        if cleaned:
            return cleaned
    return None


def executor_task_guid_from_process_id(process_id: str) -> str | None:
    """Выводит GUID ``ЗадачаИсполнителя`` из ``ПроцессID`` регистра протоколов."""

    normalized = str(process_id or "").strip().lower()
    if not normalized or normalized == _EMPTY_GUID:
        return None
    parts = normalized.split("-")
    if len(parts) != 5:
        return None
    try:
        head = int(parts[0], 16)
    except ValueError:
        return None
    parts[0] = f"{(head + _PROCESS_TO_TASK_OFFSET) & 0xFFFFFFFF:08x}"
    return "-".join(parts)


def fetch_task_execution_result(task_id: str) -> str | None:
    """GET TasksID → текст результата исполнения или ``None``."""

    normalized = str(task_id or "").strip()
    if not normalized or normalized == _EMPTY_GUID:
        return None
    if not dok_http_configured():
        return None

    url = dok_tasks_id_url()
    timeout = float(settings.DOK_HTTP_TIMEOUT or 30)
    try:
        response = requests.get(
            url,
            params={"TasksID": normalized},
            headers=_dok_auth_headers(),
            timeout=timeout,
        )
    except requests.RequestException as exc:
        logger.warning("DOK TasksID request failed for %s: %s", normalized, exc)
        return None

    if response.status_code != 200 or not response.content:
        logger.warning(
            "DOK TasksID unexpected status for %s: %s",
            normalized,
            response.status_code,
        )
        return None

    return parse_execution_result_from_internal(_decode_dok_body(response.content))


def resolve_task_execution_result(task: dict[str, Any]) -> str | None:
    """Ищет результат: сначала GUID из ``process_id``, затем ``task_id``."""

    candidates: list[str] = []
    derived = executor_task_guid_from_process_id(str(task.get("process_id") or ""))
    if derived:
        candidates.append(derived)
    task_id = str(task.get("task_id") or "").strip()
    if task_id and task_id != _EMPTY_GUID and task_id not in candidates:
        candidates.append(task_id)

    for guid in candidates:
        result = fetch_task_execution_result(guid)
        if result:
            return result
    return None


def enrich_protocol_tasks_with_execution_results(
    tasks: list[dict[str, Any]],
) -> int:
    """Заполняет ``execution_result`` у задач протокола из ДО TasksID.

    Возвращает число задач, для которых удалось получить непустой результат.
    """

    if not tasks or not dok_http_configured():
        return 0

    pending: list[int] = [
        index
        for index, task in enumerate(tasks)
        if isinstance(task, dict)
        and (
            str(task.get("process_id") or "").strip()
            or str(task.get("task_id") or "").strip()
        )
    ]
    if not pending:
        return 0

    filled = 0
    workers = min(_MAX_WORKERS, len(pending))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(resolve_task_execution_result, tasks[index]): index
            for index in pending
        }
        for future in as_completed(futures):
            index = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001
                logger.warning("DOK TasksID worker failed: %s", exc)
                continue
            if not result:
                continue
            tasks[index]["execution_result"] = result
            # Если в регистре комментарий пуст — дублируем для старых путей UI.
            if not str(tasks[index].get("comment") or "").strip():
                tasks[index]["comment"] = result
            filled += 1
    return filled


def enrich_protocol_document_execution_results(document: dict[str, Any]) -> int:
    """Обогащает ``document['tasks']`` результатами исполнения из ДО."""

    tasks = document.get("tasks")
    if not isinstance(tasks, list):
        return 0
    return enrich_protocol_tasks_with_execution_results(tasks)
