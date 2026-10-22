"""Правила внешнего заказа: роли, блокировки, карточка. Агент пишет только черновики."""

from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.external_order import (
    ExternalOrder,
    ExternalOrderAudit,
    ExternalOrderCheck,
    ExternalOrderDecision,
    ExternalOrderDiff,
    ExternalOrderDocument,
    ExternalOrderFinding,
    ExternalOrderRisk,
)

ROLES: dict[str, str] = {
    "ks": "Коммерческая служба",
    "development": "Служба развития",
    "rp": "Руководитель проекта",
    "committee": "Комитет",
    "kb": "КБ и ГСПП",
    "omto": "ОМТО",
    "finance": "ОЦОиЭП и финансы",
    "production": "Производство, качество и сервис",
    "legal": "Юридическая служба",
    "it": "ИТ и администраторы",
    "viewer": "Только просмотр",
}

STAGES: dict[str, str] = {
    "request": "Запрос",
    "calc": "Расчёт",
    "tkp": "ТКП",
    "contract": "Договор",
    "plan": "Планирование",
    "execution": "Исполнение",
    "acceptance": "Приёмка и отгрузка",
    "payment": "Оплата и закрытие",
}

STATUSES: dict[str, str] = {
    "draft": "Черновик запроса",
    "collecting": "На комплектовании",
    "calculating": "На расчёте",
    "ready_committee": "Готово к Комитету",
    "rework": "На доработке",
    "confirmed": "Подтверждено",
    "confirmed_conditions": "Подтверждено с условиями",
    "tkp_issued": "ТКП выпущено",
    "contract_review": "Договор на согласовании",
    "contract_signed": "Договор подписан",
    "in_progress": "В исполнении",
    "production": "Производственный запуск",
    "acceptance": "Приёмка и отгрузка",
    "shipped": "Отгрузка",
    "awaiting_payment": "Ожидание оплаты",
    "closed": "Закрыт",
}

CHECK_STATUSES = {
    "not_applicable": "Не применимо",
    "not_started": "Не начато",
    "open": "Не начато",
    "in_progress": "В работе",
    "review": "Требует проверки",
    "done": "Выполнено",
    "overdue": "Просрочено",
    "blocked": "Заблокировано",
}

ROUTES = {
    "full": "Полный",
    "accelerated": "Ускоренный",
    "simplified": "Упрощённый",
    "recalc": "Пересчёт",
}

DESKS: dict[str, dict] = {
    "ks": {
        "title": "Рабочий стол коммерческой службы",
        "sees": ["Новые запросы", "Комплектность", "ТКП", "Договоры на сверке", "Вопросы заказчику"],
        "denied": ["Технические, финансовые и юридические заключения"],
    },
    "development": {
        "title": "Рабочий стол службы развития",
        "sees": ["Маршрут", "Нестандартные решения", "Комплект исходных данных"],
        "denied": ["Утверждение цены и договора"],
    },
    "rp": {
        "title": "Рабочий стол руководителя проекта",
        "sees": ["Портфель", "Критический путь", "Риски", "Изменения", "Предложение закрытия"],
        "denied": ["Цена", "Платёжный факт", "Юридическое решение"],
    },
    "committee": {
        "title": "Панель Комитета",
        "sees": ["Готовность пакета", "Заключения", "Решение", "Условия", "Протокол", "Базовая версия"],
        "denied": ["Удаление истории"],
    },
    "kb": {
        "title": "Заключения КБ и ГСПП",
        "sees": ["Состав", "КД", "Аналоги", "Ограничения"],
        "denied": ["Чужие заключения"],
    },
    "omto": {
        "title": "Заключения ОМТО",
        "sees": ["Цены и сроки поставки", "Критические позиции", "Логистика"],
        "denied": ["Чужие заключения"],
    },
    "finance": {
        "title": "Финансы и ОЦОиЭП",
        "sees": ["МЦР", "Себестоимость", "Маржа", "Резерв", "БДДС", "План платежей", "Факт оплаты из 1С"],
        "denied": ["Ручная правка факта оплаты"],
    },
    "production": {
        "title": "Производство, качество и сервис",
        "sees": ["Цикл и мощности", "ПСИ", "Приёмка", "СМР и ПНР"],
        "denied": ["Чужие заключения"],
    },
    "legal": {
        "title": "Юридическая служба",
        "sees": ["Расхождения договора", "Санкции", "Гарантия"],
        "denied": ["Цена и бюджет"],
    },
    "it": {
        "title": "Администрирование",
        "sees": ["Журнал аудита", "Статус интеграций", "Очередь ошибок"],
        "denied": ["Подтверждение бизнес-решений"],
    },
    "viewer": {
        "title": "Реестр",
        "sees": ["Карточки только для чтения"],
        "denied": ["Изменение заказа"],
    },
}

_CHECKS: list[tuple[str, str, str]] = [
    ("before_calc", "Запрос и ТЗ зарегистрированы", "ks"),
    ("before_calc", "Заказчик и продукт идентифицированы", "ks"),
    ("before_calc", "Количество, срок, место и границы работ определены", "ks"),
    ("before_calc", "Назначены КС и РП", "development"),
    ("before_calc", "Выбран маршрут", "development"),
    ("before_committee", "Состав и КД определены", "kb"),
    ("before_committee", "Цены и сроки закупок актуальны", "omto"),
    ("before_committee", "Производство подтвердило цикл и мощности", "production"),
    ("before_committee", "Рассчитаны МЦР, маржа, резерв и БДДС", "finance"),
    ("before_committee", "Сформированы график, риски и заключения", "rp"),
    ("before_tkp", "Есть разрешающий протокол и базовая версия", "committee"),
    ("before_tkp", "ТКП соответствует базе и условиям протокола", "ks"),
    ("before_tkp", "Срок действия исходных цен не истёк", "omto"),
    ("before_sign", "Выполнена сверка ТКП, договора и спецификаций", "ks"),
    ("before_sign", "Закрыты блокирующие расхождения", "ks"),
    ("before_sign", "Договорные даты отражены в плане", "rp"),
    ("before_sign", "Юристы подтвердили свою область", "legal"),
    ("before_sign", "Финансы подтвердили свою область", "finance"),
    ("before_sign", "РП подтвердил свою область", "rp"),
    ("before_sign", "КС подтвердила свою область", "ks"),
    ("before_sign", "Подписная версия идентична согласованной", "ks"),
    ("before_project", "Договор подписан или есть документированное основание", "ks"),
    ("before_project", "Назначены роли", "rp"),
    ("before_project", "План и бюджет утверждены", "rp"),
    ("before_project", "Условия запуска и финансирования выполнены", "finance"),
    ("before_project", "Создано электронное дело", "ks"),
    ("before_production", "КД и состав подтверждены", "kb"),
    ("before_production", "Закупки и критические позиции обеспечены", "omto"),
    ("before_production", "Ресурсы и мощности подтверждены", "production"),
    ("before_production", "Маршрут и контроль качества определены", "production"),
    ("before_production", "Незакрытые условия не затрагивают запуск", "committee"),
    ("before_psi", "Программа и методика утверждены", "production"),
    ("before_psi", "Готовность изделия подтверждена", "production"),
    ("before_psi", "Средства измерений действительны", "production"),
    ("before_psi", "Заказчик уведомлён", "ks"),
    ("before_psi", "Комплект документов подготовлен", "ks"),
    ("before_psi", "Замечания предыдущих проверок закрыты", "production"),
    ("before_ship", "Приёмка завершена", "production"),
    ("before_ship", "Комплектность, упаковка и маркировка подтверждены", "omto"),
    ("before_ship", "Документы готовы", "ks"),
    ("before_ship", "Условия оплаты и отгрузки выполнены", "finance"),
    ("before_ship", "Логистика согласована", "omto"),
    ("before_close", "Обязательства и замечания закрыты", "rp"),
    ("before_close", "Документы архивированы", "ks"),
    ("before_close", "Претензии урегулированы", "legal"),
    ("before_close", "Гарантийная передача выполнена", "production"),
    ("before_close", "Получено 100 процентов оплаты", "finance"),
    ("before_close", "Сформированы уроки проекта", "rp"),
]

