#!/usr/bin/env python3
"""Установка агента ACT-реестра в локальный backend (и опционально на общий сервер)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.act_registry_agent_spec import build_workflow_import_payload  # noqa: E402

AUTH = os.getenv("AUTH_URL", "http://192.168.1.157:7812").rstrip("/")
LOCAL = os.getenv("BACKEND_URL", "http://127.0.0.1:7812").rstrip("/")
REGULATION = ROOT / "ACT_REGISTRY.md"


def _login(client: httpx.Client, base: str, fio: str, password: str) -> str:
    r = client.post(f"{base}/api/v1/auth/login", json={"fio": fio, "password": password})
    r.raise_for_status()
    return r.json()["access_token"]


def _import_agent(client: httpx.Client, base: str, token: str, payload: dict) -> dict:
    r = client.post(
        f"{base}/api/v1/workflows/import",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
        timeout=120.0,
    )
    r.raise_for_status()
    return r.json()


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed ACT registry agent")
    parser.add_argument("fio", nargs="?", default="Жалыбин Максим Дмитриевич")
    parser.add_argument("password", nargs="?", default="gm360249")
    parser.add_argument("--also-shared", action="store_true", help="Import on AUTH_URL too")
    parser.add_argument("--workflow-id", default="", help="Fixed workflow UUID (optional)")
    args = parser.parse_args()

    doc_text = ""
    if REGULATION.is_file():
        doc_text = REGULATION.read_text(encoding="utf-8")
    else:
        doc_text = build_workflow_import_payload()["document_text"]

    payload = build_workflow_import_payload(
        workflow_id=args.workflow_id or None,
        document_text=doc_text,
        document_name="psd_regulation_action_tracker.txt",
    )

    targets = [("local", LOCAL)]
    if args.also_shared:
        targets.append(("shared", AUTH))

    with httpx.Client(timeout=120.0) as client:
        for label, base in targets:
            try:
                token = _login(client, base, args.fio, args.password)
            except httpx.HTTPError as exc:
                print(f"[{label}] login failed ({base}): {exc}")
                continue
            try:
                result = _import_agent(client, base, token, payload)
            except httpx.HTTPError as exc:
                print(f"[{label}] import failed: {exc}")
                if hasattr(exc, "response") and exc.response is not None:
                    print(exc.response.text[:500])
                continue
            print(f"[{label}] OK: {result.get('title')} id={result.get('id')} phase={result.get('phase')}")

    print("\nWorkflow id:", payload["id"])
    print("Otkroyte Moj agenty -> ACT-reestr poruchenij -> Zapustit tipovuyu zadachu")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
