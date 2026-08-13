"""Черновик паспорта ИИ-агента по БП и выделенным функциям.

Формат как в продуктовом примере:
ИИ-агент / Цель / Триггер / Получает / Проверяет / Решения /
Может самостоятельно / Требует подтверждения / Не может / Результат.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from app.services.agent_passport import llm as llm_service
from app.services.agent_passport.types import ExtractedFunction

logger = logging.getLogger(__name__)

PASSPORT_FIELDS = (
    "name",
    "goal",
    "trigger",
    "receives",
    "checks",
    "decisions",
    "can_autonomous",
    "needs_human_approval",
    "forbidden",
    "result",
)

_FIELD_LABELS = {
    "name": "ИИ-агент",
    "goal": "Цель",
    "trigger": "Триггер",
    "receives": "Получает",
    "checks": "Проверяет",
    "decisions": "Принимает решения",
    "can_autonomous": "Может самостоятельно",
    "needs_human_approval": "Требует подтверждения человека",
    "forbidden": "Не может",
    "result": "Результат",
}

_PASSPORT_SYSTEM = (
    "Ты проектировщик ИИ-агентов по корпоративным регламентам. "
    "Заполняешь паспорт агента кратко и по делу. Возвращай СТРОГО JSON."
)

_QUESTIONS_SYSTEM = (
    "Ты помогаешь заполнить паспорт ИИ-агента. "
    "Задаёшь короткие живые вопросы на русском — как коллега, не как форма. "
    "Без канцелярита и без фраз «уточните значение». Возвращай СТРОГО JSON."
)

_ANSWER_SYSTEM = (
    "Ты проверяешь ответы пользователя для паспорта ИИ-агента. "
    "Если ответ ясный и достаточный — принимаешь и кратко нормализуешь. "
    "Если ответ расплывчатый, противоречивый или не по теме — не принимаешь "
    "и задаёшь один уточняющий вопрос. "
    "Для полей ограничений (Не может / Может самостоятельно / Требует подтверждения) "
    "ответ уровня политики достаточен: например «запрещено всё, кроме чтения», "
    "«только чтение», «все изменения только с подтверждением». "
    "Не требуй длинный перечень примеров, если политика уже ясна. "
    "Возвращай СТРОГО JSON."
)

_PASSPORT_PROMPT = """По бизнес-процессу и функциям заполни паспорт ИИ-агента.

Пример хорошего паспорта:
ИИ-агент: Контроль дебиторской задолженности
Цель: не допускать отгрузки клиентов с недопустимой задолженностью.
Триггер: поступила новая заявка на отгрузку.
Получает: клиент, окончательный заказ, договор.
Проверяет: CRM → 1С → условия договора.
Принимает решения: если ответственности нет → разрешить; если до 100 тыс. и до 7 дней → успех; если лимит выше → заблокировать и передать руководителю.
Может самостоятельно: прочитать данные, сделать расчёт, поставить отметку.
Требует подтверждения человека: изменение кредитного лимита.
Не может: проводить финансовые операции; физические шаги (склад/отгрузка) —
агент только напоминает человеку.
Результат: решение + объяснение + ссылки на исходные данные.

Верни СТРОГО JSON-объект со строковыми полями:
- "name", "goal", "trigger", "receives", "checks", "decisions",
  "can_autonomous", "needs_human_approval", "forbidden", "result"
В "forbidden" обязательно перечисли шаги с automation_kind=physical
(физические/внесистемные — нельзя выполнить программно).
Если чего-то нельзя надёжно вывести из текста — поставь пустую строку "".

Бизнес-процесс: {bp_name}

Фрагмент регламента:
\"\"\"
{excerpt}
\"\"\"

Функции агента:
{functions}

Ответ (только JSON-объект):"""

_QUESTIONS_PROMPT = """По черновику паспорта ИИ-агента сформулируй вопросы пользователю
только по незаполненным полям.

Пиши по-человечески. Если в фрагменте регламента есть релевантная фраза —
обязательно начни вопрос так:
«В этом отрывке регламента указано: \"...\".» — и сразу уточняющий вопрос.

Хорошие примеры:
- trigger → В этом отрывке регламента указано: \"сотрудник осуществляет регулярный мониторинг\". Когда запускать агента: по кнопке, по расписанию или по событию?
- receives → В этом отрывке регламента указано: \"на специализированных электронных площадках\". Откуда брать исходные данные и что именно нужно на входе?
- result → В этом отрывке регламента указано: \"информация подлежит выгрузке и фиксации\". Что должно получиться в итоге?

