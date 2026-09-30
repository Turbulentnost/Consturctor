from __future__ import annotations

import json
from typing import Any

from app.services.cursor_sdk_local import CursorSdkLocalError, run_cursor_sdk
from app.services.workflows.document import DocumentError, load_attachment_bytes


class SalaryExtractionError(RuntimeError):
    pass


def read_full_text(name: str, raw: bytes) -> str:
    """Text of every page of the document; raises when any page was not recognized."""
    try:
        attachment = load_attachment_bytes(name, raw, ocr=True)
    except DocumentError as exc:
        raise SalaryExtractionError(str(exc)) from exc
    ocr_error = str(attachment.get("ocr_error") or "").strip()
    if ocr_error:
        raise SalaryExtractionError(f"Не удалось распознать все страницы файла. {ocr_error}")
    text = str(attachment.get("text") or "").strip()
    if not text or attachment.get("text_extracted") is False:
        raise SalaryExtractionError(
            "Не удалось извлечь текст файла. Загрузите PDF, Word, Excel или изображение."
        )
    return text


def extract_salary_document(name: str, raw: bytes) -> dict[str, Any]:
    """Extract position salaries semantically with the local Cursor SDK agent."""
    text = read_full_text(name, raw)
    try:
        answer = run_cursor_sdk(_salary_prompt(name, text))
    except CursorSdkLocalError as exc:
        raise SalaryExtractionError(str(exc)) from exc
    return _parse_answer(answer)


def _salary_prompt(name: str, text: str) -> str:
    return f"""Разбери документ с окладами «{name}».
Оклад привязан к должности в подразделении, не к сотруднику: одна и та же должность
в разных подразделениях может иметь разный оклад. Извлеки ВСЕ строки без пропусков.
Верни только JSON без markdown:
{{
  "effective_from": "YYYY-MM-DD",
  "rows": [
    {{
      "department_name": "точное название подразделения или пустая строка",
      "position_name": "точное название должности",
      "amount": "число без пробелов и обозначения валюты",
      "currency": "RUB"
    }}
  ]
}}
Подразделение бери из колонки или из заголовка раздела, под которым стоит строка.
Если документ не делит должности по подразделениям, оставь department_name пустым.
Если указана только дата утверждения — используй её. Если указан период только годом,
используй первое января этого года. Не включай надбавки, итог с надбавкой, количество
ставок, номера строк и итоги: amount — именно базовый оклад.

Текст документа:
--- START DOCUMENT ---
{text}
--- END DOCUMENT ---"""


def extract_material_document(name: str, text: str) -> dict[str, Any]:
    """Positions, KPI and weights of a material incentive regulation via Cursor SDK."""
    try:
        answer = run_cursor_sdk(_material_prompt(name, text), timeout=600)
    except CursorSdkLocalError as exc:
        raise SalaryExtractionError(str(exc)) from exc
    return _parse_answer(answer, key="positions")


def _material_prompt(name: str, text: str) -> str:
    return f"""Разбери положение о материальном стимулировании «{name}».
Нужны ТОЛЬКО должности, для которых в документе есть таблица показателей премирования
(KPI с весами и итогом ЦРП 100%). Должности из грифа «Утверждаю», листа согласования,
подписей, ссылок и общего текста НЕ включай. Каждая должность — один раз.
Верни только JSON без markdown:
{{
  "effective_from": "YYYY-MM-DD",
  "department_name": "подразделение, на работников которого распространяется положение",
  "positions": [
    {{
      "position_name": "название должности как в таблице",
      "department_name": "подразделение этой должности, если в таблице указано отдельно, иначе пустая строка",
      "metrics": [
        {{
          "name": "наименование показателя",
          "weight": 40,
          "formula": "метод расчёта / оценка дословно из таблицы",
          "plan": "целевое значение, если указано, иначе пустая строка"
        }}
      ]
    }}
  ]
}}
department_name бери из названия положения (например, «работников управления делами» →
«Управление делами», в именительном падеже с заглавной буквы).
effective_from — дата введения в действие / вступления в силу; если её нет — дата утверждения.
Итоговые строки «ЦРП 100%» и «Итого» в metrics не включай. weight — целое число процентов;
сумма весов одной должности обычно 100. Если в ячейке должности несколько названий через «/»,
оставь их в одном position_name через « / ».

Текст документа:
--- START DOCUMENT ---
{text}
--- END DOCUMENT ---"""


def _parse_answer(answer: str, *, key: str = "rows") -> dict[str, Any]:
    raw = answer.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        raw = raw.rsplit("```", 1)[0].strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise SalaryExtractionError("Cursor SDK не вернул JSON")
    try:
        payload = json.loads(raw[start : end + 1])
    except json.JSONDecodeError as exc:
        raise SalaryExtractionError(f"Некорректный JSON Cursor SDK: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get(key), list):
        raise SalaryExtractionError(f"В ответе Cursor SDK отсутствует массив {key}")
    return payload
