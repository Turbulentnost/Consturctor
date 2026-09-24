"""Document_ТД_Протокол create body: mapping of agent arguments to OData fields."""

from __future__ import annotations

import pytest

from app.services import meeting_protocol_write as mpw

USERS = {
    "Соломичева Светлана Викторовна": {
        "ref_key": "5b2e1e74-a805-11eb-85c6-ac1f6b05524d",
        "fio": "Соломичева Светлана Викторовна",
        "person_key": "aaaaaaaa-0000-0000-0000-000000000001",
        "department_key": "4668a58b-6eb1-11e2-afce-001e67112509",
    },
    "Жалыбин Максим Дмитриевич": {
        "ref_key": "41290a43-5990-11f1-980e-6cb31113810e",
        "fio": "Жалыбин Максим Дмитриевич",
        "person_key": "2a2a4097-58c5-11f1-980d-6cb31113810c",
        "department_key": "2094af18-de06-11ef-95fc-6cb31113810e",
    },
}
PERSONS = {
    "Жалыбин Максим Дмитриевич": "2a2a4097-58c5-11f1-980d-6cb31113810c",
    "Соломичева Светлана Викторовна": "aaaaaaaa-0000-0000-0000-000000000001",
    "Мегрелишвили Михаил Эмзарович": "bbbbbbbb-0000-0000-0000-000000000002",
}
THEME = {
    "Ref_Key": "b2e6e94a-6885-11f1-9822-6cb31113810e",
    "Description": 'Еженедельное совещание РГ по проекту "Разработка ИИ-агентов (первая очередь)"',
    "Руководитель_Key": "5b2e1e74-a805-11eb-85c6-ac1f6b05524d",
    "Проверяющий_Key": "5b2e1e74-a805-11eb-85c6-ac1f6b05524d",
    "Проект_Key": "7e931aca-634a-11f1-981b-6cb31113810e",
    "Подразделение_Key": "4668a58b-6eb1-11e2-afce-001e67112509",
    "ВидСовещания": "Отчетное",
    "Кабинет_Key": "00000000-0000-0000-0000-000000000000",
}


@pytest.fixture(autouse=True)
def _fake_resolvers(monkeypatch):
    def resolve_user_card(query: str):
        for fio, card in USERS.items():
            if query == card["ref_key"] or query.casefold() in fio.casefold():
                return dict(card)
        raise mpw.ProtocolWriteError(f"Пользователь 1С не найден: {query}")

    def resolve_person(query: str):
        for fio, key in PERSONS.items():
            if query.casefold() in fio.casefold():
                return {"ref_key": key, "fio": fio}
        raise mpw.ProtocolWriteError(f"Физическое лицо 1С не найдено: {query}")

    def resolve_theme(query: str):
        return dict(THEME) if "ИИ-агентов" in query or query == THEME["Ref_Key"] else None

    def resolve_ref(entity: str, query: str):
        if entity == mpw.ACCESS_ENTITY and query == "Общий":
            return "bbdfce50-4266-11e8-8272-ac1f6b05524d"
        if entity == mpw.ROOM_ENTITY and "конференц" in query:
            return "35ccfb35-ad89-11f0-9720-6cb31113810e"
        return ""

    monkeypatch.setattr(mpw, "resolve_user_card", resolve_user_card)
    monkeypatch.setattr(mpw, "resolve_person", resolve_person)
    monkeypatch.setattr(mpw, "resolve_theme", resolve_theme)
    monkeypatch.setattr(mpw, "resolve_ref", resolve_ref)


