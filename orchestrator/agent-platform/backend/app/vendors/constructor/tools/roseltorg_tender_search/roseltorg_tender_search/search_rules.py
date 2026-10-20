"""Правила преобразования строк словаря в отдельные поисковые запросы.

Правила (из ТЗ):
- перечисление через запятую «,» → каждый элемент = отдельный запрос
  (например: «ууг, пуг, пург» → «ууг», «пуг», «пург»);
- варианты через слэш «/» → каждая альтернатива = отдельный запрос
  (например: «модернизация грп/грс» → «модернизация грп», «модернизация грс»;
   «модернизация / реконструкция / перевооружение / обновление» → 4 запроса);
- поиск регистронезависимый (нормализуем регистр на стороне сравнения);
- никаких дополнительных синонимов и фильтров не добавляем.
"""

from __future__ import annotations

from .keywords import EXCLUDED_LINES, KEYWORD_LINES


def _split_slash(term: str) -> list[str]:
    """Развернуть слэш-варианты.

    Поддерживает два случая:
    - одиночные слова: «модернизация / реконструкция» → ["модернизация", "реконструкция"];
    - общий префикс со слэшем внутри одного «слова»: «модернизация грп/грс»
      → ["модернизация грп", "модернизация грс"].
    """
    if "/" not in term:
        return [term.strip()]

    parts = [p.strip() for p in term.split("/") if p.strip()]

    # Случай «модернизация грп/грс»: префикс есть только у первой части,
    # у остальных — короткий хвост без пробелов. Переносим префикс.
    head_tokens = parts[0].split()
    if len(head_tokens) > 1 and all(" " not in p for p in parts[1:]):
        prefix = " ".join(head_tokens[:-1])
        first_tail = head_tokens[-1]
        expanded = [f"{prefix} {first_tail}".strip()]
        expanded += [f"{prefix} {p}".strip() for p in parts[1:]]
        return expanded

    return parts


def expand_line(line: str) -> list[str]:
    """Развернуть одну строку словаря в список запросов."""
    queries: list[str] = []
    for chunk in line.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        queries.extend(_split_slash(chunk))
    return [q for q in (q.strip() for q in queries) if q]


def build_queries(
    lines: list[str] | None = None,
    *,
    include_excluded: bool = False,
) -> list[str]:
    """Собрать полный список уникальных поисковых запросов из словаря.

    Порядок сохраняется (первое вхождение), регистр приводится к нижнему для
    сравнения дублей, но в результат попадает исходная (нормализованная) форма.
    """
    src = lines if lines is not None else KEYWORD_LINES
    seen: set[str] = set()
    result: list[str] = []
    for line in src:
        if not include_excluded and line in EXCLUDED_LINES:
            continue
        for q in expand_line(line):
            key = q.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(q)
    return result
