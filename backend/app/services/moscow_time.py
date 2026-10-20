"""Московское время для дат документов 1С.

OData ждёт наивные дату и время без Z и без смещения: это настенные часы
Europe/Moscow. datetime.now() берёт пояс машины, поэтому на сервере в UTC
документ уезжает на три часа.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

MOSCOW = ZoneInfo("Europe/Moscow")


def moscow_now() -> datetime:
    return datetime.now(MOSCOW)


def odata_moscow(value: datetime | None = None) -> str:
    """Настенные дата и время Москвы для реквизита 1С: ``ГГГГ-ММ-ДДTЧЧ:ММ:СС``."""
    if value is None:
        stamp = moscow_now()
    elif value.tzinfo is None:
        stamp = value
    else:
        stamp = value.astimezone(MOSCOW)
    return stamp.replace(microsecond=0, tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S")


def moscow_day(value: datetime | None = None) -> str:
    return odata_moscow(value)[:10]
