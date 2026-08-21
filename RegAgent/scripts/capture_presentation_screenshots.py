#!/usr/bin/env python3
"""Снимки экранов модулей RegAgent для презентации."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "docs" / "presentation" / "screenshots"


def main() -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

    from app.agent.prompts import ui_spec_has_open_questions
    from app.api_client import ApiClient
    from app.config import ensure_data_dirs
    from app.storage.repository import CardRepository
    from app.ui.login_page import LoginPage
    from app.ui.main_shell import MainShell
    from app.ui.pages.create_page import CreatePage
    from app.ui.pages.home_page import HomePage
    from app.ui.pages.kpi_page import KpiPage
    from app.ui.pages.workspace_page import WorkspacePage
    from app.ui.theme import MAIN_TEXT, app_font, load_fonts, qss_global
    from app.ui.widgets.markdown_body import MarkdownBody

    ensure_data_dirs()
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    app.setStyleSheet(qss_global(load_fonts()))

    def save(widget: QWidget, name: str, w: int = 1280, h: int = 800) -> None:
        widget.resize(w, h)
        widget.show()
        app.processEvents()
        widget.grab().save(str(OUT / f"{name}.png"))
        widget.hide()

    def wrap(page: QWidget) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet("background: #FAFCFB;")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(page)
        return frame

    repo = CardRepository()
    cards = repo.list_cards()

    save(LoginPage(ApiClient()), "01_login", 1024, 720)

    home = HomePage()
    home.set_cards(
        [c for c in cards if not ui_spec_has_open_questions(c.ui_spec)] or cards,
        [c for c in cards if ui_spec_has_open_questions(c.ui_spec)],
    )
    save(wrap(home), "02_home_agents")

    save(wrap(CreatePage()), "03_create_regulation")

    ws = WorkspacePage()
    if cards:
        card = cards[0]
        ws._card = card  # noqa: SLF001
        ws._title.setText(card.title or "RegAgent")
        ws._summary.setText(card.summary or "Помощник ПСД — регламент и поручения")
        ws._rebuild_actions()
        ws._clear_feed()
        ws._append_feed("user", "Проверь календарь Outlook на ближайшую неделю.")
        ws._append_feed(
            "agent",
            "Календарь 21–28.08: 12 встреч. 25.08 — конфликт 09:00 и 09:30.",
        )
        ws._append_feed("tool", "constructor_integrations → outlook.read_calendar")
        ws._append_feed("user", "Выгрузи поручения ТД_Поручения в Excel.")
        ws._append_feed(
            "agent",
            "209 поручений выгружены в porucheniya_td.xlsx с цветовой индикацией.",
        )
        ws._append_feed("tool", "onec.docflow_tasks (OData erp_pm)")
        ws._set_status("Готов к работе", "success")
        ws._set_interactive(True)
    save(wrap(ws), "04_workspace_agent")

    shell = MainShell(ApiClient())
    shell.resize(1280, 800)
    shell.show()
    app.processEvents()
    shell.sidebar.set_active_key("agents", animate=False)
    shell.grab().save(str(OUT / "05_main_shell.png"))
    shell.hide()
    shell.deleteLater()

    kpi = KpiPage()
    kpi.refresh(cards)
    save(wrap(kpi), "06_kpi")

    chat = QWidget()
    chat.setStyleSheet("background: #FAFCFB;")
    cv = QVBoxLayout(chat)
    cv.setContentsMargins(40, 32, 40, 32)
    h = QLabel("Диалог агента и вызов tools")
    h.setFont(app_font(26, QFont.Weight.DemiBold))
    h.setStyleSheet(f"color: {MAIN_TEXT.name()};")
    cv.addWidget(h)
    body = MarkdownBody()
    body.set_markdown(
        "**Пользователь:** `/calendar` — проверь календарь\n\n"
        "**Tool:** `outlook.read_calendar` → 12 событий\n\n"
        "**Tool:** `onec.docflow_tasks` → 209 поручений OData"
    )
    cv.addWidget(body)
    save(chat, "07_chat_integrations", 1100, 520)

    schema = QWidget()
    schema.setStyleSheet("background: #011713;")
    sl = QVBoxLayout(schema)
    sl.setContentsMargins(48, 40, 48, 40)
    st = QLabel("Модуль поручений: onec.docflow_tasks")
    st.setFont(app_font(28, QFont.Weight.Bold))
    st.setStyleSheet("color: #62E0BE;")
    sl.addWidget(st)
    flow = QHBoxLayout()
    for text in (
        "Cursor SDK",
        "constructor_integrations",
        "docflow_odata.py",
        "Document_ТД_Поручения",
        "Excel export",
    ):
        box = QLabel(text)
        box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.setFont(app_font(14, QFont.Weight.DemiBold))
        box.setStyleSheet(
            "color:#EAF7F3;background:rgba(6,72,61,0.8);"
            "border:1px solid #62E0BE;border-radius:12px;padding:18px;"
        )
        flow.addWidget(box)
    sl.addLayout(flow)
    note = QLabel("OData erp_pm · без COM · пастельная раскраска · сводка на сегодня")
    note.setFont(app_font(14))
    note.setStyleSheet("color: #A8C8BF; margin-top: 24px;")
    sl.addWidget(note)
    sl.addStretch(1)
    save(schema, "08_oauth_module", 1280, 420)

    excel = QWidget()
    excel.setStyleSheet("background: #FAFCFB;")
    el = QVBoxLayout(excel)
    el.setContentsMargins(40, 32, 40, 32)
    et = QLabel("Экспорт Excel — porucheniya_td.xlsx")
    et.setFont(app_font(24, QFont.Weight.DemiBold))
    et.setStyleSheet(f"color: {MAIN_TEXT.name()};")
    el.addWidget(et)
    grid = QHBoxLayout()
    for color, label in (
        ("#FECACA", "Просрочено"),
        ("#FFE0B2", "≤1 день"),
        ("#FFF9C4", "<3 дней"),
        ("#D4EDDA", "Принято"),
    ):
        cell = QFrame()
        cell.setStyleSheet(f"background:{color};border-radius:10px;border:1px solid #ddd;")
        cl = QVBoxLayout(cell)
        t = QLabel(label)
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setFont(app_font(13, QFont.Weight.DemiBold))
        cl.addWidget(t)
        grid.addWidget(cell)
    el.addLayout(grid)
    cols = QLabel("Колонки: Номер · О чём · Мероприятие · Статус · Срок · Дата · Приоритет · Исполнитель")
    cols.setWordWrap(True)
    cols.setStyleSheet(f"color: {MAIN_TEXT.name()}; margin-top: 16px;")
    el.addWidget(cols)
    save(excel, "09_excel_export", 1100, 360)

    app.quit()
    print("OK", OUT)


if __name__ == "__main__":
    main()
