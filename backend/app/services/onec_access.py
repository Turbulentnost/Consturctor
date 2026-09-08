"""Check the signed-in employee's 1C rights before privileged OData.

OData runs as a service account, so BSP RLS does not apply. This module
reads the same BSP objects from erp_pm SQL and denies the call when the
actor would not see the object in 1C.

Verified tables (erp_pm):
- Catalog.Пользователи = _Reference366
- Catalog.ГруппыПользователей = _Reference142
- Catalog.ГруппыДоступа = _Reference133
- Catalog.ПрофилиГруппДоступа = _Reference412
- Catalog.ИдентификаторыОбъектовМетаданных = _Reference194X1
- InformationRegister.ПраваРолей = _InfoRg47512
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from app.clients.erp_sql import ErpSqlError, _connect
from app.config import settings

logger = logging.getLogger(__name__)

_CACHE_TTL_SEC = 120.0
_PRIVILEGED_ROLES = frozenset({"ПолныеПрава", "АдминистраторСистемы"})
_GUID_CHARS = frozenset("0123456789abcdefABCDEF-")

_ODATA_TO_META = (
    ("Document_", "Документ."),
    ("Catalog_", "Справочник."),
    ("InformationRegister_", "РегистрСведений."),
    ("AccumulationRegister_", "РегистрНакопления."),
    ("AccountingRegister_", "РегистрБухгалтерии."),
    ("CalculationRegister_", "РегистрРасчета."),
    ("BusinessProcess_", "БизнесПроцесс."),
    ("Task_", "Задача."),
    ("Constant_", "Константа."),
    ("ChartOfCharacteristicTypes_", "ПланВидовХарактеристик."),
    ("ChartOfAccounts_", "ПланСчетов."),
    ("ChartOfCalculationTypes_", "ПланВидовРасчета."),
    ("ExchangePlan_", "ПланОбмена."),
    ("Enum_", "Перечисление."),
)

_RLS_ENTITIES = ("Document_", "BusinessProcess_", "Task_")
_CONFIDENTIAL_ENTITIES = ("Document_ТД_Протокол",)
_PERSON_KEYS = (
    "Подготовил_Key",
    "Ответственный_Key",
    "Руководитель_Key",
    "Автор_Key",
    "Участник_Key",
)
_DEPT_KEYS = ("Подразделение_Key",)
_SKIP_ROW_KEYS = frozenset(
    {
        "Ref_Key",
        "DataVersion",
        "odata.metadata",
        "Posted",
        "DeletionMark",
        "Number",
        "Date",
        "LineNumber",
    }
)

class OnecAccessDenied(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OnecAccessProfile:
    user_ref: str
    fio: str
    privileged: bool = False
    viewable: frozenset[str] = field(default_factory=frozenset)
    writable: frozenset[str] = field(default_factory=frozenset)
    allowed_values: frozenset[str] = field(default_factory=frozenset)
    rls_restricted: bool = False
    department_key: str = ""
    person_ref: str = ""

    def allows_view(self, full_name: str) -> bool:
        return self.privileged or full_name in self.viewable

    def allows_write(self, full_name: str) -> bool:
        return self.privileged or full_name in self.writable


_cache: dict[str, tuple[float, OnecAccessProfile]] = {}
_cache_lock = threading.Lock()


def odata_guid_to_sql_hex(value: str) -> str:
    raw = UUID(value).hex
    return (raw[16:32] + raw[12:16] + raw[8:12] + raw[0:8]).upper()


def sql_hex_to_odata_guid(value: str) -> str:
    raw = (value or "").replace("-", "").replace("0x", "").strip().upper()
    if len(raw) != 32:
        return ""
    return str(UUID(raw[24:32] + raw[20:24] + raw[16:20] + raw[0:16]))


def odata_entity_candidates(entity: str) -> list[str]:
    """Map OData entity set name to 1C metadata full names."""
    name = (entity or "").strip().lstrip("/").split("?", 1)[0]
    if "(" in name:
        name = name.split("(", 1)[0]
    if not name:
        return []
    for prefix, meta in _ODATA_TO_META:
        if not name.startswith(prefix):
            continue
        rest = name[len(prefix) :]
        names = [f"{meta}{rest}"]
        if "_" in rest:
            parent, _child = rest.rsplit("_", 1)
            names.append(f"{meta}{parent}")
        return names
    return []


def access_check_enabled() -> bool:
    return bool(getattr(settings, "onec_enforce_user_access", True))


def clear_access_cache() -> None:
    with _cache_lock:
        _cache.clear()


def load_access_profile(*, user_id: str = "", fio: str = "") -> OnecAccessProfile:
    cache_key = f"{(user_id or '').strip().upper()}|{(fio or '').strip().casefold()}"
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(cache_key)
        if hit and now - hit[0] < _CACHE_TTL_SEC:
            return hit[1]
    profile = _load_access_profile_uncached(user_id=user_id, fio=fio)
    with _cache_lock:
        _cache[cache_key] = (time.monotonic(), profile)
    return profile


def enforce_actor_access(
    *,
    action: str,
    entity: str,
    user_id: str = "",
    fio: str = "",
) -> OnecAccessProfile:
    if not access_check_enabled():
        return OnecAccessProfile(user_ref="", fio=fio or user_id, privileged=True)
    profile = load_access_profile(user_id=user_id, fio=fio)
    if action == "sql":
        if profile.privileged:
            return profile
        raise OnecAccessDenied(
            "Доступ запрещен: SQL к 1С разрешен только при роли ПолныеПрава "
            "или АдминистраторСистемы."
        )
    candidates = odata_entity_candidates(entity)
    if not candidates:
        raise OnecAccessDenied("Доступ запрещен: не удалось определить объект 1С.")
    allowed = profile.allows_write if action == "write" else profile.allows_view
    if any(allowed(name) for name in candidates):
        return profile
    shown = candidates[0]
    verb = "изменения" if action == "write" else "чтения"
    raise OnecAccessDenied(f"Доступ запрещен: нет права {verb} {shown}.")


def _is_confidential_entity(entity: str) -> bool:
    name = (entity or "").split("?", 1)[0].split("(", 1)[0]
    return any(name == prefix or name.startswith(prefix + "_") for prefix in _CONFIDENTIAL_ENTITIES)


def filter_odata_result(
    result: dict[str, Any],
    profile: OnecAccessProfile,
    entity: str,
) -> dict[str, Any]:
    if profile.privileged:
        return result
    rows = _result_rows(result)
    if not rows:
        return result
    confidential = _is_confidential_entity(entity)
    if not confidential and not profile.rls_restricted:
        return result
    if not confidential and not entity.startswith(_RLS_ENTITIES):
        return result
    if confidential:
        kept = [row for row in rows if _row_confidential_allowed(row, profile)]
        reason = "confidentiality"
    else:
        kept = [row for row in rows if _row_allowed(row, profile)]
        reason = "RLS"
    dropped = len(rows) - len(kept)
    if dropped:
        logger.info(
            "onec access %s filtered entity=%s kept=%s dropped=%s user=%s",
            reason,
            entity,
            len(kept),
            dropped,
            profile.fio,
        )
    if not kept and _looks_like_keyed_result(result, entity):
        raise OnecAccessDenied(
            "Доступ запрещен: запись 1С не входит в область данных пользователя."
        )
    return _replace_result_rows(result, kept, entity)


def _looks_like_1c_hex_id(value: str) -> bool:
    text = (value or "").strip()
    if not text or "-" in text:
        return False
    return 16 <= len(text) <= 64 and all(ch in "0123456789abcdefABCDEF" for ch in text)


def _looks_like_guid(value: str) -> bool:
    text = (value or "").strip()
    if len(text) != 36 or text.count("-") != 4:
        return False
    return all(ch in _GUID_CHARS for ch in text)


def _membership_expired(until: Any, now: datetime) -> bool:
    """1C empty date in erp_pm SQL is 2001-01-01 (year offset), not year 1."""
    if not isinstance(until, datetime):
        return False
    if until.year <= 2001 or until.year >= 3990:
        return False
    return until < now


def _is_true(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bytes):
        return any(byte != 0 for byte in value)
    if isinstance(value, (int, float)):
        return int(value) != 0
    text = str(value).strip().upper()
    return text in {"1", "01", "TRUE"}


def _load_access_profile_uncached(*, user_id: str = "", fio: str = "") -> OnecAccessProfile:
    user_id = (user_id or "").strip()
    fio = (fio or "").strip()
    if not user_id and not fio:
        raise OnecAccessDenied(
            "Доступ запрещен: нет текущего пользователя для проверки прав 1С."
        )
    try:
        conn = _connect()
    except ErpSqlError as exc:
        raise OnecAccessDenied(
            "Доступ запрещен: не удалось прочитать права 1С из erp_pm."
        ) from exc
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")
        user = _resolve_user(cur, user_id=user_id, fio=fio)
        principals = _principal_hexes(cur, user["hex"])
        groups = _access_groups(cur, principals)
        roles = _profile_roles(cur, [item["profile_hex"] for item in groups])
        privileged = any(role in _PRIVILEGED_ROLES for role in roles)
        viewable, writable = _object_rights(cur, roles) if not privileged else (frozenset(), frozenset())
        allowed_values, restricted = _rls_values(cur, groups)
        logger.info(
            "onec access loaded user=%s groups=%s roles=%s privileged=%s "
            "viewable=%s rls=%s values=%s",
            user["fio"],
            len(groups),
            len(roles),
            privileged,
            len(viewable),
            restricted,
            len(allowed_values),
        )
        return OnecAccessProfile(
            user_ref=sql_hex_to_odata_guid(user["hex"]),
            fio=user["fio"],
            privileged=privileged,
            viewable=viewable,
            writable=writable,
            allowed_values=allowed_values,
            rls_restricted=restricted and not privileged,
            department_key=sql_hex_to_odata_guid(user.get("dept") or ""),
            person_ref=sql_hex_to_odata_guid(user.get("person") or ""),
        )
    except OnecAccessDenied:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("onec access load failed")
        raise OnecAccessDenied(
            "Доступ запрещен: не удалось проверить права пользователя в 1С."
        ) from exc
    finally:
        conn.close()


def _resolve_user(cur: Any, *, user_id: str, fio: str) -> dict[str, str]:
    row = None
    if user_id and _looks_like_1c_hex_id(user_id):
        cur.execute(
            """
            SELECT TOP 2
                CONVERT(varchar(64), _IDRRef, 2) AS Id,
                CAST(_Description AS nvarchar(256)) AS Descr,
                _Marked AS Marked,
                _Fld10995 AS Invalid,
                _Fld10999 AS ServiceFlag,
                CONVERT(varchar(64), _Fld10996RRef, 2) AS Dept,
                CONVERT(varchar(64), _Fld10997RRef, 2) AS Person
            FROM dbo._Reference366 WITH (NOLOCK)
            WHERE CONVERT(varchar(64), _Fld11001, 2) = ?
            """,
            (user_id.strip().upper(),),
        )
        rows = cur.fetchall()
        if len(rows) == 1:
            row = rows[0]
    if row is None and fio:
        cur.execute(
            """
            SELECT TOP 2
                CONVERT(varchar(64), _IDRRef, 2) AS Id,
                CAST(_Description AS nvarchar(256)) AS Descr,
                _Marked AS Marked,
                _Fld10995 AS Invalid,
                _Fld10999 AS ServiceFlag,
                CONVERT(varchar(64), _Fld10996RRef, 2) AS Dept,
                CONVERT(varchar(64), _Fld10997RRef, 2) AS Person
            FROM dbo._Reference366 WITH (NOLOCK)
            WHERE LTRIM(RTRIM(_Description)) = ?
            """,
            (fio,),
        )
        rows = cur.fetchall()
        if len(rows) == 1:
            row = rows[0]
        elif len(rows) > 1:
            raise OnecAccessDenied(
                "Доступ запрещен: в 1С несколько пользователей с таким ФИО."
            )
    if row is None:
        raise OnecAccessDenied(
            "Доступ запрещен: пользователь не найден в справочнике 1С."
        )
    if _is_true(row.Marked) or _is_true(row.Invalid):
        raise OnecAccessDenied("Доступ запрещен: пользователь 1С недействителен.")
    return {
        "hex": (row.Id or "").strip().upper(),
        "fio": (row.Descr or "").strip() or fio,
        "dept": (getattr(row, "Dept", None) or "").strip().upper(),
        "person": (getattr(row, "Person", None) or "").strip().upper(),
    }


def _principal_hexes(cur: Any, user_hex: str) -> list[str]:
    principals = {user_hex}
    cur.execute(
        """
        SELECT CONVERT(varchar(64), ug._IDRRef, 2) AS Gid
        FROM dbo._Reference142_VT4765 vt WITH (NOLOCK)
        JOIN dbo._Reference142 ug WITH (NOLOCK)
            ON vt._Reference142_IDRRef = ug._IDRRef
        WHERE CONVERT(varchar(64), vt._Fld4767RRef, 2) = ?
          AND ug._Marked = 0x00
        """,
        (user_hex,),
    )
    for row in cur.fetchall():
        gid = (row.Gid or "").strip().upper()
        if gid:
            principals.add(gid)
    cur.execute(
        """
        SELECT CONVERT(varchar(64), _IDRRef, 2) AS Gid
        FROM dbo._Reference142 WITH (NOLOCK)
        WHERE LTRIM(RTRIM(_Description)) = N'Все пользователи'
          AND _Marked = 0x00
        """
    )
    for row in cur.fetchall():
        gid = (row.Gid or "").strip().upper()
        if gid:
            principals.add(gid)
    return list(principals)


def _access_groups(cur: Any, principals: list[str]) -> list[dict[str, str]]:
    if not principals:
        return []
    placeholders = ",".join("?" * len(principals))
    cur.execute(
        f"""
        SELECT DISTINCT
            CONVERT(varchar(64), g._IDRRef, 2) AS Gid,
            CONVERT(varchar(64), g._Fld4722RRef, 2) AS Pid,
            CAST(g._Description AS nvarchar(256)) AS Grp,
            vt._Fld169821 AS UntilAt
        FROM dbo._Reference133_VT4727 vt WITH (NOLOCK)
        JOIN dbo._Reference133 g WITH (NOLOCK)
            ON vt._Reference133_IDRRef = g._IDRRef
        WHERE g._Marked = 0x00
          AND CONVERT(varchar(64), vt._Fld4729_RRRef, 2) IN ({placeholders})
        """,
        principals,
    )
    groups: dict[str, dict[str, str]] = {}
    now = datetime.now()
    for row in cur.fetchall():
        until = row.UntilAt
        if _membership_expired(until, now):
            continue
        gid = (row.Gid or "").strip().upper()
        pid = (row.Pid or "").strip().upper()
        if not gid:
            continue
        groups[gid] = {"hex": gid, "profile_hex": pid, "name": (row.Grp or "").strip()}
    return list(groups.values())


def _profile_roles(cur: Any, profile_hexes: list[str]) -> list[str]:
    ids = [item for item in profile_hexes if item and item != "0" * 32]
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    cur.execute(
        f"""
        SELECT DISTINCT CAST(m._Fld6374 AS nvarchar(256)) AS RoleName
        FROM dbo._Reference412_VT12010 vt WITH (NOLOCK)
        JOIN dbo._Reference194X1 m WITH (NOLOCK)
            ON vt._Fld12012_RRRef = m._IDRRef
        WHERE CONVERT(varchar(64), vt._Reference412_IDRRef, 2) IN ({placeholders})
          AND m._Marked = 0x00
        """,
        ids,
    )
    return [str(row.RoleName or "").strip() for row in cur.fetchall() if row.RoleName]


def _object_rights(cur: Any, roles: list[str]) -> tuple[frozenset[str], frozenset[str]]:
    names = [role for role in roles if role]
    if not names:
        return frozenset(), frozenset()
    placeholders = ",".join("?" * len(names))
    cur.execute(
        f"""
        SELECT
            CAST(obj._Fld6376 AS nvarchar(512)) AS FullName,
            r._Fld47515 AS ChangeFlag,
            r._Fld47516 AS AddFlag,
            r._Fld47520 AS ViewFlag,
            r._Fld47521 AS EditFlag
        FROM dbo._InfoRg47512 r WITH (NOLOCK)
        JOIN dbo._Reference194X1 obj WITH (NOLOCK)
            ON r._Fld47513RRef = obj._IDRRef
        JOIN dbo._Reference194X1 role WITH (NOLOCK)
            ON r._Fld47514RRef = role._IDRRef
        WHERE role._Fld6374 IN ({placeholders})
          AND obj._Marked = 0x00
        """,
        names,
    )
    viewable: set[str] = set()
    writable: set[str] = set()
    for row in cur.fetchall():
        full_name = str(row.FullName or "").strip()
        if not full_name or full_name.startswith("?"):
            continue
        if _is_true(row.ViewFlag):
            viewable.add(full_name)
        if _is_true(row.ChangeFlag) or _is_true(row.AddFlag) or _is_true(row.EditFlag):
            writable.add(full_name)
    return frozenset(viewable), frozenset(writable)


def _rls_values(cur: Any, groups: list[dict[str, str]]) -> tuple[frozenset[str], bool]:
    ids = [item["hex"] for item in groups if item.get("hex")]
    if not ids:
        return frozenset(), False
    placeholders = ",".join("?" * len(ids))
    cur.execute(
        f"""
        SELECT
            CONVERT(varchar(64), _Reference133_IDRRef, 2) AS Gid,
            CONVERT(varchar(8), _Fld4734, 2) AS AllAllowed
        FROM dbo._Reference133_VT4731 WITH (NOLOCK)
        WHERE CONVERT(varchar(64), _Reference133_IDRRef, 2) IN ({placeholders})
        """,
        ids,
    )
    kind_rows = cur.fetchall()
    by_group: dict[str, list[str]] = {}
    for row in kind_rows:
        by_group.setdefault((row.Gid or "").strip().upper(), []).append(
            str(row.AllAllowed or "").strip().upper()
        )
    unrestricted = False
    restricted_ids: list[str] = []
    for gid in ids:
        flags = by_group.get(gid)
        if not flags or all(flag in {"01", "1"} for flag in flags):
            unrestricted = True
            continue
        restricted_ids.append(gid)
    if unrestricted or not restricted_ids:
        return frozenset(), False
    placeholders = ",".join("?" * len(restricted_ids))
    cur.execute(
        f"""
        SELECT CONVERT(varchar(64), _Fld4739_RRRef, 2) AS Val
        FROM dbo._Reference133_VT4736 WITH (NOLOCK)
        WHERE CONVERT(varchar(64), _Reference133_IDRRef, 2) IN ({placeholders})
        """,
        restricted_ids,
    )
    values = set()
    for row in cur.fetchall():
        guid = sql_hex_to_odata_guid((row.Val or "").strip())
        if guid:
            values.add(guid.lower())
    return frozenset(values), True


def _result_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(result.get("value"), list):
        return [row for row in result["value"] if isinstance(row, dict)]
    data = result.get("data")
    if isinstance(data, dict) and isinstance(data.get("value"), list):
        return [row for row in data["value"] if isinstance(row, dict)]
    if isinstance(data, dict) and data.get("Ref_Key"):
        return [data]
    return []


def _looks_like_keyed_result(result: dict[str, Any], _entity: str) -> bool:
    path = str(result.get("path") or "")
    if "(guid'" in path.lower():
        return True
    data = result.get("data")
    return isinstance(data, dict) and bool(data.get("Ref_Key")) and not isinstance(
        data.get("value"), list
    )


def _replace_result_rows(
    result: dict[str, Any],
    rows: list[dict[str, Any]],
    entity: str,
) -> dict[str, Any]:
    updated = dict(result)
    if isinstance(updated.get("value"), list):
        updated["value"] = rows
        updated["count"] = len(rows)
        updated["summary"] = f"получено {len(rows)} записей из 1С OData ({entity})"
    data = updated.get("data")
    if isinstance(data, dict) and isinstance(data.get("value"), list):
        next_data = dict(data)
        next_data["value"] = rows
        updated["data"] = next_data
    return updated


def _actor_keys(profile: OnecAccessProfile) -> set[str]:
    keys = set()
    for raw in (profile.user_ref, profile.person_ref):
        text = str(raw or "").strip().lower()
        if _looks_like_guid(text) and not text.startswith("00000000-0000-0000-0000-"):
            keys.add(text)
    return keys


def _row_people_and_depts(row: dict[str, Any]) -> tuple[set[str], set[str]]:
    people: set[str] = set()
    depts: set[str] = set()

    def take(key: str, value: Any) -> None:
        text = str(value or "").strip().lower()
        if not _looks_like_guid(text) or text.startswith("00000000-0000-0000-0000-"):
            return
        if key in _DEPT_KEYS:
            depts.add(text)
        if key in _PERSON_KEYS or key == "Участник" or key.endswith("Участник_Key"):
            people.add(text)

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                take(str(key), value)
                if isinstance(value, (dict, list)):
                    walk(value)
            return
        if isinstance(obj, list):
            for item in obj[:80]:
                walk(item)

    walk(row)
    return people, depts


def _row_confidential_allowed(row: dict[str, Any], profile: OnecAccessProfile) -> bool:
    if profile.privileged:
        return True
    actors = _actor_keys(profile)
    people, depts = _row_people_and_depts(row)
    if actors and people & actors:
        return True
    dept = str(profile.department_key or "").strip().lower()
    if dept and dept in depts:
        return True
    return False


def _row_allowed(row: dict[str, Any], profile: OnecAccessProfile) -> bool:
    if not profile.rls_restricted:
        return True
    if not profile.allowed_values:
        return False
    found = _row_guids(row)
    if not found:
        return True
    return bool(found & profile.allowed_values)


def _row_guids(row: dict[str, Any]) -> set[str]:
    found: set[str] = set()

    def walk(obj: Any, key: str = "") -> None:
        if isinstance(obj, dict):
            for child_key, value in obj.items():
                walk(value, str(child_key))
            return
        if isinstance(obj, list):
            for item in obj[:30]:
                walk(item, key)
            return
        if key in _SKIP_ROW_KEYS or key.endswith("_Type"):
            return
        text = str(obj or "").strip()
        if _looks_like_guid(text) and not text.startswith("00000000-0000-0000-0000-"):
            found.add(text.lower())

    walk(row)
    return found
