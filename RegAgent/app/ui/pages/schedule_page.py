from __future__ import annotations



from PySide6.QtCore import Qt, Signal

from PySide6.QtGui import QFont

from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout, QWidget



from app.models import Card

from app.storage.scheduled_repository import ScheduledTaskRepository

from app.ui.styles import primary_button_qss, secondary_button_qss

from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font

from app.ui.widgets.schedule_task_dialog import ScheduleTaskDialog





class SchedulePage(QWidget):

    finished = Signal()

    skipped = Signal()

    open_calendar = Signal()

    task_created = Signal()



    def __init__(

        self,

        task_repo: ScheduledTaskRepository | None = None,

        parent: QWidget | None = None,

    ) -> None:

        super().__init__(parent)

        self._repo = task_repo

        self._card: Card | None = None

        self._published: list[Card] = []



        title = QLabel("Расписание")

        title.setFont(app_font(28, QFont.Weight.DemiBold))

        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")



        subtitle = QLabel(

            "Настройте автоматический запуск агента: разово или по расписанию. "

            "Задачи отображаются в календаре и выполняются в фоне."

        )

        subtitle.setWordWrap(True)

        subtitle.setFont(app_font(14))

        subtitle.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")



        self._hint = QLabel("")

        self._hint.setWordWrap(True)

        self._hint.setFont(app_font(13))

        self._hint.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")



        add = QPushButton("Запланировать задачу для этого агента")

        add.setStyleSheet(primary_button_qss(radius=12))

        add.clicked.connect(self._add_task)



        calendar = QPushButton("Открыть календарь")

        calendar.setStyleSheet(secondary_button_qss(radius=12))

        calendar.clicked.connect(self.open_calendar.emit)



        done = QPushButton("Готово → к списку агентов")

        done.setStyleSheet(primary_button_qss(radius=12))

        done.clicked.connect(self.finished.emit)



        skip = QPushButton("Пропустить")

        skip.setStyleSheet(secondary_button_qss(radius=12))

        skip.clicked.connect(self.skipped.emit)

        self._action_buttons = (add, calendar, done, skip)



        layout = QVBoxLayout(self)

        layout.setContentsMargins(0, 0, 0, 0)

        layout.setSpacing(16)

        layout.addWidget(title)

        layout.addWidget(subtitle)

        layout.addWidget(self._hint)

        layout.addStretch(1)

        layout.addWidget(add, 0, Qt.AlignmentFlag.AlignRight)

        layout.addWidget(calendar, 0, Qt.AlignmentFlag.AlignRight)

        layout.addWidget(done, 0, Qt.AlignmentFlag.AlignRight)

        layout.addWidget(skip, 0, Qt.AlignmentFlag.AlignRight)



    def set_task_repo(self, repo: ScheduledTaskRepository) -> None:

        self._repo = repo



    def set_published_cards(self, cards: list[Card]) -> None:

        self._published = [c for c in cards if c.phase == "published"]



    def set_card(self, card: Card) -> None:

        self._card = card

        name = card.title or "агент"

        self._hint.setText(f"Агент «{name}» опубликован. Можно добавить первую задачу или настроить позже в календаре.")



    def set_actions_enabled(self, enabled: bool) -> None:

        for btn in self._action_buttons:

            btn.setEnabled(enabled)



    def _add_task(self) -> None:

        if self._repo is None or self._card is None:

            return

        cards = self._published or [self._card]

        dialog = ScheduleTaskDialog(

            published_cards=cards,

            parent=self,

            card_id=self._card.id,

        )

        if dialog.exec() != QDialog.DialogCode.Accepted:

            return

        saved = dialog.result_task()

        if saved is None:

            return

        self._repo.save(saved)

        self.task_created.emit()

        self._hint.setText("Задача сохранена. Её можно изменить в календаре.")