Плохо (нельзя так): «Триггер: уточните значение для агента …».

Бизнес-процесс: {bp_name}

Фрагмент регламента (если есть):
\"\"\"
{excerpt}
\"\"\"

Функции:
{functions}

Уже заполненные поля паспорта:
{filled}

Незаполненные поля (нужно спросить):
{missing}

Верни СТРОГО JSON:
{{"questions": [{{"field": "<ключ поля>", "prompt": "<вопрос пользователю>"}}]}}

Ключи field — только из списка незаполненных. Один вопрос на поле.
Ответ (только JSON-объект):"""


_FIELD_QUOTE_HINTS: dict[str, tuple[str, ...]] = {
    "name": ("агент", "процесс", "регламент"),
    "goal": ("цел", "в целях", "задач", "обеспеч", "не допуска"),
    "trigger": (
        "регулярн",
        "ежедневн",
        "расписан",
        "периодич",
        "при поступ",
        "по результат",
        "своевременн",
        "запуск",
        "мониторинг",
    ),
    "receives": (
        "получа",
        "исходн",
        "сведен",
        "информац",
        "данные",
        "площадк",
        "ресурс",
        "вход",
        "размещен",
    ),
    "checks": (
        "провер",
        "сверк",
        "контрол",
        "критер",
        "ключев",
        "1с",
        "crm",
        "excel",
    ),
    "decisions": (
        "решен",
        "определ",
        "если",
        "целесообраз",
        "участ",
        "принят",
    ),
    "can_autonomous": ("самостоятельн", "автоматическ", "без участия"),
    "needs_human_approval": (
        "согласован",
        "утвержд",
        "руководител",
        "уполномочен",
        "человек",
        "подтвержд",
    ),
    "forbidden": ("запрещ", "не допуска", "нельзя", "без права", "физическ"),
    "result": (
        "результат",
        "итог",
        "фиксац",
        "выгруз",
        "подготов",
        "переда",
        "отчет",
        "отчёт",
    ),
}


def _clean_quote(text: str, *, limit: int = 220) -> str:
    quote = " ".join(str(text or "").split()).strip(" «»\"'")
    if len(quote) > limit:
        cut = quote[: limit - 1]
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        quote = cut.rstrip(".,;:") + "…"
    return quote


def _split_regulation_chunks(excerpt: str) -> list[str]:
    text = " ".join(str(excerpt or "").split()).strip()
    if not text:
        return []
    # Убрать markdown-заголовок вида "## ..." / голый заголовок в начале.
    text = re.sub(r"^#+\s*", "", text)
    text = re.sub(
        r"^(?:[А-ЯЁA-Z][^.!?]{0,80}?)\s+(?=[А-ЯЁA-Z])",
        "",
        text,
        count=1,
    )
    parts = re.split(r"(?<=[.!?…])\s+", text)
    chunks: list[str] = []
    for part in parts:
        cleaned = part.strip(" -•\t«»\"'")
        if len(cleaned) < 35:
            continue
        if cleaned[0].islower() and not cleaned[0].isdigit():
            continue
        chunks.append(cleaned)
    if not chunks and text:
        chunks = [text]
    return chunks


def _window_around_hint(text: str, hints: list[str], *, limit: int = 200) -> str:
    """Вырезать читаемый фрагмент вокруг первого совпадения подсказки."""
    low = text.casefold().replace("ё", "е")
    pos = -1
    hit_len = 0
    for hint in hints:
        if not hint:
            continue
        idx = low.find(hint)
        if idx >= 0 and (pos < 0 or idx < pos):
            pos = idx
            hit_len = len(hint)
    if pos < 0:
        return _clean_quote(text, limit=limit)

    # Расширяем до границ по знакам препинания / пробелам.
    left = max(0, pos - 70)
    right = min(len(text), pos + hit_len + 110)
    while left > 0 and text[left] not in " \t":
        left -= 1
    while right < len(text) and text[right - 1] not in " \t,.!?;:":
        right += 1
    snippet = text[left:right].strip(" ,;:\n\t")
    if left > 0 and not snippet[:1].isupper():
        snippet = "…" + snippet
    if right < len(text):
        snippet = snippet.rstrip(".,;:") + "…"
    return _clean_quote(snippet, limit=limit)


def _pick_regulation_quote(
    excerpt: str,
    field: str,
    functions: list[ExtractedFunction] | None = None,
    *,
    min_score: int = 2,
) -> str:
    """Подобрать цитату только при уверенном совпадении с полем; иначе ''."""
    chunks = _split_regulation_chunks(excerpt)
    if not chunks:
        return ""

    hints = list(_FIELD_QUOTE_HINTS.get(field, ()))
    for fn in functions or []:
        hints.extend(
            re.findall(r"[A-Za-zА-Яа-яЁё0-9]{4,}", f"{fn.name} {fn.description}")
        )
    hints = [h.casefold().replace("ё", "е") for h in hints if h]
    if not hints:
        return ""

    best = ""
    best_score = 0
    for chunk in chunks:
        low = chunk.casefold().replace("ё", "е")
        score = sum(1 for h in hints if h and h in low)
        if score > best_score:
            best_score = score
            best = chunk

    # Без явных совпадений по смыслу поля — цитату не цепляем.
    if best_score < min_score or not best:
        return ""
    if len(best) > 160:
        return _window_around_hint(best, hints, limit=140)
    return _clean_quote(best, limit=160)


# Поля, где отсылка к регламенту реально помогает уточнить.
_QUOTE_WORTHY_FIELDS = frozenset(
    {"trigger", "receives", "checks", "decisions", "result"}
)


def _with_regulation_quote(question: str, quote: str) -> str:
    q = str(question or "").strip()
    quote = _clean_quote(quote, limit=160)
    if not quote:
        return q
    if "отрывке регламента указано" in q.casefold():
        return q
    return f"В этом отрывке регламента указано: «{quote}».\n\n{q}"


def _human_field_question(
    field: str,
    agent_name: str,
    *,
    excerpt: str = "",
    functions: list[ExtractedFunction] | None = None,
) -> str:
    """Живой вопрос по полю паспорта; цитата — только если уместна."""
    name = (agent_name or "агента").strip() or "агента"
    titled = f"«{name}»"
    templates = {
        "name": "Как назвать этого агента?",
        "goal": f"Какая главная цель у {titled}? Что он должен улучшить или не допустить?",
        "trigger": (
            f"Когда запускать {titled}: по кнопке / запросу, "
            f"по письму, по событию в системе или по расписанию?"
        ),
        "receives": (
            f"Откуда брать исходные данные для {titled} "
            f"и что именно нужно на входе?"
        ),
        "checks": (
            f"Где {titled} должен сверять данные — "
            f"1С, Excel, сайт, почта, другое?"
        ),
        "decisions": (
            f"Какие решения {titled} может принимать сам "
            f"и по каким правилам (если / то)?"
        ),
        "can_autonomous": (
            f"Что {titled} может делать самостоятельно, "
            f"без человека (например, только читать)?"
        ),
        "needs_human_approval": (
            f"В каких случаях {titled} обязан спросить человека "
            f"перед действием?"
        ),
        "forbidden": (
            f"Что агенту {titled} категорически нельзя делать? "
            f"Достаточно политики, например: только чтение данных."
        ),
        "result": (
            f"Что должно получиться в итоге работы {titled} — "
            f"какой результат увидит человек?"
        ),
    }
    base = templates.get(
        field,
        f"Расскажите кратко про «{_FIELD_LABELS.get(field, field)}» для {titled}.",
    )
    if field not in _QUOTE_WORTHY_FIELDS or not str(excerpt or "").strip():
        return base
    quote = _pick_regulation_quote(excerpt, field, functions, min_score=2)
    return _with_regulation_quote(base, quote)


def _looks_robotic_question(prompt: str) -> bool:
    low = str(prompt or "").casefold().replace("ё", "е")
    return (
        "уточните значение" in low
        or low.startswith("триггер:")
        or low.startswith("получает:")
        or low.startswith("проверяет:")
        or low.startswith("результат:")
        or "укажите значение для" in low
    )

_ANSWER_PROMPT = """Оцени ответ пользователя для одного поля паспорта ИИ-агента.

