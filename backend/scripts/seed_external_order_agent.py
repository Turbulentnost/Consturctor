"""Опубликовать агента «ИИ-агент внешнего заказа».

Запуск из backend/:
  py -3.12 scripts/seed_external_order_agent.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.session import SessionLocal, init_db
from app.services.external_order_agent import ensure_agent


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        row = ensure_agent(db)
        if row is None:
            raise SystemExit("Нужен пользователь Жалыбин Максим Дмитриевич")
        print(f"workflow_id: {row.id}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
