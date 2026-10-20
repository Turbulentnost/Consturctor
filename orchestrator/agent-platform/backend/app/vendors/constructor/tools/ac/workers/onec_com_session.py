"""Merge Orchestrator session 1C credentials into process env for COM workers."""

from __future__ import annotations

import os
from typing import Any, Mapping

ENV_COM_USR = "ONEC_COM_USR"
ENV_LOGIN = "ERP_LOGIN"
ENV_PASSWORD = "ERP_PASSWORD"


def snapshot_desktop_com_env() -> dict[str, str]:
    """Values from desktop/.env at sidecar startup (before session overrides)."""
    return {
        ENV_COM_USR: os.environ.get(ENV_COM_USR, "").strip(),
        ENV_LOGIN: os.environ.get(ENV_LOGIN, "").strip(),
        ENV_PASSWORD: os.environ.get(ENV_PASSWORD, "").strip(),
    }


def normalize_onec_cred_keys(payload: dict[str, Any]) -> dict[str, Any]:
    """Merge camelCase IPC keys into snake_case env helpers."""
    out = dict(payload)
    pairs = (
        ("onecComUsr", "onec_com_usr"),
        ("nameMail", "name_mail"),
        ("erpLogin", "erp_login"),
        ("erpPassword", "erp_password"),
        ("onecCatalogRefKey", "onec_catalog_ref_key"),
        ("userId", "user_id"),
        ("sessionOnecRef", "session_onec_ref"),
        ("sessionCustomerKey", "session_customer_key"),
    )
    for src, dst in pairs:
        if src in payload and not str(out.get(dst) or "").strip():
            out[dst] = payload[src]
    if str(out.get("login") or "").strip() and not str(out.get("fio") or "").strip():
        out["fio"] = out["login"]
    return out


def resolve_com_usr_for_env(
    payload: dict[str, Any],
    desktop_snapshot: Mapping[str, str],
) -> str | None:
    """ONEC_COM_USR for COM Usr=, or None to fall back to ERP_LOGIN (FIO).

    nameMail / username from the UI are for OData gateway, not COM Usr=.
    Only desktop/.env ONEC_COM_USR or explicit onec_com_usr_override apply here.
    """
    desktop_usr = str(desktop_snapshot.get(ENV_COM_USR) or "").strip()
    if desktop_usr:
        return desktop_usr
    override = str(payload.get("onec_com_usr_override") or "").strip()
    if override:
        return override
    return None


def apply_onec_session_credentials(
    raw: dict[str, Any] | None,
    *,
    desktop_snapshot: Mapping[str, str] | None = None,
    environ: dict[str, str] | None = None,
) -> None:
    """Apply session FIO + password; do not map nameMail into ONEC_COM_USR."""
    if not isinstance(raw, dict):
        return
    target = environ if environ is not None else os.environ
    snapshot = desktop_snapshot if desktop_snapshot is not None else snapshot_desktop_com_env()
    payload = normalize_onec_cred_keys(raw)
    password = str(payload.get("password") or payload.get("erp_password") or "")
    fio = str(
        payload.get("fio") or payload.get("erp_login") or payload.get("login") or ""
    ).strip()

    com_usr = resolve_com_usr_for_env(payload, snapshot)
    if com_usr:
        target[ENV_COM_USR] = com_usr
    else:
        target.pop(ENV_COM_USR, None)

    if fio:
        target[ENV_LOGIN] = fio
    if password:
        target[ENV_PASSWORD] = password
    elif any(key in raw for key in ("password", "erp_password", "erpPassword")):
        target.pop(ENV_PASSWORD, None)


def com_infra_configured(environ: Mapping[str, str] | None = None) -> bool:
    env = environ if environ is not None else os.environ
    conn = str(env.get("ONEC_COM_CONNECTION_STRING") or "").strip()
    server = str(env.get("ONEC_COM_SERVER") or "").strip()
    ref = str(env.get("ONEC_COM_REF") or "").strip()
    return bool(conn or (server and ref))


def com_session_auth_ready(environ: Mapping[str, str] | None = None) -> bool:
    """True when COM infra is set and session/env provides a password if Usr= is used."""
    env = environ if environ is not None else os.environ
    if not com_infra_configured(env):
        return False
    explicit = str(env.get("ONEC_COM_CONNECTION_STRING") or "").strip()
    if explicit and "Pwd=" not in explicit and "Usr=" not in explicit:
        return True
    login = str(env.get(ENV_COM_USR) or "").strip() or str(env.get(ENV_LOGIN) or "").strip()
    password = str(env.get(ENV_PASSWORD) or "").strip()
    if login and not password:
        return False
    return True


def missing_com_auth_message(environ: Mapping[str, str] | None = None) -> str:
    env = environ if environ is not None else os.environ
    if not com_infra_configured(env):
        return (
            "1С COM не настроен: задайте ONEC_COM_SERVER и ONEC_COM_REF "
            "(или ONEC_COM_CONNECTION_STRING) в orchestrator/desktop/.env."
        )
    if not com_session_auth_ready(env):
        return (
            "Войдите в Orchestrator с паролем 1С (ФИО как в erp_pm). "
            "После входа только по JWT пароль не передаётся в COM sidecar — "
            "выйдите и войдите снова или «Подключить 1С» в рабочем месте."
        )
    return "Учётные данные 1С COM не заданы."
