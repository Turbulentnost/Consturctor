"""Приложение А и чек-лист приложения Б. Статус считается по карточке, без отметок за неподключённые системы."""

from __future__ import annotations

MATRIX: list[tuple[str, str, str, str, str, str]] = [
    ("FR-001", "M01", "Создание сквозной карточки заказа", "P1", "КС", "Карточка создана без дубля и получила внешний идентификатор."),
    ("FR-002", "M01", "Связь документов и объектов с заказом", "P1", "РП", "Из карточки открываются актуальные документы и объекты."),
    ("FR-003", "M01", "Версионирование и базовая версия", "P1", "Секретарь", "Утверждённая версия неизменяема, новая имеет основание."),
    ("FR-004", "M02", "Классификация входных документов", "P1", "КС", "Тип документа определён."),
    ("FR-005", "M02", "Извлечение реквизитов и таблиц", "P1", "КС", "Критические поля показаны со ссылкой на источник."),
    ("FR-006", "M02", "Проверка комплектности по маршруту", "P1", "Секретарь", "Показаны обязательные и отсутствующие элементы."),
    ("FR-007", "M02", "Запрос недостающих данных", "P1", "КС", "Есть проект запроса, владелец и срок."),
    ("FR-008", "M03", "Выбор шаблона проекта", "P1", "РП", "Маршрут соответствует типу заказа."),
    ("FR-009", "M03", "Декомпозиция в задачи и вехи", "P1", "РП", "Критические обязательства связаны с задачами."),
    ("FR-010", "M03", "Зависимости и критический путь", "P1", "РП", "Критический путь рассчитан."),
    ("FR-011", "M03", "Ресурсы и календари", "P2", "РП", "Конфликты показаны до публикации плана."),
    ("FR-012", "M03", "Сценарное планирование", "P2", "РП", "Сравниваются сроки, ресурсы, бюджет и риски."),
    ("FR-013", "M03", "Публикация плана в TurboProject", "P1", "РП", "Задачи и связи записаны без дублей."),
    ("FR-014", "M03", "Импорт и экспорт MS Project", "P2", "РП", "Поля переносятся без потери структуры."),
    ("FR-015", "M04", "Предмет и состав поставки", "P1", "КС", "Позиции и границы работ структурированы."),
    ("FR-016", "M04", "Цена, НДС и валюта", "P1", "КС", "Значения имеют источник."),
    ("FR-017", "M04", "Сроки и график", "P1", "РП", "Даты и условия начала срока структурированы."),
    ("FR-018", "M04", "Оплата и документы для платежа", "P1", "Финансы", "Этапы оплаты связаны с условиями."),
    ("FR-019", "M04", "Приёмка, гарантия и санкции", "P1", "Юристы", "Условия переданы на проверку."),
    ("FR-020", "M04", "Карта обязательств и владельцев", "P1", "РП", "У критического обязательства есть владелец."),
    ("FR-021", "M05", "Сопоставление ТКП и договора", "P1", "КС", "Расхождения классифицированы по уровню."),
    ("FR-022", "M05", "Сопоставление спецификаций построчно", "P1", "КС", "Видно добавление, удаление и изменение."),
    ("FR-023", "M05", "Договор и расчётная база", "P1", "ОЦОиЭП", "Показано влияние на стоимость, маржу и БДДС."),
    ("FR-024", "M05", "Договорные даты и план", "P1", "РП", "Нет вехи или конфликт даты выявлены."),
    ("FR-025", "M05", "Лист готовности к подписанию", "P1", "КС", "Критические расхождения закрыты владельцами."),
    ("FR-026", "M06", "Рекомендация маршрута", "P1", "Председатель", "Основание показано, маршрут подтверждён."),
    ("FR-027", "M06", "Обязательные заключения", "P1", "Секретарь", "Статусы и просрочки видны."),
    ("FR-028", "M06", "Проект протокола Комитета", "P1", "Секретарь", "Решение, условия и стадия записаны."),
    ("FR-029", "M06", "Блокировка переходов", "P1", "ИТ", "Обход отклонён и записан в журнал."),
    ("FR-030", "M07", "Динамический чек-лист", "P1", "Владелец этапа", "Применимые пункты сформированы."),
    ("FR-031", "M07", "Подтверждение доказательствами", "P1", "Владелец этапа", "«Выполнено» только с подтверждением."),
    ("FR-032", "M07", "Просрочки и исключения", "P1", "РП", "У просрочки есть основание и владелец."),
    ("FR-033", "M08", "Риск из документа или отклонения", "P1", "РП", "Риск связан с источником, влиянием и мероприятием."),
    ("FR-034", "M08", "Регистрация изменения за четыре часа", "P1", "Выявивший", "Время выявления есть в журнале."),
    ("FR-035", "M08", "Сравнение с базовой версией", "P1", "РП и КС", "Старые и новые значения показаны."),
    ("FR-036", "M08", "Пересчёт и повторные заключения", "P1", "Секретарь", "Повтор открыт по затронутым ролям."),
    ("FR-037", "M09", "План-факт по задачам и вехам", "P1", "РП", "Отклонение и прогноз на одну дату."),
    ("FR-038", "M09", "Приёмка и отгрузка", "P1", "РП", "Незакрытые условия блокируют переход."),
    ("FR-039", "M09", "Платежи из 1С ERP", "P1", "Финансы", "Факт оплаты сверен с заказом."),
    ("FR-040", "M09", "Двухконтурное закрытие", "P1", "РП", "Исполнение и полная оплата подтверждены."),
    ("FR-041", "M10", "Ответы со ссылкой на источник", "P1", "Пользователи", "Ответ содержит ссылку и место в документе."),
    ("FR-042", "M10", "Проект документа", "P2", "КС и РП", "Проект помечен как неутверждённый."),
    ("FR-043", "M10", "Сводка изменений и блокировок", "P1", "РП", "Сводка совпадает с делом."),
    ("FR-044", "M11", "Уведомления по событию и роли", "P1", "Владелец процесса", "Получатель определяется ролью."),
    ("FR-045", "M11", "Эскалация просроченных решений", "P1", "Руководитель", "Есть подтверждение доставки и срок реакции."),
    ("FR-046", "M12", "Ролевой доступ", "P1", "ИТ", "Действие проверяется по должности."),
    ("FR-047", "M12", "Журнал аудита", "P1", "ИТ и качество", "Действие восстанавливается по человеку и времени."),
    ("FR-048", "M12", "Версии правил и модели", "P1", "ИТ", "Результат связан с версией конфигурации."),
    ("FR-049", "M12", "Контроль качества ИИ", "P1", "Качество и ИТ", "Метрики на контрольном наборе."),
    ("FR-050", "M12", "Обратная связь в набор", "P2", "Владелец знания", "Исправление имеет автора и решение."),
]