_DIFFS: list[tuple[str, str, str, str, str]] = [
    ("B01", "Идентификация", "Стороны, реквизиты, номер и дата", "ks", "material"),
    ("B02", "Предмет", "Формулировка предмета и границы поставки", "ks", "blocking"),
    ("B03", "Состав", "Номенклатура, исполнения, комплектность", "kb", "blocking"),
    ("B04", "Количество", "Количество и единицы по строкам", "ks", "blocking"),
    ("B05", "Цена", "Цена строки и итоговая цена", "finance", "blocking"),
    ("B06", "НДС", "Ставка и включение в цену", "finance", "blocking"),
    ("B07", "Валюта", "Валюта цены и платежа", "finance", "blocking"),
    ("B08", "Индексация", "Формула изменения цены", "finance", "material"),
    ("B09", "Срок поставки", "Дата и начало отсчёта", "rp", "blocking"),
    ("B10", "Этапы", "Промежуточные сроки", "rp", "material"),
    ("B11", "Место поставки", "Адрес и базис", "ks", "material"),
    ("B12", "Логистика", "Транспорт, упаковка, страхование", "omto", "material"),
    ("B13", "Оплата", "Аванс, постоплата, этапы", "finance", "blocking"),
    ("B14", "Документы для оплаты", "Счёт, акт, УПД", "finance", "material"),
    ("B15", "Удержания", "Размер и условия возврата", "finance", "blocking"),
    ("B16", "Обеспечения", "Гарантии и лимиты", "finance", "material"),
    ("B17", "Приёмка", "Порядок, сроки, критерии", "production", "blocking"),
    ("B18", "ПСИ", "Программа и результат", "production", "blocking"),
    ("B19", "Документация", "Паспорт, РЭ, сертификаты", "kb", "material"),
    ("B20", "СМР и ПНР", "Состав и условия площадки", "rp", "blocking"),
    ("B21", "Обучение", "Программа и участники", "rp", "material"),
    ("B22", "Гарантия", "Срок и объём", "legal", "blocking"),
    ("B23", "Сервис", "Срок реакции и запчасти", "production", "material"),
    ("B24", "Ответственность", "Неустойки и предел", "legal", "blocking"),
    ("B25", "Односторонний отказ", "Основания и уведомление", "legal", "blocking"),
    ("B26", "Изменение договора", "Порядок согласования", "legal", "material"),
    ("B27", "Конфиденциальность", "Состав данных и срок", "legal", "material"),
    ("B28", "Качество", "Нормативы и безопасность", "production", "blocking"),
    ("B29", "Интеллектуальные права", "КД, ПО, лицензии", "legal", "material"),
    ("B30", "Приложения", "Номера, даты, версии", "ks", "blocking"),
    ("B31", "Расчётная база", "МЦР, себестоимость, маржа", "finance", "blocking"),
    ("B32", "БДДС", "График оплаты и кассовый разрыв", "finance", "blocking"),
    ("B33", "План", "Обязательства связаны с вехами", "rp", "blocking"),
    ("B34", "Решение Комитета", "Договор соответствует протоколу", "committee", "blocking"),
    ("B35", "Подписная версия", "Файл совпадает с согласованной версией", "ks", "blocking"),
]

SECTION_WRITERS = {
    "commercial": {"ks"},
    "technical": {"kb", "production"},
    "calculation": {"finance"},
    "contract": {"ks", "legal"},
    "project": {"rp"},
    "execution": {"rp", "production"},
    "finance": {"finance"},
    "closure": {"rp"},
}
LEGAL_KEYS = {"sanctions", "warranty", "liability", "termination"}
PRICE_KEYS = {"price", "vat", "currency", "discount"}
BUDGET_KEYS = {"margin", "cost", "reserve", "bdds", "mcr"}

TRANSITION_ROLES = {
    "collecting": {"ks", "development"},
    "calculating": {"ks", "development", "rp"},
    "ready_committee": {"development", "committee"},
    "rework": {"committee"},
    "tkp_issued": {"ks"},
    "contract_review": {"ks"},
    "contract_signed": {"ks"},
    "in_progress": {"rp"},
    "production": {"rp", "production"},
    "acceptance": {"rp", "production"},
    "shipped": {"rp", "ks"},
    "awaiting_payment": {"finance", "ks"},
    "closed": {"rp"},
}

STATUS_STAGE = {
    "draft": "request",
    "collecting": "request",
    "calculating": "calc",
    "ready_committee": "calc",
    "rework": "calc",
    "confirmed": "calc",
    "confirmed_conditions": "calc",
    "tkp_issued": "tkp",
    "contract_review": "contract",
    "contract_signed": "contract",
    "in_progress": "execution",
    "production": "execution",
    "acceptance": "acceptance",
    "shipped": "acceptance",
    "awaiting_payment": "payment",
    "closed": "payment",
}

_LINK_ROLES = {"ks", "development", "finance", "it"}


def settings_ready() -> bool:
    from app.config import settings

    return bool((settings.turboproject_api_base or "").strip() and (settings.turboproject_email or "").strip())


def integrations() -> list[dict[str, str]]:
    from app.services.external_order_onec import connection_label

    state, note = connection_label()
    return [
        {"system": "1С ERP", "state": state, "note": note},
        {
            "system": "TurboProject",
            "state": "подключено" if (settings_ready()) else "не настроено",
            "note": (
                "Портфель читается для стратегических сроков. "
                "Запись задач в файл проекта API не выполняет."
                if settings_ready()
                else "В backend нет адреса или учётной записи TurboProject."
            ),
        },
        {
            "system": "CRM",
            "state": state if state == "подключено" else "не настроено",
            "note": "Сделка с клиентом читается из 1С вместе с коммерческим предложением.",
        },
        {"system": "ЭДО", "state": "не подключено", "note": "Подписанная версия прикладывается как документ дела."},
    ]


