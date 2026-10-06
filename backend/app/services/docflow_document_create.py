"""Создание документов журналов «Документооборота» из форм Orchestrator.

Состав полей каждой формы взят из $metadata ERP и из того, какие реквизиты
реально заполнены в последних документах журнала (так выглядит форма в 1С).
Документ пишется черновиком: Posted=false, без запуска маршрута — провести
и отправить его человек может уже в самой 1С.

Каждый вид документа пишется только после пробы на этом же виде: проба
создаёт документ с меткой CONSTRUCTOR_PROBE, читает его обратно и удаляет.
Итог пробы запоминается в storage, повторно её не гоняем.

Базы:
* erp — OData ERP под сервисной учёткой (как поручения и входящая);
* do  — OData 1С:Документооборота под учёткой сеанса пользователя
  (сервисная учётка в базе ДО не принимается).
"""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from urllib.parse import quote

import httpx

from app.config import BACKEND_ROOT, settings

logger = logging.getLogger(__name__)

PROBE_MARK = "CONSTRUCTOR_PROBE"
EMPTY_GUID = "00000000-0000-0000-0000-000000000000"
UNDEFINED_TYPE = "StandardODATA.Undefined"
STRING_TYPE = "Edm.String"
_GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_PROBES_PATH = BACKEND_ROOT / "storage" / "docflow_create_probes.json"
_probe_lock = threading.Lock()
_LOOKUP_LIMIT = 30
_PATH_SAFE = "/()'=,:$"


class DocumentCreateError(RuntimeError):
    pass


