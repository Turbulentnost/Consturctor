"""
Утверждение служебной записки об организации совещания в 1С:ERP (OData).

Кнопка «Утвердить» на форме записки включает реквизит УтвержденоНачальникомУД.
После этого на той же форме открывается «Оформить протокол совещания».
Статус согласования («НеСогласована» / «Согласована» / «Отклонена») кнопка не меняет.

CLI:
  python -m app.vendors.aiagentback.tools.onec.confirm_service_memo --number 000010430 --dry-run
  python -m app.vendors.aiagentback.tools.onec.confirm_service_memo --number 000010430 --approver-fio "Ильченко Екатерина Александровна"
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import requests

from app.vendors.aiagentback.tools.onec.connection import CONFIG, ODataConfig
from app.vendors.aiagentback.tools.onec.get_meetings import fetch_document_header
from app.vendors.aiagentback.tools.onec.service_memo_shared import (
    REJECTED_STATUS,
    ServiceMemoWorkflowError,
    apply_executor_fields,
    ensure_meeting_memo,
    load_memo_header,
    now_ud_timestamp,
    patch_service_memo,
)

CONFIRMED_BY_UD = "УтвержденоНачальникомУД"


def build_confirmation_patch(
    session: requests.Session,
    config: ODataConfig,
    *,
    approver_fio: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {CONFIRMED_BY_UD: True}
    if approver_fio and approver_fio.strip():
        payload["ДатаИсполненияУД"] = now_ud_timestamp()
        apply_executor_fields(session, config, payload, executor_fio=approver_fio)
    return payload


def build_confirmation_message(*, number: str | None, changed: bool, already_confirmed: bool) -> str:
    memo_number = (number or "").strip() or "?"
    if already_confirmed:
        return f"Служебная записка №{memo_number} уже утверждена. Оформление протокола доступно."
    if changed:
        return f"Служебная записка №{memo_number} утверждена. В 1С можно оформить протокол совещания."
    return f"Служебная записка №{memo_number} не изменена."


def confirm_service_memo(
    *,
    ref_key: str | None = None,
    number: str | None = None,
    approver_fio: str | None = None,
    validate_meeting_theme: bool = True,
    dry_run: bool = False,
    config: ODataConfig = CONFIG,
) -> dict[str, Any]:
    session, resolved_ref, before, metadata = load_memo_header(
        ref_key=ref_key,
        number=number,
        config=config,
    )
    if validate_meeting_theme:
        ensure_meeting_memo(session, config, before, metadata=metadata)

    status = str(before.get("Статус") or "")
    memo_number = str(before.get("Number") or number or "")
    if status == REJECTED_STATUS:
        raise ServiceMemoWorkflowError(
            f"Утверждение недоступно: служебная записка №{memo_number or '?'} отклонена"
        )

    already = bool(before.get(CONFIRMED_BY_UD))

    def result(*, header: dict[str, Any], changed: bool, dry: bool) -> dict[str, Any]:
        return {
            "ref_key": resolved_ref,
            "number": header.get("Number"),
            "date": header.get("Date"),
            "posted": header.get("Posted"),
            "status": header.get("Статус"),
            "confirmed": bool(header.get(CONFIRMED_BY_UD)),
            "already_confirmed": already and not changed,
            "changed": changed,
            "dry_run": dry,
            "approver_fio": approver_fio,
            "message": build_confirmation_message(
                number=str(header.get("Number") or memo_number),
                changed=changed,
                already_confirmed=already and not changed,
            ),
        }

    if already:
        return result(header=before, changed=False, dry=dry_run)
    if dry_run:
        checked = result(header=before, changed=False, dry=True)
        checked["message"] = "Проверка пройдена — можно утвердить. Документ не изменён."
        return checked

    patch_service_memo(
        session,
        config,
        resolved_ref,
        build_confirmation_patch(session, config, approver_fio=approver_fio),
        action_label="утверждения",
    )
    after = fetch_document_header(session, config, resolved_ref)
    if not after.get(CONFIRMED_BY_UD):
        raise ServiceMemoWorkflowError("1С не записала признак «Утверждено начальником УД»")
    return result(header=after, changed=True, dry=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Утвердить служебную записку об организации совещания в 1С:ERP (кнопка «Утвердить»).",
    )
    parser.add_argument("--ref-key", help="Ref_Key документа")
    parser.add_argument("--number", help="Номер документа, например 000010430")
    parser.add_argument(
        "--approver-fio",
        help="ФИО сотрудника УД (Catalog_Пользователи) для поля ИсполнительУД",
    )
    parser.add_argument(
        "--skip-theme-check",
        action="store_true",
        help="Не проверять тему «Организация совещаний»",
    )
    parser.add_argument("--dry-run", action="store_true", help="Только проверить документ, без записи в 1С")
    parser.add_argument("-o", "--output", help="Путь к JSON-файлу результата")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = build_parser().parse_args(argv)
    try:
        result = confirm_service_memo(
            ref_key=args.ref_key,
            number=args.number,
            approver_fio=args.approver_fio,
            validate_meeting_theme=not args.skip_theme_check,
            dry_run=args.dry_run,
        )
    except (ServiceMemoWorkflowError, RuntimeError, requests.RequestException) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1

    text = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as file:
            file.write(text)
        print(f"Сохранено: {args.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