class ExternalOrderError(Exception):
    def __init__(self, detail: str, status: int = 400) -> None:
        self.detail = detail
        self.status = status


def is_zhalybin(fio: str) -> bool:
    folded = (fio or "").casefold().replace("ё", "е")
    return all(token in folded for token in ("жалыбин", "максим", "дмитриевич"))


def role_from_profile(position: str, department: str) -> str:
    text = f"{position} {department}".casefold().replace("ё", "е")
    if "юрист" in text or "правов" in text:
        return "legal"
    if "омто" in text or "снабжен" in text or "логист" in text:
        return "omto"
    if any(token in text for token in ("финанс", "экономист", "оцо", "бддс")):
        return "finance"
    if any(token in text for token in ("конструктор", "гспп")) or " кб" in f" {text}":
        return "kb"
    if "комитет" in text:
        return "committee"
    if "руководитель проекта" in text or "проектн" in text:
        return "rp"
    if "развит" in text:
        return "development"
    if "коммерч" in text or "продаж" in text:
        return "ks"
    if any(token in text for token in ("производ", "качеств", "сервис")):
        return "production"
    if "администратор" in text or text.strip() in {"ит", "it"} or "информацион" in text:
        return "it"
    return "viewer"


def resolve_role(*, fio: str, position: str, department: str, as_role: str) -> str:
    asked = (as_role or "").strip()
    if is_zhalybin(fio) and asked in ROLES and asked != "viewer":
        return asked
    return role_from_profile(position, department)


def meta_for(*, fio: str, position: str, department: str, as_role: str) -> dict:
    role = resolve_role(fio=fio, position=position, department=department, as_role=as_role)
    return {
        "role": role,
        "role_label": ROLES[role],
        "can_switch": is_zhalybin(fio),
        "roles": [{"id": key, "label": label} for key, label in ROLES.items() if key != "viewer"],
        "desk": DESKS[role],
        "stages": [{"id": key, "label": label} for key, label in STAGES.items()],
        "statuses": [{"id": key, "label": label} for key, label in STATUSES.items()],
        "routes": [{"id": key, "label": label} for key, label in ROUTES.items()],
        "integrations": integrations(),
    }


def _load(raw: str) -> dict:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _dump(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False)


def _new_id() -> str:
    return uuid4().hex


def _audit(
    db: Session,
    order: ExternalOrder,
    *,
    fio: str,
    role: str,
    action: str,
    detail: str,
    before: str = "",
    after: str = "",
) -> None:
    db.add(
        ExternalOrderAudit(
            id=_new_id(),
            order_id=order.id,
            actor_fio=fio,
            actor_role=role,
            action=action,
            detail=detail,
            before_value=before,
            after_value=after,
        )
    )


def _require_business(role: str) -> None:
    if role == "it":
        raise ExternalOrderError("ИТ не подтверждает бизнес-решения", 403)
    if role == "viewer":
        raise ExternalOrderError("Для этой должности заказ только для чтения", 403)


def _require_owner(role: str, owner: str, what: str) -> None:
    _require_business(role)
    if role != owner:
        raise ExternalOrderError(f"Нельзя подтвердить {what} чужой роли", 403)


def _order(db: Session, order_id: str) -> ExternalOrder:
    row = db.get(ExternalOrder, order_id)
    if row is None:
        raise ExternalOrderError("Заказ не найден", 404)
    return row


def _tkp_block(decisions: list[ExternalOrderDecision]) -> str | None:
    ready = [
        item
        for item in decisions
        if item.decision in {"confirmed", "confirmed_conditions"}
        and item.protocol.strip()
        and item.base_version.strip()
    ]
    if not ready:
        return "Финальное ТКП заблокировано: нет протокола Комитета и базовой версии"
    if not any(item.decision == "confirmed" or item.conditions_closed for item in ready):
        return "Финальное ТКП заблокировано: условия протокола не закрыты"
    return None


def _sign_block(diffs: list[ExternalOrderDiff]) -> str | None:
    if any(item.level == "blocking" and item.status != "closed" for item in diffs):
        return "Подписание заблокировано: есть блокирующее расхождение"
    return None


def _close_block(order: ExternalOrder) -> str | None:
    if order.payment_percent < 100:
        return "Закрытие заблокировано: нет 100% оплаты"
    return None


def _onec_link(order: ExternalOrder) -> dict:
    link = _load(order.sections_json).get("onec")
    return link if isinstance(link, dict) else {}


def _onec_number(order: ExternalOrder) -> str:
    return str(_onec_link(order).get("order_number") or "").strip()


def _onec_key(order: ExternalOrder) -> str:
    return str(_onec_link(order).get("order_key") or "").strip()


def _path_label(order: ExternalOrder) -> str:
    raw = _onec_link(order).get("path") or ""
    try:
        steps = json.loads(raw) if isinstance(raw, str) and raw else []
    except json.JSONDecodeError:
        steps = []
    parts: list[str] = []
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict) or step.get("state") in {"waiting", "skip"}:
                continue
            detail = str(step.get("detail") or "").split(" · ")[0].strip()
            title = str(step.get("title") or "").strip()
            if title and detail:
                parts.append(f"{title}: {detail}")
    if parts:
        return " → ".join(parts)
    number = _onec_number(order)
    return f"Заказ {number}" if number else ""


def _payment_note(order: ExternalOrder) -> str:
    link = _load(order.sections_json).get("onec")
    if not isinstance(link, dict) or not str(link.get("order_number") or "").strip():
        return "Заказ клиента в 1С не привязан"
    return (
        f"1С заказ {link.get('order_number')}: оплачено {link.get('paid') or '0'} "
        f"из {link.get('amount') or '0'} ({order.payment_percent}%)"
    )


def blocks_for(order: ExternalOrder) -> list[str]:
    found = [
        _tkp_block(list(order.decisions)),
        _sign_block(list(order.diffs)),
        _close_block(order),
    ]
    return [item for item in found if item]


def _brief(order: ExternalOrder) -> dict:
    return {
        "id": order.id,
        "code": order.code,
        "customer": order.customer,
        "product": order.product,
        "stage": order.stage,
        "stage_label": STAGES.get(order.stage, order.stage),
        "status": order.status,
        "status_label": STATUSES.get(order.status, order.status),
        "route": order.route,
        "route_label": ROUTES.get(order.route, ""),
        "payment_percent": order.payment_percent,
        "payment_note": _payment_note(order),
        "onec_number": _onec_number(order),
        "onec_key": _onec_key(order),
        "onec_tkp_key": str(_onec_link(order).get("tkp_key") or "").strip(),
        "path_label": _path_label(order),
        "blocks": blocks_for(order),
    }