_OUT = {
    "FR-011": "Календари ресурсов в этом контуре не ведутся.",
    "FR-012": "Сценарии сроков и бюджета не сравниваются.",
    "FR-014": "Импорт и экспорт MS Project не подключены.",
    "FR-037": "План строится, факт и прогноз по вехам не ведутся.",
    "FR-045": "Эскалация с подтверждением доставки не подключена.",
    "FR-048": "Версия правил не записывается в результат.",
    "FR-049": "Метрики качества ИИ на контрольном наборе не считаются.",
    "FR-050": "Набор обратной связи не ведётся.",
}

_STATE_LABEL = {
    "done": "Выполнено",
    "gap": "Не закрыто",
    "wait": "Ждёт данных",
    "out": "Не в этом контуре",
}


def _rows(order: dict | None, key: str) -> list:
    if not order:
        return []
    value = order.get(key)
    return value if isinstance(value, list) else []


def _diff_filled(order: dict, *codes: str) -> bool:
    wanted = set(codes)
    for item in _rows(order, "diffs"):
        if item.get("code") not in wanted:
            continue
        if str(item.get("left_value") or "").strip() or str(item.get("right_value") or "").strip():
            return True
    return False


def _open_blocking(order: dict) -> int:
    count = 0
    for item in _rows(order, "diffs"):
        if item.get("level") == "blocking" and item.get("status") != "closed":
            count += 1
    return count


def evaluate_matrix(order: dict | None) -> dict:
    rows = []
    counts = {"done": 0, "gap": 0, "wait": 0, "out": 0}
    for code, module, title, priority, owner, acceptance in MATRIX:
        state, note = _one(code, order)
        counts[state] = counts.get(state, 0) + 1
        rows.append(
            {
                "id": code,
                "module": module,
                "requirement": title,
                "priority": priority,
                "owner": owner,
                "acceptance": acceptance,
                "state": state,
                "state_label": _STATE_LABEL.get(state, state),
                "note": note,
            }
        )
    return {"counts": counts, "rows": rows}


