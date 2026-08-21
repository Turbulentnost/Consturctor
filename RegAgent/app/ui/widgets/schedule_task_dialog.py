from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import QDate, QDateTime, Qt, QTime
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QRadioButton,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from app.models import Card, ScheduledTask, TriggerType
from app.scheduler.logic import compute_next_run, format_iso
from app.ui.styles import input_qss, primary_button_qss, secondary_button_qss
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font
from app.ui.widgets.app_dialog import AppDialog


_WEEKDAYS = [
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
]

_INTERVAL_PRESETS = [
    ("15 минут", {"preset": "15m"}),
    ("30 минут", {"preset": "30m"}),
    ("Каждый час", {"preset": "1h"}),
    ("Каждые 2 часа", {"preset": "2h"}),
]


class ScheduleTaskDialog(AppDialog):
    def __init__(
        self,
        *,
        published_cards: list[Card],
        parent: QWidget | None = None,
        card_id: str = "",
        preset_date: datetime | None = None,
        task: ScheduledTask | None = None,
    ) -> None:
        super().__init__(
            "Редактировать задачу" if task else "Запланировать задачу",
            parent=parent,
            primary="Сохранить",
            secondary="Отмена",
        )
        self._task = task
        self._result: ScheduledTask | None = None

        agent_label = QLabel("Агент")
        agent_label.setFont(app_font(12, QFont.Weight.DemiBold))
        agent_label.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        self._agent = QComboBox()
        self._agent.setStyleSheet(input_qss(radius=10))
        for card in published_cards:
            self._agent.addItem(card.title or card.id, card.id)
        if card_id:
            idx = self._agent.findData(card_id)
            if idx >= 0:
                self._agent.setCurrentIndex(idx)
        if len(published_cards) == 1:
            self._agent.setEnabled(False)

        title_label = QLabel("Название")
        title_label.setFont(app_font(12, QFont.Weight.DemiBold))
        title_label.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        self._title = QLineEdit()
        self._title.setPlaceholderText("Краткое название задачи")
        self._title.setStyleSheet(input_qss(radius=10))

        prompt_label = QLabel("Задача для агента")
        prompt_label.setFont(app_font(12, QFont.Weight.DemiBold))
        prompt_label.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        self._prompt = QPlainTextEdit()
        self._prompt.setPlaceholderText("Что агент должен сделать по расписанию…")
        self._prompt.setStyleSheet(input_qss(radius=10))
        self._prompt.setFixedHeight(100)

        schedule_label = QLabel("Расписание")
        schedule_label.setFont(app_font(12, QFont.Weight.DemiBold))
        schedule_label.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

        self._once = QRadioButton("Разово")
        self._interval = QRadioButton("Периодически")
        self._daily = QRadioButton("Ежедневно")
        self._weekly = QRadioButton("Еженедельно")
        for rb in (self._once, self._interval, self._daily, self._weekly):
            rb.setFont(app_font(12))
            rb.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        self._once.setChecked(True)

        self._once_at = QDateTimeEdit()
        self._once_at.setCalendarPopup(True)
        self._once_at.setDisplayFormat("dd.MM.yyyy HH:mm")
        self._once_at.setStyleSheet(input_qss(radius=10))
        default_dt = preset_date or datetime.now().astimezone().replace(second=0, microsecond=0)
        self._once_at.setDateTime(
            QDateTime(
                QDate(default_dt.year, default_dt.month, default_dt.day),
                QTime(default_dt.hour, default_dt.minute),
            )
        )

        self._interval_preset = QComboBox()
        self._interval_preset.setStyleSheet(input_qss(radius=10))
        for label, _ in _INTERVAL_PRESETS:
            self._interval_preset.addItem(label)

        self._daily_time = QTimeEdit()
        self._daily_time.setDisplayFormat("HH:mm")
        self._daily_time.setStyleSheet(input_qss(radius=10))
        self._daily_time.setTime(QTime(9, 0))

        self._weekday = QComboBox()
        self._weekday.setStyleSheet(input_qss(radius=10))
        for day in _WEEKDAYS:
            self._weekday.addItem(day)
        self._weekly_time = QTimeEdit()
        self._weekly_time.setDisplayFormat("HH:mm")
        self._weekly_time.setStyleSheet(input_qss(radius=10))
        self._weekly_time.setTime(QTime(9, 0))

        self._enabled = QCheckBox("Включено")
        self._enabled.setChecked(True)
        self._enabled.setFont(app_font(12))
        self._enabled.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

        self._once.toggled.connect(self._sync_schedule_fields)
        self._interval.toggled.connect(self._sync_schedule_fields)
        self._daily.toggled.connect(self._sync_schedule_fields)
        self._weekly.toggled.connect(self._sync_schedule_fields)

        form = QWidget()
        lay = QVBoxLayout(form)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(agent_label)
        lay.addWidget(self._agent)
        lay.addWidget(title_label)
        lay.addWidget(self._title)
        lay.addWidget(prompt_label)
        lay.addWidget(self._prompt)
        lay.addWidget(schedule_label)
        lay.addWidget(self._once)
        lay.addWidget(self._once_at)
        lay.addWidget(self._interval)
        lay.addWidget(self._interval_preset)
        lay.addWidget(self._daily)
        lay.addWidget(self._daily_time)
        lay.addWidget(self._weekly)
        week_row = QHBoxLayout()
        week_row.setSpacing(8)
        week_row.addWidget(self._weekday, 1)
        week_row.addWidget(self._weekly_time, 0)
        lay.addLayout(week_row)
        lay.addWidget(self._enabled)

        hint = QLabel("Агент запустится автоматически в указанное время. Запись появится в истории чата.")
        hint.setWordWrap(True)
        hint.setFont(app_font(11))
        hint.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        lay.addWidget(hint)

        self.add_body(form)
        self.resize(520, 640)

        if task is not None:
            self._load_task(task)
        self._sync_schedule_fields()

    def result_task(self) -> ScheduledTask | None:
        return self._result

    def accept(self) -> None:  # noqa: D102
        card_id = str(self._agent.currentData() or "")
        prompt = self._prompt.toPlainText().strip()
        title = self._title.text().strip() or prompt[:60] or "Запланированная задача"
        if not card_id:
            return
        if not prompt:
            return
        trigger_type, config = self._build_trigger()
        task = self._task or ScheduledTask(card_id=card_id)
        task.card_id = card_id
        task.title = title
        task.prompt = prompt
        task.trigger_type = trigger_type
        task.trigger_config = config
        task.enabled = self._enabled.isChecked()
        nxt = compute_next_run(task)
        task.next_run_at = format_iso(nxt) if nxt else ""
        self._result = task
        super().accept()

    def _load_task(self, task: ScheduledTask) -> None:
        idx = self._agent.findData(task.card_id)
        if idx >= 0:
            self._agent.setCurrentIndex(idx)
        self._title.setText(task.title)
        self._prompt.setPlainText(task.prompt)
        self._enabled.setChecked(task.enabled)
        cfg = dict(task.trigger_config or {})
        if task.trigger_type == "once":
            self._once.setChecked(True)
            run_at = cfg.get("run_at") or task.next_run_at
            if run_at:
                try:
                    dt = datetime.fromisoformat(str(run_at).replace("Z", "+00:00"))
                    local = dt.astimezone()
                    self._once_at.setDateTime(
                        QDateTime(
                            QDate(local.year, local.month, local.day),
                            QTime(local.hour, local.minute),
                        )
                    )
                except ValueError:
                    pass
        elif task.trigger_type == "interval":
            self._interval.setChecked(True)
            preset = str(cfg.get("preset") or "")
            for i, (_, pcfg) in enumerate(_INTERVAL_PRESETS):
                if pcfg.get("preset") == preset:
                    self._interval_preset.setCurrentIndex(i)
                    break
        elif task.trigger_type == "daily":
            self._daily.setChecked(True)
            self._daily_time.setTime(QTime(int(cfg.get("hour", 9)), int(cfg.get("minute", 0))))
        elif task.trigger_type == "weekly":
            self._weekly.setChecked(True)
            self._weekday.setCurrentIndex(int(cfg.get("weekday", 0)) % 7)
            self._weekly_time.setTime(QTime(int(cfg.get("hour", 9)), int(cfg.get("minute", 0))))

    def _sync_schedule_fields(self) -> None:
        once = self._once.isChecked()
        interval = self._interval.isChecked()
        daily = self._daily.isChecked()
        weekly = self._weekly.isChecked()
        self._once_at.setEnabled(once)
        self._interval_preset.setEnabled(interval)
        self._daily_time.setEnabled(daily)
        self._weekday.setEnabled(weekly)
        self._weekly_time.setEnabled(weekly)

    def _build_trigger(self) -> tuple[TriggerType, dict]:
        if self._once.isChecked():
            qdt = self._once_at.dateTime()
            local = datetime(
                qdt.date().year(),
                qdt.date().month(),
                qdt.date().day(),
                qdt.time().hour(),
                qdt.time().minute(),
                tzinfo=datetime.now().astimezone().tzinfo,
            )
            return "once", {"run_at": format_iso(local.astimezone(timezone.utc))}
        if self._interval.isChecked():
            _, cfg = _INTERVAL_PRESETS[self._interval_preset.currentIndex()]
            return "interval", dict(cfg)
        if self._daily.isChecked():
            t = self._daily_time.time()
            return "daily", {"hour": t.hour(), "minute": t.minute()}
        t = self._weekly_time.time()
        return "weekly", {
            "weekday": self._weekday.currentIndex(),
            "hour": t.hour(),
            "minute": t.minute(),
        }