def _detail(order: ExternalOrder) -> dict:
    body = _brief(order)
    body.update(
        {
            "inn": order.inn,
            "contact": order.contact,
            "order_type": order.order_type,
            "priority": order.priority,
            "owners": _load(order.owners_json),
            "sections": _load(order.sections_json),
            "project_note": "Публикация плана в TurboProject не подключена",
            "checks": [
                {
                    "id": item.id,
                    "gate": item.gate,
                    "text": item.text,
                    "owner_role": item.owner_role,
                    "owner_label": ROLES.get(item.owner_role, item.owner_role),
                    "status": item.status,
                    "status_label": CHECK_STATUSES.get(item.status, item.status),
                    "blocking": item.blocking,
                    "due_at": item.due_at.isoformat() if item.due_at else "",
                    "evidence": item.evidence,
                    "confirmed_by": item.confirmed_by,
                }
                for item in order.checks
            ],
            "diffs": [
                {
                    "id": item.id,
                    "code": item.code,
                    "area": item.area,
                    "title": item.title,
                    "owner_role": item.owner_role,
                    "owner_label": ROLES.get(item.owner_role, item.owner_role),
                    "level": item.level,
                    "status": item.status,
                    "left_value": item.left_value,
                    "right_value": item.right_value,
                    "note": item.note,
                }
                for item in order.diffs
            ],
            "risks": [
                {
                    "id": item.id,
                    "title": item.title,
                    "impact": item.impact,
                    "measure": item.measure,
                    "source": item.source,
                    "status": item.status,
                }
                for item in order.risks
            ],
            "decisions": [
                {
                    "id": item.id,
                    "protocol": item.protocol,
                    "decision": item.decision,
                    "allowed_stage": item.allowed_stage,
                    "conditions": item.conditions,
                    "conditions_closed": item.conditions_closed,
                    "base_version": item.base_version,
                    "decided_by": item.decided_by,
                }
                for item in order.decisions
            ],
            "findings": [
                {
                    "id": item.id,
                    "field": item.field,
                    "value": item.value,
                    "source_ref": item.source_ref,
                    "location": item.location,
                    "document_id": item.document_id,
                    "confidence": item.confidence,
                    "status": item.status,
                    "owner_role": item.owner_role,
                    "proposed_by": item.proposed_by,
                }
                for item in order.findings
            ],
            "documents": [
                {
                    "id": item.id,
                    "kind": item.kind,
                    "title": item.title,
                    "version": item.version,
                    "note": item.note,
                    "file_name": item.file_name,
                    "approved": item.approved,
                    "owner_role": item.owner_role,
                }
                for item in order.documents
            ],
            "audit": [
                {
                    "id": item.id,
                    "actor_fio": item.actor_fio,
                    "actor_role": item.actor_role,
                    "action": item.action,
                    "detail": item.detail,
                    "before_value": item.before_value,
                    "after_value": item.after_value,
                }
                for item in order.audit
            ],
            "gaps": [
                {
                    "id": item.id,
                    "field": item.field,
                    "owner_role": item.owner_role,
                    "owner_label": ROLES.get(item.owner_role, item.owner_role),
                    "due_at": item.due_at.isoformat() if item.due_at else "",
                    "status": item.status,
                    "detail": item.detail,
                }
                for item in order.gaps
            ],
            "baselines": [
                {
                    "id": item.id,
                    "code": item.code,
                    "composition": item.composition,
                    "cost": item.cost,
                    "mcr": item.mcr,
                    "margin": item.margin,
                    "bdds": item.bdds,
                    "deadlines": item.deadlines,
                    "reason": item.reason,
                    "immutable": item.immutable,
                }
                for item in order.baselines
            ],
            "tasks": [
                {
                    "id": item.id,
                    "title": item.title,
                    "kind": item.kind,
                    "owner_role": item.owner_role,
                    "depends_on": item.depends_on,
                    "critical": item.critical,
                    "approved": item.approved,
                    "published": item.published,
                }
                for item in order.tasks
            ],
            "lines": [
                {
                    "id": item.id,
                    "name": item.name,
                    "qty": item.qty,
                    "amount": item.amount,
                    "change": item.change,
                }
                for item in order.lines
            ],
            "notices": [
                {
                    "id": item.id,
                    "kind": item.kind,
                    "role": item.role,
                    "title": item.title,
                    "body": item.body,
                    "mail_status": item.mail_status,
                }
                for item in order.notices
            ],
        }
    )
    return body


def list_orders(db: Session) -> list[dict]:
    rows = db.query(ExternalOrder).order_by(ExternalOrder.created_at.desc()).all()
    return [_brief(row) for row in rows]


def get_order(db: Session, order_id: str) -> dict:
    from app.services.external_order_case import refresh_overdue

    row = _order(db, order_id)
    refresh_overdue(db, row)
    db.commit()
    db.refresh(row)
    return _detail(row)


def create_order(db: Session, *, role: str, fio: str, fields: dict, allow_import: bool = False) -> dict:
    allowed = {"ks", "development"} | (_LINK_ROLES if allow_import else set())
    if role not in allowed:
        raise ExternalOrderError("Карточку создаёт коммерческая служба или служба развития", 403)
    customer = str(fields.get("customer") or "").strip()
    product = str(fields.get("product") or "").strip()
    if not customer or not product:
        raise ExternalOrderError("Нужны заказчик и продукт", 400)
    number = db.query(ExternalOrder).count() + 1
    row = ExternalOrder(
        id=_new_id(),
        code=f"ВЗ-{number:04d}",
        customer=customer,
        inn=str(fields.get("inn") or "").strip(),
        contact=str(fields.get("contact") or "").strip(),
        product=product,
        order_type=str(fields.get("order_type") or "").strip(),
        priority=str(fields.get("priority") or "").strip(),
        stage="request",
        status="draft",
        owners_json=_dump({"ks": fio if role == "ks" else "", "rp": ""}),
        sections_json=_dump({key: {} for key in SECTION_WRITERS}),
        payment_percent=0,
        created_by=fio,
    )
    db.add(row)
    db.flush()
    from app.services.external_order_case import check_seed

    for gate, text, owner in _CHECKS:
        seed = check_seed(gate, row.route, row.order_type, text)
        db.add(
            ExternalOrderCheck(
                id=_new_id(),
                order_id=row.id,
                gate=gate,
                text=text,
                owner_role=owner,
                status=seed["status"],
                evidence=seed["evidence"],
                blocking=seed["blocking"],
                due_at=seed["due_at"],
            )
        )
    for code, area, title, owner, level in _DIFFS:
        db.add(
            ExternalOrderDiff(
                id=_new_id(),
                order_id=row.id,
                code=code,
                area=area,
                title=title,
                owner_role=owner,
                level=level,
            )
        )
    _audit(db, row, fio=fio, role=role, action="create", detail=row.code)
    db.commit()
    db.refresh(row)
    return _detail(row)