def _enum(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    return [{"value": value, "label": label} for value, label in pairs]


USERS = "Catalog_Пользователи"
ORGS = "Catalog_Организации"
PARTNERS = "Catalog_Партнеры"
CONTRACTORS = "Catalog_Контрагенты"
DEPARTMENTS = "Catalog_СтруктураПредприятия"
GRIFS = "Catalog_ТД_ГрифыДоступа"

ORDER_FIELDS: list[dict[str, Any]] = [
    {"key": "Организация_Key", "label": "Организация", "type": "ref", "catalog": ORGS, "required": True},
    {"key": "ТемаСлужебнойЗаписки", "label": "Тема", "type": "text", "required": True, "composite": True},
    {"key": "Содержание", "label": "Содержание", "type": "textarea"},
    {"key": "ГрифДоступа_Key", "label": "Гриф доступа", "type": "ref", "catalog": GRIFS, "required": True},
    {"key": "Проект_Key", "label": "Проект", "type": "ref", "catalog": "Catalog_Проекты"},
    {"key": "Ответственный_Key", "label": "Ответственный", "type": "ref", "catalog": USERS, "required": True, "default": "me"},
    {"key": "Комментарий", "label": "Комментарий", "type": "textarea"},
]

# type: text | textarea | date | number | ref | enum | bool
# composite=True — составной реквизит 1С: строка пишется с X_Type=Edm.String.
# default="me" — ФИО вошедшего пользователя.
KINDS: dict[str, dict[str, Any]] = {
    "incoming": {
        "title": "Входящая корреспонденция",
        "journal": "correspondence",
        "base": "erp",
        "entity": "Document_ТД_ВходящаяКорреспонденция",
        "writer": "incoming",
        "mark_field": "theme",
        "fields": [
            {"key": "theme", "label": "Тема", "type": "text", "required": True},
            {"key": "partner", "label": "Партнёр (от кого)", "type": "text", "required": True},
            {"key": "department_id", "label": "Кому (подразделение)", "type": "enum", "required": True, "options_from": "departments"},
            {"key": "organization", "label": "Организация", "type": "enum", "options_from": "organizations", "default": "НП"},
            {"key": "payer", "label": "Плательщик / направление", "type": "enum", "options_from": "payers"},
            {"key": "email_sender", "label": "Email отправителя", "type": "text"},
            {"key": "content", "label": "Содержание", "type": "textarea"},
        ],
        "tables": [],
    },
    "outgoing": {
        "title": "Исходящая корреспонденция",
        "journal": "correspondence",
        "base": "erp",
        "entity": "Document_ТД_ИсходящаяКорреспонденция",
        "mark_field": "ТемаСлужебнойЗаписки",
        "defaults": {"Статус": "Подготовлен"},
        "fields": [
            {"key": "Организация_Key", "label": "Организация", "type": "ref", "catalog": ORGS, "required": True},
            {"key": "ТемаСлужебнойЗаписки", "label": "Тема", "type": "text", "required": True, "composite": True},
            {"key": "Содержание", "label": "Содержание", "type": "textarea"},
            {"key": "Контрагент_Key", "label": "Контрагент (кому)", "type": "ref", "catalog": CONTRACTORS, "required": True},
            {"key": "Партнер_Key", "label": "Партнёр", "type": "ref", "catalog": PARTNERS, "required": True, "fill_from": ("Контрагент_Key", CONTRACTORS, "Партнер_Key"), "hint": "Если пусто — партнёр контрагента"},
            {"key": "EmailПолучателяПисьма", "label": "Email получателя", "type": "text"},
            {"key": "Направление", "label": "Направление", "type": "enum", "required": True, "options": _enum(
                ("КоммерческийДиректор", "Коммерческий директор"),
                ("ПрочиеВнутренние", "Прочие внутренние"),
                ("ДиректорНПО", "Директор НПО"),
                ("ТехническийДиректор", "Технический директор"),
                ("ДиректорПроизводства2", "Директор производства"),
                ("ФинансовыйДиректор", "Финансовый директор"),
                ("ЗаместительДиректораПоЭкономическойБезопасности", "Зам. директора по экономической безопасности"),
                ("ИсполнительныйДиректор", "Исполнительный директор"),
            )},
            {"key": "НомерВходящий", "label": "Номер входящего (на что отвечаем)", "type": "text"},
            {"key": "ДатаВходящая", "label": "Дата входящего", "type": "date"},
            {"key": "ГрифДоступа_Key", "label": "Гриф доступа", "type": "ref", "catalog": GRIFS},
            {"key": "Ответственный_Key", "label": "Ответственный", "type": "ref", "catalog": USERS, "required": True, "default": "me"},
            {"key": "Комментарий", "label": "Комментарий", "type": "textarea"},
        ],
        "tables": [],
    },
    "memo": {
        "title": "Служебная записка",
        "journal": "memos",
        "base": "erp",
        "entity": "Document_ТД_СлужебнаяЗаписка",
        "mark_field": "ТемаСлужебнойЗаписки",
        "defaults": {"Статус": "НеСогласована"},
        "fields": [
            {"key": "Организация_Key", "label": "Организация", "type": "ref", "catalog": ORGS, "required": True},
            {"key": "Подразделение_Key", "label": "Подразделение", "type": "ref", "catalog": DEPARTMENTS, "required": True},
            {"key": "ТемаСлужебнойЗаписки", "label": "Тема", "type": "text", "required": True, "composite": True},
            {"key": "ТекстСлужебнойЗаписки", "label": "Текст записки", "type": "textarea", "required": True},
            {"key": "Направление", "label": "Кому (направление)", "type": "enum", "required": True, "options": _enum(
                ("ПрочиеВнутренние", "Прочие внутренние"),
                ("УправлениеДелами", "Управление делами"),
                ("ОперационныйДиректор", "Операционный директор"),
                ("ФинансовыйДиректор", "Финансовый директор"),
                ("ДиректорПоПроизводству", "Директор по производству"),
                ("НачальникСервиснойСлужбы", "Начальник сервисной службы"),
                ("РевизионнаяКомиссия", "Ревизионная комиссия"),
                ("ДиректорГлавныйКонструктор", "Директор — главный конструктор"),
            )},
            {"key": "СрокИсполнения", "label": "Срок исполнения", "type": "date"},
            {"key": "Приоритет_Key", "label": "Приоритет", "type": "ref", "catalog": "Catalog_Приоритеты"},
            {"key": "Проект_Key", "label": "Проект", "type": "ref", "catalog": "Catalog_Проекты"},
            {"key": "ГрифДоступа_Key", "label": "Гриф доступа", "type": "ref", "catalog": GRIFS},
            {"key": "Ответственный_Key", "label": "Автор (ответственный)", "type": "ref", "catalog": USERS, "required": True, "default": "me"},
            {"key": "Комментарий", "label": "Комментарий", "type": "textarea"},
        ],
        "tables": [],
    },
    "payment": {
        "title": "Заявка на расходование ДС",
        "journal": "payments",
        "base": "erp",
        "entity": "Document_ЗаявкаНаРасходованиеДенежныхСредств",
        "mark_field": "Комментарий",
        "defaults": {
            "Статус": "НеСогласована",
            "ПланированиеСуммы": "ВВалютеПлатежа",
            "ВариантОплаты": "ПредоплатаДоПоступления",
            "ВидПеречисленияВБюджет": "ИнойПлатеж",
        },
        "fields": [
            {"key": "Организация_Key", "label": "Организация", "type": "ref", "catalog": ORGS, "required": True},
            {"key": "ХозяйственнаяОперация", "label": "Хозяйственная операция", "type": "enum", "required": True, "options": _enum(
                ("ОплатаПоставщику", "Оплата поставщику"),
                ("ВыдачаДенежныхСредствПодотчетнику", "Выдача подотчётнику"),
                ("ПеречислениеВБюджет", "Перечисление в бюджет"),
                ("ВыплатаЗарплаты", "Выплата зарплаты"),
            )},
            {"key": "СуммаДокумента", "label": "Сумма", "type": "number", "required": True},
            {"key": "Валюта_Key", "label": "Валюта", "type": "ref", "catalog": "Catalog_Валюты", "required": True, "default": "руб"},
            {"key": "ФормаОплатыЗаявки", "label": "Форма оплаты", "type": "enum", "required": True, "default": "Безналичная", "options": _enum(
                ("Безналичная", "Безналичная"),
                ("Наличная", "Наличная"),
            )},
            {"key": "ЖелательнаяДатаПлатежа", "label": "Желательная дата платежа", "type": "date", "required": True},
            {"key": "Контрагент_Key", "label": "Контрагент (получатель)", "type": "ref", "catalog": CONTRACTORS},
            {"key": "Партнер_Key", "label": "Партнёр", "type": "ref", "catalog": PARTNERS},
            {"key": "БанковскийСчет_Key", "label": "Банковский счёт организации", "type": "ref", "catalog": "Catalog_БанковскиеСчетаОрганизаций"},
            {"key": "БанковскийСчетКонтрагента_Key", "label": "Банковский счёт контрагента", "type": "ref", "catalog": "Catalog_БанковскиеСчетаКонтрагентов"},
            {"key": "ПодотчетноеЛицо_Key", "label": "Подотчётное лицо", "type": "ref", "catalog": "Catalog_ФизическиеЛица"},
            {"key": "СтатьяДвиженияДенежныхСредств_Key", "label": "Статья ДДС", "type": "ref", "catalog": "Catalog_СтатьиДвиженияДенежныхСредств", "required": True},
            {"key": "ТД_ЦФО_Key", "label": "ЦФО", "type": "ref", "catalog": "Catalog_ТД_ЦФО", "required": True},
            {"key": "Подразделение_Key", "label": "Подразделение", "type": "ref", "catalog": DEPARTMENTS, "required": True},
            {"key": "НазначениеПлатежа", "label": "Назначение платежа", "type": "textarea", "required": True},
            {"key": "КтоЗаявил_Key", "label": "Кто заявил", "type": "ref", "catalog": USERS, "required": True, "default": "me"},
            {"key": "Комментарий", "label": "Комментарий", "type": "textarea"},
        ],
        "tables": [
            {
                "key": "РасшифровкаПлатежа",
                "label": "Расшифровка платежа",
                "columns": [
                    {"key": "Сумма", "label": "Сумма", "type": "number", "required": True},
                    {"key": "СтатьяДвиженияДенежныхСредств_Key", "label": "Статья ДДС", "type": "ref", "catalog": "Catalog_СтатьиДвиженияДенежныхСредств"},
                    {"key": "Комментарий", "label": "Комментарий", "type": "text"},
                ],
            }
        ],
    },
    "forwarding": {
        "title": "Поручение экспедитору",
        "journal": "forwarding",
        "base": "erp",
        "entity": "Document_ПоручениеЭкспедитору",
        "mark_field": "ОсобыеУсловияПеревозкиОписание",
        "defaults": {"ТД_Статус": "Подготовлен"},
        "fields": [
            {"key": "ТипыЗаявок", "label": "Тип заявки", "type": "enum", "required": True, "options": _enum(
                ("ЗаявкаНаПеревозТМЦ", "Перевоз ТМЦ"),
                ("ЗаявкаНаПеревозГрузовНаТерриторииБазыЛибоГРП", "Перевоз по территории базы / ГРП"),
                ("ЗаявкиНаПеревозкуГрузовВЛогистическиеКомпании", "Перевозка в логистические компании"),
                ("ПассажирскиеПеревозкиКорпоративныйТранспорт", "Пассажирские перевозки"),
                ("Такси", "Такси"),
                ("ЗаявкаНаПеревозДокументов", "Перевоз документов"),
            )},
            {"key": "СпособДоставки", "label": "Способ доставки", "type": "enum", "required": True, "options": _enum(
                ("ПоручениеЭкспедиторуСоСклада", "Со склада"),
                ("ПоручениеЭкспедиторуНаСклад", "На склад"),
                ("ПоручениеЭкспедиторуВПункте", "В пункте"),
            )},
            {"key": "ДатаВыполнения", "label": "Дата выполнения", "type": "date", "required": True},
            {"key": "Грузоотправитель_Key", "label": "Грузоотправитель", "type": "ref", "catalog": ORGS, "required": True},
            {"key": "Грузополучатель_Key", "label": "Грузополучатель", "type": "ref", "catalog": PARTNERS},
            {"key": "ТД_КонтрагентГрузополучателя_Key", "label": "Контрагент грузополучателя", "type": "ref", "catalog": CONTRACTORS},
            {"key": "АдресГрузополучателя", "label": "Адрес грузополучателя", "type": "text"},
            {"key": "АдресДоставки", "label": "Адрес доставки", "type": "text"},
            {"key": "Пункт", "label": "Пункт", "type": "text", "required": True, "composite": True},
            {"key": "Склад_Key", "label": "Склад", "type": "ref", "catalog": "Catalog_Склады"},
            {"key": "ЗонаДоставки_Key", "label": "Зона доставки", "type": "ref", "catalog": "Catalog_ЗоныДоставки", "required": True},
            {"key": "ТипТранспортногоСредства_Key", "label": "Тип транспорта", "type": "ref", "catalog": "Catalog_ТипыТранспортныхСредств"},
            {"key": "ХарактерПогрузки", "label": "Характер погрузки", "type": "enum", "options": _enum(
                ("Верхняя", "Верхняя"),
                ("Задняя", "Задняя"),
                ("Боковая", "Боковая"),
            )},
            {"key": "КоличествоМест", "label": "Количество мест", "type": "number", "required": True},
            {"key": "Вес", "label": "Вес, кг", "type": "number"},
            {"key": "Объем", "label": "Объём, м³", "type": "number"},
            {"key": "ТД_ПлательщикНаправление", "label": "Плательщик / направление", "type": "enum", "required": True, "options": _enum(
                ("ТурбулентностьДОНПроизводство1", "Турбулентность-ДОН Производство"),
                ("АЛМАЗ", "АЛМАЗ"),
                ("ГК", "ГК"),
                ("ТурбулентностьДОНРУ", "Турбулентность-ДОН РУ"),
                ("ТурбулентностьДОНМС", "Турбулентность-ДОН МС"),
                ("Метрогазсервис", "Метрогазсервис"),
                ("БМИ", "БМИ"),
            )},
            {"key": "КонтактноеЛицоГрузополучателя", "label": "Контактное лицо", "type": "text"},
            {"key": "ТелефонКонтактногоЛица", "label": "Телефон контактного лица", "type": "text"},
            {"key": "ОсобыеУсловияПеревозкиОписание", "label": "Груз и особые условия", "type": "textarea", "required": True},
            {"key": "ДополнительнаяИнформацияПоДоставке", "label": "Доп. информация по доставке", "type": "textarea"},
            {"key": "Подразделение_Key", "label": "Подразделение", "type": "ref", "catalog": DEPARTMENTS, "required": True},
            {"key": "Ответственный_Key", "label": "Ответственный", "type": "ref", "catalog": USERS, "required": True, "default": "me"},
        ],
        "tables": [],
    },
    "order": {
        "title": "Приказ",
        "journal": "orders",
        "base": "erp",
        "entity": "Document_ТД_Приказ",
        "mark_field": "ТемаСлужебнойЗаписки",
        "defaults": {"Статус": "Подготовлен"},
        "fields": ORDER_FIELDS,
        "tables": [],
    },
    "directive": {
        "title": "Распоряжение",
        "journal": "orders",
        "base": "erp",
        "entity": "Document_ТД_Распоряжение",
        "mark_field": "ТемаСлужебнойЗаписки",
        "defaults": {"Статус": "Подготовлен"},
        "fields": ORDER_FIELDS,
        "tables": [],
    },
    "incentive": {
        "title": "Приказ о мерах материального стимулирования",
        "journal": "incentives",
        "base": "do",
        "entity": "Catalog_ВнутренниеДокументы",
        "mark_field": "Заголовок",
        # Справочник.ВидыВнутреннихДокументов → «Приказ о мерах материального стимулирования».
        "fixed": {"ВидДокумента_Key": "0c0b6059-d4e6-11e7-8267-ac1f6b05524d"},
        "fields": [
            {"key": "Заголовок", "label": "Заголовок", "type": "text", "required": True},
            {"key": "employee", "label": "Депремируемый сотрудник", "type": "ref", "catalog": USERS, "required": True, "property": "Депремируемый сотрудник"},
            {"key": "percent", "label": "Процент депремирования", "type": "number", "required": True, "property": "Процент депремирования"},
            {"key": "salary_period", "label": "Период зарплаты", "type": "text", "required": True, "property": "Период зарплаты"},
            {"key": "task", "label": "Не выполненная задача", "type": "textarea", "required": True, "property": "Не выполненная задача"},
            {"key": "approver", "label": "Утверждающий руководитель", "type": "ref", "catalog": USERS, "required": True, "property": "Утверждающий руководитель"},
            {"key": "controller", "label": "Контролирующий руководитель", "type": "ref", "catalog": USERS, "property": "Контролирующий руководитель"},
            {"key": "Содержание", "label": "Содержание", "type": "textarea"},
            {"key": "Организация_Key", "label": "Организация", "type": "ref", "catalog": ORGS, "required": True},
            {"key": "Ответственный_Key", "label": "Ответственный", "type": "ref", "catalog": USERS, "required": True, "default": "me"},
            {"key": "Подготовил_Key", "label": "Подготовил", "type": "ref", "catalog": USERS, "required": True, "default": "me"},
        ],
        "tables": [],
    },
}

# Журналы, у которых уже есть своя форма создания в приложении.
EXISTING_FORMS = {"assignments": "assignment", "protocols": "protocol"}

# Присоединённые файлы БСП: у каждого документа ERP свой справочник.
FILE_CATALOGS: dict[str, str] = {
    "incoming": "Catalog_ТД_ВходящаяКорреспонденцияПрисоединенныеФайлы",
    "outgoing": "Catalog_ТД_ИсходящаяКорреспонденцияПрисоединенныеФайлы",
    "memo": "Catalog_ТД_СлужебнаяЗапискаПрисоединенныеФайлы",
    "order": "Catalog_ТД_ПриказПрисоединенныеФайлы",
    "directive": "Catalog_ТД_РаспоряжениеПрисоединенныеФайлы",
    "payment": "Catalog_ЗаявкаНаРасходованиеДенежныхСредствПрисоединенныеФайлы",
    "forwarding": "Catalog_ПоручениеЭкспедиторуПрисоединенныеФайлы",
}
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_FILES = 10

# Правая колонка формы — как в карточке документа 1С. Многострочные поля идут под колонками.
RIGHT_COLUMN: dict[str, set[str]] = {
    "incoming": {"partner", "email_sender", "payer"},
    "outgoing": {"НомерВходящий", "ДатаВходящая", "EmailПолучателяПисьма", "ГрифДоступа_Key", "Ответственный_Key"},
    "memo": {"СрокИсполнения", "Приоритет_Key", "Проект_Key", "ГрифДоступа_Key", "Ответственный_Key"},
    "payment": {
        "СуммаДокумента",
        "Валюта_Key",
        "ФормаОплатыЗаявки",
        "ЖелательнаяДатаПлатежа",
        "БанковскийСчет_Key",
        "СтатьяДвиженияДенежныхСредств_Key",
        "ТД_ЦФО_Key",
        "КтоЗаявил_Key",
    },
    "forwarding": {
        "ТипТранспортногоСредства_Key",
        "ХарактерПогрузки",
        "КоличествоМест",
        "Вес",
        "Объем",
        "ТД_ПлательщикНаправление",
        "КонтактноеЛицоГрузополучателя",
        "ТелефонКонтактногоЛица",
        "Подразделение_Key",
        "Ответственный_Key",
    },
    "order": {"ГрифДоступа_Key", "Проект_Key", "Ответственный_Key"},
    "directive": {"ГрифДоступа_Key", "Проект_Key", "Ответственный_Key"},
    "incentive": {"approver", "controller", "Ответственный_Key", "Подготовил_Key"},
}


def field_side(kind_id: str, field: dict[str, Any]) -> str:
    if field["type"] == "textarea":
        return "wide"
    return "right" if field["key"] in RIGHT_COLUMN.get(kind_id, set()) else "left"


# ---------------------------------------------------------------- OData clients


def _do_base_url() -> str:
    explicit = (settings.docflow_odata_base_url or "").strip().rstrip("/")
    if explicit:
        return explicit
    server = (settings.dok_http_server or "").strip()
    if not server:
        return ""
    port = int(settings.dok_http_port or 81)
    base_path = (settings.dok_http_base_path or "/doc").strip().rstrip("/") or "/doc"
    return f"http://{server}:{port}{base_path}/odata/standard.odata"


def _session_auth(args: dict[str, Any]) -> tuple[str, str] | None:
    user = str(args.get("erp_login") or args.get("fio") or args.get("username") or "").strip()
    password = str(args.get("erp_password") or args.get("password") or "").strip()
    return (user, password) if user and password else None


class _ODataClient:
    """Тонкий OData-клиент: без подтягивания навигации, чтобы поиск по справочникам был быстрым."""

    def __init__(self, base: str, auth: tuple[str, str], *, label: str, validate: bool) -> None:
        self.base = base.rstrip("/")
        self.auth = auth
        self.label = label
        self.validate = validate
        self.timeout = float(settings.odata_timeout_sec or 60)

    def _entity(self, entity: str) -> str:
        if not self.validate:
            return entity
        from app.services.onec_security import validate_odata_entity
        from app.services.onec_tools import _odata_allowlist, _odata_extra_entities

        return validate_odata_entity(entity, allowlist=_odata_allowlist(), extra_allowed=_odata_extra_entities())

    def _url(self, path: str) -> str:
        head, _, query = path.partition("?")
        url = f"{self.base}/{quote(head, safe=_PATH_SAFE)}"
        return f"{url}?{query}" if query else url

    def _check(self, response: httpx.Response) -> None:
        if response.status_code in {401, 403}:
            raise DocumentCreateError(f"{self.label} не приняла логин и пароль 1С")
        if response.status_code >= 400:
            from app.services.onec_tools import _parse_onec_http_error

            raise DocumentCreateError(_parse_onec_http_error(response))

    def _send(self, method: str, path: str, body: dict[str, Any] | None = None) -> httpx.Response:
        headers = {"Accept": "application/json"}
        if method == "DELETE":
            headers["If-Match"] = "*"
        with httpx.Client(timeout=self.timeout, auth=self.auth) as client:
            return client.request(method, self._url(path), json=body, headers=headers)

    def get(self, entity: str, *, filt: str = "", top: int = 20, ref_key: str = "") -> list[dict[str, Any]]:
        entity = self._entity(entity)
        if ref_key:
            path = f"{entity}(guid'{ref_key}')?$format=json"
        else:
            path = f"{entity}?$format=json&$top={top}"
            if filt:
                path += "&$filter=" + quote(filt, safe="=,'()")
        response = self._send("GET", path)
        self._check(response)
        data = response.json()
        if ref_key:
            return [data] if isinstance(data, dict) else []
        return [row for row in (data.get("value") or []) if isinstance(row, dict)]

    def post(self, entity: str, body: dict[str, Any]) -> dict[str, Any]:
        response = self._send("POST", self._entity(entity), body)
        self._check(response)
        data = response.json()
        return data if isinstance(data, dict) else {}

    def patch(self, entity: str, ref_key: str, body: dict[str, Any]) -> None:
        self._check(self._send("PATCH", f"{self._entity(entity)}(guid'{ref_key}')", body))

    def delete(self, entity: str, ref_key: str) -> None:
        response = self._send("DELETE", f"{self._entity(entity)}(guid'{ref_key}')")
        if response.status_code != 404:
            self._check(response)


def _client(kind: dict[str, Any], args: dict[str, Any]) -> _ODataClient:
    if kind["base"] == "do":
        auth = _session_auth(args)
        if not auth:
            raise DocumentCreateError("Для документов Документооборота нужен вход в 1С (ФИО и пароль сеанса)")
        base = _do_base_url()
        if not base:
            raise DocumentCreateError("Адрес базы Документооборота не настроен (DOK_HTTP_SERVER)")
        return _ODataClient(base, auth, label="База Документооборота", validate=False)
    from app.services.onec_tools import _odata_auth

    base = (settings.odata_base_url or "").strip()
    service_auth = _odata_auth({})
    if not base or not service_auth:
        raise DocumentCreateError("OData ERP не настроена (ODATA_BASE_URL и учётка)")
    return _ODataClient(base, service_auth, label="ERP", validate=True)


# ---------------------------------------------------------------- helpers


def _kind(kind_id: str) -> dict[str, Any]:
    kind = KINDS.get(str(kind_id or "").strip())
    if kind is None:
        raise DocumentCreateError(f"Неизвестный вид документа: {kind_id or '—'}. Доступно: {', '.join(KINDS)}")
    return kind


def _quote(text: str) -> str:
    return text.replace("'", "''")


def _pick(rows: list[dict[str, Any]], query: str) -> dict[str, Any] | None:
    needle = " ".join(query.split()).casefold()
    scored: list[tuple[int, int, dict[str, Any]]] = []
    for row in rows:
        name = str(row.get("Description") or "").strip()
        low = name.casefold()
        if not low:
            continue
        if low == needle:
            rank = 0
        elif low.startswith(needle):
            rank = 1
        elif needle in low:
            rank = 2
        else:
            continue
        scored.append((rank, len(low), row))
    scored.sort(key=lambda item: (item[0], item[1]))
    return scored[0][2] if scored else None


def lookup_catalog(client: _ODataClient, catalog: str, query: str, *, limit: int = _LOOKUP_LIMIT) -> list[dict[str, str]]:
    text = " ".join(str(query or "").split())
    filt = "DeletionMark eq false"
    if text:
        filt += f" and substringof('{_quote(text)}', Description)"
    rows = client.get(catalog, filt=filt, top=limit)
    items = [
        {"key": str(row.get("Ref_Key") or ""), "name": str(row.get("Description") or "").strip()}
        for row in rows
        if str(row.get("Description") or "").strip() and not row.get("IsFolder")
    ]
    items.sort(key=lambda item: (not item["name"].casefold().startswith(text.casefold()), item["name"]))
    return items


def _resolve_ref(client: _ODataClient, catalog: str, value: str, label: str) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return ""
    if _GUID_RE.match(text):
        return text
    rows = client.get(
        catalog,
        filt=f"DeletionMark eq false and substringof('{_quote(text)}', Description)",
        top=50,
    )
    chosen = _pick([row for row in rows if not row.get("IsFolder")], text)
    if chosen is None:
        raise DocumentCreateError(f"«{label}»: в 1С не найдено «{text}»")
    return str(chosen.get("Ref_Key") or "")


def _day(value: Any, label: str) -> str:
    text = str(value or "").strip()[:10]
    if not text:
        return ""
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%dT00:00:00")
        except ValueError:
            continue
    raise DocumentCreateError(f"«{label}»: дата в формате ГГГГ-ММ-ДД, получено «{text}»")


def _number(value: Any, label: str) -> float | int | None:
    text = str(value if value is not None else "").replace(" ", "").replace(",", ".").strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError as exc:
        raise DocumentCreateError(f"«{label}»: нужно число, получено «{text}»") from exc
    return int(number) if number.is_integer() else number


def _default_value(field: dict[str, Any], actor_fio: str) -> Any:
    default = field.get("default")
    if default == "me":
        return actor_fio
    return default if default is not None else ""


def _convert(
    client: _ODataClient,
    field: dict[str, Any],
    raw: Any,
) -> Any:
    kind = field["type"]
    label = field["label"]
    if kind == "ref":
        return _resolve_ref(client, field["catalog"], str(raw or ""), label)
    if kind == "date":
        return _day(raw, label)
    if kind == "number":
        return _number(raw, label)
    if kind == "bool":
        return str(raw).strip().lower() in {"1", "true", "yes", "да", "on"}
    if kind == "enum":
        text = str(raw or "").strip()
        options = field.get("options")
        if text and isinstance(options, list):
            values = {item["value"] for item in options}
            by_label = {item["label"].casefold(): item["value"] for item in options}
            if text not in values:
                text = by_label.get(text.casefold(), "")
                if not text:
                    raise DocumentCreateError(f"«{label}»: значение не из списка 1С")
        return text
    return " ".join(str(raw or "").split()) if kind == "text" else str(raw or "").strip()


def _filled(value: Any) -> bool:
    return value not in (None, "", EMPTY_GUID)


def _values_with_defaults(kind: dict[str, Any], values: dict[str, Any], actor_fio: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for field in kind["fields"]:
        raw = values.get(field["key"])
        if raw in (None, "") and field.get("default") is not None:
            raw = _default_value(field, actor_fio)
        out[field["key"]] = raw
    return out


def _missing(kind: dict[str, Any], values: dict[str, Any]) -> list[str]:
    return [
        field["label"]
        for field in kind["fields"]
        if field.get("required")
        and not field.get("fill_from")
        and not str(values.get(field["key"]) or "").strip()
    ]


def _fill_from_source(client: _ODataClient, kind: dict[str, Any], body: dict[str, Any]) -> None:
    """Реквизит, который 1С требует, но в форме можно не вводить: берём его из выбранного объекта."""
    for field in kind["fields"]:
        source = field.get("fill_from")
        if not source or _filled(body.get(field["key"])):
            continue
        source_key, catalog, attribute = source
        ref = body.get(source_key)
        if _filled(ref):
            rows = client.get(catalog, ref_key=str(ref))
            value = str(rows[0].get(attribute) or "") if rows else ""
            if _filled(value):
                body[field["key"]] = value
                continue
        if field.get("required"):
            raise DocumentCreateError(f"Укажите «{field['label']}»: 1С не сохранит документ без него")


def _sample(client: _ODataClient, entity: str) -> dict[str, Any]:
    try:
        rows = client.get(entity, top=1)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Образец %s не прочитан: %s", entity, exc)
        return {}
    return rows[0] if rows else {}


def _composite_defaults(sample: dict[str, Any], body: dict[str, Any]) -> None:
    """Каждый составной реквизит 1С требует X_Type. Пустые — Undefined."""
    for key in sample:
        if not str(key).endswith("_Type"):
            continue
        base = str(key)[: -len("_Type")]
        if key in body:
            continue
        if _filled(body.get(base)):
            body[key] = STRING_TYPE
            continue
        body[key] = UNDEFINED_TYPE
        body[base] = ""


def build_body(
    kind_id: str,
    values: dict[str, Any],
    *,
    client: _ODataClient,
    actor_fio: str,
    tables: dict[str, Any] | None = None,
    sample: dict[str, Any] | None = None,
) -> dict[str, Any]:
    kind = _kind(kind_id)
    merged = _values_with_defaults(kind, values, actor_fio)
    missing = _missing(kind, merged)
    if missing:
        raise DocumentCreateError("Заполните обязательные поля: " + ", ".join(missing))
    body: dict[str, Any] = {"DeletionMark": False}
    if kind["base"] == "erp":
        body["Posted"] = False
        body["Date"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    body.update(kind.get("defaults") or {})
    body.update(kind.get("fixed") or {})
    properties: list[tuple[str, Any, dict[str, Any]]] = []
    for field in kind["fields"]:
        raw = merged.get(field["key"])
        if not str(raw if raw is not None else "").strip():
            continue
        value = _convert(client, field, raw)
        if not _filled(value):
            continue
        if field.get("property"):
            properties.append((field["property"], value, field))
            continue
        body[field["key"]] = value
        if field.get("composite"):
            body[f"{field['key']}_Type"] = STRING_TYPE
    _fill_from_source(client, kind, body)
    if kind_id == "payment":
        body["ДатаПлатежа"] = body.get("ЖелательнаяДатаПлатежа", "")
        body["ФормаОплатыБезналичная"] = body.get("ФормаОплатыЗаявки") == "Безналичная"
        body["ФормаОплатыНаличная"] = body.get("ФормаОплатыЗаявки") == "Наличная"
    for table in kind.get("tables") or []:
        rows = _table_rows(client, table, (tables or {}).get(table["key"]))
        if not rows and kind_id == "payment":
            rows = [
                {
                    "LineNumber": "1",
                    "Сумма": body.get("СуммаДокумента"),
                    "СтатьяДвиженияДенежныхСредств_Key": body.get("СтатьяДвиженияДенежныхСредств_Key", EMPTY_GUID),
                    "Партнер_Key": body.get("Партнер_Key", EMPTY_GUID),
                    "Подразделение_Key": body.get("Подразделение_Key", EMPTY_GUID),
                    "Организация_Key": body.get("Организация_Key", EMPTY_GUID),
                }
            ]
        if rows:
            body[table["key"]] = rows
    if properties:
        body["ДополнительныеРеквизиты"] = _property_rows(client, properties)
    _composite_defaults(sample or {}, body)
    return body


def _table_rows(client: _ODataClient, table: dict[str, Any], raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        row: dict[str, Any] = {}
        for column in table["columns"]:
            value = item.get(column["key"])
            if not str(value if value is not None else "").strip():
                continue
            converted = _convert(client, column, value)
            if _filled(converted):
                row[column["key"]] = converted
        if not row:
            continue
        missing = [c["label"] for c in table["columns"] if c.get("required") and c["key"] not in row]
        if missing:
            raise DocumentCreateError(f"«{table['label']}», строка {len(rows) + 1}: заполните {', '.join(missing)}")
        row["LineNumber"] = str(len(rows) + 1)
        rows.append(row)
    return rows


_PROPERTY_CATALOG = "ChartOfCharacteristicTypes_ДополнительныеРеквизитыИСведения"


def _property_rows(client: _ODataClient, properties: list[tuple[str, Any, dict[str, Any]]]) -> list[dict[str, Any]]:
    """Дополнительные реквизиты ДО: Свойство_Key ищем по наименованию свойства."""
    rows: list[dict[str, Any]] = []
    for name, value, field in properties:
        found = client.get(_PROPERTY_CATALOG, filt=f"substringof('{_quote(name)}', Description)", top=10)
        chosen = _pick(found, name)
        if chosen is None:
            raise DocumentCreateError(f"В Документообороте нет дополнительного реквизита «{name}»")
        row: dict[str, Any] = {"LineNumber": str(len(rows) + 1), "Свойство_Key": chosen["Ref_Key"]}
        if field["type"] == "ref":
            row["Значение"] = value
            row["Значение_Type"] = f"StandardODATA.{field['catalog']}"
        elif field["type"] == "number":
            row["Значение"] = value
            row["Значение_Type"] = "Edm.Double"
        else:
            row["Значение"] = str(value)
            row["Значение_Type"] = STRING_TYPE
        rows.append(row)
    return rows


# ---------------------------------------------------------------- probes


def _probe_store() -> dict[str, Any]:
    try:
        return json.loads(_PROBES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _remember_probe(kind_id: str, result: dict[str, Any]) -> None:
    with _probe_lock:
        store = _probe_store()
        store[kind_id] = {
            "ok": bool(result.get("ok")),
            "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "entity": result.get("entity"),
            "summary": result.get("summary"),
            "error": result.get("error") or "",
            "files": bool(result.get("files")),
        }
        _PROBES_PATH.parent.mkdir(parents=True, exist_ok=True)
        _PROBES_PATH.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")


def probe_passed(kind_id: str, *, files: bool = False) -> bool:
    record = _probe_store().get(kind_id, {})
    if not record.get("ok"):
        return False
    return bool(record.get("files")) or not files or kind_id not in FILE_CATALOGS


def _delete_probe(client: _ODataClient, entity: str, ref_key: str) -> bool:
    """Физическое удаление. Пометки на удаление мало: тест остался бы в журнале."""
    if not _GUID_RE.match(ref_key or ""):
        return False
    try:
        client.delete(entity, ref_key)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Проба %s %s не удалилась: %s", entity, ref_key, exc)
    try:
        client.patch(entity, ref_key, {"DeletionMark": True})
    except Exception:  # noqa: BLE001
        pass
    return False


def _probe_values(kind_id: str, client: _ODataClient, actor_fio: str, topic: str) -> dict[str, Any]:
    """Обязательные поля пробы: первая подходящая запись справочника или первое значение списка."""
    kind = _kind(kind_id)
    values: dict[str, Any] = {}
    for field in kind["fields"]:
        if not field.get("required"):
            continue
        key = field["key"]
        if field.get("default") is not None:
            values[key] = _default_value(field, actor_fio)
            if field["type"] != "ref" or values[key]:
                continue
        if field["type"] == "ref":
            items = lookup_catalog(client, field["catalog"], "", limit=20)
            if not items:
                raise DocumentCreateError(f"Справочник {field['catalog']} пуст — проба невозможна")
            values[key] = items[0]["key"]
        elif field["type"] == "enum":
            options = field.get("options") or []
            values[key] = options[0]["value"] if options else ""
        elif field["type"] == "number":
            values[key] = 1
        elif field["type"] == "date":
            values[key] = datetime.now().strftime("%Y-%m-%d")
        else:
            values[key] = topic
    values[kind["mark_field"]] = topic
    return values


def run_probe(kind_id: str, args: dict[str, Any], *, actor_fio: str) -> dict[str, Any]:
    kind = _kind(kind_id)
    entity = kind["entity"]
    if kind.get("writer") == "incoming":
        # Документ и .msg в этот же справочник файлов пишет регистрация почты — путь уже проверен.
        result = {
            "ok": True,
            "files": True,
            "entity": entity,
            "summary": "Входящая пишется проверенным onec.incoming_correspondence_write",
        }
        _remember_probe(kind_id, result)
        return result
    client = _client(kind, args)
    topic = f"{PROBE_MARK} {datetime.now().strftime('%Y%m%d-%H%M%S')}"
    created_key = ""
    file_entity = FILE_CATALOGS.get(kind_id, "")
    file_key = ""
    try:
        values = _probe_values(kind_id, client, actor_fio, topic)
        body = build_body(kind_id, values, client=client, actor_fio=actor_fio, sample=_sample(client, entity))
        created = client.post(entity, body)
        created_key = str(created.get("Ref_Key") or "")
        if not created_key:
            raise DocumentCreateError("1С не вернула Ref_Key созданного документа")
        back = client.get(entity, ref_key=created_key)
        if not back or PROBE_MARK not in str(back[0].get(kind["mark_field"]) or ""):
            raise DocumentCreateError("Прочитанный документ не совпал с пробой")
        if file_entity:
            file_key = _post_file(
                client, file_entity, created_key, f"{PROBE_MARK}.txt", PROBE_MARK.encode("ascii"), author_key=""
            )
            stored = client.get(file_entity, ref_key=file_key)
            if not stored or str(stored[0].get("ВладелецФайла_Key") or "") != created_key:
                raise DocumentCreateError("Прикреплённый файл пробы не нашёлся у документа")
            if not _delete_probe(client, file_entity, file_key):
                raise DocumentCreateError(f"Файл пробы {file_key} не удалился — удалите его в 1С")
            file_key = ""
        if not _delete_probe(client, entity, created_key):
            result = {
                "ok": False,
                "entity": entity,
                "error": f"Тест {created_key} создан, но не удалился — удалите его в 1С",
                "test_left": created_key,
            }
        else:
            result = {
                "ok": True,
                "files": bool(file_entity),
                "entity": entity,
                "summary": f"Проба записи {kind['title']}"
                + (" с файлом" if file_entity else "")
                + ": создан, прочитан и удалён",
            }
    except Exception as exc:  # noqa: BLE001
        if file_key:
            _delete_probe(client, file_entity, file_key)
        left = bool(created_key) and not _delete_probe(client, entity, created_key)
        result = {
            "ok": False,
            "entity": entity,
            "error": str(exc),
            **({"test_left": created_key} if left else {}),
        }
    _remember_probe(kind_id, result)
    return result


# ---------------------------------------------------------------- files


def _post_file(
    client: _ODataClient, entity: str, owner_key: str, filename: str, content: bytes, *, author_key: str
) -> str:
    from app.services.erp_incoming import _build_attached_file_body

    body = _build_attached_file_body(
        document_ref_key=owner_key, filename=filename, content=content, author_key=author_key
    )
    created = client.post(entity, body)
    file_key = str(created.get("Ref_Key") or "")
    if not file_key:
        raise DocumentCreateError(f"1С не вернула ссылку на файл «{filename}»")
    try:
        # БСП считает файл занятым, пока заполнен «Редактирует».
        client.patch(entity, file_key, {"Редактирует_Key": EMPTY_GUID})
    except Exception:  # noqa: BLE001
        pass
    return file_key


def _decode_files(raw: Any) -> list[tuple[str, bytes]]:
    import base64
    import binascii

    if not raw:
        return []
    if not isinstance(raw, list):
        raise DocumentCreateError("files: список {name, base64}")
    if len(raw) > MAX_FILES:
        raise DocumentCreateError(f"Не больше {MAX_FILES} файлов за раз")
    out: list[tuple[str, bytes]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = Path(str(item.get("name") or "").strip()).name
        if not name:
            raise DocumentCreateError("У файла нет имени")
        try:
            content = base64.b64decode(str(item.get("base64") or ""), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise DocumentCreateError(f"Файл «{name}» повреждён при передаче") from exc
        if not content:
            raise DocumentCreateError(f"Файл «{name}» пустой")
        if len(content) > MAX_FILE_BYTES:
            raise DocumentCreateError(f"Файл «{name}» больше {MAX_FILE_BYTES // (1024 * 1024)} МБ")
        out.append((name, content))
    return out


def attach_files(
    kind_id: str, ref_key: str, files: list[tuple[str, bytes]], *, args: dict[str, Any], actor_fio: str
) -> dict[str, Any]:
    entity = FILE_CATALOGS.get(kind_id)
    if not entity:
        raise DocumentCreateError("К этому виду документа файлы прикрепляются в самой 1С")
    if not _GUID_RE.match(ref_key or ""):
        raise DocumentCreateError("ref_key документа должен быть GUID")
    client = _client(_kind(kind_id), args)
    try:
        author_key = _resolve_ref(client, USERS, actor_fio, "Автор") if actor_fio else ""
    except DocumentCreateError:
        author_key = ""
    attached: list[str] = []
    failed: list[dict[str, str]] = []
    for name, content in files:
        try:
            _post_file(client, entity, ref_key, name, content, author_key=author_key)
            attached.append(name)
        except Exception as exc:  # noqa: BLE001
            failed.append({"name": name, "error": str(exc)[:300]})
    return {"attached": attached, "failed": failed}


# ---------------------------------------------------------------- create


def _web_url(kind: dict[str, Any], ref_key: str) -> str:
    if not _GUID_RE.match(ref_key or ""):
        return ""
    parts = ref_key.lower().split("-")
    ref = parts[3] + parts[4] + parts[2] + parts[1] + parts[0]
    metadata = kind["entity"].replace("Document_", "Документ.").replace("Catalog_", "Справочник.")
    if kind["base"] == "do":
        base = _do_base_url().split("/odata/")[0]
    else:
        base = settings.odata_base_url.strip().rstrip("/").split("/odata/")[0]
    return f"{base}/#e1cib/data/{quote(metadata)}?ref={ref}" if base else ""


def _create_incoming(values: dict[str, Any]) -> dict[str, Any]:
    from app.services.erp_incoming import handle_incoming_correspondence_write

    result = handle_incoming_correspondence_write({**values, "action": "create", "attach_msg": "false"})
    return {
        "ref_key": str(result.get("erp_document_id") or ""),
        "number": str(result.get("number") or ""),
    }


def create_document(kind_id: str, args: dict[str, Any], *, actor_fio: str) -> dict[str, Any]:
    kind = _kind(kind_id)
    values = args.get("values") if isinstance(args.get("values"), dict) else {}
    files = _decode_files(args.get("files"))
    if files and kind_id not in FILE_CATALOGS:
        raise DocumentCreateError("К этому виду документа файлы прикрепляются в самой 1С")
    if not probe_passed(kind_id, files=bool(files)):
        probe = run_probe(kind_id, args, actor_fio=actor_fio)
        if not probe.get("ok"):
            raise DocumentCreateError(
                f"Проба записи «{kind['title']}» не прошла, документ не создан: {probe.get('error') or '—'}"
            )
    if kind.get("writer") == "incoming":
        missing = _missing(kind, _values_with_defaults(kind, values, actor_fio))
        if missing:
            raise DocumentCreateError("Заполните обязательные поля: " + ", ".join(missing))
        created = _create_incoming(_values_with_defaults(kind, values, actor_fio))
    else:
        client = _client(kind, args)
        body = build_body(
            kind_id,
            values,
            client=client,
            actor_fio=actor_fio,
            tables=args.get("tables") if isinstance(args.get("tables"), dict) else None,
            sample=_sample(client, kind["entity"]),
        )
        data = client.post(kind["entity"], body)
        created = {"ref_key": str(data.get("Ref_Key") or ""), "number": str(data.get("Number") or data.get("Code") or "")}
    ref_key = created["ref_key"]
    number = created["number"]
    title = kind["title"]
    summary = f"{title} создан(а) в 1С черновиком" + (f": {number}" if number else "")
    file_result: dict[str, Any] = {"attached": [], "failed": []}
    if files and ref_key:
        file_result = attach_files(kind_id, ref_key, files, args=args, actor_fio=actor_fio)
        if file_result["attached"]:
            summary += f". Файлов прикреплено: {len(file_result['attached'])}"
        if file_result["failed"]:
            summary += ". Не прикрепились: " + ", ".join(item["name"] for item in file_result["failed"])
    return {
        "ok": bool(ref_key),
        "summary": summary,
        "kind": kind_id,
        "entity": kind["entity"],
        "ref_key": ref_key,
        "number": number,
        "web_url": _web_url(kind, ref_key),
        **file_result,
    }


# ---------------------------------------------------------------- schema


def _incoming_options() -> dict[str, list[dict[str, str]]]:
    from app.services.erp_incoming import handle_incoming_correspondence

    meta = handle_incoming_correspondence({"action": "meta"})
    return {
        name: [{"value": str(item["code"]), "label": str(item["name"])} for item in meta.get(name) or []]
        for name in ("departments", "organizations", "payers")
    }


def schema(kind_id: str = "") -> dict[str, Any]:
    kinds = []
    incoming_options: dict[str, list[dict[str, str]]] | None = None
    for key, kind in KINDS.items():
        if kind_id and key != kind_id:
            continue
        fields = []
        for field in kind["fields"]:
            item = {k: v for k, v in field.items() if k not in {"property", "fill_from"}}
            if field.get("fill_from"):
                item["required"] = False
            item["side"] = field_side(key, field)
            if field.get("options_from"):
                if incoming_options is None:
                    try:
                        incoming_options = _incoming_options()
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Списки входящей не прочитаны: %s", exc)
                        incoming_options = {}
                item["options"] = incoming_options.get(field["options_from"], [])
            fields.append(item)
        kinds.append(
            {
                "id": key,
                "title": kind["title"],
                "journal": kind["journal"],
                "base": kind["base"],
                "fields": fields,
                "tables": kind.get("tables") or [],
                "probe_ok": probe_passed(key),
                "files": key in FILE_CATALOGS,
                "max_file_mb": MAX_FILE_BYTES // (1024 * 1024),
                "max_files": MAX_FILES,
            }
        )
    return {"summary": f"Формы создания: {len(kinds)}", "kinds": kinds, "existing_forms": EXISTING_FORMS}


# ---------------------------------------------------------------- tool


def handle_docflow_document_create(
    args: dict[str, Any],
    *,
    actor_fio: str = "",
    actor_user_id: str = "",
) -> dict[str, Any]:
    del actor_user_id
    action = str(args.get("action") or "schema").strip().lower()
    kind_id = str(args.get("kind") or "").strip()
    actor = str(args.get("fio") or actor_fio or "").strip()
    if action == "schema":
        return schema(kind_id)
    if action == "lookup":
        kind = _kind(kind_id)
        catalog = str(args.get("catalog") or "").strip()
        allowed = {
            field.get("catalog")
            for field in kind["fields"] + [c for t in kind.get("tables") or [] for c in t["columns"]]
            if field.get("catalog")
        }
        if catalog not in allowed:
            raise DocumentCreateError(f"Справочник {catalog or '—'} не используется в форме «{kind['title']}»")
        items = lookup_catalog(_client(kind, args), catalog, str(args.get("query") or ""))
        return {"summary": f"Найдено: {len(items)}", "items": items}
    if action == "probe":
        return run_probe(kind_id, args, actor_fio=actor)
    if action == "create":
        return create_document(kind_id, args, actor_fio=actor)
    raise DocumentCreateError("action: schema | lookup | probe | create")


def stub_docflow_document_create(args: dict[str, Any], **_: Any) -> dict[str, Any]:
    action = str(args.get("action") or "schema").strip().lower()
    if action == "schema":
        return schema(str(args.get("kind") or ""))
    return {"summary": "stub: OData 1С не настроена", "ok": False, "action": action}
