"""Агент процессов: периодичность и основание задач, новости «Сегодня», проверки утверждения."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.org import OrgMember, OrgUnit
from app.models.platform_task import PlatformTask, PlatformTaskFile
from app.models.today_news import TodayNews, TodayNewsRecipient
from app.models.user import AppUser
from app.services import platform_tasks, today_news
from app.services.org_structure import fio_key
from app.services.server_agents import process_tools
from app.services.server_agents.process_agent import text_diff

OWNER_ID = "u-owner"
CHIEF = "Хозуян Иван Владимирович"
CHIEF_ID = "u-chief"
CLERK = "Петрова Анна Сергеевна"
CLERK_ID = "u-clerk"

APPROVED = (
    "УТВЕРЖДАЮ Генеральный директор А.Б. Амураль 01.10.2026. "
    "Инструкция по ведению реестра чертежей. "
    "3.1. Главный конструктор И.В. Хозуян ежемесячно проверяет реестр чертежей и подписывает акт сверки. "
    "3.2. Специалист по документации ведёт реестр."
)
DRAFT = (
    "Проект инструкции по ведению реестра чертежей. "
    "3.1. Главный конструктор И.В. Хозуян ежемесячно проверяет реестр чертежей."
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", future=True)
    tables = [
        t.__table__
        for t in (AppUser, OrgUnit, OrgMember, PlatformTask, PlatformTaskFile, TodayNews, TodayNewsRecipient)
    ]
    Base.metadata.create_all(engine, tables=tables)
    session = sessionmaker(bind=engine, future=True)()
    for user_id, fio, position in (
        (OWNER_ID, "Мангасарян Давид Каренович", "руководитель сектора"),
        (CHIEF_ID, CHIEF, "главный конструктор"),
        (CLERK_ID, CLERK, "специалист по документации"),
    ):
        session.add(AppUser(id=user_id, fio=fio, position=position, department="КБ"))
        session.add(
            OrgMember(fio_key=fio_key(fio), fio=fio, user_id=user_id, position=position, unit_id="", department="КБ")
        )
    session.commit()
    yield session
    session.close()


@pytest.fixture()
def notes(monkeypatch) -> list[dict]:
    sent: list[dict] = []
    monkeypatch.setattr(platform_tasks, "_notify", lambda _db, **kwargs: sent.append(kwargs))
    return sent


def _workspace(tmp_path, monkeypatch, text: str, phase: str = "act"):
    (tmp_path / "texts").mkdir()
    (tmp_path / "texts" / "f1.txt").write_text(text, encoding="utf-8")
    (tmp_path / "recent.json").write_text(
        json.dumps(
            [{"file_id": "f1", "name": "Инструкция.docx", "owner_user_id": OWNER_ID, "text_file": "texts/f1.txt"}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / "phase.txt").write_text(phase, encoding="utf-8")
    monkeypatch.setenv(process_tools.WORKSPACE_ENV, str(tmp_path))
    return tmp_path


def _task_payload(**extra) -> dict:
    payload = {
        "file_id": "f1",
        "approval_quote": "УТВЕРЖДАЮ Генеральный директор А.Б. Амураль 01.10.2026",
        "assignee_fio": CHIEF,
        "position": "главный конструктор",
        "process_quote": "Главный конструктор И.В. Хозуян ежемесячно проверяет реестр чертежей",
        "description": "Проверить реестр чертежей и подписать акт сверки",
        "due_at": (datetime.now(timezone.utc) + timedelta(days=5)).isoformat(),
        "recurrence": "monthly",
        "basis": "П. 3.1: ежемесячная сверка реестра, такой задачи у него не было",
    }
    payload.update(extra)
    return payload


# ---------- задачи платформы ----------


def test_month_shift_keeps_last_day():
    moment = datetime(2026, 1, 31, 12, 0, tzinfo=timezone.utc)
    assert platform_tasks.shift_period(moment, "monthly").day == 28
    assert platform_tasks.shift_period(moment, "quarterly").month == 4
    assert platform_tasks.shift_period(moment, "weekly") == moment + timedelta(days=7)


def test_recurring_task_spawns_next_once(db, notes):
    task = platform_tasks.create_task(
        db,
        author_id=OWNER_ID,
        author_fio="Мангасарян Давид Каренович",
        assignee_fio=CLERK,
        description="Сдать сводку",
        priority="normal",
        due_at=datetime.now(timezone.utc) + timedelta(days=1),
        basis="Протокол совещания №5",
        recurrence="weekly",
    )
    assert task["basis"] == "Протокол совещания №5" and task["recurrence"] == "weekly"
    assert "Основание: Протокол совещания №5" in notes[0]["body"]
    assert platform_tasks.spawn_recurring(db) == 0
    row = db.get(PlatformTask, task["id"])
    row.posted_at = datetime.now(timezone.utc) - timedelta(days=8)
    row.due_at = datetime.now(timezone.utc) - timedelta(days=6)
    db.commit()
    assert platform_tasks.spawn_recurring(db) == 1
    assert platform_tasks.spawn_recurring(db) == 0
    series = db.query(PlatformTask).filter(PlatformTask.series_id == task["id"]).all()
    assert len(series) == 2
    child = next(item for item in series if item.id != task["id"])
    assert child.basis == "Протокол совещания №5"
    assert platform_tasks._utc(child.due_at) > datetime.now(timezone.utc)


def test_recurrence_is_validated(db, notes):
    with pytest.raises(platform_tasks.PlatformTaskError, match="Периодичность"):
        platform_tasks.create_task(
            db,
            author_id=OWNER_ID,
            author_fio="Мангасарян Давид Каренович",
            assignee_fio=CLERK,
            description="x",
            priority="normal",
            due_at=datetime.now(timezone.utc) + timedelta(days=1),
            recurrence="hourly",
        )


def test_agent_task_is_accepted_when_done(db, notes):
    task = platform_tasks.create_agent_task(
        db,
        source=process_tools.AGENT_SOURCE,
        source_ref="f1",
        author_label="Оркестратор",
        notify_sender_id=OWNER_ID,
        assignee_user_id=CHIEF_ID,
        description="Проверить реестр",
        basis="Инструкция",
        due_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    done = platform_tasks.change_status(db, user_id=CHIEF_ID, task_id=task["id"], action="done")
    assert done["accepted_at"] and not done["awaiting_review"]
    assert len(notes) == 1


# ---------- новости ----------


def test_news_is_shown_until_date_and_dismissed(db):
    until = datetime.now(timezone.utc) + timedelta(days=2)
    news = today_news.publish(db, title="Изменился процесс", body="Текст", show_until=until, user_ids=[CHIEF_ID])
    assert [item["id"] for item in today_news.list_for(db, CHIEF_ID)] == [news["id"]]
    assert today_news.list_for(db, CLERK_ID) == []
    today_news.dismiss(db, CHIEF_ID, news["id"])
    assert today_news.list_for(db, CHIEF_ID) == []
    db.get(TodayNews, news["id"]).show_until = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    everyone = today_news.publish(db, title="Всем", body="", show_until=until, user_ids=[], everyone=True)
    assert [item["id"] for item in today_news.list_for(db, CLERK_ID)] == [everyone["id"]]
    with pytest.raises(today_news.NewsError, match="будущем"):
        today_news.publish(db, title="Старое", body="", show_until=datetime.now(timezone.utc), user_ids=[CHIEF_ID])


def test_news_photo_is_stored_and_shown_to_recipients_only(db, tmp_path, monkeypatch):
    monkeypatch.setattr(today_news, "_storage_dir", lambda: tmp_path / "news")
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    until = datetime.now(timezone.utc) + timedelta(days=1)
    news = today_news.publish(db, title="С фото", body="", show_until=until, user_ids=[CHIEF_ID], image=png)
    assert news["image_url"] == f"/api/v1/today/news/{news['id']}/image"
    path, media = today_news.image_for(db, CHIEF_ID, news["id"])
    assert media == "image/png" and open(path, "rb").read() == png
    with pytest.raises(today_news.NewsError):
        today_news.image_for(db, CLERK_ID, news["id"])
    with pytest.raises(today_news.NewsError, match="PNG"):
        today_news.publish(db, title="Не фото", body="", show_until=until, user_ids=[CHIEF_ID], image=b"text")
    with pytest.raises(today_news.NewsError, match="сетевой"):
        today_news.load_image(r"C:\Windows\win.ini")


# ---------- инструменты агента ----------


def test_approval_must_be_quoted_from_text():
    assert process_tools.approval_ok("УТВЕРЖДАЮ Генеральный директор А.Б. Амураль", APPROVED)
    assert not process_tools.approval_ok("Генеральный директор А.Б. Амураль", APPROVED)
    assert not process_tools.approval_ok("УТВЕРЖДАЮ Генеральный директор", DRAFT)


def test_task_by_position_and_initials_then_news(db, notes, tmp_path, monkeypatch):
    workspace = _workspace(tmp_path, monkeypatch, APPROVED)
    result = process_tools.create_task(db, workspace, _task_payload())
    task = db.get(PlatformTask, result["task_id"])
    assert task.assignee_user_id == CHIEF_ID and task.recurrence == "monthly"
    assert task.basis.startswith("Утверждённый документ «Инструкция.docx»: УТВЕРЖДАЮ")
    assert task.source == process_tools.AGENT_SOURCE and task.source_ref == "f1"
    with pytest.raises(process_tools.ToolRefused, match="уже есть"):
        process_tools.create_task(db, workspace, _task_payload())
    news = process_tools.publish_news(
        db,
        workspace,
        {
            "file_id": "f1",
            "approval_quote": "УТВЕРЖДАЮ Генеральный директор А.Б. Амураль",
            "title": "Изменился процесс ведения реестра чертежей",
            "body": "Главный конструктор ежемесячно сверяет реестр. Поставлена периодическая задача.",
            "show_until": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
            "recipients": [CLERK, "Неизвестный Человек"],
        },
    )
    assert news["recipients"] == 2 and news["not_linked"] == [CLERK, "Неизвестный Человек"]
    shown = today_news.list_for(db, CHIEF_ID)
    assert shown[0]["task_ids"] == [result["task_id"]] and shown[0]["kind"] == "process_change"
    assert today_news.list_for(db, OWNER_ID) and not today_news.list_for(db, CLERK_ID)


def test_manager_gets_control_task_with_same_due_and_period(db, notes, tmp_path, monkeypatch):
    director = "Амураль Игорь Борисович"
    db.add(AppUser(id="u-dir", fio=director, position="директор", department="Дирекция"))
    db.add(OrgMember(fio_key=fio_key(director), fio=director, user_id="u-dir", position="директор", unit_id="dir"))
    db.add(OrgUnit(id="dir", name="Дирекция", parent_id="", head_fio=director))
    db.add(OrgUnit(id="kb", name="КБ", parent_id="dir", head_fio=CHIEF))
    db.get(OrgMember, fio_key(CHIEF)).unit_id = "kb"
    db.get(OrgMember, fio_key(CLERK)).unit_id = "kb"
    db.commit()
    facts = process_tools.sources.superiors(db, CHIEF)
    assert facts["heads_units"] == ["КБ"] and [item["fio"] for item in facts["unit_chain_heads"]] == [director]
    assert [item["fio"] for item in process_tools.sources.superiors(db, CLERK)["unit_chain_heads"]] == [CHIEF, director]

    workspace = _workspace(tmp_path, monkeypatch, APPROVED)
    result = process_tools.create_task(
        db, workspace, _task_payload(control_fio=director, control_reason="Руководитель КБ подчиняется дирекции")
    )
    assert result["control"]["created"] and result["control"]["manager"] == director
    own = db.get(PlatformTask, result["task_id"])
    control = db.get(PlatformTask, result["control"]["task_id"])
    assert control.assignee_user_id == "u-dir" and control.recurrence == "monthly"
    assert platform_tasks._utc(control.due_at) == platform_tasks._utc(own.due_at)
    assert control.description.startswith(f"Контроль: {CHIEF} — ")
    assert f"Контроль исполнения задачи подчинённого: {CHIEF}" in control.basis
    assert control.basis.endswith("Руководитель КБ подчиняется дирекции")

    news = process_tools.publish_news(
        db,
        workspace,
        {
            "file_id": "f1",
            "approval_quote": "УТВЕРЖДАЮ Генеральный директор А.Б. Амураль",
            "title": "Изменился процесс ведения реестра",
            "body": "Ежемесячная сверка реестра.",
            "show_until": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        },
    )
    assert news["recipients"] == 3
    assert today_news.list_for(db, "u-dir")[0]["task_ids"] == [own.id, control.id]


def test_control_needs_real_superior_with_account(db, notes, tmp_path, monkeypatch):
    boss = "Сидоров Олег Петрович"
    db.add(OrgMember(fio_key=fio_key(boss), fio=boss, user_id="", position="начальник КБ", unit_id="", department="КБ"))
    db.commit()
    workspace = _workspace(tmp_path, monkeypatch, APPROVED)
    result = process_tools.create_task(db, workspace, _task_payload(control_fio=CLERK))
    assert result["control"]["created"] is False and "не руководитель" in result["control"]["reason"]
    result = process_tools.create_task(
        db, workspace, _task_payload(description="Подписать акт сверки реестра у директора", control_fio=boss)
    )
    assert result["control"]["reason"] == "У контролирующего нет учётной записи в системе"
    assert process_tools.sources.is_superior(db, CHIEF, boss)
    assert db.query(PlatformTask).count() == 2
    assert process_tools.create_task(
        db, workspace, _task_payload(description="Обновить реестр чертежей после сверки")
    ).get("control") is None


def test_news_takes_image_generated_in_this_run_only(db, notes, tmp_path, monkeypatch):
    monkeypatch.setattr(today_news, "_storage_dir", lambda: tmp_path / "news")
    home = tmp_path / "home"
    monkeypatch.setattr(process_tools.Path, "home", classmethod(lambda cls: home))
    (tmp_path / "3f2c-run").mkdir()
    workspace = _workspace(tmp_path / "3f2c-run", monkeypatch, APPROVED)
    assets = home / ".cursor" / "projects" / f"C-Users-srv-var-{workspace.name}" / "assets"
    assets.mkdir(parents=True)
    jpeg = b"\xff\xd8\xff\xe0" + b"0" * 64
    (assets / "process.jpg").write_bytes(jpeg)
    stranger = tmp_path / "other.jpg"
    stranger.write_bytes(jpeg)
    payload = {
        "file_id": "f1",
        "approval_quote": "УТВЕРЖДАЮ Генеральный директор А.Б. Амураль",
        "title": "Новый порядок сверки реестра",
        "body": "Реестр чертежей сверяется ежемесячно.",
        "show_until": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        "image": str(stranger),
    }
    with pytest.raises(process_tools.ToolRefused, match="generateImage"):
        process_tools.publish_news(db, workspace, payload)
    news = process_tools.publish_news(db, workspace, payload | {"image": str(assets / "process.jpg")})
    assert news["image"] is True
    path, media = today_news.image_for(db, OWNER_ID, news["news_id"])
    assert media == "image/jpeg" and open(path, "rb").read() == jpeg
    assert process_tools.generated_assets(workspace) == [assets]


def test_scan_needs_page_where_signature_is_seen(db, notes, tmp_path, monkeypatch):
    workspace = _workspace(tmp_path, monkeypatch, APPROVED)
    manifest = json.loads((workspace / "recent.json").read_text(encoding="utf-8"))
    manifest[0]["page_images"] = ["pages/f1-p1.png", "pages/f1-p26.png"]
    (workspace / "recent.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(process_tools.ToolRefused, match="скан"):
        process_tools.create_task(db, workspace, _task_payload())
    with pytest.raises(process_tools.ToolRefused, match="скан"):
        process_tools.create_task(db, workspace, _task_payload(approval_page="pages/other-p1.png"))
    result = process_tools.create_task(
        db,
        workspace,
        _task_payload(approval_page="pages\\f1-p1.png", approval_seen="подпись, дата 28.11.2024, штамп «Действующий»"),
    )
    basis = db.get(PlatformTask, result["task_id"]).basis
    assert "(скан, стр. 1: подпись, дата 28.11.2024, штамп «Действующий»)" in basis


def test_pdf_pages_are_rendered_first_and_last():
    pymupdf = pytest.importorskip("pymupdf")
    document = pymupdf.open()
    for _ in range(5):
        document.new_page()
    pages = process_tools.sources.pdf_page_images(document.tobytes())
    assert [number for number, _ in pages] == [1, 2, 5]
    assert all(png.startswith(b"\x89PNG") for _, png in pages)


def test_draft_is_refused(db, notes, tmp_path, monkeypatch):
    workspace = _workspace(tmp_path, monkeypatch, DRAFT)
    with pytest.raises(process_tools.ToolRefused, match="не подтверждён"):
        process_tools.create_task(db, workspace, _task_payload(approval_quote="Проект инструкции по ведению реестра"))
    assert db.query(PlatformTask).count() == 0


def test_plan_phase_and_unlinked_person_are_refused(db, notes, tmp_path, monkeypatch):
    workspace = _workspace(tmp_path, monkeypatch, APPROVED, phase="plan")
    with pytest.raises(process_tools.ToolRefused, match="плана"):
        process_tools.create_task(db, workspace, _task_payload())
    (workspace / "phase.txt").write_text("act", encoding="utf-8")
    with pytest.raises(process_tools.ToolRefused, match="не связан"):
        process_tools.create_task(
            db,
            workspace,
            _task_payload(assignee_fio="Мангасарян Давид Каренович", position="руководитель сектора"),
        )


def test_diff_shows_new_duty():
    old = "1. Общие положения. 3.1. Специалист по документации ведёт реестр."
    new = old + " 3.2. Главный конструктор ежемесячно проверяет реестр."
    diff = text_diff(old, new)
    assert "+ 3.2. Главный конструктор ежемесячно проверяет реестр." in diff
    assert not any(line.startswith("- ") for line in diff.splitlines())