def _args() -> dict:
    return {
        "topic": "Разработка ИИ-агентов",
        "date": "2026-09-21",
        "time_start": "10:30",
        "time_end": "11:00",
        "room": "малый конференц-зал",
        "participants": ["Соломичева Светлана Викторовна", "Жалыбин Максим Дмитриевич", "Неизвестный Гость"],
        "agenda": ["Статус ИИ-агентов", {"question": "Библиотека агентов", "responsible": "Жалыбин"}],
        "decisions": ["Подключить агента совещаний в библиотеку", {"text": "Расчёт KPI", "due": "2026-09-24"}],
        "tasks": [
            {"text": "Проверить в outlook регистрацию вх.корр в 1с", "executor": "Жалыбин Максим Дмитриевич", "due": "2026-09-24"},
            {"text": "Сделать расчёт КПИ", "executor": "Комаркова", "due": "2026-09-22", "priority": "Высокий"},
        ],
        "comment": "Сформировано ИИ-агентом по аудиозаписи 1 сент., 13.07_ (1).aac",
    }


def test_header_comes_from_theme_and_session():
    body, meta = mpw.build_protocol_create_body(_args(), actor_fio="Жалыбин Максим Дмитриевич")
    assert body["ТемаСовещания_Key"] == THEME["Ref_Key"]
    assert body["Руководитель_Key"] == USERS["Соломичева Светлана Викторовна"]["ref_key"]
    assert body["Ответственный_Key"] == USERS["Соломичева Светлана Викторовна"]["ref_key"]
    assert body["Подготовил_Key"] == USERS["Жалыбин Максим Дмитриевич"]["ref_key"]
    assert body["Проект_Key"] == THEME["Проект_Key"]
    assert body["Подразделение_Key"] == THEME["Подразделение_Key"]
    assert body["Кабинет_Key"] == "35ccfb35-ad89-11f0-9720-6cb31113810e"
    assert body["ГрифДоступа_Key"] == "bbdfce50-4266-11e8-8272-ac1f6b05524d"
    assert body["ВидСовещания"] == "Отчетное"
    assert body["Статус"] == "Подготовлен"
    assert body["Posted"] is False
    assert body["Date"].startswith("2026-09-21")
    assert body["ВремяНачалаСовещания"] == "0001-01-01T10:30:00"
    assert body["ВремяОкончанияСовещания"] == "0001-01-01T11:00:00"
    assert meta["leader"] == "Соломичева Светлана Викторовна"
    assert meta["prepared_by"] == "Жалыбин Максим Дмитриевич"


def test_tabular_sections_map_to_1c_fields():
    body, meta = mpw.build_protocol_create_body(_args(), actor_fio="Жалыбин Максим Дмитриевич")
    attendees = body["ПрисутствующиеНаСовещании"]
    assert [row["Участник_Key"] for row in attendees] == [
        PERSONS["Соломичева Светлана Викторовна"],
        PERSONS["Жалыбин Максим Дмитриевич"],
    ]
    assert attendees[1]["LineNumber"] == "2"
    assert "Соломичева Светлана Викторовна; Жалыбин Максим Дмитриевич" == body["КраткийСоставДокумента"]

    agenda = body["ПовесткаСовещания"]
    assert agenda[0]["Вопрос"] == "Статус ИИ-агентов"
    assert agenda[0]["Вопрос_Type"] == "Edm.String"
    assert agenda[1]["Ответственный_Key"] == PERSONS["Жалыбин Максим Дмитриевич"]

    decisions = body["Решения"]
    assert decisions[0]["ТекстРешения"] == "Подключить агента совещаний в библиотеку"
    assert decisions[0]["ДатаНачала"] == "2026-09-21T00:00:00"
    assert decisions[0]["ДокументОснование_Type"] == "StandardODATA.Undefined"
    assert decisions[1]["ДатаОкончания"] == "2026-09-24T23:59:59"

    tasks = body["ПеременныеЗадачиПротокола"]
    assert tasks[0]["Задача"].startswith("Проверить в outlook")
    assert tasks[0]["Ответственный_Key"] == PERSONS["Жалыбин Максим Дмитриевич"]
    assert tasks[0]["Автор_Key"] == USERS["Соломичева Светлана Викторовна"]["ref_key"]
    assert tasks[0]["ДатаПостановкиЗадачи"] == "2026-09-21T00:00:00"
    assert tasks[0]["ДатаФактическогоИсполнения"] == "2026-09-24T23:59:59"
    assert tasks[1]["Приоритет"] == "Высокий"
    assert "Ответственный_Key" not in tasks[1]  # Комаркова не найдена

    assert meta["tasks_count"] == 2 and meta["agenda_count"] == 2 and meta["decisions_count"] == 2