def _guard_section(role: str, section: str, values: dict) -> None:
    _require_business(role)
    if role == "rp" and section == "commercial" and PRICE_KEYS & set(values):
        raise ExternalOrderError("РП не меняет цену", 403)
    if role == "rp" and section == "finance":
        raise ExternalOrderError("РП не меняет платёжный факт", 403)
    if role == "legal" and (
        section == "calculation" or (section == "commercial" and PRICE_KEYS & set(values))
    ):
        raise ExternalOrderError("Юридическая служба не утверждает цену и бюджет", 403)
    writers = SECTION_WRITERS.get(section)
    if writers is None:
        raise ExternalOrderError("Неизвестный раздел", 400)
    if role not in writers:
        raise ExternalOrderError("Этот раздел ведёт другая роль", 403)
    if section == "contract" and LEGAL_KEYS & set(values) and role != "legal":
        raise ExternalOrderError("Нельзя изменить юридическое заключение", 403)


def patch_order(db: Session, order_id: str, *, role: str, fio: str, fields: dict) -> dict:
    row = _order(db, order_id)
    _require_business(role)
    sections = fields.get("sections") if isinstance(fields.get("sections"), dict) else {}
    current = _load(row.sections_json)
    for name, values in sections.items():
        if not isinstance(values, dict):
            continue
        _guard_section(role, str(name), values)
        bucket = dict(current.get(name) or {})
        bucket.update({str(key): value for key, value in values.items()})
        current[name] = bucket
    if sections:
        row.sections_json = _dump(current)
    if "route" in fields:
        if role not in {"development", "committee"}:
            raise ExternalOrderError("Маршрут назначает служба развития или Комитет", 403)
        route = str(fields.get("route") or "")
        if route not in ROUTES:
            raise ExternalOrderError("Неизвестный маршрут", 400)
        row.route = route
        from app.services.external_order_case import retarget_checks

        retarget_checks(row)
        _audit(db, row, fio=fio, role=role, action="route", detail=route, before="", after=route)
    if isinstance(fields.get("owners"), dict) and role in {"ks", "development", "rp"}:
        owners = _load(row.owners_json)
        owners.update({str(key): str(value) for key, value in fields["owners"].items()})
        row.owners_json = _dump(owners)
    _audit(db, row, fio=fio, role=role, action="patch", detail="Карточка обновлена")
    db.commit()
    db.refresh(row)
    return _detail(row)


def _blocked(db: Session, row: ExternalOrder, fio: str, role: str, reason: str) -> None:
    from app.services.external_order_case import notify

    _audit(db, row, fio=fio, role=role, action="blocked", detail=reason)
    notify(db, row, kind="block", role=role, title="Переход заблокирован", body=reason)
    db.commit()


def _ready_block(row: ExternalOrder) -> str | None:
    from app.services.external_order_case import open_gate

    text = open_gate(row, {"before_calc", "before_committee"})
    if text:
        return f"Готово к Комитету заблокировано: {text}"
    if any(item.status == "open" for item in row.gaps):
        return "Готово к Комитету заблокировано: есть пробел без источника"
    return None


def _project_block(row: ExternalOrder) -> str | None:
    from app.services.external_order_case import open_gate

    if not str(_load(row.owners_json).get("rp") or "").strip():
        return "Проектный запуск заблокирован: не назначен руководитель проекта"
    if not any(task.approved for task in row.tasks):
        return "Проектный запуск заблокирован: базовый план не утверждён"
    if any(item.decision == "confirmed_conditions" and not item.conditions_closed for item in row.decisions):
        return "Проектный запуск заблокирован: не закрыты условия протокола"
    text = open_gate(row, {"before_project"})
    if text:
        return f"Проектный запуск заблокирован: {text}"
    return None


def _production_block(row: ExternalOrder) -> str | None:
    from app.services.external_order_case import open_gate

    price = str((_load(row.sections_json).get("commercial") or {}).get("price") or "").strip()
    if not price:
        return "Производственный запуск заблокирован: не подтверждена цена"
    text = open_gate(row, {"before_production"})
    if text:
        return f"Производственный запуск заблокирован: {text}"
    return None


def _ship_block(row: ExternalOrder) -> str | None:
    from app.services.external_order_case import open_gate

    text = open_gate(row, {"before_ship"})
    if text:
        return f"Отгрузка заблокирована: {text}"
    if not any(item.kind in {"acceptance", "shipping", "upd"} for item in row.documents):
        return "Отгрузка заблокирована: нет приёмочных документов"
    return None


def transition(db: Session, order_id: str, *, role: str, fio: str, target: str) -> dict:
    row = _order(db, order_id)
    _require_business(role)
    if target not in TRANSITION_ROLES:
        raise ExternalOrderError("Неизвестный статус", 400)
    if role not in TRANSITION_ROLES[target]:
        raise ExternalOrderError("Этот переход выполняет другая роль", 403)
    if target == "ready_committee":
        reason = _ready_block(row)
        if reason:
            _blocked(db, row, fio, role, reason)
            raise ExternalOrderError(reason, 409)
    if target == "tkp_issued":
        reason = _tkp_block(list(row.decisions))
        if reason:
            _audit(db, row, fio=fio, role=role, action="blocked", detail=reason)
            db.commit()
            raise ExternalOrderError(reason, 409)
    if target == "contract_signed":
        reason = _sign_block(list(row.diffs))
        if reason:
            _audit(db, row, fio=fio, role=role, action="blocked", detail=reason)
            db.commit()
            raise ExternalOrderError(reason, 409)
    if target == "in_progress":
        reason = _project_block(row)
        if reason:
            _blocked(db, row, fio, role, reason)
            raise ExternalOrderError(reason, 409)
    if target == "production":
        reason = _production_block(row)
        if reason:
            _blocked(db, row, fio, role, reason)
            raise ExternalOrderError(reason, 409)
    if target in {"acceptance", "shipped"}:
        reason = _ship_block(row)
        if reason:
            _blocked(db, row, fio, role, reason)
            raise ExternalOrderError(reason, 409)
    if target == "closed":
        reason = _close_block(row)
        if reason:
            _audit(db, row, fio=fio, role=role, action="blocked", detail=reason)
            db.commit()
            raise ExternalOrderError(reason, 409)
    row.status = target
    row.stage = STATUS_STAGE[target]
    _audit(db, row, fio=fio, role=role, action="transition", detail=STATUSES[target])
    db.commit()
    db.refresh(row)
    return _detail(row)


