"""Оклад и базовая премия сотрудника из 1С:ЗУП (OData) для денежной формы ИЦПП.

Значения берутся срезом последних периодического регистра показателей расчёта
зарплаты на конец отчётного периода. Суммы нигде не кэшируются и не пишутся в лог.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date
from urllib.parse import quote

import httpx

from app.config import settings
from app.services.onec_tools import _odata_auth

_REGISTER = "InformationRegister_ЗначенияПериодическихПоказателейРасчетаЗарплатыСотрудников"
_OKLAD = "Оклад"
_BASE_BONUS = "БазоваяПремияДляМесячнаяПремияПоФормуле"
_EMPTY_KEY = "00000000-0000-0000-0000-000000000000"

_indicator_lock = threading.Lock()
_indicator_keys: dict[str, str] = {}


class SalaryLookupError(Exception):
    pass


@dataclass(frozen=True)
class SalaryInfo:
    oklad: float | None
    base_bonus: float | None
    as_of: date


def _odata_text(value: str) -> str:
    return value.replace("'", "''")


def _get(client: httpx.Client, path: str) -> list[dict]:
    base = str(settings.odata_base_url or "").rstrip("/")
    response = client.get(f"{base}/{path}", headers={"Accept": "application/json"})
    if response.status_code >= 400:
        raise SalaryLookupError(f"1С ответила {response.status_code}")
    data = response.json()
    value = data.get("value") if isinstance(data, dict) else None
    return value if isinstance(value, list) else []


def _indicators(client: httpx.Client) -> dict[str, str]:
    with _indicator_lock:
        if _indicator_keys:
            return dict(_indicator_keys)
    flt = quote(f"Идентификатор eq '{_OKLAD}' or Идентификатор eq '{_BASE_BONUS}'")
    rows = _get(client, f"Catalog_ПоказателиРасчетаЗарплаты?$format=json&$select=Ref_Key,Идентификатор&$filter={flt}")
    found = {str(row.get("Идентификатор") or ""): str(row.get("Ref_Key") or "") for row in rows}
    with _indicator_lock:
        _indicator_keys.update({k: v for k, v in found.items() if k and v})
        return dict(_indicator_keys)


def _employee_keys(client: httpx.Client, fio: str) -> list[str]:
    name = _odata_text(" ".join(fio.split()))
    for condition in (f"Description eq '{name}'", f"substringof('{name}', Description)"):
        flt = quote(f"DeletionMark eq false and {condition}")
        rows = _get(client, f"Catalog_Сотрудники?$format=json&$select=Ref_Key&$filter={flt}")
        keys = [str(row.get("Ref_Key") or "") for row in rows if row.get("Ref_Key")]
        if keys:
            return keys
    return []


def lookup_salary(fio: str, as_of: date) -> SalaryInfo | None:
    """None — сотрудник не найден в 1С; поля None — показатель не заведён."""
    if not str(fio or "").strip():
        return None
    if not settings.odata_base_url:
        raise SalaryLookupError("OData 1С не настроена")
    auth = _odata_auth()
    if not auth:
        raise SalaryLookupError("Нет учётных данных OData 1С")
    try:
        with httpx.Client(timeout=settings.odata_timeout_sec, auth=auth) as client:
            indicators = _indicators(client)
            employees = _employee_keys(client, fio)
            if not employees:
                return None
            period = f"{as_of.isoformat()}T23:59:59"
            wanted = {key: ident for ident, key in indicators.items()}
            latest: dict[str, tuple[str, float]] = {}
            for employee in employees:
                flt = quote(f"Сотрудник_Key eq guid'{employee}'")
                rows = _get(
                    client,
                    f"{_REGISTER}_RecordType/SliceLast(Period=datetime'{period}')"
                    f"?$format=json&$select=Period,Показатель_Key,Значение,ДействуетДо&$filter={flt}",
                )
                for row in rows:
                    ident = wanted.get(str(row.get("Показатель_Key") or ""))
                    if not ident:
                        continue
                    until = str(row.get("ДействуетДо") or "")[:10]
                    if until and not until.startswith("0001") and until < as_of.isoformat():
                        continue
                    stamp = str(row.get("Period") or "")
                    value = float(row.get("Значение") or 0)
                    if value and (ident not in latest or stamp > latest[ident][0]):
                        latest[ident] = (stamp, value)
    except httpx.HTTPError as exc:
        raise SalaryLookupError("1С не ответила") from exc
    return SalaryInfo(
        oklad=latest[_OKLAD][1] if _OKLAD in latest else None,
        base_bonus=latest[_BASE_BONUS][1] if _BASE_BONUS in latest else None,
        as_of=as_of,
    )