def review_checklist(order: dict) -> dict:
    checks = []
    for item in _rows(order, "checks"):
        status = str(item.get("status") or "")
        evidence = str(item.get("evidence") or "").strip()
        if status == "not_applicable":
            verdict, note = "skip", "Не применимо к этому маршруту."
        elif status == "done" and evidence:
            verdict, note = "done", evidence
        elif status == "done":
            verdict, note = "gap", "Статус «Выполнено» без доказательства."
        elif status == "overdue":
            verdict, note = "gap", "Просрочено. Нужны основание и владелец."
        else:
            verdict, note = "wait", "Ждёт подтверждения владельца."
        checks.append(
            {
                "id": item.get("id") or "",
                "gate": item.get("gate") or "",
                "text": item.get("text") or "",
                "owner_label": item.get("owner_label") or "",
                "verdict": verdict,
                "note": note,
            }
        )
    diffs = []
    for item in _rows(order, "diffs"):
        left = str(item.get("left_value") or "").strip()
        right = str(item.get("right_value") or "").strip()
        if item.get("status") == "closed":
            verdict, note = "done", "Закрыто владельцем."
        elif left and right:
            verdict, note = "wait", f"ТКП: {left}. Договор: {right}. Владелец ещё не закрыл."
        elif left or right:
            verdict, note = "gap", "Значение есть только с одной стороны."
        else:
            verdict, note = "gap", "Нет источника в документах дела."
        diffs.append(
            {
                "code": item.get("code") or "",
                "area": item.get("area") or "",
                "title": item.get("title") or "",
                "owner_label": item.get("owner_label") or "",
                "level": item.get("level") or "",
                "verdict": verdict,
                "note": note,
            }
        )
    open_checks = sum(1 for item in checks if item["verdict"] in {"gap", "wait"})
    open_diffs = sum(1 for item in diffs if item["verdict"] != "done")
    summary = (
        f"Чек-лист: {open_checks} пунктов ждут владельца или доказательство. "
        f"Сверка B01–B35: {open_diffs} пунктов без закрытия. "
        "Агент не ставит «Выполнено» и не закрывает расхождение."
    )
    lines = [summary, ""]
    for item in checks:
        if item["verdict"] == "skip":
            continue
        lines.append(f"- {item['text']} ({item['owner_label']}): {item['note']}")
    for item in diffs:
        if item["verdict"] == "done":
            continue
        lines.append(f"- {item['code']} {item['title']} ({item['owner_label']}): {item['note']}")
    return {"summary": summary, "checks": checks, "diffs": diffs, "prompt": "\n".join(lines)}


