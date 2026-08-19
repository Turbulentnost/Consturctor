#!/usr/bin/env python3
"""Fetch open assignments where current user is executor — OData + DOK HTTP from infra/.env."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
env: dict[str, str] = {}
for line in (ROOT / "infra" / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, _, value = line.partition("=")
    env[key.strip()] = value.strip().strip('"').strip("'")


def load_env() -> None:
    for key, value in env.items():
        import os

        os.environ.setdefault(key, value)


load_env()

BASE = env["ODATA_BASE_URL"].rstrip("/")
FIO = env.get("ERP_LOGIN", "")
USER_AUTH = (env.get("ERP_LOGIN", ""), env.get("ERP_PASSWORD", ""))
SVC_AUTH = (env.get("ODATA_USERNAME", ""), env.get("ODATA_PASSWORD", ""))
ENTITY = "Task_ЗадачаИсполнителя"


def find_user_ref(client: httpx.Client, auth: tuple[str, str]) -> str | None:
    """Resolve Catalog_Пользователи Ref_Key for ERP_LOGIN FIO."""
    offset = 0
    while offset < 5000:
        params = {
            "$format": "json",
            "$top": "500",
            "$skip": str(offset),
            "$select": "Ref_Key,Description,DeletionMark",
        }
        resp = client.get(f"{BASE}/Catalog_Пользователи", params=params, auth=auth)
        if resp.status_code != 200:
            print("Catalog_Пользователи error:", resp.status_code, resp.text[:200])
            return None
        rows = resp.json().get("value") or []
        if not rows:
            break
        for row in rows:
            if row.get("DeletionMark"):
                continue
            desc = (row.get("Description") or "").strip()
            if desc == FIO:
                return str(row.get("Ref_Key"))
        for row in rows:
            desc = (row.get("Description") or "").strip()
            if "Жалыбин" in desc and "Максим" in desc:
                print("partial catalog match:", desc)
                return str(row.get("Ref_Key"))
        offset += len(rows)
    return None


def fetch_crm_register(client: httpx.Client, auth: tuple[str, str], user_ref: str) -> list[dict]:
    """CRM widget tasks — InformationRegister_CRM_ЗадачиПользователей if published."""
    entity = "InformationRegister_CRM_ЗадачиПользователей"
    params = {
        "$format": "json",
        "$top": "50",
        "$orderby": "Поставлено desc",
    }
    resp = client.get(f"{BASE}/{entity}", params=params, auth=auth)
    print(f"  CRM register -> HTTP {resp.status_code}")
    if resp.status_code != 200:
        print("   ", resp.text[:180].replace("\n", " "))
        return []
    rows = resp.json().get("value") or []
    mine: list[dict] = []
    for row in rows:
        user = row.get("Пользователь") or row.get("Пользователь_Key") or ""
        if str(user) == user_ref:
            mine.append(row)
            continue
        desc = (row.get("Пользователь@navigationLinkUrl") or "") + str(row)
        if user_ref in desc:
            mine.append(row)
    if not mine and rows:
        # Some registers expose only keys — return recent slice for manual inspect
        print(f"  CRM rows total={len(rows)}, no key match — returning open-looking rows")
        for row in rows:
            closed = row.get("Закрыта") or row.get("Closed")
            if closed in (None, "", "0001-01-01T00:00:00"):
                mine.append(row)
    return mine[:50]


def fetch_odata_tasks(client: httpx.Client, auth: tuple[str, str], user_ref: str) -> list[dict]:
    """1C OData often ignores Исполнитель in $filter — paginate + client-side filter."""
    mine: list[dict] = []
    skip = 0
    page_size = 200
    max_scan = 3000

    while skip < max_scan and len(mine) < 100:
        params = {
            "$format": "json",
            "$top": str(page_size),
            "$skip": str(skip),
            "$filter": "Executed eq false",
            "$orderby": "Date desc",
        }
        resp = client.get(f"{BASE}/{ENTITY}", params=params, auth=auth)
        print(f"  page skip={skip} -> HTTP {resp.status_code}")
        if resp.status_code != 200:
            print("   ", resp.text[:180].replace("\n", " "))
            break
        rows = resp.json().get("value") or []
        if not rows:
            break
        for row in rows:
            ref = str(row.get("Исполнитель") or row.get("Исполнитель_Key") or "")
            if ref == user_ref:
                mine.append(row)
        skip += len(rows)

    print(f"  open tasks for executor: {len(mine)} (scanned {skip} rows)")
    if mine:
        return mine

    # Fallback: include recently completed tasks for this executor
    skip = 0
    while skip < 1500 and len(mine) < 50:
        params = {
            "$format": "json",
            "$top": str(page_size),
            "$skip": str(skip),
            "$orderby": "Date desc",
        }
        resp = client.get(f"{BASE}/{ENTITY}", params=params, auth=auth)
        if resp.status_code != 200:
            break
        rows = resp.json().get("value") or []
        if not rows:
            break
        for row in rows:
            ref = str(row.get("Исполнитель") or row.get("Исполнитель_Key") or "")
            if ref == user_ref:
                mine.append(row)
        skip += len(rows)
    print(f"  all tasks (incl. done) for executor: {len(mine)} (scanned {skip} rows)")
    return mine


def fetch_dok_http(client: httpx.Client, user_ref: str | None = None) -> list[dict]:
    """Try document-management HTTP service (DOK_HTTP_* in .env)."""
    user = env.get("DOK_HTTP_USER", "")
    password = env.get("DOK_HTTP_PASSWORD", "")
    if not user or not password:
        return []

    server = env.get("DOK_HTTP_SERVER", "192.168.2.229")
    port = env.get("DOK_HTTP_PORT", "81")
    base_path = env.get("DOK_HTTP_BASE_PATH", "/doc").rstrip("/")
    service = env.get("DOK_HTTP_SERVICE", "dterp")
    template = env.get("DOK_HTTP_TEMPLATE", "Tasks").strip('"')
    timeout = float(env.get("DOK_HTTP_TIMEOUT", "30"))
    user_ref = user_ref or env.get("ODATA_USER_REF", "")

    explicit = env.get("DOK_HTTP_URL", "").strip('"')
    candidates = []
    if explicit:
        candidates.append(explicit.rstrip("/"))
    candidates.extend(
        [
            f"http://{server}:{port}{base_path}/hs/{service}/{template}",
            f"http://{server}:{port}{base_path}/hs/{service}/{template}/User",
            f"http://{server}:{port}{base_path}/hs/{service}/TasksII",
            f"http://{server}:{port}{base_path}/hs/{service}/TasksII/User",
        ]
    )

    auth = (user, password)
    erp_auth = (env.get("ERP_LOGIN", ""), env.get("ERP_PASSWORD", ""))
    auth_variants = [auth]
    if erp_auth[0] and erp_auth not in auth_variants:
        auth_variants.append(erp_auth)

    get_params = [{}, {"user": FIO}, {"User": FIO}, {"login": FIO}]
    if user_ref:
        get_params.extend([{"user": user_ref}, {"UserID": user_ref}])

    post_bodies: list[tuple[str, dict[str, str], bytes]] = [
        ("json-user", {"Content-Type": "application/json"}, json.dumps({"user": FIO}, ensure_ascii=False).encode()),
        (
            "1c-xml-structure",
            {"Content-Type": "application/xml; charset=utf-8"},
            f"""<?xml version="1.0" encoding="UTF-8"?>