def confirm_check(db: Session, order_id: str, check_id: str, *, role: str, fio: str, evidence: str) -> dict:
    row = _order(db, order_id)
    item = next((check for check in row.checks if check.id == check_id), None)
    if item is None:
        raise ExternalOrderError("Пункт не найден", 404)
    _require_owner(role, item.owner_role, "пункт чек-листа")
    proof = (evidence or "").strip()
    if not proof:
        raise ExternalOrderError("Нужно доказательство", 400)
    item.status = "done"
    item.evidence = proof
    item.confirmed_by = fio
    _audit(db, row, fio=fio, role=role, action="confirm_check", detail=item.text)
    db.commit()
    db.refresh(row)
    return _detail(row)


def close_diff(db: Session, order_id: str, diff_id: str, *, role: str, fio: str, note: str) -> dict:
    row = _order(db, order_id)
    item = next((diff for diff in row.diffs if diff.id == diff_id), None)
    if item is None:
        raise ExternalOrderError("Пункт сверки не найден", 404)
    _require_owner(role, item.owner_role, "расхождение")
    if not (note or "").strip():
        raise ExternalOrderError("Нужно решение владельца", 400)
    item.status = "closed"
    item.note = note.strip()
    _audit(db, row, fio=fio, role=role, action="close_diff", detail=item.code)
    db.commit()
    db.refresh(row)
    return _detail(row)


def add_risk(db: Session, order_id: str, *, role: str, fio: str, fields: dict) -> dict:
    row = _order(db, order_id)
    _require_business(role)
    if role not in {"rp", "ks", "production", "finance"}:
        raise ExternalOrderError("Риск регистрирует руководитель проекта или владелец области", 403)
    title = str(fields.get("title") or "").strip()
    if not title:
        raise ExternalOrderError("Нужно название риска", 400)
    db.add(
        ExternalOrderRisk(
            id=_new_id(),
            order_id=row.id,
            title=title,
            impact=str(fields.get("impact") or ""),
            measure=str(fields.get("measure") or ""),
            source=str(fields.get("source") or ""),
            created_by=fio,
        )
    )
    _audit(db, row, fio=fio, role=role, action="risk", detail=title)
    db.commit()
    db.refresh(row)
    return _detail(row)


def add_decision(db: Session, order_id: str, *, role: str, fio: str, fields: dict) -> dict:
    row = _order(db, order_id)
    if role != "committee":
        raise ExternalOrderError("Решение Комитета фиксирует только Комитет", 403)
    decision = str(fields.get("decision") or "")
    if decision not in {"confirmed", "confirmed_conditions", "rework"}:
        raise ExternalOrderError("Неизвестное решение", 400)
    protocol = str(fields.get("protocol") or "").strip()
    base_version = str(fields.get("base_version") or "").strip()
    baseline_id = str(fields.get("baseline_id") or "").strip()
    from app.services.external_order_case import lock_baseline

    baseline = lock_baseline(row, baseline_id, base_version) if decision != "rework" else None
    if decision != "rework" and (not protocol or baseline is None):
        raise ExternalOrderError("Нужны протокол и базовая версия", 400)
    if baseline is not None and baseline not in row.baselines:
        db.add(baseline)
        db.flush()
    closed = decision == "confirmed"
    db.add(
        ExternalOrderDecision(
            id=_new_id(),
            order_id=row.id,
            protocol=protocol,
            decision=decision,
            allowed_stage=str(fields.get("allowed_stage") or "tkp"),
            conditions=str(fields.get("conditions") or ""),
            conditions_closed=closed,
            base_version=baseline.code if baseline is not None else "",
            baseline_id=baseline.id if baseline is not None else "",
            decided_by=fio,
        )
    )
    if decision == "rework":
        row.status = "rework"
    elif decision == "confirmed":
        row.status = "confirmed"
    else:
        row.status = "confirmed_conditions"
    row.stage = "calc"
    _audit(db, row, fio=fio, role=role, action="decision", detail=protocol or decision)
    db.commit()
    db.refresh(row)
    return _detail(row)


def close_conditions(
    db: Session,
    order_id: str,
    decision_id: str,
    *,
    role: str,
    fio: str,
    document_id: str = "",
) -> dict:
    from app.services.external_order_case import notify

    row = _order(db, order_id)
    if role != "committee":
        raise ExternalOrderError("Условия закрывает Комитет", 403)
    item = next((decision for decision in row.decisions if decision.id == decision_id), None)
    if item is None:
        raise ExternalOrderError("Решение не найдено", 404)
    document = next((doc for doc in row.documents if doc.id == document_id), None)
    if document is None or document.owner_role in {"", "committee"}:
        _audit(db, row, fio=fio, role=role, action="conditions_rejected", detail=item.protocol or decision_id)
        notify(
            db,
            row,
            kind="condition",
            role="committee",
            title="Условие не закрыто",
            body="Нет документа владельца заключения",
        )
        db.commit()
        raise ExternalOrderError("Закрытие условия отклонено: нет документа владельца заключения", 409)
    item.conditions_closed = True
    _audit(
        db,
        row,
        fio=fio,
        role=role,
        action="conditions_closed",
        detail=item.protocol,
        before="открыто",
        after=document.title,
    )
    db.commit()
    db.refresh(row)
    return _detail(row)


def add_document(db: Session, order_id: str, *, role: str, fio: str, fields: dict) -> dict:
    row = _order(db, order_id)
    if role not in {"ks", "development", "rp", "legal"}:
        raise ExternalOrderError("Документ в дело кладёт коммерческая служба, развитие, РП или юрист", 403)
    title = str(fields.get("title") or "").strip()
    if not title:
        raise ExternalOrderError("Нужно название документа", 400)
    db.add(
        ExternalOrderDocument(
            id=_new_id(),
            order_id=row.id,
            kind=str(fields.get("kind") or "other"),
            title=title,
            version=str(fields.get("version") or ""),
            note=str(fields.get("note") or ""),
        )
    )
    _audit(db, row, fio=fio, role=role, action="document", detail=title)
    db.commit()
    db.refresh(row)
    return _detail(row)


def propose(db: Session, order_id: str, *, fio: str, findings: list, diffs: list) -> dict:
    """Черновики агента. Фактом они становятся только после «Принять» владельцем."""
    row = _order(db, order_id)
    created = 0
    for item in findings:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or "").strip()
        value = str(item.get("value") or "").strip()
        source = str(item.get("source_ref") or "").strip()
        location = str(item.get("location") or "").strip()
        if not field or not value or not source:
            continue
        if not location:
            from app.services.external_order_case import add_gap

            add_gap(
                db,
                row,
                field=field,
                owner_role=str(item.get("owner_role") or "ks"),
                detail="Вывод без места в источнике не сохранён",
            )
            continue
        db.add(
            ExternalOrderFinding(
                id=_new_id(),
                order_id=row.id,
                field=field,
                value=value,
                source_ref=source,
                location=location,
                document_id=str(item.get("document_id") or ""),
                confidence=str(item.get("confidence") or ""),
                status="draft",
                owner_role=str(item.get("owner_role") or "ks"),
                proposed_by=fio or "агент",
            )
        )
        created += 1
    for item in diffs:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        match = next((diff for diff in row.diffs if diff.code == code), None)
        if match is None or match.status == "closed":
            continue
        match.left_value = str(item.get("left_value") or match.left_value)
        match.right_value = str(item.get("right_value") or match.right_value)
        match.note = str(item.get("note") or "")
        match.status = "draft"
        created += 1
    _audit(db, row, fio=fio or "агент", role="agent", action="propose", detail=f"черновиков: {created}")
    db.commit()
    db.refresh(row)
    body = _detail(row)
    body["proposed"] = created
    body["note"] = "Черновик не является фактом, пока владелец не нажмёт «Принять»."
    return body


