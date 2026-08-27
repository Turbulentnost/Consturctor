from __future__ import annotations

import json
from typing import Any


def build_form_prompt(
    *,
    fio: str,
    position: str,
    agents: list[dict[str, Any]],
) -> str:
    listing = json.dumps(agents, ensure_ascii=False, indent=2, default=str)
    return f"""
Ты куратор KPI должности сотрудника Constructor, не KPI ИИ-агентов.
Спроектируй 3-5 плиток про то, как работает сам сотрудник, опираясь на его активных агентов
как на описание обязанностей. Не делай плитки success_rate / runs_count / ошибки прогонов агента.

Сотрудник:
- ФИО: {fio or "—"}
- Должность: {position or "—"}

Активные агенты (паспорта):
{listing or "[]"}

Верни ТОЛЬКО один JSON-объект (можно в блоке ```json), без текста вокруг.
Схема:
{{
  "summary": "как измеряем работу сотрудника",
  "tiles": [
    {{
      "id": "snake_case",
      "name": "человеческое имя KPI должности",
      "plan": {{
        "label": "План",
        "value": 95,
        "unit": "%",
        "description": "норма работы сотрудника"
      }},
      "fact": {{
        "label": "Факт",
        "value": null,
        "unit": "%",
        "description": "как измерять факт по работе сотрудника"
      }},
      "measure": {{
        "kind": "snake_case",
        "params": {{"weight": 25, "window_days": 90}},
        "formula": "человеческая формула"
      }},
      "method": {{
        "plan_explanation": "простыми словами: откуда план и когда он меняется",
        "fact_explanation": "простыми словами: как считать факт, какие источники (Outlook, 1C, файлы)",
        "score_explanation": "простыми словами: как получается процент и что значат цвета",
        "system": "техническая инструкция фоновому агенту: какие инструменты вызвать и как считать",
        "how": "технически как считать факт",
        "when": "только периодичность, например каждый день",
        "plan_update": "когда обновлять план",
        "fact_update": "когда обновлять факт",
        "percent_formula": "как считать KPI 0-100",
        "green_min": 90,
        "yellow_min": 70,
        "schedule": {{
          "kind": "interval",
          "interval_seconds": 86400,
          "at": ""
        }}
      }}
    }}
  ]
}}

Правила:
- 3-5 плиток, сумма weight в measure.params примерно 100.
- Плитки про работу человека (сроки документов, качество, контроль поручений), не про аптайм агента.
- fact.value и score_percent всегда null.
- Не выдумывай поля 1С. В system пиши, какие инструменты смотреть: Outlook календарь, 1С задачи, файлы прогонов.
- Не вызывай constructor_tool в этом ответе — только JSON.
""".strip()


def build_calc_prompt(
    *,
    fio: str,
    position: str,
    tiles: list[dict[str, Any]],
    due_tile_ids: list[str],
    locked: bool,
) -> str:
    context = json.dumps(
        {
            "fio": fio or "",
            "position": position or "",
            "locked": locked,
            "due_tile_ids": due_tile_ids,
            "tiles": tiles,
        },
        ensure_ascii=False,
        indent=2,
        default=str,
    )
    lock_rule = (
        "Состав плиток, id, имена, цели плана и методику менять нельзя."
        if locked
        else "Не меняй id, имена и методику. Можно обновить только plan.value если методика велит."
    )
    return f"""
Ты считаешь KPI должности сотрудника Constructor по уже утверждённой методике.
{lock_rule}
Посчитай факт, score_percent и evidence для плиток из due_tile_ids.
Если методика велит обновить план — обнови plan.value, иначе оставь план как есть.

Используй доступные инструменты (Outlook, 1С, файлы), как написано в method.system.
Ничего не выдумывай: нет данных — fact.value = null, score_percent = null, evidence = "нет данных".

Контекст:
{context}

Верни ТОЛЬКО один JSON-объект:
{{
  "tiles": [
    {{
      "id": "tile_id",
      "plan": {{"value": 95}},
      "fact": {{"value": 90, "unit": "%", "description": "кратко что посчитали"}},
      "score_percent": 90,
      "evidence": "откуда взяты числа, сколько заседаний/поручений"
    }}
  ]
}}

Правила:
- Только плитки из due_tile_ids.
- score_percent 0-100 или null.
- Не добавляй новые плитки и не переименовывай существующие.
""".strip()