def test_unresolved_names_go_to_comment_not_error():
    body, meta = mpw.build_protocol_create_body(_args(), actor_fio="Жалыбин Максим Дмитриевич")
    assert any("Неизвестный Гость" in item for item in meta["unresolved"])
    assert any("Комаркова" in item for item in meta["unresolved"])
    assert body["Комментарий"].startswith("Сформировано ИИ-агентом")
    assert "Не сопоставлено с 1С" in body["Комментарий"]


def test_leader_falls_back_to_session_without_theme():
    args = _args()
    args["topic"] = "Совещание без темы в справочнике"
    body, meta = mpw.build_protocol_create_body(args, actor_fio="Жалыбин Максим Дмитриевич")
    assert "ТемаСовещания_Key" not in body
    assert body["Руководитель_Key"] == USERS["Жалыбин Максим Дмитриевич"]["ref_key"]
    assert body["Подразделение_Key"] == USERS["Жалыбин Максим Дмитриевич"]["department_key"]
    assert any("тема совещания" in item for item in meta["unresolved"])


def test_leader_required_when_nothing_known():
    args = _args()
    args["topic"] = ""
    with pytest.raises(mpw.ProtocolWriteError):
        mpw.build_protocol_create_body(args)


def test_empty_protocol_is_rejected(monkeypatch):
    monkeypatch.setattr(mpw, "_odata_post", lambda *_: pytest.fail("POST must not happen"))
    with pytest.raises(mpw.ProtocolWriteError):
        mpw.handle_protocol_write(
            {"topic": "Разработка ИИ-агентов", "date": "2026-09-21"},
            actor_fio="Жалыбин Максим Дмитриевич",
        )


def test_create_posts_and_returns_number(monkeypatch):
    posted: dict = {}

    def fake_post(args):
        posted.update(args)
        return {"data": {"Ref_Key": "96396617-b5b0-11f1-9889-6cb31113810c", "Number": "ДР__062_О_427"}}

    monkeypatch.setattr(mpw, "_odata_post", fake_post)
    result = mpw.handle_protocol_write(_args(), actor_fio="Жалыбин Максим Дмитриевич")
    assert posted["entity"] == mpw.PROTOCOL_ENTITY
    assert result["number"] == "ДР__062_О_427"
    assert result["ref_key"] == "96396617-b5b0-11f1-9889-6cb31113810c"
    assert result["posted"] is False
    assert "ДР__062_О_427" in result["summary"]
    assert result["unresolved"]


def test_time_parsing_variants():
    assert mpw._time_value("9:05") == "0001-01-01T09:05:00"
    assert mpw._time_value("2026-09-21T10:30:00") == "0001-01-01T10:30:00"
    assert mpw._time_value("") == ""
    with pytest.raises(mpw.ProtocolWriteError):
        mpw._time_value("25:00")


def test_tool_registered_as_write_tool():
    from app.services import onec_tools

    assert "onec.meeting_protocol_write" in onec_tools.ONEC_TOOLS
    assert "onec.meeting_protocol_write" in onec_tools.ONEC_WRITE_TOOLS
    assert onec_tools.REAL_HANDLERS["onec.meeting_protocol_write"] is mpw.handle_protocol_write
    stub = onec_tools.STUB_HANDLERS["onec.meeting_protocol_write"]({"tasks": ["a"]})
    assert stub["source"] == "stub" and stub["entity"] == mpw.PROTOCOL_ENTITY