def accept_finding(db: Session, order_id: str, finding_id: str, *, role: str, fio: str) -> dict:
    row = _order(db, order_id)
    item = next((finding for finding in row.findings if finding.id == finding_id), None)
    if item is None:
        raise ExternalOrderError("Вывод не найден", 404)
    _require_owner(role, item.owner_role, "вывод агента")
    item.status = "accepted"
    _audit(db, row, fio=fio, role=role, action="accept_finding", detail=item.field)
    db.commit()
    db.refresh(row)
    return _detail(row)


def draft_onec(db: Session, order_id: str, *, fio: str, fields: dict) -> dict:
    """Готовит черновик документа 1С. Саму запись делает onec.docflow_document_create после подтверждения."""
    row = _order(db, order_id)
    kind = str(fields.get("kind") or "")
    if kind not in {"memo", "assignment"}:
        raise ExternalOrderError("В 1С из этого модуля уходит только черновик записки или поручения", 400)
    title = str(fields.get("title") or "").strip()
    text = str(fields.get("text") or "").strip()
    if not title or not text:
        raise ExternalOrderError("Нужны заголовок и текст черновика", 400)
    db.add(
        ExternalOrderFinding(
            id=_new_id(),
            order_id=row.id,
            field=f"draft_1c_{kind}",
            value=text,
            source_ref=title,
            confidence="",
            status="draft",
            owner_role="ks" if kind == "memo" else "rp",
            proposed_by=fio or "агент",
        )
    )
    _audit(db, row, fio=fio or "агент", role="agent", action="draft_1c", detail=f"{kind}: {title}")
    db.commit()
    return {
        "ok": True,
        "draft": True,
        "kind": kind,
        "title": title,
        "text": text,
        "note": (
            "Это черновик, в 1С он ещё не записан. "
            "Следующий шаг — onec.docflow_document_create action=create. "
            "Человек подтверждает отправку."
        ),
    }


def invoke_tool(arguments: dict, *, fio: str) -> dict:
    from app.db.session import SessionLocal

    action = str((arguments or {}).get("action") or "read")
    order_id = str((arguments or {}).get("order_id") or "").strip()
    db = SessionLocal()
    try:
        if action == "read":
            return read_case(db, order_id)
        if action == "propose":
            return propose(
                db,
                order_id,
                fio=fio,
                findings=list((arguments or {}).get("findings") or []),
                diffs=list((arguments or {}).get("diffs") or []),
            )
        if action == "draft_1c":
            return draft_onec(db, order_id, fio=fio, fields=arguments or {})
        raise ExternalOrderError("Неизвестное действие")
    except ExternalOrderError as exc:
        raise RuntimeError(exc.detail) from exc
    finally:
        db.close()


def _order_by_onec(db: Session, ref_key: str) -> ExternalOrder | None:
    key = (ref_key or "").strip()
    if not key:
        return None
    for row in db.query(ExternalOrder).all():
        if _onec_key(row) == key:
            return row
    return None


def recent_onec_orders() -> dict:
    from app.services.external_order_onec import OnecLinkError, recent_tkp

    try:
        return recent_tkp()
    except OnecLinkError as exc:
        raise ExternalOrderError(exc.detail, exc.status) from exc


def _order_by_tkp(db: Session, ref_key: str) -> ExternalOrder | None:
    key = (ref_key or "").strip()
    if not key:
        return None
    for row in db.query(ExternalOrder).all():
        if str(_onec_link(row).get("tkp_key") or "") == key:
            return row
    return None


def import_tkp_order(db: Session, *, role: str, fio: str, ref_key: str) -> dict:
    if role not in _LINK_ROLES:
        raise ExternalOrderError(
            "Путь из 1С загружают коммерческая служба, развитие, финансы или ИТ",
            403,
        )
    key = (ref_key or "").strip()
    if not key:
        raise ExternalOrderError("Нужно коммерческое предложение из 1С", 400)
    found = _order_by_tkp(db, key)
    if found is not None:
        return _detail(found)
    from app.services.external_order_onec import OnecLinkError, trace_tkp

    try:
        traced = trace_tkp(key)
    except OnecLinkError as exc:
        raise ExternalOrderError(exc.detail, exc.status) from exc
    number = traced.get("tkp_number") or "без номера"
    customer = traced.get("counterparty") or "Контрагент из 1С"
    product = traced.get("comment") or f"ТКП {number}"
    created = create_order(
        db,
        role=role,
        fio=fio,
        fields={"customer": customer, "product": product, "inn": traced.get("inn") or ""},
        allow_import=True,
    )
    row = _order(db, created["id"])
    _apply_onec(row, traced)
    _audit(
        db,
        row,
        fio=fio,
        role=role,
        action="onec_path",
        detail=_path_label(row) or number,
    )
    db.commit()
    db.refresh(row)
    return _detail(row)


def import_onec_order(db: Session, *, role: str, fio: str, ref_key: str) -> dict:
    if role not in _LINK_ROLES:
        raise ExternalOrderError(
            "Заказ из 1С загружают коммерческая служба, развитие, финансы или ИТ",
            403,
        )
    key = (ref_key or "").strip()
    if not key:
        raise ExternalOrderError("Нужен заказ клиента из 1С", 400)
    found = _order_by_onec(db, key)
    if found is not None:
        return _detail(found)
    from app.services.external_order_onec import OnecLinkError, read_order

    try:
        preview = read_order(key)
    except OnecLinkError as exc:
        raise ExternalOrderError(exc.detail, exc.status) from exc
    number = str(preview.get("order_number") or "").strip() or "без номера"
    customer = str(preview.get("counterparty") or "").strip() or "Контрагент из 1С"
    created = create_order(
        db,
        role=role,
        fio=fio,
        fields={
            "customer": customer,
            "product": f"Заказ клиента {number}",
            "inn": str(preview.get("inn") or ""),
        },
        allow_import=True,
    )
    return link_onec(db, created["id"], role=role, fio=fio, ref_key=key)


