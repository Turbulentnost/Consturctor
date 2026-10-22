"""CRM-сделка из 1С и стратегические сроки из портфеля TurboProject.

Запись задач в файл MPP этот модуль не делает: API портфеля читает проекты.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.external_orders import (
    ExternalOrderError,
    _LINK_ROLES,
    _audit,
    _dump,
    _load,
    _onec_link,
    _order,
    _detail,
)


def link_strategy(db: Session, order_id: str, *, role: str, fio: str) -> dict:
    if role not in _LINK_ROLES | {"rp"}:
        raise ExternalOrderError(
            "Стратегический план связывают коммерческая служба, развитие, руководитель проекта, финансы или ИТ",
            403,
        )
    row = _order(db, order_id)
    onec = _onec_link(row)
    query = _query(row.customer, str(onec.get("deal_name") or ""), str(onec.get("order_number") or ""))
    if not query:
        raise ExternalOrderError("Сначала загрузите ТКП: без заказчика и сделки портфель не к чему привязать", 400)
    from app.services.turboproject import TurboProjectError, search_projects

    try:
        found = search_projects({"query": query, "limit": 8})
    except TurboProjectError as exc:
        raise ExternalOrderError(str(exc), 502) from exc
    projects = found.get("projects") if isinstance(found.get("projects"), list) else []
    chosen = _pick(projects, row.customer, str(onec.get("deal_name") or ""))
    sections = _load(row.sections_json)
    if chosen is None:
        sections["strategy"] = {
            "file_id": "",
            "project_name": "",
            "note": f"В TurboProject нет проекта по запросу «{query}».",
        }
    else:
        dates = chosen.get("dates") if isinstance(chosen.get("dates"), dict) else {}
        data = chosen.get("data_1c") if isinstance(chosen.get("data_1c"), dict) else {}
        sections["strategy"] = {
            "file_id": str(chosen.get("file_id") or ""),
            "project_name": str(chosen.get("project_name") or ""),
            "owner": str(chosen.get("owner") or ""),
            "customer": str(chosen.get("customer") or ""),
            "start_date": str(dates.get("start_date") or ""),
            "finish_date": str(dates.get("finish_date") or ""),
            "baseline_finish": str(dates.get("baseline_finish") or ""),
            "number": str(data.get("nomer_proekta") or ""),
            "status": str(data.get("status_proekta") or ""),
            "note": "Сроки прочитаны из портфеля. Задачи в файл TurboProject не записываются.",
        }
    row.sections_json = _dump(sections)
    saved = sections["strategy"]
    _audit(
        db,
        row,
        fio=fio,
        role=role,
        action="strategy",
        detail=saved.get("project_name") or saved.get("note") or query,
    )
    db.commit()
    db.refresh(row)
    return _detail(row)


def _query(customer: str, deal_name: str, order_number: str) -> str:
    text = deal_name.strip()
    if "/" in text:
        text = text.split("/", 1)[1]
    words = [part.strip(" ,.") for part in text.split() if part.strip(" ,.")]
    words = [part for part in words if part.casefold() not in {"сделка", "с"}]
    short = " ".join(words[:4]).strip()
    if short:
        return short[:80]
    if customer.strip():
        return customer.strip()[:80]
    return order_number.strip()


def _pick(projects: list, customer: str, deal_name: str) -> dict | None:
    folded_customer = customer.casefold()
    folded_deal = deal_name.casefold()
    best: tuple[int, dict] | None = None
    for item in projects:
        if not isinstance(item, dict):
            continue
        name = str(item.get("project_name") or "").casefold()
        party = str(item.get("customer") or "").casefold()
        score = 0
        if folded_customer and (folded_customer in name or folded_customer in party):
            score += 2
        if folded_deal and any(token in name for token in folded_deal.split() if len(token) > 3):
            score += 1
        if best is None or score > best[0]:
            best = (score, item)
    return best[1] if best else None