Поле: {field_label} ({field})
Предыдущий вопрос: {question}
Ответ пользователя: {answer}
Текущее значение поля (если было): {current}

Контекст паспорта:
{passport_context}

Критерии:
- accepted=true, если ответ по теме и его достаточно, чтобы записать поле;
- тогда normalized_value — краткая деловая формулировка для паспорта (1-2 фразы);
- для forbidden / can_autonomous / needs_human_approval ответ-политика достаточен
  («запрещено всё кроме чтения», «только чтение данных», «все write с подтверждением») —
  accepted=true, не проси список частных запретов;
- accepted=false, если ответ пустой по смыслу («да», «ок», «не знаю» без деталей),
  уклончивый или не по теме — тогда follow_up: один конкретный
  уточняющий вопрос на русском (без шаблона «уточните значение»).

Верни СТРОГО JSON:
{{"accepted": true/false, "normalized_value": "...", "follow_up": "..."}}

Ответ (только JSON-объект):"""


_SCOPE_FIELDS = frozenset({"forbidden", "can_autonomous", "needs_human_approval"})


@dataclass
class AgentPassport:
    """Паспорт агента + пробелы и вопросы к пользователю."""

    name: str = ""
    goal: str = ""
    trigger: str = ""
    receives: str = ""
    checks: str = ""
    decisions: str = ""
    can_autonomous: str = ""
    needs_human_approval: str = ""
    forbidden: str = ""
    result: str = ""
    missing_fields: list[str] = field(default_factory=list)
    questions: list[dict] = field(default_factory=list)
    source: str = "heuristic"

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "goal": self.goal,
            "trigger": self.trigger,
            "receives": self.receives,
            "checks": self.checks,
            "decisions": self.decisions,
            "can_autonomous": self.can_autonomous,
            "needs_human_approval": self.needs_human_approval,
            "forbidden": self.forbidden,
            "result": self.result,
            "missing_fields": list(self.missing_fields),
            "questions": list(self.questions),
            "source": self.source,
        }

    def format_text(self) -> str:
        lines = [
            f"ИИ-агент: {self.name or '—'}",
            f"Цель: {self.goal or '—'}",
            f"Триггер: {self.trigger or '—'}",
            f"Получает: {self.receives or '—'}",
            f"Проверяет: {self.checks or '—'}",
            f"Принимает решения: {self.decisions or '—'}",
            f"Может самостоятельно: {self.can_autonomous or '—'}",
            f"Требует подтверждения человека: {self.needs_human_approval or '—'}",
            f"Не может: {self.forbidden or '—'}",
            f"Результат: {self.result or '—'}",
        ]
        return "\n".join(lines)




def draft_passport(
    *,
    bp_name: str,
    excerpt: str,
    functions: list[ExtractedFunction],
    agent_name: str | None = None,
) -> AgentPassport:
    """Собрать черновик паспорта (LLM, иначе эвристика)."""
    normalized = [fn.with_derived_approval() for fn in functions if fn.name.strip()]
    if not normalized:
        raise ValueError("Нужна хотя бы одна функция для паспорта агента")

    llm_result = _draft_with_llm(bp_name, excerpt, normalized)
    if llm_result is not None:
        passport = llm_result
        passport.source = "llm"
    else:
        passport = _heuristic_draft(bp_name, excerpt, normalized)
        passport.source = "heuristic"

    if agent_name and agent_name.strip():
        passport.name = agent_name.strip()
    elif not passport.name.strip():
        passport.name = (bp_name or "ИИ-агент").strip()

    return _with_gaps(
        passport,
        bp_name=bp_name,
        excerpt=excerpt,
        functions=normalized,
    )


def complete_passport(
    passport: AgentPassport,
    *,
    answers: dict[str, str] | None = None,
    field_updates: dict[str, str] | None = None,
    bp_name: str = "",
    excerpt: str = "",
    functions: list[ExtractedFunction] | None = None,
) -> AgentPassport:
    """Закрыть пробелы ответами; неясные ответы — уточняющий вопрос LLM."""
    data = passport.as_dict()
    prev_prompts = {
        str(q.get("field")): str(q.get("prompt") or "")
        for q in (passport.questions or [])
        if isinstance(q, dict) and q.get("field")
    }

    # Прямые правки полей (редактирование карточки) — без доп. проверки.
    for key, value in (field_updates or {}).items():
        if key in PASSPORT_FIELDS and str(value).strip():
            data[key] = str(value).strip()

    # Ответы на вопросы: LLM принимает или просит уточнить.
    answer_updates: dict[str, str] = {}
    for key, value in (answers or {}).items():
        if key in PASSPORT_FIELDS:
            answer_updates[key] = value
        elif key.startswith("q_"):
            field_name = key[2:]
            if field_name in PASSPORT_FIELDS:
                answer_updates[field_name] = value

    follow_ups: list[dict] = []
    agent_name = str(data.get("name") or bp_name or "агента")
    for field_name, raw_answer in answer_updates.items():
        answer = str(raw_answer or "").strip()
        if not answer:
            continue
        verdict = _evaluate_passport_answer(
            field=field_name,
            answer=answer,
            question=prev_prompts.get(field_name, ""),
            current=str(data.get(field_name) or ""),
            passport_data=data,
        )

        if verdict.get("accepted"):
            normalized = str(verdict.get("normalized_value") or answer).strip()
            if normalized:
                data[field_name] = normalized
            # Политика «только чтение» закрывает и «может самостоятельно».
            if field_name == "forbidden" and _is_read_only_policy(answer):
                if not str(data.get("can_autonomous") or "").strip():
                    data["can_autonomous"] = "Только чтение данных."
                if not str(data.get("needs_human_approval") or "").strip():
                    data["needs_human_approval"] = (
                        "Любые действия сверх чтения данных."
                    )
        else:
            follow_up = str(verdict.get("follow_up") or "").strip()
            if not follow_up or _looks_robotic_question(follow_up):
                follow_up = _human_field_question(
                    field_name,
                    agent_name,
                    excerpt=excerpt,
                    functions=functions,
                )
            elif (
                field_name in _QUOTE_WORTHY_FIELDS
                and excerpt
                and "отрывке регламента указано" not in follow_up.casefold()
            ):
                quote = _pick_regulation_quote(
                    excerpt, field_name, functions, min_score=2
                )
                follow_up = _with_regulation_quote(follow_up, quote)
            follow_ups.append(
                {
                    "id": f"q_{field_name}",
                    "field": field_name,
                    "prompt": follow_up,
                }
            )

    updated = AgentPassport(
        name=str(data.get("name") or ""),
        goal=str(data.get("goal") or ""),
        trigger=str(data.get("trigger") or ""),
        receives=str(data.get("receives") or ""),
        checks=str(data.get("checks") or ""),
        decisions=str(data.get("decisions") or ""),
        can_autonomous=str(data.get("can_autonomous") or ""),
        needs_human_approval=str(data.get("needs_human_approval") or ""),
        forbidden=str(data.get("forbidden") or ""),
        result=str(data.get("result") or ""),
        source=str(data.get("source") or passport.source),
    )
    result = _with_gaps(
        updated,
        bp_name=bp_name or updated.name,
        excerpt=excerpt,
        functions=functions or [],
    )

    if follow_ups:
        follow_fields = {str(item["field"]) for item in follow_ups}
        # Поля с неясным ответом остаются открытыми.
        for field_name in follow_fields:
            setattr(result, field_name, "")
            if field_name not in result.missing_fields:
                result.missing_fields.insert(0, field_name)
        # Без дублей, follow-up поля — в начале.
        ordered_missing: list[str] = []
        for field_name in list(follow_fields) + list(result.missing_fields):
            if field_name not in ordered_missing:
                ordered_missing.append(field_name)
        result.missing_fields = ordered_missing
        other = [
            q
            for q in result.questions
            if isinstance(q, dict) and str(q.get("field")) not in follow_fields
        ]
        result.questions = follow_ups + other

    return result


def _fold(text: str) -> str:
    return str(text or "").casefold().replace("ё", "е")


def _is_read_only_policy(answer: str) -> bool:
    low = _fold(answer)
    return any(
        p in low
        for p in (
            "только чтен",
            "кроме чтен",
            "только читать",
            "чтение данных",
            "только просмотр",
            "read-only",
            "readonly",
            "только read",
        )
    ) or (
        ("запрещ" in low or "нельзя" in low or "ничего" in low)
        and ("чтен" in low or "read" in low)
    )


def _normalize_scope_policy(field: str, answer: str) -> str:
    """Нормализовать явные политики ограничений; '' если не распознано."""
    text = " ".join(str(answer or "").split()).strip()
    if not text:
        return ""
    low = _fold(text)
    read_only = _is_read_only_policy(text)
    all_forbidden = read_only or any(
        p in low
        for p in (
            "все запрещ",
            "запрещено все",
            "запрещено всё",
            "всё запрещ",
            "все нельзя",
            "ничего нельзя",
            "ничего кроме",
            "запрещено всё кроме",
            "запрещено все кроме",
        )
    )

    if field == "forbidden":
        if read_only or all_forbidden:
            return (
                "Любые действия, кроме чтения данных: запись, изменение, "
                "удаление, отправка, принятие решений без человека."
            )
        if any(p in low for p in ("запрещ", "нельзя", "не может", "без права")):
            return text
        return ""

    if field == "can_autonomous":
        if read_only:
            return "Только чтение данных."
        if any(p in low for p in ("может", "самостоятельн", "автономн", "только")):
            return text
        return ""

    if field == "needs_human_approval":
        if read_only or all_forbidden:
            return "Любые действия сверх чтения данных."
        if any(
            p in low
            for p in ("подтвержд", "соглас", "человек", "вручную", "hitl", "все")
        ):
            return text
        return ""

    return ""


def _evaluate_passport_answer(
    *,
    field: str,
    answer: str,
    question: str,
    current: str,
    passport_data: dict,
) -> dict:
    """Принять ответ: ясные политики — без переспроса LLM."""
    heuristic = _evaluate_answer_heuristic(field, answer)
    policy = _normalize_scope_policy(field, answer) if field in _SCOPE_FIELDS else ""
    if policy:
        return {
            "accepted": True,
            "normalized_value": policy,
            "follow_up": "",
        }

    llm = _evaluate_answer_with_llm(
        field=field,
        answer=answer,
        question=question,
        current=current,
        passport_data=passport_data,
    )
    if llm is None:
        return heuristic
    # LLM не должна заново дробить уже принятую содержательную политику.
    if (
        field in _SCOPE_FIELDS
        and not llm.get("accepted")
        and heuristic.get("accepted")
        and len(" ".join(answer.split())) >= 12
    ):
        return heuristic
    return llm


def _evaluate_answer_with_llm(
    *,
    field: str,
    answer: str,
    question: str,
    current: str,
    passport_data: dict,
) -> dict | None:
    context_lines = []
    for key in PASSPORT_FIELDS:
        value = str(passport_data.get(key) or "").strip()
        if value:
            context_lines.append(f"- {_FIELD_LABELS[key]}: {value}")
    raw = llm_service.generate(
        _ANSWER_PROMPT.format(
            field_label=_FIELD_LABELS.get(field, field),
            field=field,
            question=question or "(не указан)",
            answer=answer,
            current=current or "(пусто)",
            passport_context="\n".join(context_lines) or "(черновик почти пуст)",
        ),
        system=_ANSWER_SYSTEM,
    )
    if not raw:
        return None
    payload = _parse_json_object(raw)
    if not isinstance(payload, dict) or "accepted" not in payload:
        return None
    accepted = bool(payload.get("accepted"))
    return {
        "accepted": accepted,
        "normalized_value": str(payload.get("normalized_value") or "").strip(),
        "follow_up": str(payload.get("follow_up") or "").strip(),
    }


def _evaluate_answer_heuristic(field: str, answer: str) -> dict:
    """Fallback без LLM: отсечь совсем пустые/короткие ответы."""
    text = " ".join(answer.split()).strip()
    low = _fold(text)
    vague = {
        "да",
        "нет",
        "ок",
        "ok",
        "хорошо",
        "не знаю",
        "хз",
        "возможно",
        "потом",
        "—",
        "-",
    }
    policy = _normalize_scope_policy(field, text) if field in _SCOPE_FIELDS else ""
    if policy:
        return {
            "accepted": True,
            "normalized_value": policy,
            "follow_up": "",
        }
    if len(text) < 3 or low in vague:
        return {
            "accepted": False,
            "normalized_value": "",
            "follow_up": _human_field_question(field, "агента"),
        }
    return {
        "accepted": True,
        "normalized_value": text,
        "follow_up": "",
    }


def passport_from_dict(data: dict | None) -> AgentPassport:
    raw = data or {}
    return AgentPassport(
        name=str(raw.get("name") or ""),
        goal=str(raw.get("goal") or ""),
        trigger=str(raw.get("trigger") or ""),
        receives=str(raw.get("receives") or ""),
        checks=str(raw.get("checks") or ""),
        decisions=str(raw.get("decisions") or ""),
        can_autonomous=str(raw.get("can_autonomous") or ""),
        needs_human_approval=str(raw.get("needs_human_approval") or ""),
        forbidden=str(raw.get("forbidden") or ""),
        result=str(raw.get("result") or ""),
        missing_fields=list(raw.get("missing_fields") or []),
        questions=list(raw.get("questions") or []),
        source=str(raw.get("source") or "heuristic"),
    )




def _with_gaps(
    passport: AgentPassport,
    *,
    bp_name: str = "",
    excerpt: str = "",
    functions: list[ExtractedFunction] | None = None,
) -> AgentPassport:
    missing: list[str] = []
    for key in PASSPORT_FIELDS:
        value = str(getattr(passport, key) or "").strip()
        if not value:
            missing.append(key)

    passport.missing_fields = missing
    if not missing:
        passport.questions = []
        return passport

    # Если есть текст регламента — сразу живые вопросы с цитатой
    # (предсказуемее, чем ждать LLM).
    if str(excerpt or "").strip():
        passport.questions = _template_questions(
            passport,
            missing,
            excerpt=excerpt,
            functions=functions,
        )
        return passport

    llm_questions = _questions_with_llm(
        passport,
        missing,
        bp_name=bp_name or passport.name,
        excerpt=excerpt,
        functions=functions or [],
    )
    if llm_questions is not None:
        passport.questions = llm_questions
    else:
        passport.questions = _template_questions(
            passport,
            missing,
            excerpt=excerpt,
            functions=functions,
        )
    return passport


def _template_questions(
    passport: AgentPassport,
    missing: list[str],
    *,
    excerpt: str = "",
    functions: list[ExtractedFunction] | None = None,
) -> list[dict]:
    name = passport.name or "агента"
    return [
        {
            "id": f"q_{key}",
            "field": key,
            "prompt": _human_field_question(
                key,
                name,
                excerpt=excerpt,
                functions=functions,
            ),
        }
        for key in missing
    ]


def _questions_with_llm(
    passport: AgentPassport,
    missing: list[str],
    *,
    bp_name: str,
    excerpt: str,
    functions: list[ExtractedFunction],
) -> list[dict] | None:
    filled_lines = []
    for key in PASSPORT_FIELDS:
        if key in missing:
            continue
        value = str(getattr(passport, key) or "").strip()
        if value:
            filled_lines.append(f"- {_FIELD_LABELS[key]} ({key}): {value}")
    missing_lines = [f"- {_FIELD_LABELS[key]} ({key})" for key in missing]
    listing = "\n".join(
        f"- {fn.name} [{fn.action_level}"
        f"{'/physical' if fn.is_physical else ''}]"
        + (f": {fn.description}" if fn.description else "")
        for fn in functions
    ) or "(нет)"

    raw = llm_service.generate(
        _QUESTIONS_PROMPT.format(
            bp_name=bp_name or passport.name or "Бизнес-процесс",
            excerpt=(excerpt or "")[:4000] or "(нет)",
            functions=listing[:3000],
            filled="\n".join(filled_lines) or "(пока пусто)",
            missing="\n".join(missing_lines),
        ),
        system=_QUESTIONS_SYSTEM,
    )
    if not raw:
        return None
    payload = _parse_json_object(raw)
    if not isinstance(payload, dict):
        return None
    items = payload.get("questions")
    if not isinstance(items, list):
        return None

    by_field: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or "").strip()
        prompt = str(item.get("prompt") or "").strip()
        if field in missing and prompt and not _looks_robotic_question(prompt):
            by_field[field] = prompt

    if not by_field:
        return None

    name = passport.name or bp_name or "агента"
    questions: list[dict] = []
    for key in missing:
        prompt = by_field.get(key)
        if not prompt:
            prompt = _human_field_question(
                key, name, excerpt=excerpt, functions=functions
            )
        elif (
            key in _QUOTE_WORTHY_FIELDS
            and excerpt
            and "отрывке регламента указано" not in prompt.casefold()
        ):
            prompt = _with_regulation_quote(
                prompt,
                _pick_regulation_quote(excerpt, key, functions, min_score=2),
            )
        questions.append({"id": f"q_{key}", "field": key, "prompt": prompt})
    return questions


def _draft_with_llm(
    bp_name: str,
    excerpt: str,
    functions: list[ExtractedFunction],
) -> AgentPassport | None:
    listing = "\n".join(
        f"- {fn.name} [{fn.action_level}"
        f"{'/physical' if fn.is_physical else ''}]"
        + (f": {fn.description}" if fn.description else "")
        for fn in functions
    )
    raw = llm_service.generate(
        _PASSPORT_PROMPT.format(
            bp_name=bp_name or "Бизнес-процесс",
            excerpt=(excerpt or "")[:6000],
            functions=listing[:4000],
        ),
        system=_PASSPORT_SYSTEM,
    )
    if not raw:
        return None
    payload = _parse_json_object(raw)
    if not isinstance(payload, dict):
        return None
    return AgentPassport(
        name=str(payload.get("name") or bp_name or "").strip(),
        goal=str(payload.get("goal") or "").strip(),
        trigger=str(payload.get("trigger") or "").strip(),
        receives=str(payload.get("receives") or "").strip(),
        checks=str(payload.get("checks") or "").strip(),
        decisions=str(payload.get("decisions") or "").strip(),
        can_autonomous=str(payload.get("can_autonomous") or "").strip(),
        needs_human_approval=str(payload.get("needs_human_approval") or "").strip(),
        forbidden=str(payload.get("forbidden") or "").strip(),
        result=str(payload.get("result") or "").strip(),
    )


def _heuristic_draft(
    bp_name: str,
    excerpt: str,
    functions: list[ExtractedFunction],
) -> AgentPassport:
    reads = [
        fn.name
        for fn in functions
        if fn.action_level in {"read", "create_draft"}
        and not fn.requires_human_approval
        and not fn.is_physical
    ]
    hitl = [fn.name for fn in functions if fn.requires_human_approval and not fn.is_physical]
    dangerous = [
        fn.name for fn in functions if fn.action_level == "dangerous"
    ]
    physical = [fn.name for fn in functions if fn.is_physical]
    writes = [
        fn.name
        for fn in functions
        if fn.action_level in {"write", "dangerous"}
        and not fn.is_physical
    ]

    text_l = f"{bp_name}\n{excerpt}".casefold()
    trigger = ""
    if any(w in text_l for w in ("заявк", "поступил", "входящ", "событи", "письм")):
        trigger = "поступило новое событие по процессу"
    receives = ""
    if "клиент" in text_l:
        receives = "клиент"
    if "договор" in text_l:
        receives = (receives + ", договор").strip(", ")
    if "заказ" in text_l:
        receives = (receives + ", заказ").strip(", ")

    checks_parts = []
    if any(w in text_l for w in ("1с", "erp")):
        checks_parts.append("1С")
    if "crm" in text_l:
        checks_parts.append("CRM")
    if "outlook" in text_l or "почт" in text_l:
        checks_parts.append("Outlook")
    checks = " → ".join(checks_parts)

    forbidden_parts = list(physical)
    forbidden_parts.extend(dangerous)
    if not forbidden_parts:
        forbidden_parts.append("проводить финансовые операции без подтверждения")

    return AgentPassport(
        name=bp_name.strip() or "ИИ-агент",
        goal=f"Выполнять процесс «{bp_name.strip()}» согласно регламенту"
        if bp_name.strip()
        else "",
        trigger=trigger,
        receives=receives,
        checks=checks,
        decisions="",
        can_autonomous=", ".join(reads) if reads else "читать данные и готовить черновики",
        needs_human_approval=", ".join(hitl)
        if hitl
        else (", ".join(writes) if writes else ""),
        forbidden=", ".join(forbidden_parts),
        result="решение + краткое объяснение по шагам",
    )


def _split_items(text: str) -> list[str]:
    if not text.strip():
        return []
    parts = re.split(r"\s*→\s*|\s*>\s*|[;,\n]+", text)
    return [p.strip() for p in parts if p.strip()]


def _guess_source(text: str) -> str:
    low = text.casefold()
    if any(x in low for x in ("1с", "1c", "erp")):
        return "1c_erp"
    if "outlook" in low or "почт" in low:
        return "outlook"
    if "crm" in low:
        return "crm"
    if "email" in low or "e-mail" in low:
        return "email"
    return "user_input"


def _guess_can_find(text: str) -> bool:
    return _guess_source(text) in {"1c_erp", "outlook", "crm", "email"}


def _parse_json_object(raw: str) -> dict | None:
    text = (raw or "").strip()
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    try:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("passport: не удалось разобрать JSON ответа LLM")
        return None
    return data if isinstance(data, dict) else None