def search_onec(query: str = "", counterparty_key: str = "") -> dict:
    from app.services.external_order_onec import OnecLinkError, search

    try:
        return search(query, counterparty_key)
    except OnecLinkError as exc:
        raise ExternalOrderError(exc.detail, exc.status) from exc


def _apply_onec(row: ExternalOrder, link: dict[str, str]) -> None:
    sections = _load(row.sections_json)
    previous = sections.get("onec") if isinstance(sections.get("onec"), dict) else {}
    flat = {key: str(value or "") for key, value in link.items() if key not in {"suggested_stage", "suggested_status"}}
    for key in ("path", "tkp_key", "tkp_number", "tkp_status", "tkp_status_label", "contract_number"):
        if not flat.get(key) and previous.get(key):
            flat[key] = str(previous.get(key) or "")
    sections["onec"] = flat
    row.sections_json = _dump(sections)
    row.payment_percent = int(link.get("payment_percent") or 0)
    if link.get("counterparty"):
        row.customer = str(link["counterparty"])
    if link.get("inn"):
        row.inn = str(link["inn"])
    stage = str(link.get("suggested_stage") or "")
    status = str(link.get("suggested_status") or "")
    if stage in STAGES:
        row.stage = stage
    if status in STATUSES:
        row.status = status


def link_onec(db: Session, order_id: str, *, role: str, fio: str, ref_key: str) -> dict:
    if role not in _LINK_ROLES:
        raise ExternalOrderError(
            "Привязку заказа 1С делает коммерческая служба, развитие, финансы или ИТ",
            403,
        )
    from app.services.external_order_onec import OnecLinkError, read_order, tkp_key_for_order, trace_tkp

    row = _order(db, order_id)
    try:
        traced = _trace_or_order(ref_key, read_order, tkp_key_for_order, trace_tkp)
    except OnecLinkError as exc:
        raise ExternalOrderError(exc.detail, exc.status) from exc
    _apply_onec(row, traced)
    _audit(
        db,
        row,
        fio=fio,
        role=role,
        action="onec_link",
        detail=_path_label(row) or f"{traced.get('order_number')} · {traced.get('payment_percent')}%",
    )
    db.commit()
    db.refresh(row)
    return _detail(row)


def refresh_onec(db: Session, order_id: str, *, role: str, fio: str) -> dict:
    if role == "viewer":
        raise ExternalOrderError("Для этой должности заказ только для чтения", 403)
    from app.services.external_order_onec import OnecLinkError, read_order, tkp_key_for_order, trace_tkp

    row = _order(db, order_id)
    saved = _load(row.sections_json).get("onec")
    saved = saved if isinstance(saved, dict) else {}
    tkp_key = str(saved.get("tkp_key") or "")
    ref_key = str(saved.get("order_key") or "")
    if not tkp_key and not ref_key:
        raise ExternalOrderError("Сначала загрузите ТКП или заказ клиента из 1С", 400)
    try:
        if tkp_key:
            traced = trace_tkp(tkp_key)
        else:
            traced = _trace_or_order(ref_key, read_order, tkp_key_for_order, trace_tkp)
    except OnecLinkError as exc:
        raise ExternalOrderError(exc.detail, exc.status) from exc
    _apply_onec(row, traced)
    _audit(db, row, fio=fio, role=role, action="onec_refresh", detail=_path_label(row) or f"{traced.get('payment_percent')}%")
    db.commit()
    db.refresh(row)
    return _detail(row)


def upload_order_file(db: Session, order_id: str, *, role: str, fio: str, fields: dict) -> dict:
    from app.services.external_order_case import store_file

    row = _order(db, order_id)
    store_file(
        db,
        row,
        role=role,
        fio=fio,
        kind=str(fields.get("kind") or "other"),
        filename=str(fields.get("filename") or ""),
        content_b64=str(fields.get("content_base64") or ""),
    )
    db.commit()
    db.refresh(row)
    return _detail(row)


def approve_order_file(db: Session, order_id: str, document_id: str, *, role: str, fio: str) -> dict:
    from app.services.external_order_case import approve_file

    row = _order(db, order_id)
    approve_file(db, row, document_id, role=role, fio=fio)
    db.commit()
    db.refresh(row)
    return _detail(row)


def delete_order_file(db: Session, order_id: str, document_id: str, *, role: str, fio: str) -> dict:
    from app.services.external_order_case import delete_file

    row = _order(db, order_id)
    delete_file(db, row, document_id, role=role, fio=fio)
    db.commit()
    db.refresh(row)
    return _detail(row)


def add_baseline(db: Session, order_id: str, *, role: str, fio: str, fields: dict) -> dict:
    from app.services.external_order_case import create_baseline

    row = _order(db, order_id)
    create_baseline(db, row, role=role, fio=fio, fields=fields)
    db.commit()
    db.refresh(row)
    return _detail(row)


def make_plan(db: Session, order_id: str, *, role: str, fio: str) -> dict:
    from app.services.external_order_case import build_plan

    row = _order(db, order_id)
    build_plan(db, row, role=role, fio=fio)
    db.commit()
    db.refresh(row)
    return _detail(row)


def accept_plan(db: Session, order_id: str, *, role: str, fio: str) -> dict:
    from app.services.external_order_case import approve_plan

    row = _order(db, order_id)
    approve_plan(db, row, role=role, fio=fio)
    db.commit()
    db.refresh(row)
    return _detail(row)


def publish_order_plan(db: Session, order_id: str, *, role: str, fio: str) -> dict:
    from app.services.external_order_case import publish_plan

    row = _order(db, order_id)
    publish_plan(db, row, role=role, fio=fio)
    db.commit()
    db.refresh(row)
    return _detail(row)


def _trace_or_order(ref_key: str, read_order, tkp_key_for_order, trace_tkp) -> dict:
    tkp_key = tkp_key_for_order(ref_key)
    if tkp_key:
        return trace_tkp(tkp_key)
    return read_order(ref_key)


def read_case(db: Session, order_id: str) -> dict:
    body = get_order(db, order_id)
    raw = ""
    sections = body.get("sections") if isinstance(body.get("sections"), dict) else {}
    onec = sections.get("onec") if isinstance(sections.get("onec"), dict) else {}
    raw = str(onec.get("path") or "")
    try:
        path = json.loads(raw) if raw else []
    except json.JSONDecodeError:
        path = []
    body["onec_path"] = path if isinstance(path, list) else []
    body["agent_limits"] = (
        "Не утверждай цену, договор, бюджет, риск и стадию. "
        "Каждый вывод указывай со ссылкой на документ и место: абзац, страница или ячейка. "
        "Без места в источнике вывод не сохранится. "
        "В 1С отправляй только черновик записки, протокола или поручения, человек подтверждает отправку. "
        "Путь заказа читай из onec_path: ТКП, заказ клиента, договор, производство, отгрузка, оплата. "
        "Не придумывай документы, которых в этом пути нет. Стадию по пути не переводи."
    )
    return body