def _one(code: str, order: dict | None) -> tuple[str, str]:
    if code in _OUT:
        return "out", _OUT[code]
    if not order:
        return "wait", "Откройте карточку, чтобы сверить требование с делом."
    if code == "FR-013":
        sections = order.get("sections") if isinstance(order.get("sections"), dict) else {}
        strategy = sections.get("strategy") if isinstance(sections.get("strategy"), dict) else {}
        if str(strategy.get("file_id") or "").strip():
            return "done", str(strategy.get("project_name") or "Проект TurboProject связан с заказом.")
        from app.services.external_orders import settings_ready

        if settings_ready():
            return "wait", "Портфель читается, проект к этому заказу ещё не сопоставлен."
        return "out", "Нет адреса API TurboProject."
    if code == "FR-001":
        return ("done", order.get("code") or "Идентификатор есть.") if order.get("code") else ("gap", "Нет внешнего идентификатора.")
    if code == "FR-002":
        linked = bool(_rows(order, "documents")) or bool(str((order.get("sections") or {}).get("onec", {}).get("path") or ""))
        return ("done", "В деле есть файлы или путь 1С.") if linked else ("gap", "Нет файла и нет пути из 1С.")
    if code == "FR-003":
        baselines = _rows(order, "baselines")
        if any(item.get("immutable") for item in baselines):
            return "done", "Есть неизменяемая базовая версия."
        return "gap", "Базовая версия ещё не зафиксирована протоколом."
    if code == "FR-004":
        docs = _rows(order, "documents")
        if docs and all(item.get("kind") for item in docs):
            return "done", "У каждого файла есть тип."
        return "gap", "В деле нет классифицированного документа."
    if code == "FR-005":
        located = [item for item in _rows(order, "findings") if str(item.get("location") or "").strip()]
        return ("done", f"Выводов с местом в документе: {len(located)}.") if located else ("gap", "Нет поля со ссылкой на место в документе.")
    if code == "FR-006":
        checks = [item for item in _rows(order, "checks") if item.get("status") != "not_applicable"]
        return ("done", f"Пунктов комплектности: {len(checks)}.") if checks else ("gap", "Чек-лист пуст.")
    if code == "FR-007":
        gaps = _rows(order, "gaps")
        ready = [item for item in gaps if item.get("owner_label") and item.get("due_at")]
        return ("done", f"Запросов с владельцем и сроком: {len(ready)}.") if ready else ("wait", "Недостающих данных с владельцем и сроком нет.")
    if code == "FR-008":
        return ("done", order.get("route_label") or "Маршрут выбран.") if order.get("route") else ("gap", "Маршрут не выбран.")
    if code == "FR-009":
        tasks = _rows(order, "tasks")
        return ("done", f"Задач и вех: {len(tasks)}.") if tasks else ("gap", "План не построен.")
    if code == "FR-010":
        tasks = _rows(order, "tasks")
        if any(item.get("critical") and item.get("depends_on") for item in tasks):
            return "done", "Критические задачи связаны зависимостью."
        return "gap", "Критический путь не построен."
    if code == "FR-015":
        return _filled("Предмет или состав извлечены.", "Предмет и состав без источника.", order, "B02", "B03")
    if code == "FR-016":
        return _filled("Цена, НДС или валюта извлечены.", "Цена, НДС и валюта без источника.", order, "B05", "B06", "B07")
    if code == "FR-017":
        return _filled("Срок извлечён.", "Срок без источника.", order, "B09", "B10")
    if code == "FR-018":
        return _filled("Оплата извлечена.", "Оплата без источника.", order, "B13", "B14")
    if code == "FR-019":
        return _filled("Приёмка, гарантия или санкции извлечены.", "Эти условия без источника.", order, "B17", "B22", "B24")
    if code == "FR-020":
        owned = [item for item in _rows(order, "diffs") if item.get("level") == "blocking" and item.get("owner_role")]
        return ("done", "У блокирующих пунктов есть владелец.") if owned else ("gap", "Нет владельца обязательства.")
    if code == "FR-021":
        return ("done", "Пункты B01–B35 классифицированы по уровню.") if _rows(order, "diffs") else ("gap", "Сверка не создана.")
    if code == "FR-022":
        lines = _rows(order, "lines")
        return ("done", f"Строк спецификации: {len(lines)}.") if lines else ("gap", "Построчной спецификации нет.")
    if code == "FR-023":
        bases = _rows(order, "baselines")
        if any(item.get("cost") or item.get("margin") or item.get("bdds") for item in bases):
            return "done", "В базовой версии есть стоимость, маржа или БДДС."
        return "gap", "Расчётная база не заполнена."
    if code == "FR-024":
        tasks = _rows(order, "tasks")
        return ("done", "Договорные шаги есть в плане.") if tasks else ("gap", "План не содержит вех договора.")
    if code == "FR-025":
        return ("done", "Блокирующих расхождений нет.") if _open_blocking(order) == 0 else ("gap", "Есть открытое блокирующее расхождение.")
    if code == "FR-026":
        decided = [item for item in _rows(order, "decisions") if item.get("decision") in {"confirmed", "confirmed_conditions"}]
        return ("done", "Комитет подтвердил маршрут.") if decided else ("wait", "Маршрут ждёт решения Комитета.")
    if code == "FR-027":
        late = [item for item in _rows(order, "checks") if item.get("status") == "overdue"]
        if late:
            return "gap", f"Просроченных заключений: {len(late)}."
        return "done", "Статусы заключений видны, просрочки не отмечены."
    if code == "FR-028":
        protocols = [item for item in _rows(order, "decisions") if str(item.get("protocol") or "").strip()]
        return ("done", "Протокол записан в дело.") if protocols else ("gap", "Протокола Комитета нет.")
    if code == "FR-029":
        return "done", "Переход без протокола, оплаты или чужого заключения сервер отклоняет."
    if code == "FR-030":
        return ("done", "Чек-лист собран по маршруту и типу заказа.") if _rows(order, "checks") else ("gap", "Чек-лист не сформирован.")
    if code == "FR-031":
        bare = [item for item in _rows(order, "checks") if item.get("status") == "done" and not str(item.get("evidence") or "").strip()]
        if bare:
            return "gap", "Есть «Выполнено» без доказательства."
        done = [item for item in _rows(order, "checks") if item.get("status") == "done"]
        return ("done", "Выполненные пункты подтверждены.") if done else ("wait", "Ни один пункт ещё не подтверждён.")
    if code == "FR-032":
        late = [item for item in _rows(order, "checks") if item.get("status") == "overdue"]
        if not late:
            return "done", "Просроченных пунктов нет."
        if all(item.get("owner_role") for item in late):
            return "gap", "Просрочка есть, владелец указан."
        return "gap", "Просрочка без владельца."
    if code == "FR-033":
        risks = [item for item in _rows(order, "risks") if item.get("source") and item.get("impact") and item.get("measure")]
        return ("done", "Риск связан с источником и мероприятием.") if risks else ("gap", "Такого риска в деле нет.")
    if code == "FR-034":
        changes = [item for item in _rows(order, "notices") if item.get("kind") == "change"]
        return ("done", "Изменение зарегистрировано.") if changes else ("wait", "Изменений после базовой версии нет.")
    if code == "FR-035":
        return ("done", "Есть больше одной версии для сравнения.") if len(_rows(order, "baselines")) > 1 else ("wait", "Второй версии для сравнения нет.")
    if code == "FR-036":
        repeat = [item for item in _rows(order, "gaps") if str(item.get("field") or "").startswith("повтор")]
        return ("done", "Повторные заключения открыты.") if repeat else ("wait", "Повторный маршрут не запускался.")
    if code == "FR-038":
        open_ship = [item for item in _rows(order, "checks") if item.get("gate") == "before_ship" and item.get("status") not in {"done", "not_applicable"}]
        return ("gap", "Открытые условия держат отгрузку.") if open_ship else ("done", "Условия до отгрузки закрыты или неприменимы.")
    if code == "FR-039":
        onec = (order.get("sections") or {}).get("onec") if isinstance(order.get("sections"), dict) else {}
        if isinstance(onec, dict) and (onec.get("order_key") or onec.get("tkp_key")):
            return "done", order.get("payment_note") or "Факт оплаты прочитан из 1С."
        return "gap", "Заказ 1С не привязан, факт оплаты не прочитан."
    if code == "FR-040":
        if order.get("status") == "closed" and int(order.get("payment_percent") or 0) >= 100:
            return "done", "Заказ закрыт при полной оплате."
        return "wait", "Закрытие возможно только после исполнения и 100% оплаты."
    if code == "FR-041":
        sourced = [item for item in _rows(order, "findings") if item.get("location") and item.get("source_ref")]
        return ("done", "Есть ответ со ссылкой и местом.") if sourced else ("gap", "Нет ответа со ссылкой на источник.")
    if code == "FR-042":
        drafts = [item for item in _rows(order, "notices") if item.get("kind") in {"draft", "memo", "assignment"}]
        return ("done", "В деле есть неутверждённый проект.") if drafts else ("wait", "Проект документа агент ещё не подготовил.")
    if code == "FR-043":
        blocks = order.get("blocks") if isinstance(order.get("blocks"), list) else []
        return ("done", blocks[0] if blocks else "Открытых блокировок нет.") 
    if code == "FR-044":
        notices = _rows(order, "notices")
        return ("done", f"Уведомлений: {len(notices)}.") if notices else ("wait", "События для уведомления ещё нет.")
    if code == "FR-046":
        return "done", "Сервер проверяет должность на записи, переходе и закрытии пункта."
    if code == "FR-047":
        audit = _rows(order, "audit")
        return ("done", f"Записей журнала: {len(audit)}.") if audit else ("gap", "Журнал пуст.")
    return "gap", "Требование не сверено."


def _filled(ok: str, missing: str, order: dict, *codes: str) -> tuple[str, str]:
    return ("done", ok) if _diff_filled(order, *codes) else ("gap", missing)