<Structure xmlns="http://v8.1c.ru/8.1/data/core"
 xmlns:xs="http://www.w3.org/2001/XMLSchema"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Property name="Пользователь">
    <Value xsi:type="xs:string">{FIO}</Value>
  </Property>
</Structure>""".encode("utf-8"),
        ),
        ("text-fio", {"Content-Type": "text/plain; charset=utf-8"}, FIO.encode("utf-8")),
    ]

    def parse_response(resp: httpx.Response) -> list[dict] | None:
        if resp.status_code != 200 or not resp.text.strip():
            return None
        try:
            data = resp.json()
        except json.JSONDecodeError:
            return None
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("tasks", "Tasks", "value", "items", "data"):
                if isinstance(data.get(key), list):
                    return data[key]
            return [data]
        return None

    seen: set[str] = set()
    for url in candidates:
        if url in seen:
            continue
        seen.add(url)
        for auth in auth_variants:
            print(f"\n=== DOK HTTP {url} (auth={auth[0][:20]}...) ===")
            for params in get_params:
                label = json.dumps(params, ensure_ascii=False) if params else "{}"
                try:
                    resp = client.get(url, auth=auth, params=params or None, timeout=timeout)
                    print(f"  GET {label} -> {resp.status_code}", resp.text[:160].replace("\n", " "))
                    parsed = parse_response(resp)
                    if parsed:
                        return parsed
                except Exception as exc:  # noqa: BLE001
                    print(f"  GET {label} FAIL:", exc)
            for name, headers, content in post_bodies:
                try:
                    resp = client.post(url, auth=auth, headers=headers, content=content, timeout=timeout)
                    print(f"  POST {name} -> {resp.status_code}", resp.text[:160].replace("\n", " "))
                    parsed = parse_response(resp)
                    if parsed:
                        return parsed
                except Exception as exc:  # noqa: BLE001
                    print(f"  POST {name} FAIL:", exc)
    return []


def fetch_com_fallback() -> tuple[list[dict], str]:
    """When OData/DOK are empty, use local onec-com service (same ERP session as GUI)."""
    import urllib.request

    body = json.dumps(
        {"payload": {"mine_only": True, "prefer_crm": True, "limit": 50}},
        ensure_ascii=False,
    ).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:7831/api/v1/tools/onec.com.query_tasks/invoke",
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode())
    except Exception as exc:  # noqa: BLE001
        print("\n=== COM fallback unavailable ===")
        print(" ", exc)
        return [], ""
    if not data.get("ok"):
        print("\n=== COM fallback error ===", data.get("error"))
        return [], ""
    payload = data.get("data") or {}
    rows = payload.get("tasks") or []
    source = str(payload.get("task_source") or "com")
    print(f"\n=== COM fallback ({source}): {len(rows)} поручений ===")
    return rows, source


def print_tasks(rows: list[dict], source: str) -> None:
    print(f"\n=== {source}: {len(rows)} поручений ===")
    for row in rows[:25]:
        num = row.get("Number") or row.get("number") or row.get("Номер") or ""
        dt = str(
            row.get("Date")
            or row.get("date")
            or row.get("Дата")
            or row.get("Поставлено")
            or row.get("КрайнийСрок")
            or ""
        )[:16]
        desc = (
            row.get("Description")
            or row.get("description")
            or row.get("Наименование")
            or row.get("subject")
            or row.get("Title")
            or ""
        )
        print(f"  {num:18} | {dt} | {str(desc)[:75]}")


def main() -> int:
    print("Пользователь (исполнитель):", FIO)
    print("OData:", BASE)

    with httpx.Client() as client:
        user_ref = find_user_ref(client, USER_AUTH) or find_user_ref(client, SVC_AUTH)
        print("Ref_Key исполнителя:", user_ref)

        odata_rows: list[dict] = []
        crm_rows: list[dict] = []
        if user_ref:
            print("\n=== OData InformationRegister CRM ===")
            crm_rows = fetch_crm_register(client, USER_AUTH, user_ref)
            if not crm_rows:
                crm_rows = fetch_crm_register(client, SVC_AUTH, user_ref)

            print("\n=== OData Task_ЗадачаИсполнителя (auth=ERP user) ===")
            odata_rows = fetch_odata_tasks(client, USER_AUTH, user_ref)
            if not odata_rows:
                print("\n=== OData fallback (auth=odata.user) ===")
                odata_rows = fetch_odata_tasks(client, SVC_AUTH, user_ref)

        dok_rows = fetch_dok_http(client, user_ref)

    com_rows: list[dict] = []
    com_source = ""
    if not crm_rows and not odata_rows and not dok_rows:
        com_rows, com_source = fetch_com_fallback()

    print_tasks(crm_rows, "OData CRM_ЗадачиПользователей")
    print_tasks(odata_rows, "OData ERP Task_ЗадачаИсполнителя")
    if dok_rows:
        print_tasks(dok_rows, "DOK HTTP")
    if com_rows:
        print_tasks(com_rows, f"COM fallback ({com_source})")

    report = {
        "user": FIO,
        "user_ref": user_ref,
        "odata_note": (
            "OData не возвращает личные поручения пользователя: $filter по Исполнитель игнорируется, "
            "задачи из COM отсутствуют в выборке OData (RLS/публикация)."
            if not odata_rows
            else ""
        ),
        "crm_tasks": crm_rows,
        "odata_tasks": odata_rows,
        "dok_http_tasks": dok_rows,
        "com_fallback_tasks": com_rows,
        "com_fallback_source": com_source,
    }
    out = ROOT / "logs" / "my_porucheniya_odata.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nJSON: {out}")
    return 0 if crm_rows or odata_rows or dok_rows or com_rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
