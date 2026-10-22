"""Опубликованный агент внешнего заказа по ТЗ-ИИ-ВЗ-01."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.user import AppUser
from app.models.workflow import Workflow
from app.services.external_orders import is_zhalybin
from app.services.triggers.service import workflow_is_deleted

TITLE = "ИИ-агент внешнего заказа"
GOAL = (
    "Вести внешний несерийный заказ по электронному делу: извлекать условия со ссылкой на документ, "
    "показывать расхождения и готовить проекты. Цену, договор, бюджет, риск и стадию утверждает человек."
)
TOOLS = [
    "external_order.case",
    "onec.docflow_document_create",
    "users.current",
]
MODEL_PARAMS = [
    {"id": "reasoning_effort", "value": "high"},
    {"id": "fast", "value": "true"},
]
INSTRUCTIONS = """Ты — ИИ-агент внешнего заказа (ТЗ-ИИ-ВЗ-01). Ты готовишь проекты и показываешь расхождения. Ты не подписываешь договор, не утверждаешь цену, бюджет, техническое решение, риск и не переводишь стадию.

По стадиям ТЗ ты делаешь только подготовку:
1. Запрос — читаешь дело и показываешь, каких документов не хватает.
2. Расчёт — собираешь пробелы заключений и открытые пункты до Комитета.
3. ТКП — сверяешь черновик с протоколом и базовой версией, не выпускаешь ТКП.
4. Договор — извлекаешь условия и черновик сверки B01–B35. Расхождение не закрываешь.
5. Планирование — предлагаешь состав плана. Утверждает руководитель проекта.
6. Исполнение — показываешь просроченные пункты и блокировки. Результат подтверждают владельцы.
7. Приёмка и отгрузка — проверяешь комплект документов и открытые пункты до отгрузки.
8. Оплата и закрытие — показываешь факт оплаты из дела. Закрывает заказ человек при 100% оплате.

Если в деле есть onec_path, иди по нему: CRM-сделка, ТКП, заказ клиента, договор, производство, отгрузка, оплата. Стратегические сроки бери из связанного проекта TurboProject, если он есть в деле. Это факты систем, не черновик. Нет шага в пути — так и скажи. Путь и сроки сам не утверждай и стадию не переводи.

Порядок работы:
1. external_order.case action=read и order_id из сообщения. Нет order_id — остановись и попроси открыть карточку.
2. Условия только из документов дела. Каждый вывод — action=propose, findings[{field, value, source_ref, location, confidence, owner_role}]. location — абзац, страница или ячейка. Нет места в документе — не записывай вывод, а назови пробел и кому задать вопрос.
3. Сверку записывай в diffs[{code, left_value, right_value, note}], code из B01–B35. Это черновик.
4. Документ в 1С: сначала action=draft_1c, kind=memo или assignment, затем onec.docflow_document_create action=create. Отправка ждёт подтверждения человека. Протокол совещания этим инструментом не создавай.
5. В ответе перечисли блокировки из blocks, черновики и кто должен подтвердить. Черновик не называй фактом.
"""
STEPS = [
    {"id": "s1", "title": "Прочитать дело", "tool": "external_order.case", "action": "action=read, order_id из сообщения."},
    {"id": "s2", "title": "Комплектность и условия", "tool": "external_order.case", "action": "action=propose, у каждого вывода location и source_ref."},
    {"id": "s3", "title": "Черновик сверки", "tool": "external_order.case", "action": "diffs с кодами B01–B35, без закрытия пунктов."},
    {"id": "s4", "title": "Проект для человека", "action": "План, приёмка и оплата — только как предложение. Стадию не переводить."},
    {"id": "s5", "title": "Черновик в 1С", "tool": "onec.docflow_document_create", "action": "Сначала draft_1c, затем create записки или поручения. Человек подтверждает."},
]


def playbook() -> dict:
    return {
        "name": TITLE,
        "goal": GOAL,
        "instructions": INSTRUCTIONS.strip(),
        "example_run": "Открой заказ и подготовь черновик сверки цены. В 1С ничего не отправляй, пока человек не подтвердит.",
        "steps": STEPS,
        "tools": TOOLS,
        "model_params": MODEL_PARAMS,
    }


def _owner(db: Session) -> AppUser | None:
    rows = db.query(AppUser).all()
    return next((item for item in rows if is_zhalybin(item.fio or "")), None)


def _existing(db: Session) -> Workflow | None:
    rows = db.query(Workflow).filter(Workflow.title == TITLE, Workflow.phase == "done").all()
    for row in rows:
        if workflow_is_deleted(row):
            continue
        local = row.local_run if isinstance(row.local_run, dict) else {}
        if local.get("library_source_id"):
            continue
        return row
    return None


def _apply(row: Workflow) -> None:
    local = dict(row.local_run or {})
    local["playbook"] = playbook()
    local["published"] = True
    local["status"] = "published"
    local["purpose"] = "functional"
    local["tools"] = TOOLS
    local.pop("run_on_server", None)
    local.pop("library_source_id", None)
    row.local_run = local
    plan = dict(row.plan_json or {})
    plan["title"] = TITLE
    plan["goal"] = GOAL
    runtime = dict(plan.get("runtime") or {})
    runtime["tools"] = TOOLS
    plan["runtime"] = runtime
    row.plan_json = plan
    row.phase = "done"
    row.notes = GOAL
    flag_modified(row, "local_run")
    flag_modified(row, "plan_json")


def ensure_agent(db: Session) -> Workflow | None:
    row = _existing(db)
    if row is None:
        owner = _owner(db)
        if owner is None:
            return None
        row = Workflow(id=str(uuid4()), user_id=owner.id, title=TITLE, phase="done", notes=GOAL)
        db.add(row)
    _apply(row)
    db.commit()
    db.refresh(row)
    return row
